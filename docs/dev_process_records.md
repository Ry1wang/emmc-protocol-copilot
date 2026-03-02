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
| Phase 3 | ✅ 已完成 | Agent 化 |
| Phase 4 | ✅ 已完成 | 效果评估 |
| Phase 5 | ✅ 已完成 | 界面部署 |

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

## Phase 3: Agent 化 ✅
**目标**: 从简单问答升级为有推理能力的智能体

**设计方案**: `docs/phase3_agent_design.md`

**关键任务**:
- [✅] 用 LangGraph 构建 Agent，赋予它多个工具：
  - Tool 1: eMMC 文档检索（RAG）—— `search_emmc_docs`
  - Tool 2: 术语解释（针对专业缩写）—— `explain_term`
  - Tool 3: 规范对比（不同 eMMC 版本差异）—— `compare_versions`
  - Tool 4: 计算工具（如容量/时序计算）—— `calculate`
- [✅] Agent 可以根据问题自动决定调用哪个工具，支持多轮追问
- [✅] 单轮测试（Q1–Q12）完成，通过率 ≥ 91%（详见 `docs/agent_full_test_results_v2.md`）
- [✅] 多轮对话测试（5 轮/2 组）全部通过（详见下方）

**里程碑**: 能处理"eMMC 5.1 和 5.0 在 HS400 模式上有什么区别？分别适用于什么场景？"这类复杂问题

### 单轮测试结果（`docs/agent_full_test_results_v2.md`）
- Q1–Q12 中 11/12 通过（≥91%）
- calculate 工具 Bug（`**kwargs` → `parameters: dict`）已修复并验证
- Q4（TRAN_SPEED 编码计算）、Q7（Boot 分区计算）经 calculate 工具正确执行

### 多轮对话测试（`tools/run_multiturn_test.py`，2026-03-02）

**组 1：FFU 连续追问（3 轮，thread_id=`phase3-multiturn-ffu`）**

| 轮次 | 用户问题 | 核心表现 |
|------|----------|----------|
| 1 | 什么是 FFU？ | `explain_term` + `search_emmc_docs` 双工具，准确定义 FFU = Field Firmware Update [B51 §6.6.18 p.92] |
| 2 | 进入这种模式需要配置哪个寄存器的哪个位？ | **正确继承上文"FFU"语境**，无需重申，直接给出 MODE_CONFIG [30] = 0x01 [B51 §7.4.114 p.247] |
| 3 | 那这个操作最大需要等待多久（即超时时间怎么算）？ | **"那这个操作"代词消歧成功**，检索 GENERIC_CMD6_TIME [248]，给出超时 = 值 × 10ms，最大 2550ms |

**组 2：CACHE_CTRL 版本发散（2 轮，thread_id=`phase3-multiturn-cache`）**

| 轮次 | 用户问题 | 核心表现 |
|------|----------|----------|
| 1 | CACHE_CTRL [33] 寄存器有什么用？ | BM25 精确命中，给出 CACHE_EN Bit 0 定义 [B51 §7.4.111 p.246] |
| 2 | eMMC 4.51 版本也有这个功能吗？ | 自动触发 `compare_versions` 工具，三版本对比，确认 4.51/5.0/5.1 功能完全一致 |

**结论**：5/5 轮通过，上下文继承（代词消歧）和跨版本比对均正常工作。

---

## Phase 4: 效果评估 ✅
**目标**: 用数据证明系统有效（面试核心加分项）

**关键任务**:
- [✅] 构建测试集（20 个 eMMC 相关 Q&A 对，覆盖 factual / calculation / comparison / edge_case）
- [✅] 使用 RAGAS 框架评估三条 Pipeline（Dense RAG、Hybrid RAG、LangGraph Agent）
- [✅] 记录各 Pipeline 指标对比

**里程碑**: RAGAS 评测报告已生成（`docs/ragas_eval_results.md`）

### RAGAS 评测结果汇总（20 题）

