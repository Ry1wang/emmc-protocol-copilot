# Phase 2 — RAG 检索链路：设计文档

> **文档说明**：本文档为事后补写（Post-hoc Documentation），依据 Phase 2 实际实现反向整理，
> 还原设计决策与实现方案，供维护者和后续开发者参考。

---

## 1. 目标与范围

### 1.1 Phase 目标

在 Phase 1 构建的 ChromaDB 向量库基础上，构建完整的 RAG（检索增强生成）问答链路，
实现对 eMMC 规范的精准语义检索与带引用格式的答案生成。

**核心假设（本 Phase 需要验证）**：
> 混合检索（Dense + BM25 + RRF）相比纯语义检索，对技术术语（寄存器名称、十六进制值、命令编号）的召回率更高，能为 LLM 提供更准确的上下文。

### 1.2 里程碑

```
# 构建 BM25 关键词索引
uv run python -m emmc_copilot.retrieval.cli build-bm25 --input data/processed/

# 验证混合检索效果
uv run python -m emmc_copilot.retrieval.cli search "HS400 tuning flow" --n 5

# 运行完整 RAG 问答
uv run python -m emmc_copilot.qa.cli ask "What is the EXT_CSD CACHE_CTRL register?"
```

三条命令验证通过后，端到端 RAG 链路可用：用户提问 → 混合检索 → LLM 生成含引用的答案。

### 1.3 不在范围内

- Agent 工具集成（search_emmc_docs / explain_term）→ Phase 3
- RAGAS 基准评估 → Phase 4
- 前端界面 → Phase 5
- 生产部署（Pinecone / Railway） → 后续迭代

---

## 2. 系统输入

### 2.1 Phase 1 交付物

| 输入 | 路径 | 说明 |
|---|---|---|
| **JSONL chunks** | `data/processed/*_chunks.jsonl` | EMMCChunk schema，三版本合计 9085 chunks |
| **ChromaDB 向量库** | `data/vectorstore/chroma/` | `emmc_docs` + `emmc_glossary` 两个 collection |
| **嵌入接口** | `emmc_copilot.retrieval.BGEEmbedder` | BGE-M3，1024 维，L2 归一化 |

### 2.2 检索挑战分析

Phase 1 的文档特征决定了纯语义检索的局限：

| 检索场景 | 纯语义检索缺陷 | 设计影响 |
|---|---|---|
| 寄存器名查询（`EXT_CSD[33]`）| 语义空间中 "33" 无特殊含义 | 需要精确关键词匹配（BM25） |
| 命令号查询（`CMD6`、`CMD21`）| BGE-M3 对数字标识符召回弱 | BM25 下划线保留分词 |
| 十六进制值（`0x1A`）| 纯向量检索对 hex 无感知 | BM25 补充精确匹配 |
| 版本差异查询 | 不同版本相似内容混淆 | ChromaDB 元数据过滤 |
| 跨行寄存器表 | 行级 chunk 缺乏上下文 | 邻行扩展策略 |

---

## 3. 系统架构

### 3.1 整体数据流

```
用户问题
        │
        ▼
┌───────────────────────────────────────┐
│    RAG Chain (qa/chain.py)            │
│                                       │
│  QueryExpander                        │  ← LLM 生成 2 个查询变体
│      ↓                                │
│  HybridRetriever                      │  ← 混合检索入口
│   ├── Dense Path                      │
│   │   ├── BGEEmbedder.embed_query()   │  ← BAAI/bge-m3，1024 维
│   │   └── ChromaDB.query()           │  ← emmc_docs，40 候选
│   ├── BM25 Path                       │
│   │   └── BM25Corpus.search()        │  ← rank_bm25，40 候选
│   ├── RRF Fusion (k=60)              │  ← 合并双路结果
│   ├── NeighborExpander               │  ← TABLE/REGISTER 邻行扩展
│   └── List[Document] (top-15)        │
│      ↓                                │
│  format_docs_with_citations()         │  ← 生成带 Cite-as 的上下文
│      ↓                                │
│  ChatPromptTemplate                   │  ← 系统提示 + 引用规则
│      ↓                                │
│  DeepSeek LLM                         │  ← temperature=0.1
│      ↓                                │
│  含内联引用的答案                      │
└───────────────────────────────────────┘
```

### 3.2 模块文件结构

