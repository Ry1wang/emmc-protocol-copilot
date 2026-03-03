# Phase 1 — 数据准备：设计文档

> **文档说明**：本文档为事后补写（Post-hoc Documentation），依据 Phase 1 实际实现反向整理，
> 还原设计决策与实现方案，供维护者和后续开发者参考。

---

## 1. 目标与范围

### 1.1 Phase 目标

构建 eMMC 规范文档的完整数据入库链路，为 Phase 2 RAG 检索提供高质量知识库。

**核心假设（本 Phase 需要验证）**：
> eMMC 协议 PDF 能被解析并切片为语义完整的 chunks，向量化存入 ChromaDB 后，可被有效检索。

### 1.2 里程碑

```
uv run python -m emmc_copilot.ingestion.cli ingest --pdf data/raw/JESD84-B51.pdf
uv run python -m emmc_copilot.retrieval.cli index --input data/processed/
```

两条命令串行执行后，ChromaDB 中存有完整的 eMMC 文档向量索引，可对外提供检索服务。

### 1.3 不在范围内

- 检索策略优化（BM25、混合检索）→ Phase 2
- RAG 链路与 LLM 对接 → Phase 2
- Agent 工具集成 → Phase 3

---

## 2. 输入数据特征分析

**这是本 Phase 最重要的前置工作。** 切片策略的所有设计决策都来源于对文档特征的理解。

| 特征 | 具体描述 | 设计影响 |
|---|---|---|
| **规模** | 352 页，469 个 TOC 条目，5 层嵌套结构 | 必须解析 TOC，按章节边界切片 |
| **内容混合** | 寄存器表、命令规格表、时序图、正文说明 | 不同内容类型需要不同切片策略 |
| **上下文依赖** | 寄存器引用其他寄存器，命令引用寄存器字段 | chunk 需携带章节路径上下文 |
| **前置噪声** | 约 20 页封面、法律声明、目录、图表索引 | 需识别并过滤 Front Matter |
| **多版本** | 需支持 JESD84-B51（5.1）、B50（5.0）、A441（4.51）| Schema 中需有 version 字段 |
| **水印干扰** | 页面含固定坐标水印文字 | 需坐标过滤 + 正则清洗 |

---

## 3. 系统架构

### 3.1 整体数据流

```
原始 PDF 文件（data/raw/）
        │
        ▼
┌───────────────────────────────┐
│    IngestionPipeline          │  src/emmc_copilot/ingestion/
│                               │
│  PDFParser                    │  ← PyMuPDF + pdfplumber 封装
│      ↓                        │
│  StructureExtractor           │  ← TOC 解析 / Front Matter 判定
│      ↓                        │
│  BlockClassifier              │  ← 逐块内容类型识别
│      ↓                        │
│  ┌──────────────────────┐     │
│  │  Chunkers（按类型）   │     │
│  │  TextChunker         │     │
│  │  TableChunker        │     │
│  │  FigureChunker       │     │
│  │  DefinitionChunker   │     │
│  └──────────────────────┘     │
│      ↓                        │
│  List[EMMCChunk]              │  ← 统一 schema 输出
└───────────────────────────────┘
        │
        ▼  写入 JSONL
data/processed/JESD84-B51_chunks.jsonl
        │
        ▼
┌───────────────────────────────┐
│    Indexing Pipeline          │  src/emmc_copilot/retrieval/
│                               │
│  EMMCIndexer                  │
│    ├── BGEEmbedder            │  ← BAAI/bge-m3，本地运行
│    └── EMMCVectorStore        │  ← ChromaDB 持久化
└───────────────────────────────┘
        │
        ▼
data/vectorstore/chroma/
  ├── emmc_docs       ← 全量可检索 chunks
  └── emmc_glossary   ← 仅术语定义 chunks（DEFINITION 类型）
```

### 3.2 模块文件结构