| Pipeline | Faithfulness | AnswerRelevancy | ContextPrecision | ContextRecall |
|----------|:---:|:---:|:---:|:---:|
| Dense-only RAG（基线） | 0.5923 | 0.8377 | 0.5910 | 0.3492 |
| Hybrid RAG（BGE-M3 + BM25 + RRF） | 0.6452 | 0.7878 | 0.6736 | 0.2900 |
| **LangGraph Agent（4 工具）** | **0.8495** | **0.8082** | **0.8321** | **0.6303** |

**结论**：Agent Pipeline 在 Faithfulness（+0.257）、ContextPrecision（+0.241）、ContextRecall（+0.281）上均显著优于 Dense 基线，综合性能最优。

---

## Phase 5: 界面部署 ✅
**目标**: 有可演示的产品界面

**关键任务**:
- [✅] 用 Chainlit 实现流式聊天 Web 界面（`app.py`）
- [✅] 接入 LangSmith 实现全链路 Trace 可观测性
- [✅] 实现版本切换（⚙️ 选择器，支持 4.51 / 5.0 / 5.1 / all）
- [✅] 完成代码审查并修复 7 个问题（事件循环阻塞、session 竞争、空消息等）
- [✅] 验收测试通过（核心功能 4 Case + UI 手动验证）

**里程碑**: 本地可通过 `uv run chainlit run app.py` 启动，浏览器即可演示

### 实现要点
- **流式输出策略**：`astream_events v2` 区分 reasoning token 与最终答案，仅对用户展示最终回答
- **工具可视化**：每个工具调用以 `cl.Step` 展示，可折叠查看 input/output
- **多轮上下文**：`MemorySaver` + `thread_id = Chainlit session.id`，刷新页面自动隔离
- **LangSmith 分组**：每条请求通过 `RunnableConfig.metadata.session_id` 归属到对应 session

### 核心文件
| 文件 | 用途 |
|------|------|
| `app.py` | Chainlit 入口（on_start / on_settings_update / on_message） |
| `chainlit.md` | 欢迎页静态内容 |
| `docs/phase5_frontend_design.md` | 设计方案 |
| `docs/phase5_test_plan.md` | 验收测试计划（含 9 个 Case）|

---

## 关键文件路径
- `src/emmc_copilot/ingestion/` — 文档解析与切片
- `src/emmc_copilot/retrieval/` — 检索模块（含 BM25 + HybridRetriever）
- `src/emmc_copilot/qa/chain.py` — RAG 链路入口
- `src/emmc_copilot/agent/` — LangGraph Agent（state/prompt/tools/graph/cli）
- `app.py` — Chainlit 前端入口（Phase 5）
- `chainlit.md` — 欢迎页（Phase 5）
- `tools/run_multiturn_test.py` — 多轮对话验收脚本（单进程，保留 MemorySaver 状态）
- `docs/chunking_design.md` — 完整切片设计文档

## 相关文档
- `docs/dev_process_records.md` — 完整开发记录
- `docs/known_issues.md` — Phase 1 & Phase 2 已知问题汇总（数据质量 + 检索准确性）
- `docs/phase3_agent_design.md` — Phase 3 Agent 化实现方案
- `docs/phase3_test_plan.md` — Phase 3 验收测试计划
- `docs/agent_full_test_results.md` — Phase 3 单轮测试结果 v1（含分析）
- `docs/agent_full_test_results_v2.md` — Phase 3 单轮测试结果 v2（calculate 修复后）
- `docs/agent_vs_notebooklm_analysis.md` — 与 Notebook LM 对比分析
- `docs/rag_full_test_results.md` — 基础 RAG 测试结果
- `docs/hybrid_rag_test_results.md` — Hybrid RAG 测试结果（含人工审核）
- `docs/ragas_eval_results.md` — Phase 4 RAGAS 评测报告（3 Pipeline 对比）
- `docs/phase5_frontend_design.md` — Phase 5 Chainlit 前端设计方案
- `docs/phase5_test_plan.md` — Phase 5 验收测试计划
