# eMMC Protocol Copilot — 已知问题记录

本文档汇总 Phase 1（数据摄取）和 Phase 2（RAG 检索）开发过程中发现的重点问题，包括优先级分类、根因分析及解决方案状态。

---

## Phase 1：数据摄取质量问题

### 优先级 P0（严重影响检索质量与语义）

#### P0-1. 噪声污染（Watermark & Header/Footer）
- **现象**：每个 Chunk 都包含 "ruyi"、"Downloaded by..."、"JEDEC Standard No. 84-B51" 等重复干扰信息。
- **影响**：污染 Embedding 向量空间，降低相关度分值。
- **解决方案**：在 `parser.py` 实现 BBox 坐标过滤（剔除页眉页脚区域）并增加正则全局清洗。
- **状态**：✅ 已解决

#### P0-2. 残桩碎片（Stub Chunks）
- **现象**：出现大量仅包含 "cont'd"、"continued on next page" 或物理分页符的碎片（Chunk 7、10、14、19）。
- **影响**：浪费检索窗口（Context Window），导致 LLM 召回无效信息。
- **解决方案**：实施 `_is_valid_chunk` 逻辑（分类型最小阈值过滤）并增强 Semantic Flow Merger（跨页合并）。
- **状态**：✅ 已解决

#### P0-3. 技术参数表误判（Table Detection & Misclassification）
- **现象**：关键电平/测试表（如 Chunk 1）被误判为正文导致乱码，部分表被误判为 `figure`。
- **影响**：核心技术参数采集丢失，无法准确回答具体 bit 位或电压值。
- **解决方案**：调优 `pdfplumber` 参数（`snap_tolerance`），并支持 `vertical_strategy: text` 作为回退策略。
- **状态**：✅ 已解决

---

### 优先级 P1（影响上下文准确性与搜索命中）

#### P1-4. 章节路径漂移（Section Path Drift）
- **现象**：Chunk 内容与其 Metadata 中的 `section_title` 或 `section_path` 不匹配（如 Chunk 30）。
- **影响**：提供错误的上下文参考，可能导致 LLM 在寻找"第 X 章"时产生幻觉。
- **解决方案**：在 `parser.py` 的解析循环中对标题检测逻辑增加强一致性校验（Barrier Check）。
- **状态**：✅ 已解决

#### P1-5. 寄存器位域破碎（Register Map Fragmentation）
- **现象**：寄存器描述（如 [187] 位域）被切分到不同块中，缺乏整体视图信息。
- **影响**：无法回答复杂的寄存器结构问题。
- **解决方案**：针对 `ContentType.REGISTER` 实施特殊的合并策略，确保一个完整的位域映射区块不被分割。
- **状态**：🔶 部分缓解（Phase 2 邻居扩展召回相邻行），未完全解决

#### P1-6. Unicode/特殊字符不一致
- **现象**：频繁出现 `e •MMC`、`∆ TPH`、`e 2 •MMC` 等非标字符。
- **影响**：关键词检索（Keyword Match）命中率低。
- **解决方案**：在清洗阶段实施标准文本归一化（Normalize），统一替换为 `eMMC` 等核心词。
- **状态**：✅ 已解决

---

### 优先级 P2（局部优化）

#### P2-7. 表格单元格噪声
- **现象**：复杂矩阵表中混入 `i/y/u` 等线条残留字符。
- **影响**：局部排版略乱，语义影响相对较小。
- **解决方案**：在表格提取过程中增加单字符单元格过滤逻辑（仅过滤 `i`，保留 `Y/N/U` 等语义字符）。
- **状态**：✅ 已解决（见 Bug #10）

---

### 代码缺陷（Code Review）

#### Bug 8. `stats()` front_matter 数值严重失真（`pipeline.py:134–136`）🔴
- **现象**：运行输出 `front_matter: 391`，而实际 `is_front_matter=True` 的 chunk 只有 76 条，虚报 315 条。
- **根因**：`front_matter_count = total - searchable - short_filtered` 推导公式未考虑 full-table chunks 被排除但既不是 front_matter 也不是 short_filtered 的情况。
- **解决方案**：直接统计 `sum(1 for c in self.chunks if c.is_front_matter)`。
- **状态**：✅ 已修复

#### Bug 9. `_is_valid_chunk()` 解析 `chunk.text` 去 prefix 不可靠（`pipeline.py:51–68`）🔴
- **现象**：82 个 text chunk 被误过滤。TABLE chunk 的 text 第二行是 caption 而非纯内容；TEXT chunk 中信号名（"DAT1"、4字符）被 `min_chars=40` 过滤掉。
- **根因**：应使用 `raw_text` 字段（存储去掉 prefix 的内容）做长度判断，而非解析 `text` 字符串。
- **解决方案**：改用 `chunk.raw_text.strip()` 进行判断。
- **状态**：✅ 已修复