```
src/emmc_copilot/
├── retrieval/
│   ├── __init__.py           # 对外导出: BGEEmbedder, EMMCIndexer, EMMCVectorStore
│   │                         #           BM25Corpus, HybridRetriever
│   ├── embedder.py           # BGEEmbedder：BGE-M3 懒加载封装
│   ├── vectorstore.py        # EMMCVectorStore：ChromaDB 双 collection 管理
│   ├── indexer.py            # EMMCIndexer：JSONL → 向量 → 入库编排
│   ├── bm25_index.py         # BM25Corpus：关键词索引 + pickle 持久化
│   ├── hybrid_retriever.py   # HybridRetriever：LangChain BaseRetriever 实现
│   ├── version_filter.py     # 版本检测 + ChromaDB where 条件构建
│   └── cli.py                # CLI: index / stats / search / build-bm25
│
└── qa/
    ├── chain.py              # build_chain()：LCEL RAG 主链路
    ├── retriever.py          # EMMCRetriever：Dense-only 降级 Retriever
    ├── prompt.py             # 系统提示词 + 引用格式规则
    └── cli.py                # CLI: ask / chat 子命令
```

---

## 4. 核心数据结构

### 4.1 LangChain Document Schema

HybridRetriever 返回标准 LangChain `Document` 对象，metadata 字段约定如下：

```python
Document(
    page_content = str,          # EMMCChunk.text（含上下文前缀）
    metadata = {
        "chunk_id":      str,    # UUID4，与 JSONL 一一对应
        "source":        str,    # "JESD84-B51.pdf"
        "version":       str,    # "5.1" | "5.0" | "4.51"
        "page_start":    int,    # PDF 物理页码（1-indexed）
        "page_end":      int,
        "section_path":  str,    # JSON 字符串，如 "[\"6\", \"6.10\"]"
        "section_title": str,    # "Detailed command description"
        "content_type":  str,    # "text" | "table" | "figure" | "definition" | "register"
        "is_row_chunk":  bool,   # TABLE 行组 chunk 标记
        "distance":      float,  # 余弦距离（仅 Dense 路径）
        "bm25_score":    float,  # BM25 分数（仅 BM25 路径）
        "rrf_score":     float,  # RRF 融合分数
    }
)
```

### 4.2 引用标签格式

Chain 为每个检索结果生成编号 + Cite-as 标签，LLM 直接复制到答案：

```
[1] Source: JESD84-B51.pdf (pages 246-246)
    Section: 7 > 7.4 > 7.4.111 — CACHE_CTRL
    Cite-as: [B51 §7.4.111 p.246]

    <chunk text...>
```

---

## 5. 各模块设计决策

### 5.1 BM25 分词策略（bm25_index.py）

**核心问题**：eMMC 技术文档中大量术语包含下划线（`EXT_CSD`、`HS_TIMING`）和数字（`CMD6`、`52MHz`）。
标准 NLP 分词器会错误地拆分这些词。

**设计决策**：自定义分词器，Regex 为 `[a-z0-9_]+`（保留下划线）：

```python
# 示例
"EXT_CSD[33]" → ["ext_csd", "33"]
"CMD6 switch mode" → ["cmd6", "switch", "mode"]
"52MHz DDR" → ["52mhz", "ddr"]
```

**索引文本**：`section_title + raw_text`（而非 `text`，避免上下文前缀引入噪声）。

**过滤规则**：跳过 `is_front_matter=True` 的 chunk，与 ChromaDB 索引行为对齐。

### 5.2 RRF 融合策略（hybrid_retriever.py）

**背景**：Dense 检索结果为余弦距离（0–2 区间），BM25 结果为 TF-IDF 分数（无界），两者量纲不同，无法直接加权求和。

**设计决策**：使用 Reciprocal Rank Fusion（RRF）：

```python
# 公式
rrf_score(chunk) = Σ 1 / (k + rank_in_list)

# 参数
k = 60          # 平滑常数，防止 top-1 独占权重
n_candidates = 40   # 每条路径取 40 个候选
n_results = 15      # 最终输出 15 个 Document
```

**优势**：
- 不依赖分数校准，天然支持异构检索器合并
- `k=60` 使双路 top-1 各贡献 `1/61 ≈ 0.016`，避免单路垄断
- 对仅出现在一条路径中的 chunk 也能正确评分

### 5.3 版本过滤策略（version_filter.py）

**问题**：三个版本规范（5.1、5.0、4.51）内容高度相似，语义检索会混入旧版结果。

**设计决策**：查询时动态检测版本意图，构建 ChromaDB `where` 过滤条件：

| 查询文本 | 检测结果 | ChromaDB 过滤 |
|---|---|---|
| `"eMMC 5.1 HS400"` | `["5.1"]` | `{"version": "5.1"}` |
| `"B50 and B51 difference"` | `["5.0", "5.1"]` | `{"version": {"$in": ["5.0", "5.1"]}}` |
| `"what is CMD6"` | `[]`（无明确版本） | `{"version": "5.1"}`（默认） |
| `EMMC_VERSION=all` | —— | 无过滤 |

