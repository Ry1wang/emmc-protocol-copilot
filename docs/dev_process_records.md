## 开发路线
[✅] Phase 0  调研选型
[ ] Phase 1  数据准备
[ ] Phase 2  RAG核心 
[ ] Phase 3  Agent化 
[ ] Phase 4  效果评估
[ ] Phase 5  界面部署

---

### Phase 0
[✅] Claude 提供技术选型分析文档，最终确定技术选型

---

### Phase 1
目标： 能读入eMMC文档并完成向量化存储
关键任务：
[✅] 收集 eMMC 规范文档（JESD84系列，JEDEC官网可下载）
[✅] 搭建 Python 环境（推荐用 uv 管理依赖）
[ ] 实现文档 → 切片 → Embedding → 存入 Chroma 的完整链路
里程碑： python ingest.py 一键完成文档入库

搭建 Python 环境说明
```
1. 使用 Python 3.11 , uv 管理依赖，区分 生产依赖和开发依赖
2. 创建 .env.example，将配置信息保存到该文件，如API_KEY, URL等
3. 创建清晰的项目目录，如`src/`, `tests/`, `data/`, `log/`等
4. 配置 .gitignore, 屏蔽 .env、.venv、log等
```

文档切片逻辑说明
```
请你基于以下考量设计文档切片逻辑：
1. 我们需要充分考虑eMMC协议文档的特点——高度结构化、数据密度极高、上下文深度依赖，设计出能最大程度保证数据准确的切片方式。
2. 针对表格、矢量图、位图和文字，需要有不同的切片方式，保留的元数据格式需要统一。
3. 需要提取文档中的术语定义，以便后续Agent能够正确解释。
4. PDF文档的页码需要保留，以便后续Agent能够正确引用。
5. PDF文档前面的目录、序号需要与正文的解析区别开。
```

实现切片后检验效果
```
1. 是否存在重复解析表格数据？
存在。原因是两个库各自独立提取数据，PyMuPDF提取所有 text_blocks(含表格内部文字)，pdfplumber独立提取 table_blocks(相同内容的结构化版本)。旧的去重机制是判断文本块与表格区域重叠 > 60% 时跳过，避免重复分类，但由于两个解析库(PyMuPDF和pdfplumber)对"同一个框"的边界划定不一致，导致系统误判，把本来属于表格里的字当成了表格外的正文，造成了数据重复。
修复方案是将面积比检测替换为中心点包含检测(+2pt 容差)，也就是判断文本块的几何中心是否落在表格区域内。

2. 表格数据是以一整张表的形式存在，还是拆分了每一行数据？有些表格最底部可能存在Note，是否有保留这些Note？表头的单元格可能有换行的情况，如 146页的Table 49，表头是否取的"CMD Index"，而不是"CMD"和"Index"？
整张表存储，序列化为 Markdown，切片仅在超过 6000 字符时才按行组分块。
表格底部的Note被当成普通数据行，混入表格最后一行，修复后独立显示Note。
多行表头没有正确合并，修复后正确合并。

3. 表格中，多行子行的处理是否正确？比如还是刚才的 Table 49，第一个数据行是CMD0，它的第二列有三种分类，是否正确将这些类别序列化？另外，数据单元格中存在的换行符，是否有做清除？
修复前：sub-row 的 col 0 为空，RAG                        
检索到该行时不知道它属于哪条命令：
| CMD0 | bc  | [31:0] 00000000 | ... |
|      | bc  | [31:0] F0F0F0F0 | ... |   ← 无法独立理解
|      | —   | [31:0]FFFFFFFA  | ... |   ← 无法独立理解

修复后（_forward_fill_key）：每行自带主键，任意一行单独取
出都语义完整：
| CMD0 | bc  | [31:0] 00000000 | ... |
| CMD0 | bc  | [31:0] F0F0F0F0 | ... |
| CMD0 | —   | [31:0]FFFFFFFA  | ... |

单元格内的换行符已经处理。

4. 将表格以整张表存储，做向量检索的时候是否会权重降低？比如我想了解 CMD0 的参数含义，预期是检索 Table 49的信息。

5. 文本处理部分，如果一个无序列表格式的文字段落跨页，是否会被切割？如果切割，如何保证语义的连续性和完整性？
每读完一页就强制把文字切断（Flush），而新方案取消了页末自动切断，新的逻辑是跨页无缝合并和智能触发切段（Flush）的三个阈值。

6. 让 Gemini 从 chunks.json 文件中随机抽样20条数据，分析数据内容、格式是否有问题。
结论：该版本的数据已具备基础可用性，能够回答关于章节位置和简单定义的查询，但在处理复杂寄存器位域（Bit Fields）和跨页长段落时，鲁棒性（Robustness）仍有提升空间。

发现的主要问题：
A. 碎片化与“残桩” Chunk (Stub Chunks)
现象：多个 Chunk（如 Chunk 7, 10, 14, 19）内容只有“cont’d”、“DAT0 Optional”或空页眉。
影响：在 RAG 检索时，这些 chunk 可能会被召回但由于缺乏实际语义，会浪费上下文窗口（Context Window）。
根源：目前的解析逻辑是按页物理分割，导致跨页的标题或末尾琐碎文字被独立切片。
B. 表格解析质量参差不齐 (Table Quality)
类型识别错误：部分原本是表格的内容被识别成了 figure（如 Chunk 3 的 Table 37，Chunk 18 的 Table 145）。
空表问题：Chunk 15 和 Chunk 20 只有表头（Driver Type, Bit 15...），没有任何数据行。
噪声干扰：复杂矩阵表（如 Chunk 17）中混入了 i, y, u 等字符。这通常是 PDF 水印或线条在文本提取时产生的干扰。
C. 水印干扰 (Watermark Noise)
现象：几乎每个 Chunk 都在 raw_text 中包含 ruyi（水印名）或 Downloaded by ru yi... 等信息。
影响：增加了 Embedding 的噪声，可能导致检索相关度偏移。
D. 寄存器/协议格式处理 (Register Maps)
亮点：Chunk 9 (Register) 成功捕捉到了 eMMC 的寄存器描述格式（Size, Type, Description），这对技术问答非常有用。
E. 关键表格被误判为正文 (Table-as-Text)
现象：Chunk 1 (Bus testing procedure) 包含了非常关键的总线测试电平表，但被识别成了 TEXT，导致所有的位信息（0, 10xxxxxxxxxx...）挤在了一起，完全失去了物理对应关系。
后果：用户询问“DAT1 的测试 pattern 是什么”时，LLM 很难从这段乱序文字中给出精确答案。
根源：pdfplumber 的默认设置可能漏掉了这种只有水平线或者完全靠对齐生成的表。
F. “幽灵”寄存器字段 (Phantom Register Fields)
现象：Chunk 18 (ERASE_TIMEOUT_MULT) 和 Chunk 21 (CONTEXT_CONF)。
内容：0x00 Not defined 0x01 ... 这种典型的寄存器位定义被提取成了碎片。Chunk 21 甚至只有一行 Context configuration CONTEXT_CONF 15 R/W/E _P [51:37]。
后果：寄存器的位偏移（Bit Offset）数据分散在不同 Chunk 中，无法提供完整的寄存器视图。
G. Section Path 深度漂移 (Path Drift)
现象：Chunk 30。它的 section_title 是 e•MMC System Overview，但正文开头却是 5.3 e •MMC Device Overview。
根源：Parser 在检测到新的标题时可能没有及时“切断”并更新当前 Chunk 的 Metadata，导致 5.1 的路径里混入了 5.3 的内容。
H. 特殊字符与 Unicode 编码 (Encoding Issues)
现象：Chunk 2, 4, 30 中频繁出现 e •MMC（中间带有点号）、e 2 •MMC、∆ TPH。
后果：如果用户搜索 eMMC 或 TPH，模糊匹配可能会因为这些不可见字符/点号而失效。

说明与改进建议：
A. 实施语义流合并 (Semantic Flow Merger)：
建议：取消强制页末 Flush。只有当检测到 heading_level 变化或 content_type 切换（且距离上个 chunk 较远）时才触发 Flush。这样可以消除“cont'd”类的残桩。
B. 水印与页header/footer 过滤：
操作：在 parser.py 中增加坐标过滤（BBox Filter），剔除页面顶端和底端的固定区域。利用正则清洗 ruyi 和 ry_lang@outlook.com 等固定噪声。
C. 精细化表格处理：
操作：针对寄存器表，pdfplumber 的 table_settings 需要针对“垂直线不完整”的表进行调优（如开启 snap_tolerance）。
D. 短 Chunk 丢弃：
操作：在 Ingestion 阶段对 text 长度小于 30 字符且不含关键信息的 chunk 直接丢弃。

下指令：先列出问题解决优先级和解决方案，确认一个方案修复一个问题。

```
---

