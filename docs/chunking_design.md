# Phase 1 — eMMC PDF 文档切片方案设计

## Context

eMMC 协议文档（JESD84-B51.pdf 等）具有以下特点：
- 352 页，469 个 TOC 条目，5 层嵌套结构
- 内容类型混合：寄存器定义表、命令规格表、时序状态机图、正文说明
- 上下文深度依赖（寄存器引用其他寄存器、命令引用寄存器字段）
- 前置 Front Matter 约 20 页（封面、法律声明、目录、图表索引）

目标：实现能最大程度保证语义完整性的切片管线，支持后续 RAG + Agent 准确检索。

---

## 模块结构

```
src/emmc_copilot/ingestion/
├── schema.py          # 统一 Chunk 元数据 Pydantic 模型
├── parser.py          # PDFParser：PyMuPDF + pdfplumber 封装，构建页面模型
├── structure.py       # StructureExtractor：TOC 解析 / Front Matter 判定 / 章节映射
├── classifier.py      # BlockClassifier：逐块内容类型识别（text/table/figure/definition）
├── chunkers/
│   ├── __init__.py
│   ├── text.py        # TextChunker：带章节上下文的递归字符分割
│   ├── table.py       # TableChunker：pdfplumber 表格 → Markdown → Chunk
│   ├── figure.py      # FigureChunker：向量图/位图 bbox → 标题 + 文字标注 → Chunk
│   └── definition.py  # DefinitionChunker：术语定义提取
├── pipeline.py        # IngestionPipeline：编排所有 Chunker，输出统一 Chunk 列表
└── cli.py             # CLI 入口：`python -m emmc_copilot.ingestion.cli ingest`
```

---

## 统一元数据 Schema（schema.py）

```python
class ContentType(str, Enum):
    TEXT       = "text"
    TABLE      = "table"
    FIGURE     = "figure"      # 向量图（矢量）
    BITMAP     = "bitmap"      # 位图
    DEFINITION = "definition"  # 术语定义
    REGISTER   = "register"    # 寄存器定义（text 的子类型）

class EMMCChunk(BaseModel):
    chunk_id:       str           # UUID4
    source:         str           # "JESD84-B51.pdf"
    version:        str           # "5.1" | "5.0" | "4.51"
    page_start:     int           # PDF 物理页码（1-indexed）
    page_end:       int           # 多页 chunk 的结束页
    section_path:   list[str]     # ["6", "6.10", "6.10.4"]（章节编号列表）
    section_title:  str           # "Detailed command description"
    heading_level:  int           # 1-5，与 TOC 层级对齐
    content_type:   ContentType
    is_front_matter: bool         # True = 封面/目录/法律声明等，不参与向量检索
    chunk_index:    int           # 同一 section 内的顺序序号
    text:           str           # 最终写入向量库的文本（含 prefix 上下文）
    raw_text:       str           # 原始提取文本（不含 prefix）
    table_markdown: str | None    # 仅 TABLE 类型填充
    figure_caption: str | None    # 仅 FIGURE/BITMAP 类型填充
    term:           str | None    # 仅 DEFINITION 类型填充（术语名）
```

---

## 各模块实现细节

### 1. structure.py — 文档结构提取

**目的**：解析 TOC，构建章节树，判定每页所属章节和是否为 Front Matter。

**关键逻辑**：
- `doc.get_toc()` 获取 TOC 列表（469 条，5 层）
- 构建 `{page_num: SectionNode}` 映射（每页属于哪个章节）
- **Front Matter 判定**：TOC 中第一个 Level-1 条目对应的页码即为 body 起始页；所有物理页码 < body_start 的页面标记为 `is_front_matter=True`
- TOC 页本身：提取章节树结构供映射使用，但不生成可检索的 Chunk

```
body_start_page = toc[first_level1_entry].page  # 通常约第 20 页
```

---

### 2. classifier.py — 内容类型分类

**目的**：对每页的每个内容区块判定类型。

**判定规则（按优先级）**：

