# eMMC Protocol Copilot — 开发路线

## 项目概述
eMMC 协议智能问答 Agent，基于 RAG 技术实现技术文档的智能检索与问答。

---

## 开发路线总览
| Phase | 状态 | 阶段目标 |
|-------|------|----------|
| Phase 0 | ✅ 已完成 | 调研选型 |
| Phase 1 | ✅ 已完成 | 数据准备 |
| Phase 2 | ✅ 已完成 | RAG 核心 |
| Phase 3 | 待开发 | Agent 化 |
| Phase 4 | 待开发 | 效果评估 |
| Phase 5 | 待开发 | 界面部署 |

---

## Phase 0: 调研选型 ✅
- Claude 提供技术选型分析文档，最终确定技术选型
- **技术栈**: LangChain v0.3, LangGraph, PyMuPDF+pdfplumber, ChromaDB→Pinecone, BGE-M3, DeepSeek, Chainlit, RAGAS

---

## Phase 1: 数据准备 ✅
**目标**: 能读入 eMMC 文档并完成向量化存储

**关键任务**:
- [✅] 收集 eMMC 规范文档（JESD84 系列，JEDEC 官网可下载）
- [✅] 搭建 Python 环境（使用 uv 管理依赖）
- [✅] 实现文档 → 切片 → Embedding → 存入 Chroma 的完整链路

**里程碑**: `python ingest.py` 一键完成文档入库

### 文档切片设计要点
1. 充分考虑 eMMC 协议文档特点——高度结构化、数据密度极高、上下文深度依赖
2. 针对表格、矢量图、位图和文字，采用不同的切片方式
3. 提取文档中的术语定义
4. 保留 PDF 页码以便引用
5. 区分目录/序号与正文解析

### 已解决的切片问题
- **重复解析表格**: 修复 PyMuPDF 和 pdfplumber 边界判定不一致问题，采用中心点包含检测
- **表格子行处理**: 实现 `_forward_fill_key`，确保每行语义完整
- **跨页段落**: 取消页末自动切断，实现跨页无缝合并和智能切段
- **水印干扰**: 坐标过滤 + 正则清洗固定噪声
- **表格碎片化**: 整表存储 + Markdown 序列化，仅在超 6000 字符时才分块

---

## Phase 2: RAG 核心 ✅
**目标**: 能基于 eMMC 文档准确回答问题

**关键任务**:
- [✅] 实现基础 RAG：检索相关 chunk → 拼接 Prompt → LLM 生成
- [✅] 优化检索质量（混合检索 = 语义检索 + BM25 关键词检索）
- [✅] 添加引用溯源（回答时标注来自文档第几页）

**里程碑**: 能正确回答"eMMC 的 Boot 分区大小是多少？"此类问题

### 检索优化
- **混合检索**: BGE-M3 语义向量 + BM25 关键词 + RRF 融合
- **BM25 索引**: 9085 chunks from all 3 spec PDFs
- **引用格式**: `[Doc §section p.page]` 替代裸 `[N]` 引用

### 测试结果
- 基础 RAG: 75% 成功率 (rag_full_test_results.md)
- Hybrid RAG v2: 显著提升 (hybrid_rag_test_results_v2.md)

### 失败问题根因分析
1. **行级 row-chunk 切割**导致表格信息碎片化
2. **精确字段检索**靠语义向量天然劣势（寄存器索引号不敏感）
3. **n_results=5**在复杂问题上覆盖不足

---

## Phase 3: Agent 化 (待开发)
**目标**: 从简单问答升级为有推理能力的智能体

**关键任务**:
- [ ] 用 LangGraph 构建 Agent，赋予它多个工具：
  - Tool 1: eMMC 文档检索（RAG）
  - Tool 2: 术语解释（针对专业缩写）
  - Tool 3: 规范对比（不同 eMMC 版本差异）
  - Tool 4: 计算工具（如容量/时序计算）
- [ ] Agent 可以根据问题自动决定调用哪个工具，支持多轮追问

**里程碑**: 能处理"eMMC 5.1 和 5.0 在 HS400 模式上有什么区别？分别适用于什么场景？"这类复杂问题

---

## Phase 4: 效果评估 (待开发)
**目标**: 用数据证明系统有效（面试核心加分项）

**关键任务**:
- [ ] 构建小型测试集（20~30 个 eMMC 相关 Q&A 对）
- [ ] 使用 RAGAS 框架评估：
  - faithfulness（忠实度）
  - answer_relevancy（相关性）
  - context_recall（召回率）
- [ ] 记录优化前后的指标变化

**里程碑**: 能在 PPT/README 里展示一张评估指标对比图

---

## Phase 5: 界面部署 (待开发)
**目标**: 有可演示的产品界面

**关键任务**:
- [ ] 用 Streamlit 或 Gradio 快速搭建聊天界面（1-2 小时）
- [ ] 部署到 Hugging Face Spaces 或 Railway（免费）
- [ ] 整理 GitHub README（架构图、演示 GIF、技术栈徽章）

**里程碑**: 有一个可以直接甩链接给面试官的在线 Demo

---

## 关键文件路径
- `src/emmc_copilot/ingestion/` — 文档解析与切片
- `src/emmc_copilot/retrieval/` — 检索模块
- `chain.py` — RAG 链路入口
- `docs/chunking_design.md` — 完整切片设计文档

## 相关文档
- `docs/dev_process_records.md` — 完整开发记录
- `docs/known_issues.md` — Phase 1 & Phase 2 已知问题汇总（数据质量 + 检索准确性）
- `docs/rag_full_test_results.md` — 基础 RAG 测试结果
- `docs/hybrid_rag_test_results.md` — Hybrid RAG 测试结果（含人工审核）