```
src/emmc_copilot/
├── ingestion/
│   ├── schema.py          # EMMCChunk Pydantic 模型（数据契约）
│   ├── parser.py          # PDFParser：页面级数据提取
│   ├── structure.py       # StructureExtractor：TOC + Front Matter
│   ├── classifier.py      # BlockClassifier：内容类型判定
│   ├── chunkers/
│   │   ├── text.py        # TextChunker
│   │   ├── table.py       # TableChunker
│   │   ├── figure.py      # FigureChunker
│   │   └── definition.py  # DefinitionChunker
│   ├── pipeline.py        # IngestionPipeline：编排入口
│   └── cli.py             # CLI：ingest 命令
│
└── retrieval/
    ├── embedder.py        # BGEEmbedder（懒加载）
    ├── vectorstore.py     # EMMCVectorStore（ChromaDB 封装）
    ├── indexer.py         # EMMCIndexer：JSONL → 向量 → 入库
    └── cli.py             # CLI：index / stats / search / build-bm25 命令
```

---

## 4. 核心数据结构：EMMCChunk Schema

**Schema 先行原则**：ingestion（生产者）和 retrieval（消费者）共享此契约，独立开发。

```python
class ContentType(str, Enum):
    TEXT       = "text"
    TABLE      = "table"
    FIGURE     = "figure"      # 矢量图
    BITMAP     = "bitmap"      # 位图
    DEFINITION = "definition"  # 术语定义
    REGISTER   = "register"    # 寄存器定义（TEXT 的子类型）

class EMMCChunk(BaseModel):
    chunk_id:        str           # UUID4，全局唯一
    source:          str           # "JESD84-B51.pdf"
    version:         str           # "5.1" | "5.0" | "4.51"
    page_start:      int           # PDF 物理页码（1-indexed）
    page_end:        int           # 多页 chunk 的结束页
    section_path:    list[str]     # ["6", "6.10", "6.10.4"]
    section_title:   str           # "Detailed command description"
    heading_level:   int           # 1–5，与 TOC 层级对齐
    content_type:    ContentType
    is_front_matter: bool          # True = 封面/目录等，不参与检索
    chunk_index:     int           # 同一 section 内的顺序序号
    text:            str           # 写入向量库的文本（含上下文前缀）
    raw_text:        str           # 原始提取文本（不含前缀）
    table_markdown:  str | None    # 仅 TABLE 类型
    figure_caption:  str | None    # 仅 FIGURE/BITMAP 类型
    term:            str | None    # 仅 DEFINITION 类型（术语名）
    is_row_chunk:    bool          # TABLE 行组 chunk 标记
```

**关键设计决策**：`text` 字段包含上下文前缀，`raw_text` 保留原始内容。这使检索质量更高，同时保留了原始内容供调试。

---

## 5. 各模块设计决策

### 5.1 内容类型分类（classifier.py）

判定优先级（从高到低）：

| 优先级 | 条件 | 判定类型 |
|:---:|---|---|
| 1 | pdfplumber 可提取表格 bbox，有明确行列结构 | `TABLE` |
| 2 | PyMuPDF `get_drawings()` 有聚集区域，面积 > 5000 pt² | `FIGURE` |
| 3 | PyMuPDF `get_images()` 有嵌入图片 | `BITMAP` |
| 4 | 章节标题含 "Definition" / "Abbreviation" / "Glossary" | `DEFINITION` |
| 5 | 文本块匹配寄存器模式：`[bit_range]` + 枚举值表 | `REGISTER` |
| 6 | 其余 | `TEXT` |

**重复解析问题**：PyMuPDF 与 pdfplumber 对表格边界判定不一致。解决方案：采用**中心点包含检测**（point-in-bbox）而非边界对齐检测，确保同一表格区域不被两个解析器重复处理。

### 5.2 TEXT 切片策略（chunkers/text.py）

- **切割边界**：优先在 Level-2/3 章节边界切割，不跨节
- **Chunk 大小**：600–800 tokens（BGE-M3 最优区间），overlap 100 tokens
- **跨页处理**：取消页末自动切断，文本在同一章节内跨页无缝累积，仅在章节切换或非文本块出现时 flush
- **上下文前缀**：每个 chunk 的 `text` 字段头部追加：
  ```
  [eMMC {version} | {section_path} {section_title} | Page {page_start}]
  {raw_text}
  ```