| 条件 | 判定类型 |
|------|---------|
| `pdfplumber` 能 extract 到表格 bbox，且该区域有明确行列 | `TABLE` |
| `page.get_drawings()` 有聚集区域且面积 > 5000 pt² | `FIGURE`（向量图）|
| `page.get_images()` 有嵌入图片 | `BITMAP` |
| 页面所属章节标题含 "Definition" / "Abbreviation" / "Glossary" | `DEFINITION` |
| 文本块匹配寄存器模式：`[bit_range]` + 枚举值表 | `REGISTER` |
| 其余文本块 | `TEXT` |

---

### 3. chunkers/text.py — 文本切片

**策略**：基于章节边界的递归字符分割，加章节上下文前缀。

- **分割粒度**：优先在 Level-2/3 章节边界切割（不跨节）
- **Chunk 大小**：600–800 tokens（BGE-M3 最优区间），overlap 100 tokens
- **上下文前缀**：每个 chunk 的 `text` 字段头部追加：

  ```
  [eMMC {version} | {section_path} {section_title} | Page {page_start}]
  {raw_text}
  ```

- **REGISTER 子类型**：寄存器定义（寄存器名 + 所有位字段描述 + 值枚举表）作为**原子单元**，不拆分；若超过 1200 tokens 则按位字段分组切割，每组携带寄存器名 header。

---

### 4. chunkers/table.py — 表格切片

**策略**：完整保留表格语义，序列化为 Markdown。

- 使用 `pdfplumber.page.extract_tables()` 提取原始单元格
- 转换为 Markdown 格式（列标题 + 行数据）
- 在 `text` 字段前缀添加：表格标题（Table N — ）+ 所属章节
- **大表处理**：若 Markdown > 1500 tokens，按逻辑行组（如按 Command Class）切割，每个子 Chunk 携带完整列标题行
- **表格延续页**：检测相邻页 bbox 对齐的表格，合并为同一 Chunk

```
# text 示例
[eMMC 5.1 | 6.10.4 Detailed command description | Page 146]
Table 49 — Basic commands (class 0 and class 1)

| CMD INDEX | Type | Argument | Response | Description |
| CMD0      | bc   | [31:0] stuff bits | ...  | GO_IDLE_STATE |
...
```

---

### 5. chunkers/figure.py — 图形切片

**策略**：不嵌入图像本身，提取语义文本标注。

**向量图（矢量图）**：
- 找到 drawing 聚集的 bbox（矩形包围盒）
- 提取 bbox 内所有文本块（图内文字标注：状态名、信号名、时序标签等）
- 提取 bbox 上方/下方最近的 caption 文本（含 "Figure N —"）
- `text` = `[Figure {caption}]\n{bbox内所有文字标注，换行分隔}`

**位图（bitmap，当前 B51 正文中无，但需支持）**：
- 提取周边 caption 和说明文字
- `text` = `[Figure {caption} - bitmap image]\n{surrounding_text}`
- `raw_text` 保存图片 hash 供未来 Vision 模型扩展

---

### 6. chunkers/definition.py — 术语定义提取

**两轮提取**：

**Round 1（专属章节）**：
- 定位 TOC 中标题含 "Definition" / "Abbreviations" / "Glossary" 的章节页面
- 使用正则解析每个术语条目，模式：
  ```
  r"^([A-Z][A-Z0-9_/\-]+)\s*[:\-–]\s*(.+)"   # 缩写定义
  r"^\d+\.\d+\s+([^\.]+)\s*\n(.+)"             # 编号定义
  ```
- 每条术语独立成一个 Chunk（`content_type=DEFINITION`，`term=术语名`）

**Round 2（行内定义）**：
- 全文扫描含 `"means"`, `"is defined as"`, `"refers to"`, `"(abbreviated as"` 的句子
- 提取为定义 Chunk，同时在来源 text chunk 的元数据中标注 `has_inline_definition=True`

**术语 Glossary 集合**：所有 DEFINITION Chunk 额外存入 Chroma 的独立 collection `"emmc_glossary"`，供 Agent 工具优先查询。

---

## 数据流向

