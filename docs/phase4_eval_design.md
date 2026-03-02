# Phase 4 — 效果评估方案设计

## 1. 背景与目标

Phase 3 已完成 LangGraph Agent 的实现与手动验收测试（单轮 11/12 通过，多轮 5/5 通过）。Phase 4 的目标是**用量化指标证明系统有效**，产出可直接用于简历、PPT 和 README 的评测报告。

### 评测问题

| 问题 | 答案 |
|------|------|
| "你的系统有多准？" | 用 Faithfulness + AnswerRelevancy 量化 |
| "混合检索比纯向量检索好多少？" | 对比 Baseline vs Hybrid RAG |
| "Agent 比纯 RAG 链有什么提升？" | 对比 Hybrid Chain vs Agent |

### 里程碑

`data/eval/ground_truth.jsonl`（20 条标注数据）+ `docs/ragas_eval_results.md`（含指标对比表）

---

## 2. RAGAS 指标选择

**版本**：RAGAS 0.4.3（`ragas.metrics.collections`）

| 指标 | 含义 | 所需字段 | 是否需要 LLM 裁判 |
|------|------|----------|-------------------|
| **Faithfulness** | 答案中的声明是否均有检索内容支撑（防幻觉） | `user_input`, `response`, `retrieved_contexts` | ✅ |
| **AnswerRelevancy** | 答案是否切题（不偏题、不废话） | `user_input`, `response`, `retrieved_contexts` | ✅ |
| **ContextPrecision** | 检索出的 chunks 中有多少是真正有用的（精准率） | `user_input`, `retrieved_contexts`, `reference` | ✅ |
| **ContextRecall** | 参考答案所需的信息在检索结果中是否都覆盖到了 | `retrieved_contexts`, `reference` | ✅ |

**LLM 裁判**：复用 DeepSeek（`DEEPSEEK_API_KEY` 环境变量），通过 `LangchainLLM` 包装器接入 RAGAS。

---

## 3. 评测数据集设计

### 3.1 数据规模

**20 条**标注样本，覆盖 4 种问题类型：

| 类型 | 数量 | 说明 |
|------|------|------|
| `factual` | 8 | 事实性检索：寄存器定义、协议流程、模式说明 |
| `calculation` | 4 | 数值计算：容量/时序/分区大小公式 |
| `comparison` | 5 | 跨版本对比：4.51 vs 5.0 vs 5.1 |
| `edge_case` | 3 | 边界测试：不存在的寄存器、诱导性问题、越界查询 |

Phase 3 的 Q1–Q9 直接复用（9 条），再补充 11 条新问题凑足 20 条。

### 3.2 文件格式

`data/eval/ground_truth.jsonl`，每行一个 JSON 对象：

```json
{
  "id": "Q01",
  "type": "factual",
  "version": "5.1",
  "question": "在 HS200 模式下，主机需要遵循什么样的 Tuning 流程？请详细列出。",
  "reference": "HS200 Tuning 流程由主机发送 CMD19（SEND_TUNING_BLOCK）触发。设备以 64B 固定模式响应。主机采样后若 CRC 无误则移动采样点，否则记录失败。主机需在 40 次以内找到正确采样窗口（SAMPLING_POINT），并将窗口中心写入 HS_TIMING。失败时须执行软复位后重试。[B51 §6.6.5.1]",
  "notes": "需检索 Tuning Block 和 SAMPLING_POINT 相关内容"
}
```

字段说明：
- `id`：唯一编号（Q01–Q20）
- `type`：问题类型（`factual` / `calculation` / `comparison` / `edge_case`）
- `version`：主要涉及的规范版本（`5.1` / `5.0` / `4.51` / `all`）
- `question`：原始用户问题（中文）
- `reference`：人工撰写的简洁参考答案（作为 ContextPrecision / ContextRecall 的 ground truth）
- `notes`（可选）：标注备注

### 3.3 20 条问题规划

**复用自 Phase 3（Q01–Q09）**：

| ID | 类型 | 问题摘要 |
|----|------|----------|
| Q01 | factual | HS200 Tuning 流程 |
| Q02 | factual | BKOPS 含义与痛点 |
| Q03 | comparison | eMMC 5.1 vs 5.0 HS400 差异 |
| Q04 | calculation | BOOT_SIZE_MULT=0x10 时 Boot 分区大小 |
| Q05 | edge_case | eMMC 5.2 SUPER_TURBO_SPEED 是否存在 |
| Q06 | comparison | RPMB 含义 + 4.51 vs 5.1 大小计算差异 |
| Q07 | calculation | Boot 分区大小公式 |
| Q08 | factual | HS_TIMING 寄存器取值含义 |
| Q09 | factual | CSD 寄存器结构 |

