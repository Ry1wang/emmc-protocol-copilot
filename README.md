# eMMC Protocol Copilot

基于 RAG + LangGraph Agent 的 eMMC 协议规范智能问答系统。支持对 JESD84-B51（5.1）、B50（5.0）、B451（4.51）三个版本规范的精准检索与问答，提供带章节引用的技术答案。

---

## 系统架构

```
eMMC 规范 PDF（JESD84-B51/B50/B451）
          │
          ▼
  ┌─────────────────┐
  │  Phase 1 Ingest │  PDF 解析 → 内容分类 → 语义切片 → JSONL
  └────────┬────────┘
           │
           ▼
  ┌─────────────────┐
  │  Phase 2 RAG    │  BGE-M3 向量化 → ChromaDB + BM25 混合检索 + RRF 融合
  └────────┬────────┘
           │
           ▼
  ┌─────────────────┐
  │  Phase 3 Agent  │  LangGraph ReAct Agent，4 个工具，支持多轮对话
  └────────┬────────┘
           │
           ▼
  ┌─────────────────┐
  │  Phase 4 Eval   │  RAGAS 评估：三条 pipeline 基准对比（忠实度 / 相关性 / 召回）
  └────────┬────────┘
           │
           ▼
  ┌─────────────────┐
  │  Phase 5 前端   │  Chainlit Web UI + LangSmith 监控
  └─────────────────┘
```

---

## 技术栈