#### Bug 10. 单字符噪声过滤误删 Y/N 列数据（`parser.py:470–471`）🔴
- **现象**：`if len(c) == 1 and c.lower() in 'iyun'` 会把表格单元格中的 `'y'`、`'n'`、`'u'` 替换为 `None`。
- **根因**：`'Y'`/`'N'` 是 eMMC spec capability 表格的标准值（Supported/Not Supported）；`'U'` 表示 Undefined，均有语义；仅 `'i'` 是 pdfplumber 误读竖线的典型残留。
- **解决方案**：仅过滤 `c.lower() in 'i'`，保留其余单字符。
- **状态**：✅ 已修复

#### Bug 11. Definition 文本收集使用尚未更新的 `current_section`（`pipeline.py:244–251`）🟡
- **现象**：同一页内存在 sub-page section 切换时，新 section 的文本被错误归入上一个 section 的定义桶。
- **根因**：收集定义文本的循环在执行 sub-page 检测（更新 `current_section`）的循环之前执行。
- **解决方案**：将两个循环合并为一个，先做 section 检测再收集文本。
- **状态**：✅ 已修复

#### 设计问题 12. `_normalize_heading()` 与 `_normalize_label()` 重复实现（`pipeline.py` vs `structure.py`）🟡
- **现象**：两个函数实现完全相同，分别独立定义在两个模块。一旦有人修改其中一个将静默失效。
- **解决方案**：将 `_normalize_label()` 从 `structure.py` export，在 `pipeline.py` 直接导入复用，删除 `_normalize_heading()`。
- **状态**：⬜ 待处理（低优先级，功能不受影响）

#### 设计问题 13. `label_to_section` 重复 key 静默覆盖（`structure.py:131–133`）🟡
- **现象**：eMMC spec 中多个章节可能拥有相同短标题（如多处"General"），字典推导式后者会静默覆盖前者。
- **解决方案**：只保留第一次出现的唯一 label，跳过后续重复。
- **状态**：✅ 已修复

#### 维护问题 14. 异常静默吞没（`parser.py:479–480`）🟢
- **现象**：`except Exception: pass` 让 pdfplumber 解析失败时不留任何记录，表格静默丢失。
- **解决方案**：改为 `logger.warning("pdfplumber failed on page %d: %s", idx + 1, exc)`。
- **状态**：✅ 已修复

#### 维护问题 15. `jEDEC` 拼写错误（`pipeline.py:41`）🟢
- **现象**：`_NOISE_PATTERNS` 中写作 `jEDEC Standard`，应为 `JEDEC Standard`。`re.IGNORECASE` 保证功能不受影响，但拼写混乱。
- **解决方案**：改为 `JEDEC`。
- **状态**：✅ 已修复

#### 维护问题 16. `PageModel` 未使用的 import（`pipeline.py:15`）🟢
- **现象**：`from .parser import PDFParser, PageModel` 中 `PageModel` 在模块内未被直接引用。
- **解决方案**：移除 `PageModel`。
- **状态**：✅ 已修复

---

## Phase 2：检索质量问题

### 背景

Phase 2 基于混合检索（Dense BGE-M3 + BM25 + RRF）实现，测试集 Q1–Q20 共 20 道问题，结果：
- 正确：11/20（Q2、Q3、Q6、Q7、Q9、Q11、Q14、Q15、Q16、Q17、Q18）
- 轻微不足：3/20（Q8、Q10、Q13）
- 严重遗漏（检索未命中）：6/20（Q1、Q4、Q5、Q12、Q19、Q20）

详细测试内容见 `docs/hybrid_rag_test_results.md`。

---

### 根因分析

| 问题类别 | 受影响题目 | 根因 |
|---------|-----------|------|
| BM25 + Dense 均未命中目标 chunk | Q4、Q12、Q19 | 相关寄存器行级 chunk 未被召回 |
| 检索到表但 LLM 未逐行解析 | Q1、Q5 | 多字段表未逐行对应输出 |
| 检索到章节但缺少属性列（默认值）| Q20 | EXT_CSD 表 Properties 列 chunk 未命中 |
| LLM 推理不足（上下文已有但未利用）| Q8、Q10、Q13 | 需要跨 chunk 推断或使用领域通用约定 |

---

### 严重遗漏详情

#### R2-1. HS_TIMING [185] 默认值 0x0 遗漏（Q1）
- **现象**：答案仅给出 0x1/0x2/0x3，漏掉 Table 143 中 `0x0 = Backwards compatible interface timings` 的定义。
- **根因**：TABLE chunk 以行级切割存储，默认值行所在的 row-chunk 未被 BM25 或 Dense 召回。
- **已实施改进**：邻居扩展（neighbor_expand）可部分缓解，n_candidates 从 20 提升至 40。
- **待解决**：TABLE chunk 的 `table_markdown` 应独立建 BM25 索引以提升全行覆盖。