**默认行为**：默认查询 `"5.1"` 版本，可通过环境变量 `EMMC_VERSION` 覆盖。

### 5.4 邻行扩展策略（hybrid_retriever.py）

**问题**：寄存器表和命令表按行切割后，单行 chunk 丢失了列标题行上下文（`is_row_chunk=True`）。

**设计决策**：对 TABLE 和 REGISTER 类型 chunk，通过 BM25Corpus 按文档顺序获取 ±1 相邻 chunk：

```python
# 约束条件：同一 source 文件 + 同一 section_path 内的邻居才纳入
if neighbor.source == hit.source and neighbor.section_path == hit.section_path:
    expand_docs.append(neighbor)
```

**防止跨节污染**：section 边界约束确保不会把相邻章节的内容误认为上下文。

### 5.5 查询扩展策略（qa/chain.py）

**问题**：用户提问往往简短或口语化，可能使用不同于文档的表述（"启动分区"vs"Boot Partition"）。

**设计决策**：可选的 LLM 查询扩展（`QUERY_EXPAND=1` 时启用）：

```python
# LLM 被要求生成 2 个技术变体，强调寄存器名、十六进制、命令号
variants = llm.invoke(expand_prompt)

# 多路检索后按 chunk_id 去重
all_docs = deduplicate_by_id([
    retriever.invoke(q) for q in [original_query] + variants
])
```

**效果**：提升对技术同义词和缩写的召回，代价是多 1 次 LLM 推理调用。

### 5.6 Dense-only 降级设计（qa/retriever.py）

**设计决策**：当 BM25 索引文件（`corpus.pkl`）不存在时，自动降级为 EMMCRetriever（纯语义检索）：

```python
# chain.py 启动时检测
if (bm25_dir / "corpus.pkl").exists():
    retriever = HybridRetriever(...)      # 生产路径
else:
    logger.warning("BM25 index not found, using dense-only retriever")
    retriever = EMMCRetriever(...)        # 降级路径
```

**好处**：开发环境无需完整构建 BM25 索引也能运行调试。

---

## 6. RAG 链路整合（qa/chain.py）

### 6.1 LCEL 链路组装

```python
chain = (
    RunnablePassthrough.assign(expanded=_expand_queries)  # 可选
    | RunnablePassthrough.assign(docs=retriever)
    | RunnablePassthrough.assign(context=format_docs_with_citations)
    | prompt
    | llm
    | StrOutputParser()
)
```

### 6.2 引用生成规则

`format_docs_with_citations()` 为每个检索结果生成编号 + 结构化标签，
系统提示要求 LLM **逐字复制** `Cite-as:` 标签内容到答案中：

```
系统提示关键规则：
1. 用 [B51 §section p.page] 格式引用，数字与方括号之间不加空格
2. 答案中每个关键事实必须至少有一个引用
3. 不要编造未出现在上下文中的引用
4. 语言与用户问题保持一致（中文问题 → 中文回答）
```

### 6.3 环境变量

| 变量名 | 默认值 | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY` | 必填 | DeepSeek API 密钥 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` | API 端点 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | 模型 ID |
| `CHROMA_PERSIST_DIR` | `data/vectorstore/chroma` | ChromaDB 持久化路径 |
| `BM25_INDEX_DIR` | `data/vectorstore/bm25` | BM25 索引目录 |
| `QUERY_EXPAND` | `1` | `"1"` 启用查询扩展，`"0"` 禁用 |
| `EMMC_VERSION` | `5.1` | 默认检索版本；`"all"` 不过滤 |

---

## 7. CLI 接口设计

### 7.1 Retrieval CLI

```bash
# 向量化入库（从 JSONL 到 ChromaDB）
uv run python -m emmc_copilot.retrieval.cli index \
    --input data/processed/ \
    --vectorstore data/vectorstore/chroma/

# 查看 collection 统计
uv run python -m emmc_copilot.retrieval.cli stats \
    --vectorstore data/vectorstore/chroma/

# 语义检索验证（单次搜索调试）
uv run python -m emmc_copilot.retrieval.cli search \
    "EXT_CSD register index 33" \
    --n 3 --v 5.1 --collection docs

# 构建 BM25 关键词索引
uv run python -m emmc_copilot.retrieval.cli build-bm25 \
    --input data/processed/ \
    --output data/vectorstore/bm25/
```

### 7.2 Q&A CLI

```bash
# 单次问答（带来源显示）
uv run python -m emmc_copilot.qa.cli ask \
    "eMMC 的 Boot 分区大小是多少？" \
    --show-sources

# 交互式对话（REPL 模式）
uv run python -m emmc_copilot.qa.cli chat --show-sources
# 退出：输入 quit / exit / q
```

---

## 8. 关键风险与应对