**新增（Q10–Q20）**：

| ID | 类型 | 问题 |
|----|------|------|
| Q10 | factual | `CACHE_CTRL [33]` 寄存器 Bit 0 的含义，以及如何通过 CMD6 开启缓存 |
| Q11 | factual | `MODE_CONFIG [30]` 寄存器进入 FFU 模式的配置值和操作步骤 |
| Q12 | calculation | 设备 `GENERIC_CMD6_TIME [248]` 值为 0x64，MODE_CONFIG 的最大超时是多少？ |
| Q13 | factual | eMMC 的 Command Queuing（CQ）功能是什么？主机如何向设备下发队列化命令？ |
| Q14 | comparison | `RPMB_SIZE_MULT` 在 eMMC 4.51 和 5.1 中的编码公式是否相同？ |
| Q15 | factual | `SLEEP_CURRENT [VCC]` 寄存器如何编码睡眠电流？最大编码值对应多少 µA？ |
| Q16 | calculation | `S_C_VCC [143]` 值为 5，该设备睡眠模式 VCC 最大电流是多少？ |
| Q17 | factual | eMMC 设备的 Sanitize 操作是什么？与 Erase 的区别是什么？ |
| Q18 | edge_case | eMMC 4.51 协议中是否支持 HS400 模式？ |
| Q19 | comparison | eMMC 5.0 和 5.1 对 Enhanced Strobe 的支持差异 |
| Q20 | edge_case | 如果主机在 HS200 模式下不执行 Tuning 直接发命令，规范是如何约束的？ |

---

## 4. 评测对象（三个 Pipeline）

### 4.1 Baseline：Dense-only RAG

- **检索器**：`EMMCRetriever`（BGE-M3 语义向量，无 BM25）
- **生成链**：`build_chain()`（强制关闭 BM25，设置 `BM25_INDEX_DIR=""`）
- **标签**：`dense_rag`

### 4.2 Hybrid RAG（当前生产）

- **检索器**：`HybridRetriever`（Dense + BM25 + RRF k=60）
- **生成链**：`build_chain()`（正常加载 `data/vectorstore/bm25/corpus.pkl`）
- **标签**：`hybrid_rag`

### 4.3 Agent（LangGraph）

- **检索器**：`HybridRetriever`（同 Hybrid，作为 `search_emmc_docs` 底层）
- **生成**：`build_agent()` 全工具调用
- **特殊处理**：contexts 来源于 agent 执行过程中所有 `search_emmc_docs` 和 `compare_versions` 工具的原始返回内容（通过自定义回调或 `ToolMessage` 提取）
- **标签**：`agent`

---

## 5. 系统架构

```
data/eval/ground_truth.jsonl         ← 人工标注的 20 条 Q&A
          │
          ▼
src/emmc_copilot/evaluation/
  ├── dataset.py     ← 加载 JSONL，构造 List[SingleTurnSample]
  ├── runner.py      ← 驱动 pipeline 生成 response + contexts，调用 RAGAS evaluate()
  └── report.py      ← 将 EvaluationResult 格式化为 Markdown 报告
          │
          ▼
tools/run_ragas_eval.py              ← CLI 入口（typer）
          │
          ▼
docs/ragas_eval_results.md           ← 最终输出报告（含三 pipeline 对比表）
```

### 5.1 contexts 提取策略

| Pipeline | contexts 提取方式 |
|----------|------------------|
| Dense / Hybrid RAG | `retriever.invoke(question)` → 取 `doc.page_content` |
| Agent | 执行 `graph.invoke(...)` 同时注入 `ContextCollector` 回调，收集所有工具调用返回的文档文本 |

Agent 的 `ContextCollector`：继承 `BaseCallbackHandler`，在 `on_tool_end()` 中收集所有工具（如 `search_emmc_docs`、`compare_versions`、`calculate` 等）的输出字符串，合并为 `retrieved_contexts` 列表。这能有效防止 `calculate` 产生的纯数学计算结果在评判忠实度（Faithfulness）时被误判为“幻觉”。

---

## 6. 实现方案

### 新增文件（4 个）

