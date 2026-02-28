# Data Ingestion Issue Prioritization & Roadmap (Based on 50-Chunk Sample Analysis)

## 优先级 P0 (严重影响检索质量与语义)

### 1. 噪声污染 (Watermark & Header/Footer)
*   **现象**: 每个 Chunk 都包含 "ruyi"、"Downloaded by..."、"JEDEC Standard No. 84-B51" 等重复干扰信息。
*   **影响**: 污染 Embedding 向量空间，降低相关度分值。
*   **解决方案**: 在 `parser.py` 实现 BBox 坐标过滤（剔除页眉页脚区域）并增加正则全局清洗。

### 2. 残桩碎片 (Stub Chunks)
*   **现象**: 出现大量仅包含 "cont'd"、"continued on next page" 或物理分页符的碎片（Chunk 7, 10, 14, 19）。
*   **影响**: 浪费检索窗口（Context Window），导致 LLM 召回无效信息。
*   **解决方案**: 实施 `_is_valid_chunk` 逻辑（分类型最小阈值过滤）并增强 `Semantic Flow Merger`（跨页合并）。

### 3. 技术参数表误判 (Table Detection & Misclassification)
*   **现象**: 关键电平/测试表（如 Chunk 1）被误判为正文导致乱码，部分表被误判为 `figure`。
*   **影响**: 核心技术参数采集丢失，无法准确回答具体 bit 位或电压值。
*   **解决方案**: 调优 `pdfplumber` 参数（`snap_tolerance`），并支持 `vertical_strategy: text` 作为回退策略。

---

## 优先级 P1 (影响上下文准确性与搜索命中)

### 4. 章节路径漂移 (Section Path Drift)
*   **现象**: Chunk 内容与其 Metadata 中的 `section_title` 或 `section_path` 不匹配（如 Chunk 30）。
*   **影响**: 提供错误的上下文参考，可能导致 LLM 在寻找“第 X 章”时产生幻觉。
*   **解决方案**: 在 `parser.py` 的解析循环中对标题检测逻辑增加强一致性校验（Barrier Check）。

### 5. 寄存器位域破碎 (Register Map Fragmentation)
*   **现象**: 寄存器描述（如 [187] 位域）被切分到不同块中，缺乏整体视图信息。
*   **影响**: 无法回答复杂的寄存器结构问题。
*   **解决方案**: 针对 `ContentType.REGISTER` 实施特殊的合并策略，确保一个完整的位域映射区块不被分割。

### 6. Unicode/特殊字符不一致
*   **现象**: 频繁出现 `e •MMC`、`∆ TPH`、`e 2 •MMC` 等非标字符。
*   **影响**: 关键词检索（Keyword Match）命中率低。
*   **解决方案**: 在清洗阶段实施标准文本归一化（Normalize），统一替换为 `eMMC` 等核心词。

---

## 优先级 P2 (局部优化)

### 7. 表格单元格单元噪声
*   **现象**: 复杂矩阵表中混入 `i/y/u` 等线条残留字符。
*   **影响**: 局部排版略乱，语义影响相对较小。
*   **解决方案**: 在表格提取过程中增加单字符单元格过滤逻辑。