```
docs/protocol/*.pdf
    │
    ├─▶ structure.py        → TOC 树 + 章节→页面映射 + Front Matter 边界
    │
    ├─▶ parser.py           → 每页的 PageModel（blocks列表: bbox, type, text/drawing/image）
    │
    ├─▶ classifier.py       → 每个 block 标注 ContentType
    │
    ├─▶ pipeline.py         → 路由至对应 Chunker
    │       ├── text.py     → List[EMMCChunk] (TEXT / REGISTER)
    │       ├── table.py    → List[EMMCChunk] (TABLE)
    │       ├── figure.py   → List[EMMCChunk] (FIGURE / BITMAP)
    │       └── definition.py → List[EMMCChunk] (DEFINITION)
    │
    └─▶ 输出
            ├── data/processed/{version}_chunks.jsonl    # 所有 Chunk（含 front matter 标记）
            └── data/vectorstore/chroma/                 # 仅 is_front_matter=False 的 Chunk
                    ├── collection: "emmc_docs"          # 所有可检索 Chunk
                    └── collection: "emmc_glossary"      # 仅 DEFINITION Chunk
```

---

## Front Matter 处理细则

| 区域 | 处理方式 | 进入向量库 |
|------|---------|-----------|
| 封面页、法律声明 | 跳过，不生成 Chunk | ❌ |
| 目录页（TOC） | 提取章节树结构，不生成 Chunk | ❌ |
| 图表索引（Figure/Table List）| 提取图表编号→页码映射，不生成 Chunk | ❌ |
| 前言（Foreword / Scope） | 生成 TEXT Chunk，标记 `is_front_matter=True` | ❌ |
| 规范性引用文件（Normative References）| 生成 TEXT Chunk，标记 `is_front_matter=True` | ❌ |

---

## 关键实现注意事项

1. **表格与文本重叠**：pdfplumber 表格 bbox 与 PyMuPDF 文本块可能重叠；需从文本 pipeline 中移除已被 TableChunker 处理的 bbox 区域。

2. **多列布局**：部分页面双栏排版；需按 x 坐标排序文本块（x < 中线为左栏，否则右栏），分别处理后再合并。

3. **寄存器位字段表**：典型格式如 `EXT_CSD[bit]` + 值枚举，识别关键词 `"Reserved"`, `"R/W"`, `"OTP"`, `"[bits"` 来触发 REGISTER 类型。

4. **页码偏移**：JESD84-B51 物理页 1 = PDF 封面，物理页 5 ≈ TOC 第 1 页，文档中印刷页码与物理页码有偏移；统一使用 **PyMuPDF 物理页码（0-indexed 转 1-indexed）** 作为 `page_start`。

5. **版本标签**：从文件名提取版本（`B51` → `"5.1"`），注入所有 Chunk 的 `version` 字段。

---

## 实现顺序

1. **schema.py** — 定义 EMMCChunk 和 ContentType（无依赖，先实现）
2. **parser.py** — PDFParser 封装，返回 PageModel 列表
3. **structure.py** — StructureExtractor（依赖 parser）
4. **classifier.py** — BlockClassifier（依赖 parser 输出的 PageModel）
5. **chunkers/definition.py** — DefinitionChunker（相对独立）
6. **chunkers/text.py** — TextChunker（依赖 structure + classifier）
7. **chunkers/table.py** — TableChunker（依赖 pdfplumber）
8. **chunkers/figure.py** — FigureChunker（依赖 PyMuPDF drawings）
9. **pipeline.py** — IngestionPipeline（依赖所有 Chunker）
10. **cli.py** — CLI 入口

---

## 验证方式

```bash
# 对单个 PDF 运行切片，输出 JSONL
uv run python -m emmc_copilot.ingestion.cli ingest \
    --pdf docs/protocol/JESD84-B51.pdf \
    --output data/processed/

# 验证检查点
# 1. 检查 Front Matter：is_front_matter=True 的 chunk 数量应 < 总数的 10%
# 2. 检查术语定义：glossary 集合应有 50+ 条
# 3. 检查表格：content_type=table 的 chunk 应有 table_markdown 字段非空
# 4. 检查图形：content_type=figure 的 chunk 的 figure_caption 应非空
# 5. 抽查寄存器：content_type=register 的 chunk 应包含 EXT_CSD 关键字
# 6. 检查页码连续性：相邻 chunk 的 page_start 应单调不减
```