#### `data/eval/ground_truth.jsonl`
20 条 Q&A 标注数据，人工撰写 `reference` 字段。

#### `src/emmc_copilot/evaluation/dataset.py`

```python
def load_ground_truth(path: Path) -> list[dict]:
    """加载 JSONL，返回原始 dict 列表"""

def to_ragas_samples(
    records: list[dict],
    responses: list[str],
    contexts: list[list[str]],
) -> EvaluationDataset:
    """将 records + pipeline 输出组装为 EvaluationDataset"""
```

#### `src/emmc_copilot/evaluation/runner.py`

```python
def run_dense_rag(questions: list[str]) -> tuple[list[str], list[list[str]]]:
    """运行 Dense-only RAG，返回 (responses, contexts_per_q)"""

def run_hybrid_rag(questions: list[str]) -> tuple[list[str], list[list[str]]]:
    """运行 Hybrid RAG chain"""

def run_agent(questions: list[str]) -> tuple[list[str], list[list[str]]]:
    """运行 LangGraph Agent，通过回调收集 contexts"""

def ragas_evaluate(
    dataset: EvaluationDataset,
    llm,           # ChatOpenAI (DeepSeek)
    embeddings,    # BGEEmbedder 包装
) -> EvaluationResult:
    """调用 ragas.evaluate()，返回 EvaluationResult"""
```

`ContextCollector`（内部类）：
```python
class ContextCollector(BaseCallbackHandler):
    def __init__(self): self.contexts = []
    def on_tool_end(self, output, *, run_id, **kwargs):
        # 收集所有工具的输出内容，避免 RAGAS 在处理数值和常识查询时误判幻觉
        self.contexts.append(str(output))
```

#### `src/emmc_copilot/evaluation/report.py`

```python
def format_report(
    results: dict[str, EvaluationResult],   # {"dense_rag": ..., "hybrid_rag": ..., "agent": ...}
    output_path: Path,
) -> None:
    """输出 Markdown 报告（含对比表、逐题明细）"""
```

报告结构：
```markdown
# RAGAS 评测报告

## 汇总指标对比（三 Pipeline）

| Pipeline       | Faithfulness | AnswerRelevancy | ContextPrecision | ContextRecall |
|----------------|:------------:|:---------------:|:----------------:|:-------------:|
| dense_rag      |              |                 |                  |               |
| hybrid_rag     |              |                 |                  |               |
| agent          |              |                 |                  |               |

## 按问题类型（Type）聚合对比

*说明：不同问题类型在 RAGAS 下的分数分布差异极大（例如计算题和边界题的 Recall 指标可能扭曲）。因此分组展示最能体现检索引擎在事实性（factual）问题上的真实差距。*

| Type       | Faithfulness | AnswerRelevancy | ContextPrecision | ContextRecall |
|------------|:------------:|:---------------:|:----------------:|:-------------:|
| factual    |              |                 |                  |               |
| calculation|              |                 |                  |               |
| comparison |              |                 |                  |               |
| edge_case  |              |                 |                  |               |

## 免责声明 (Disclaimer)
*由于担任法官（Judge）和生成基线（Generator）的模型均为 DeepSeek，本评测分数可能包含一定的“自我偏好偏差”（Self-Preference Bias）。此量化指标体系的核心价值在于相同大模型基座下，不同检索/路由方案（Dense vs Hybrid vs Agent）之间的**相对性能提升（Relative Delta）对比**。*

## 逐题评分明细（hybrid_rag）
...
```

#### `tools/run_ragas_eval.py`

```python
# 用法:
#   uv run python tools/run_ragas_eval.py --pipeline hybrid_rag
#   uv run python tools/run_ragas_eval.py --pipeline all --output docs/ragas_eval_results.md

@app.command()
def main(
    pipeline: str = typer.Option("all", help="dense_rag | hybrid_rag | agent | all"),
    gt_path: Path = typer.Option("data/eval/ground_truth.jsonl"),
    output: Path = typer.Option("docs/ragas_eval_results.md"),
    sample: int = typer.Option(0, help="仅跑前 N 条（0=全部），用于快速冒烟"),
):
```

### 修改文件（2 个）

#### `src/emmc_copilot/evaluation/__init__.py`
```python
from .dataset import load_ground_truth, to_ragas_samples
from .runner import run_dense_rag, run_hybrid_rag, run_agent, ragas_evaluate
from .report import format_report
__all__ = [...]
```