#### R2-2. BKOPS_EN [163] Auto BKOPS 值 0x02 遗漏（Q4）
- **现象**：答案声称"找不到 0x02 的含义"。规范明确定义 `0x02 = Auto Background Operations 使能`。
- **根因**：该行级 row-chunk 未被召回，BM25 词频对 `0x02` 的精确匹配不敏感。
- **已实施改进**：Query expansion 生成含 `BKOPS_EN [163] 0x02` 的变体查询；n_candidates=40。
- **待解决**：精确十六进制值查询的召回率仍有提升空间。

#### R2-3. CSD [21:15] 多字段识别失败（Q5）
- **现象**：答案将 [21:15] 误当作单一字段查找，实际对应 6 个独立字段（WRITE_BL_PARTIAL、FILE_FORMAT_GRP、COPY、PERM_WRITE_PROTECT、TMP_WRITE_PROTECT、FILE_FORMAT）。
- **根因**：CSD 寄存器表格以行级 chunk 存储，多字段位范围查询无法用单次检索覆盖全部相关行。
- **待解决**：需要寄存器表格的整表检索能力，或支持 bit 范围覆盖查询。

#### R2-4. CMD46 非法 Task ID 的 Device Status 错误位（Q12）
- **现象**：答案只说"返回 Illegal Command"，未给出具体 bit 编号（bit 22 = `ILLEGAL_COMMAND`）。
- **根因**：Device Status 位定义表的对应 row-chunk 未命中。
- **已实施改进**：System prompt 中注入 `Device Status bit 22 = ILLEGAL_COMMAND` 领域约定。
- **待解决**：仅靠 prompt 约定无法覆盖所有 bit 的精确定义，需改善召回。

#### R2-5. eMMC 4.51 Sanitize 最小超时时间（Q19）
- **现象**：答案直接放弃，称"无法回答"。B451 文档应有对应超时描述。
- **根因**：版本过滤默认为 5.1，导致 B451 特有内容无法通过隐式版本检测召回；需用户显式指定版本或检索策略覆盖全版本。
- **已实施改进**：支持 `EMMC_VERSION=all` 禁用版本过滤；query expansion 含版本关键词。
- **待解决**：需完善跨版本内容的主动召回策略。

#### R2-6. BARRIER_EN [31] 上电默认值（Q20）
- **现象**：答案称"未明确说明"，实际规范明确为上电默认值 0（disabled）。
- **根因**：EXT_CSD 表的 Properties 列（含 power-on value）所在 chunk 未命中。
- **待解决**：EXT_CSD 字段的 power-on value、R/W 属性应在 chunk metadata 中显式存储，而非依赖全文检索。

---

### 已实施的技术方案调整

| 调整项 | 描述 | 涉及文件 |
|--------|------|---------|
| 混合检索（Dense + BM25 + RRF）| 解决精确标识符（EXT_CSD[33]、CMD6 等）的语义盲区 | `retrieval/bm25_index.py`, `retrieval/hybrid_retriever.py` |
| n_candidates=40, n_results=15 | 扩大候选池以提升召回覆盖 | `retrieval/hybrid_retriever.py` |
| 邻居扩展（neighbor_expand）| 对 TABLE/REGISTER chunk 扩展相邻行，缓解行级切割碎片化 | `retrieval/hybrid_retriever.py` |
| Query Expansion | LLM 生成 2 个英文变体查询，三路去重合并，提升精确标识符召回 | `qa/chain.py` |
| 版本感知过滤 | 默认检索 eMMC 5.1；从 query 自动检测版本；支持多版本 `$in` 过滤 | `retrieval/version_filter.py` |
| 引用格式升级 | 从裸 `[N]` 升级为 `[B51 §7.4.111 p.246]`，支持用户直接定位 PDF 页码 | `qa/chain.py`, `qa/prompt.py` |
| Prompt 领域约定 | 注入小端字节序、非存在字段明确否定、Device Status bit 22 等约定 | `qa/prompt.py` |
| 未引入 Re-ranking | 评估后认为 Cross-Encoder re-rank 成本高、收益边际；当前问题根因在召回而非排序 | — |

---

### 未解决的高优先级问题

| 编号 | 问题 | 影响 | 建议方案 |
|------|------|------|---------|
| U-1 | TABLE row-chunk 覆盖不完整 | Q1、Q4、Q5 | `table_markdown` 独立建 BM25 索引，或整表检索 |
| U-2 | EXT_CSD Properties 列（默认值、R/W 属性）未结构化存储 | Q20 | chunk metadata 显式存储 power-on value 和 access type |
| U-3 | 精确十六进制值（`0x02`）BM25 命中不稳定 | Q4 | BM25 tokenizer 对 hex 值的 n-gram 增强 |
| U-4 | 跨版本内容（B451 特有）在默认 5.1 过滤下无法召回 | Q19 | 版本感知 fallback 策略：若主版本零结果则扩展搜索 |
| U-5 | P1-5 寄存器位域破碎（Register Map Fragmentation）| Q5 等 | Phase 3 前需对 REGISTER type chunk 实施完整位域合并策略 |