| 风险 | 描述 | 应对策略 | 状态 |
|---|---|---|:---:|
| 技术术语召回不足 | BGE-M3 对 `CMD6`、`EXT_CSD[33]` 等精确标识符语义感知弱 | BM25 路径补充精确关键词匹配 | ✅ 已解决 |
| 跨版本内容污染 | 旧版本（B50/B451）相似内容混入检索结果 | 查询时动态版本过滤 | ✅ 已解决 |
| 寄存器行 chunk 上下文缺失 | 行级切割丢失列标题，LLM 无法理解位字段含义 | TABLE/REGISTER 邻行扩展 | ✅ 已解决 |
| 量纲不同导致融合失效 | Dense 距离与 BM25 分数无法直接加权 | RRF 按排名融合，不依赖分数量纲 | ✅ 已解决 |
| 幻觉引用 | LLM 生成不存在的章节引用 | Cite-as 标签预生成，LLM 仅复制 | ✅ 已缓解 |
| 查询扩展引入噪声 | LLM 生成的变体语义偏移 | 多路检索后去重，非 union 操作 | ✅ 已缓解 |
| 开发环境依赖缺失 | BM25 索引未构建时链路失败 | Dense-only 自动降级 | ✅ 已解决 |

---

## 9. 验收标准

Phase 2 完成的判定标准：

```bash
# 构建全套索引
uv run python -m emmc_copilot.retrieval.cli index --input data/processed/
uv run python -m emmc_copilot.retrieval.cli build-bm25 --input data/processed/

# 验证各节点
uv run python -m emmc_copilot.retrieval.cli stats
uv run python -m emmc_copilot.retrieval.cli search "HS400 enhanced strobe" --n 5
uv run python -m emmc_copilot.qa.cli ask "What is EXT_CSD[33] CACHE_CTRL?" --show-sources
```

| 验收项 | 期望值 | 验证方式 |
|---|---|---|
| BM25 索引 chunks 数 | ≈ 9085（三版本合计） | `build-bm25` 输出日志 |
| `emmc_docs` collection 大小 | > 1400 chunks（B51 单版本） | `stats` 命令 |
| 混合检索延迟 | < 200ms（不含 LLM） | `search` 命令计时 |
| 寄存器查询命中率 | "EXT_CSD" 查询 top-3 含相关 chunk | `search "EXT_CSD CACHE_CTRL"` 人工判断 |
| 引用格式正确 | 答案含 `[B51 §x.x p.xxx]` 格式引用 | `ask` 命令输出 |
| 版本过滤生效 | B51 查询不返回 B50 chunks | metadata.version 字段检查 |
| Dense-only 降级可用 | 删除 corpus.pkl 后问答仍可运行 | 手动测试降级路径 |

---

## 10. 交付给 Phase 3 的接口

Phase 2 完成后，Phase 3 可直接使用的组件：

```python
# 混合检索器（Phase 3 Agent 的 search_emmc_docs 工具底层）
from emmc_copilot.retrieval import HybridRetriever, BGEEmbedder, EMMCVectorStore, BM25Corpus
from emmc_copilot.retrieval.version_filter import build_version_filter

embedder = BGEEmbedder()
store = EMMCVectorStore("data/vectorstore/chroma")
bm25 = BM25Corpus.load("data/vectorstore/bm25/corpus.pkl")

retriever = HybridRetriever(
    embedder=embedder,
    store=store,
    bm25=bm25,
    n_results=15,
    default_version="5.1",
)

# 直接检索
docs = retriever.invoke("HS400 enhanced strobe tuning")

# 术语专项检索（Phase 3 explain_term 工具底层）
results = store.query(
    query_embedding=embedder.embed_query("EXT_CSD"),
    n_results=5,
    collection="glossary"  # 仅检索 emmc_glossary collection
)

# 完整 RAG 链路（Phase 3 可直接调用）
from emmc_copilot.qa.chain import build_chain
chain = build_chain()
answer = chain.invoke({"question": "What is the HS400 tuning procedure?"})
```

**检索结果数据契约**：每个 `Document` 包含：
- `page_content`：带上下文前缀的 chunk 文本（用于 LLM 输入）
- `metadata.chunk_id`：全局唯一 ID（用于去重和引用追踪）
- `metadata.source`、`metadata.version`、`metadata.page_start`：引用定位
- `metadata.section_path`、`metadata.section_title`：章节导航
- `metadata.content_type`：区分 text / table / register / definition
- `metadata.rrf_score`：融合排名分数（可用于 Agent 置信度判断）

---

*Phase 2 Design Document — eMMC Protocol Copilot*
*文档类型：Post-hoc Documentation（事后补写）*
*基于实际实现反向整理，版本对应 Phase 2 最终实现状态*