#### `pyproject.toml`
将 `ragas >= 0.1` 更新为 `ragas >= 0.4.3`（锁定已验证版本）。

---

## 7. 实现顺序

1. **数据标注**：手工完善 `data/eval/ground_truth.jsonl` 的 `reference` 字段（最核心，决定指标可信度）
2. **`dataset.py`**：加载 JSONL + 组装 `EvaluationDataset`
3. **`runner.py`**：实现三个 pipeline 的 response + contexts 提取
   - 先实现 `run_hybrid_rag`（最简单，直接用现有 chain + retriever）
   - 再实现 `run_agent`（需要 ContextCollector 回调）
   - 最后实现 `run_dense_rag`（需临时禁用 BM25 路径）
4. **`report.py`**：格式化 Markdown 报告
5. **`tools/run_ragas_eval.py`**：CLI 入口
6. **冒烟测试**：`--sample 3` 用 3 条快速验证整条链路
7. **全量评测**：跑 20 条，产出最终报告

---

## 8. RAGAS LLM 配置

```python
import os
from langchain_openai import ChatOpenAI
from langchain_core.embeddings import Embeddings as LCEmbeddings
from ragas.llms import _LangchainLLMWrapper        # RAGAS 0.4.x 正确类名（LangchainLLM 已不存在）
from ragas.embeddings import _LangchainEmbeddingsWrapper  # LangchainEmbeddingsWrapper 是已废弃的别名
from ragas import RunConfig

# Judge LLM — DeepSeek（与 Agent 共用 API Key，无需新增账号）
judge_llm = _LangchainLLMWrapper(
    ChatOpenAI(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        base_url=os.getenv("DEEPSEEK_BASE_URL"),
        api_key=os.getenv("DEEPSEEK_API_KEY"),
    )
)

# Judge Embeddings — BGEEmbedder 薄适配器
# BGEEmbedder._model 是懒加载私有属性（初始为 None），不可直接传给 RAGAS。
# 需将其包装为实现 LangChain Embeddings 接口的适配器，以复用已加载的模型权重。
from emmc_copilot.retrieval.embedder import BGEEmbedder

class BGEEmbeddingsAdapter(LCEmbeddings):
    """将 BGEEmbedder 包装为 LangChain Embeddings 接口，供 RAGAS AnswerRelevancy 使用。"""
    def __init__(self, embedder: BGEEmbedder):
        self._e = embedder
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._e.embed(texts)
    def embed_query(self, text: str) -> list[float]:
        return self._e.embed_query(text)

# embedder_instance 由 runner.py 从 build_chain() / build_agent() 获取，避免重复加载
judge_embeddings = _LangchainEmbeddingsWrapper(BGEEmbeddingsAdapter(embedder_instance))

# 限制并发以防 DeepSeek API Rate Limit（429 Error）
eval_config = RunConfig(max_workers=2, max_retries=10)
# 调用评估时传入: ragas_evaluate(..., run_config=eval_config)
```

---

## 9. 验收标准

| 验收项 | 指标 |
|--------|------|
| 数据集完整性 | 20 条 Q&A，`reference` 字段全部非空 |
| Hybrid RAG Faithfulness | ≥ 0.80 |
| Hybrid RAG AnswerRelevancy | ≥ 0.75 |
| Hybrid 优于 Dense | ContextPrecision 和 ContextRecall 均提升 |
| 报告可读性 | 生成 Markdown 含三 pipeline 对比表 + 逐题明细 |

---

## 10. 关键文件路径参考

| 文件 | 用途 |
|------|------|
| `src/emmc_copilot/qa/chain.py:build_chain()` | Hybrid / Dense RAG 链入口 |
| `src/emmc_copilot/agent/graph.py:build_agent()` | Agent 入口 |
| `src/emmc_copilot/retrieval/hybrid_retriever.py` | HybridRetriever（BM25 + Dense + RRF） |
| `src/emmc_copilot/retrieval/vectorstore.py` | ChromaDB 封装，`query()` 返回格式 |
| `data/vectorstore/bm25/corpus.pkl` | BM25 索引（9085 chunks） |
| `data/eval/ground_truth.jsonl` | **待创建** — 20 条标注数据 |
| `src/emmc_copilot/evaluation/` | **待实现** — 评测模块（已有空 `__init__.py`） |
| `tools/run_ragas_eval.py` | **待创建** — CLI 入口 |
| `docs/ragas_eval_results.md` | **评测输出** — 最终报告 |