### Phase 2
目标： 能基于eMMC文档准确回答问题
关键任务：
[ ] 实现基础 RAG：检索相关chunk → 拼接Prompt → LLM生成
[ ] 优化检索质量（混合检索 = 语义检索 + BM25关键词检索）
[ ] 添加引用溯源（回答时标注来自文档第几页，面试亮点！）
里程碑： 能正确回答"eMMC的Boot分区大小是多少？"此类问题

---

### Phase 3
目标： 从简单问答升级为有推理能力的智能体
[ ] 用 LangGraph 构建 Agent，赋予它多个工具：
    - Tool 1: eMMC文档检索（RAG）
    - Tool 2: 术语解释（针对专业缩写）
    - Tool 3: 规范对比（不同eMMC版本差异）
    - Tool 4: 计算工具（如容量/时序计算）
[ ] Agent 可以根据问题自动决定调用哪个工具，支持多轮追问。
里程碑： 能处理"eMMC 5.1和5.0在HS400模式上有什么区别？分别适用于什么场景？"这类复杂问题

---

### Phase 4
目标： 用数据证明你的系统有效（面试核心加分项！）
[ ] 构建一个小型测试集（20~30个eMMC相关Q&A对）
[ ] 使用 RAGAS 框架评估：
    - faithfulness（忠实度）
    - answer_relevancy（相关性）
    - context_recall（召回率）
[ ] 记录优化前后的指标变化
里程碑： 能在PPT/README里展示一张评估指标对比图

---

### Phase 5
目标： 有可演示的产品界面
[ ] 用 Streamlit 或 Gradio 快速搭建聊天界面（1-2小时）
[ ] 部署到 Hugging Face Spaces 或 Railway（免费）
[ ] 整理 GitHub README（架构图、演示GIF、技术栈徽章）
里程碑： 有一个可以直接甩链接给面试官的在线Demo