- **水印清洗**：坐标过滤（边缘固定位置）+ 正则清洗已知噪声模式

### 5.3 TABLE 切片策略（chunkers/table.py）

**核心原则**：整表存储，保留语义完整性。

- pdfplumber 提取原始单元格 → 转换为 Markdown 格式（含列标题 + 行数据）
- `text` 前缀：表格标题（`Table N —`）+ 所属章节
- **大表处理**：Markdown > 1500 tokens 时，按逻辑行组切割，每个子 chunk 携带完整列标题行（`is_row_chunk=True`）
- **表格子行处理**：实现 `_forward_fill_key`，确保合并单元格场景下每行语义完整
- **跨页表格**：检测相邻页 bbox 对齐的表格，合并为同一 chunk

**可检索性规则**：全表 chunk（`is_row_chunk=False`）默认不加入检索索引，仅保留行组 chunk，除非是寄存器映射表（CSD/EXT_CSD 等关键章节）。

### 5.4 FIGURE 切片策略（chunkers/figure.py）

不嵌入图像本身（避免多模态依赖），提取语义文本标注：

- **矢量图**：提取 bbox 内所有文字标注（状态名、信号名、时序标签）+ 图注 caption
- **位图**：提取周边 caption 和说明文字；保留图片 hash 供未来 Vision 扩展

### 5.5 DEFINITION 两轮提取（chunkers/definition.py）

**Round 1（专属章节）**：定位 TOC 中标题含 "Definition" / "Abbreviations" 的章节，正则解析每个术语条目。

**Round 2（正文内联）**：扫描正文中符合术语定义模式的段落（`术语 — 定义` 格式），补充专属章节未覆盖的术语。

DEFINITION 类型 chunk 同时写入 `emmc_docs` 和 `emmc_glossary` 两个 collection，支持后续 Agent 的 `explain_term` 工具专项查询。

---

## 6. Embedding 与向量存储

### 6.1 BGEEmbedder 设计（embedder.py）

- **模型**：`BAAI/bge-m3`（1024 维，支持中英文，MTEB 性能优异）
- **懒加载**：模型在首次调用 `embed()` 时才加载，避免 import 阶段拖慢启动
- **向量归一化**：输出 L2 归一化向量，使余弦相似度等价于点积（适配 Chroma 的 HNSW 索引）
- **批处理**：默认 batch_size=32，避免显存溢出
- **精度**：默认 FP16，在保持精度的同时减少显存占用

### 6.2 EMMCVectorStore 设计（vectorstore.py）

**双 Collection 策略**：

| Collection | 内容 | 用途 |
|---|---|---|
| `emmc_docs` | 所有可检索 chunks | Phase 2 RAG 主检索 |
| `emmc_glossary` | 仅 DEFINITION chunks | Phase 3 `explain_term` 工具专用 |

**Upsert 幂等性**：以 `chunk_id` 为主键，重复运行 `index` 命令不产生重复数据。

**metadata 过滤支持**：存储 `version`、`source`、`content_type`、`page_start` 等字段，支持 Phase 2 的版本过滤检索（`where={"version": "5.1"}`）。

---

## 7. 可检索性过滤规则

并非所有 chunk 都进入检索索引。过滤规则（按优先级）：

```
过滤掉：
  1. is_front_matter = True          → 封面、目录等无实质内容
  2. content_type = TABLE
     AND is_row_chunk = False
     AND 章节名不含关键寄存器标识    → 全表 chunk，避免与行组重复
  3. len(raw_text.strip()) < 最小阈值 → 内容不足的碎片 chunk

最小长度阈值（按类型）：
  TEXT:        20 chars
  TABLE:       25 chars（行组 chunk 本身较小）
  FIGURE:      30 chars
  BITMAP:      30 chars
  DEFINITION:   8 chars
  REGISTER:    40 chars
```

---

## 8. CLI 接口设计

### 8.1 Ingestion CLI

```bash
# 标准入库（单文件）
uv run python -m emmc_copilot.ingestion.cli ingest \
    --pdf data/raw/JESD84-B51.pdf \
    --output data/processed/

# 批量处理（目录下所有 PDF）
uv run python -m emmc_copilot.ingestion.cli ingest \
    --pdf-dir data/raw/ \
    --output data/processed/
```