| 类别 | 技术选型 |
|---|---|
| 开发框架 | Python 3.11 + [uv](https://github.com/astral-sh/uv) |
| LLM 框架 | LangChain v0.3 / LangGraph |
| LLM | DeepSeek（OpenAI 兼容接口） |
| Embedding | BAAI/bge-m3（1024 维，中英文） |
| 文档解析 | PyMuPDF + pdfplumber |
| 向量数据库 | ChromaDB（开发）→ Pinecone（生产） |
| 关键词检索 | rank-bm25（混合检索路径） |
| 前端 | Chainlit |
| 评估 | RAGAS |
| 可观测性 | LangSmith |

---

## 项目结构

```
emmc-protocol-copilot/
├── src/emmc_copilot/
│   ├── ingestion/          # Phase 1：PDF 解析与切片
│   │   ├── schema.py       # EMMCChunk Pydantic 数据模型
│   │   ├── parser.py       # PDFParser（PyMuPDF + pdfplumber）
│   │   ├── structure.py    # TOC 解析 + Front Matter 判定
│   │   ├── classifier.py   # 内容类型分类（text/table/figure/definition/register）
│   │   ├── chunkers/       # 各类型切片器
│   │   ├── pipeline.py     # IngestionPipeline 编排入口
│   │   └── cli.py          # CLI: ingest 命令
│   ├── retrieval/          # Phase 2：向量化与检索
│   │   ├── embedder.py     # BGEEmbedder（懒加载，FP16）
│   │   ├── vectorstore.py  # EMMCVectorStore（ChromaDB 双 collection）
│   │   ├── indexer.py      # JSONL → embed → ChromaDB
│   │   ├── bm25_index.py   # BM25Corpus（关键词索引）
│   │   ├── hybrid_retriever.py  # HybridRetriever（Dense + BM25 + RRF）
│   │   ├── version_filter.py    # 版本检测与过滤
│   │   └── cli.py          # CLI: index / stats / search / build-bm25
│   ├── qa/                 # Phase 2：RAG 问答链路
│   │   ├── chain.py        # build_chain()：LCEL RAG 主链路
│   │   ├── retriever.py    # EMMCRetriever（Dense-only 降级）
│   │   ├── prompt.py       # 系统提示词 + 引用格式规则
│   │   └── cli.py          # CLI: ask / chat 命令
│   ├── agent/              # Phase 3：LangGraph Agent
│   │   ├── state.py        # AgentState（MemorySaver 多轮）
│   │   ├── tools.py        # 4 个工具：search / explain_term / compare / calculate
│   │   ├── graph.py        # LangGraph StateGraph 构建
│   │   ├── prompt.py       # Agent 系统提示
│   │   └── cli.py          # CLI: ask / chat 命令
│   └── evaluation/         # Phase 4：RAGAS 评估
│       ├── runner.py       # 三条 pipeline 基准测试
│       └── dataset.py      # Q&A 数据集加载
├── app.py                  # Phase 5：Chainlit 前端入口
├── data/
│   ├── processed/          # JSONL chunks（gitignored）
│   └── vectorstore/
│       ├── chroma/         # ChromaDB 持久化（gitignored）
│       └── bm25/           # BM25 索引 corpus.pkl（gitignored）
├── docs/                   # 设计文档与测试报告（见下文）
├── tools/                  # 开发辅助脚本
└── tests/                  # pytest 测试
```

---

## 快速开始

### 1. 环境准备

```bash
# 安装 uv（如未安装）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 安装依赖
uv sync --dev

# 配置环境变量
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY
```

`.env` 必填项：

```bash
DEEPSEEK_API_KEY=sk-...

# 可选（有默认值）
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat
EMMC_VERSION=5.1        # 默认检索版本，可选 5.0 / 4.51 / all
QUERY_EXPAND=1          # 查询扩展，设为 0 可禁用
LANGCHAIN_API_KEY=...   # LangSmith 监控，不填则禁用追踪
```

### 2. 准备数据

将 eMMC 规范 PDF 放入 `docs/protocol/`（gitignored）：

```
docs/protocol/
├── JESD84-B51.pdf   # eMMC 5.1
├── JESD84-B50.pdf   # eMMC 5.0（可选）
└── JESD84-B451.pdf  # eMMC 4.51（可选）
```

### 3. Phase 1：文档切片入库

```bash
# 解析 PDF，生成 JSONL chunks
uv run python -m emmc_copilot.ingestion.cli ingest \
    --pdf-dir docs/protocol/ \
    --output data/processed/
```

### 4. Phase 2：向量化与构建索引

```bash
# 向量化入库（ChromaDB）
uv run python -m emmc_copilot.retrieval.cli index \
    --input data/processed/ \
    --vectorstore data/vectorstore/chroma/

# 构建 BM25 关键词索引（混合检索必需）
uv run python -m emmc_copilot.retrieval.cli build-bm25 \
    --input data/processed/ \
    --output data/vectorstore/bm25/

# 验证索引状态
uv run python -m emmc_copilot.retrieval.cli stats
```

### 5. 运行问答

**方式一：RAG 链路（命令行）**

```bash
# 单次问答
uv run python -m emmc_copilot.qa.cli ask "HS400 的 tuning 流程是什么？" --show-sources

# 交互式对话
uv run python -m emmc_copilot.qa.cli chat
```

**方式二：Agent（命令行）**

```bash
# 单次问答（支持多工具调用）
uv run python -m emmc_copilot.agent.cli ask "比较 eMMC 5.1 和 5.0 的 HS400 差异"

# 多轮对话
uv run python -m emmc_copilot.agent.cli chat
```

**方式三：Chainlit 前端**

```bash
chainlit run app.py
# 访问 http://localhost:8000
```

---

## Agent 工具说明

Phase 3 Agent 配备 4 个工具：

| 工具 | 作用 |
|---|---|
| `search_emmc_docs` | 混合检索 eMMC 规范，返回带章节引用的内容片段 |
| `explain_term` | 查询术语定义（专走 `emmc_glossary` collection） |
| `compare_versions` | 对比两个版本规范的差异（分别检索后对比） |
| `calculate` | 计算存储容量、时序参数等数值（Python 安全求值） |

---

## 开发辅助

```bash
# 检索效果验证（Dense-only）
uv run python tools/verify_retrieval.py

# 混合 RAG 链路测试（20 问）
uv run python tools/test_rag_pipeline.py

# Agent 全量测试（12 问）
uv run python tools/test_agent_pipeline.py

# Agent 多轮对话测试（单进程，MemorySaver 要求）
uv run python tools/run_multiturn_test.py

# RAGAS 评估（三条 pipeline 基准对比）
uv run python tools/run_ragas_eval.py
```

---

## docs/ 文档目录

### 设计文档

| 文件 | 说明 |
|---|---|
| `eMMC_Agent_技术选型文档.md` | Phase 0：技术选型决策（LangChain / ChromaDB / BGE-M3 / DeepSeek 等选型理由） |
| `chunking_design.md` | Phase 1 原始设计规格（实现前编写，含实现顺序、多列布局、页码偏移等细节） |
| `phase1_data_pipeline_design.md` | Phase 1 实现后复盘（Post-hoc），含风险记录、验收标准、交付给 Phase 2 的接口 |
| `phase2_rag_design.md` | Phase 2 RAG 检索链路复盘（混合检索、RRF 融合、版本过滤、引用格式等决策） |
| `phase3_agent_design.md` | Phase 3 Agent 实现方案（LangGraph ReAct、4 工具设计、MemorySaver 多轮） |
| `phase4_eval_design.md` | Phase 4 RAGAS 评估方案（三条 pipeline 基准、指标选择、Q&A 数据集构建） |
| `phase5_frontend_design.md` | Phase 5 Chainlit 前端 + LangSmith 监控设计 |

### 测试方案

| 文件 | 说明 |
|---|---|
| `phase3_test_plan.md` | Phase 3 Agent 测试方案（单轮 12 问 + 多轮 5 组场景设计） |
| `phase5_test_plan.md` | Phase 5 前端与监控体验测试方案 |

### 测试结果

| 文件 | 说明 |
|---|---|
| `retrieval_test_v51.md` | Dense-only 检索验证结果（10 问，BGE-M3 + ChromaDB） |
| `hybrid_rag_test_results.md` | 混合 RAG 测试结果 v1（20 问） |
| `hybrid_rag_test_results_v2.md` | 混合 RAG 测试结果 v2（查询扩展优化后） |
| `rag_full_test_results.md` | RAG 链路完整测试（含引用格式验证） |
| `agent_full_test_results.md` | Agent 全量测试结果 v1（12 问） |
| `agent_full_test_results_v2.md` | Agent 全量测试结果 v2（calculate bug 修复后） |
| `ragas_eval_results.md` | RAGAS 评测报告（Dense / Hybrid / Agent 三条 pipeline 对比） |

### 分析与参考

| 文件 | 说明 |
|---|---|
| `agent_vs_notebooklm_analysis.md` | Agent 输出与 NotebookLM 的深度对比分析 |
| `notebook_lm_compare_agent.md` | NotebookLM 原始回答记录（对比基准） |
| `known_issues.md` | 已知问题记录（Phase 1–2 开发中发现的问题、根因、解决状态） |
| `dev_process_records.md` | 开发路线记录（各 Phase 进展与里程碑） |

---

## 数据说明

| 路径 | 内容 | Git 状态 |
|---|---|---|
| `docs/protocol/*.pdf` | eMMC 规范原始 PDF | gitignored（需手动放置） |
| `data/processed/*.jsonl` | 切片后的 JSONL chunks | gitignored |
| `data/vectorstore/chroma/` | ChromaDB 持久化索引 | gitignored |
| `data/vectorstore/bm25/corpus.pkl` | BM25 关键词索引 | gitignored |

> 以上数据文件均不提交至 Git，需在本地重新构建。构建顺序见[快速开始](#快速开始)第 3–4 步。