### 8.2 Retrieval CLI

```bash
# 向量化入库
uv run python -m emmc_copilot.retrieval.cli index \
    --input data/processed/ \
    --vectorstore data/vectorstore/chroma/

# 查看统计
uv run python -m emmc_copilot.retrieval.cli stats

# 语义检索验证
uv run python -m emmc_copilot.retrieval.cli search \
    "HS400 mode enhanced strobe" --n 3 --version 5.1

# 构建 BM25 索引（Phase 2 使用）
uv run python -m emmc_copilot.retrieval.cli build-bm25 \
    --input data/processed/ \
    --output data/vectorstore/bm25/
```

---

## 9. 关键风险与应对

| 风险 | 描述 | 应对策略 | 状态 |
|---|---|---|:---:|
| 表格解析冲突 | PyMuPDF 与 pdfplumber 边界判定不一致，导致重复解析 | 中心点包含检测 | ✅ 已解决 |
| 表格碎片化 | 行级切割导致表格语义破碎 | 整表存储 + 仅超限才分块 | ✅ 已解决 |
| 跨页段落断裂 | 页末自动切断，段落语义不完整 | 章节内跨页累积，延迟 flush | ✅ 已解决 |
| 水印干扰 | 固定水印文字混入 chunk 内容 | 坐标过滤 + 正则清洗 | ✅ 已解决 |
| 合并单元格语义丢失 | 表格子行缺少父行 key | `_forward_fill_key` 实现 | ✅ 已解决 |
| 术语语义漂移 | eMMC 专有缩写在向量空间中语义模糊 | 独立 glossary collection | ✅ 已缓解 |

---

## 10. 验收标准

Phase 1 完成的判定标准：

```bash
# 运行完整入库流程
uv run python -m emmc_copilot.ingestion.cli ingest --pdf-dir data/raw/
uv run python -m emmc_copilot.retrieval.cli index --input data/processed/
uv run python -m emmc_copilot.retrieval.cli build-bm25 --input data/processed/

# 验证检查点
uv run python -m emmc_copilot.retrieval.cli stats
```

| 验收项 | 期望值 | 验证方式 |
|---|---|---|
| 全量 chunks 数 | 三个版本合计 > 8000 | `stats` 命令 |
| BM25 索引 chunks 数 | ≈ 9085 | `build-bm25` 输出 |
| glossary 术语数 | ≥ 50 条 | `stats --collection glossary` |
| Front Matter 占比 | < 总数 10% | 抽查 `is_front_matter=True` 数量 |
| TABLE chunks 有 markdown | `table_markdown` 字段非空 | 抽查 5 条 TABLE chunk |
| DEFINITION chunks 有术语 | `term` 字段非空 | 抽查 5 条 DEFINITION chunk |
| 语义检索可用 | 能召回相关结果 | `search "HS400 boot partition"` |

---

## 11. 交付给 Phase 2 的接口

Phase 1 完成后，Phase 2 可以使用的接口：

```python
# 检索接口（Phase 2 直接使用）
from emmc_copilot.retrieval.embedder import BGEEmbedder
from emmc_copilot.retrieval.vectorstore import EMMCVectorStore

embedder = BGEEmbedder()
store = EMMCVectorStore("data/vectorstore/chroma")

# 语义检索
results = store.query(
    query_embedding=embedder.embed_query("HS400 tuning flow"),
    n_results=5,
    where={"version": "5.1"},      # 版本过滤
    collection="docs"              # 或 "glossary"
)

# BM25 索引（Phase 2 混合检索使用）
# data/vectorstore/bm25/corpus.pkl  ← 直接加载
```

**数据契约**：每个检索结果包含 `id`、`document`（即 `EMMCChunk.text`）、`metadata`（含 `source`、`version`、`page_start`、`section_path` 等）、`distance` 字段。

---

*Phase 1 Design Document — eMMC Protocol Copilot*
*文档类型：Post-hoc Documentation（事后补写）*
*基于实际实现反向整理，版本对应 Phase 1 最终实现状态*