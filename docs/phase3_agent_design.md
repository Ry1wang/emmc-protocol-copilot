# Phase 3 Agent 化实现方案

## 1. 概述与目标

### 目标
在 Phase 2 混合检索（Dense + BM25 + RRF）基础上，用 LangGraph 构建具备工具调用能力的 Agent，从"单次 RAG 问答"升级为"有推理能力的多轮智能体"。

### 里程碑
能正确处理以下类型的复杂问题：
- `"eMMC 5.1 和 5.0 在 HS400 模式上有什么区别？分别适用于什么场景？"` — 跨版本比对
- `"BOOT_SIZE_MULT 值为 0x10 时，Boot 分区实际有多大？"` — 规范公式计算
- `"HS_TIMING 是什么意思？它和哪些寄存器有关联？"` — 术语 + 检索联动
- 以上问题的多轮追问（"那 4.51 呢？"、"帮我再换算一下"）

---

## 2. 架构总览

### 现有基础（Phase 2）
```
HybridRetriever ──► format_docs_with_citations ──► Prompt ──► DeepSeek ──► Answer
     ↑
  BGE-M3 + ChromaDB（emmc_docs, emmc_glossary）
  BM25Corpus（corpus.pkl）
  Version filter（detect_versions）
  Query expansion（LLM variants）
```

### Phase 3 新增组件
```
Human Message
    │
    ▼
┌─────────────────────────────────────────────┐
│           LangGraph Agent Graph              │
│                                              │
│  ┌──────────────┐    ┌──────────────────┐   │
│  │  agent_node  │◄───│   tools_node     │   │
│  │  (DeepSeek)  │    │  (Tool Executor) │   │
│  └──────┬───────┘    └────────▲─────────┘   │
│         │ tool_calls?         │              │
│         └─────────────────────┘              │
│         │ no tool_calls                      │
│         ▼                                    │
│        END                                   │
└─────────────────────────────────────────────┘
    │
    ▼
AI Message（含 Cite-as 标注）
```

### 4 个工具
| 工具 | 函数名 | 触发场景 | 核心依赖 |
|------|--------|---------|---------|
| eMMC 文档检索 | `search_emmc_docs` | 规范事实、寄存器定义、命令说明 | HybridRetriever |
| 术语解释 | `explain_term` | 缩写/术语含义查询 | ChromaDB glossary collection |
| 版本对比 | `compare_versions` | "X 与 Y 的区别"、版本演进 | HybridRetriever × 多版本 |
| 规范计算 | `calculate` | 容量、时序、编码值换算 | 内置公式库 |

---

## 3. LangGraph 图设计

### 3.1 State 定义

```python
# agent/state.py
from typing import Annotated
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    # add_messages 自动追加（不覆盖），天然支持多轮对话
```

`messages` 使用 `add_messages` reducer，每轮调用都追加，保留完整对话历史。
无需额外字段：检索结果通过 `ToolMessage` 内嵌在消息链中，LLM 自然读取。

### 3.2 节点设计

**`agent_node`**（DeepSeek 决策节点）
```
输入：AgentState（包含历史消息）
输出：AIMessage
  - 如包含 tool_calls → 继续执行工具
  - 如不包含 tool_calls → 终止，输出最终回答
```

```python
# graph.py
def agent_node(state: AgentState) -> dict:
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}
```

**`tools_node`**（并行工具执行节点）
- 使用 `langgraph.prebuilt.ToolNode`（自动处理并发工具调用）
- 输出：`list[ToolMessage]`，每条对应一次工具调用结果

### 3.3 边设计

```python
from langgraph.prebuilt import tools_condition

graph.add_node("agent", agent_node)
graph.add_node("tools", ToolNode(tools))
graph.add_edge(START, "agent")
graph.add_conditional_edges(
    "agent",
    tools_condition,   # 检查最后一条 AIMessage 是否含 tool_calls
    {"tools": "tools", END: END},
)
graph.add_edge("tools", "agent")   # 工具结果返回 agent 节点继续推理
```

工具调用循环：`agent → tools → agent → tools → ... → agent → END`
最大迭代次数由 `recursion_limit` 控制（默认 25，可配置）。

### 3.4 多轮对话支持

**in-memory（同一进程内）**：

```python
from langgraph.checkpoint.memory import MemorySaver

checkpointer = MemorySaver()
compiled_graph = graph.compile(checkpointer=checkpointer)

# 每次对话用相同 thread_id
config = {"configurable": {"thread_id": "user-session-1"}}
compiled_graph.invoke({"messages": [HumanMessage(content=question)]}, config=config)
```

**后续可扩展**（Phase 5）：替换为 `SqliteSaver` 实现跨进程持久化。

---

## 4. 工具详细设计

### Tool 1：`search_emmc_docs` — eMMC 文档检索

**用途**：检索 eMMC 规范正文（寄存器定义、命令说明、时序图、协议流程等）。

**接口**：
```python
@tool
def search_emmc_docs(query: str, version: str = "") -> str:
    """Search the eMMC (JEDEC JESD84) specification for technical content.

    Use this for register definitions, command descriptions, timing parameters,
    protocol flows, or any fact from the eMMC specification.

    Args:
        query: The technical query in English, using spec terminology.
               Include register names (e.g. EXT_CSD, BKOPS_EN), hex values,
               command names (CMD6, CMD46), and timing mode names (HS200, HS400).
        version: Optional version filter. One of "5.1", "5.0", "4.51", or ""
                 (empty = use session default, usually "5.1").
    Returns:
        Formatted excerpts with Cite-as tags for inline citation.
    """
```

**实现要点**：
- 复用 `format_docs_with_citations()`（已在 `qa/chain.py` 实现）
- 版本参数覆盖 `retriever.default_version`（通过 `detect_versions` 自动检测或参数指定）
- 内部调用 `_expand_queries()` 生成 2 个变体查询，三路去重（与 Phase 2 保持一致）

### Tool 2：`explain_term` — 术语解释

**用途**：查询 eMMC 专业缩写/术语定义，使用 ChromaDB `emmc_glossary` collection。

**接口**：
```python
@tool
def explain_term(term: str) -> str:
    """Look up the definition of an eMMC technical term or abbreviation.

    Use this when the user asks what an abbreviation means (e.g. BKOPS, FFU,
    CMDQ, HPI, RPMB) or requests a concise definition before deeper analysis.

    Args:
        term: The term or abbreviation to look up (e.g. "BKOPS", "FFU", "HS400").
    Returns:
        Definition(s) found in the eMMC glossary, or a message if not found.
    """
```

**实现要点**：
- 直接向量查询 `emmc_glossary` collection（已有 DEFINITION 类型的 chunk）
- `n_results=5`，结果以纯文本返回（不需要 Cite-as 格式，定义较短）
- 若 glossary 无结果，fallback 到 `search_emmc_docs`（自动处理）

### Tool 3：`compare_versions` — 版本对比

**用途**：对同一特性/字段在不同 eMMC 版本间进行并排比较。

**接口**：
```python
@tool
def compare_versions(feature: str, versions: str = "4.51,5.0,5.1") -> str:
    """Compare an eMMC feature or register field across multiple spec versions.

    Use this when the user asks about differences between eMMC versions,
    or when version-specific behavior needs to be highlighted.

    Args:
        feature: The feature, register, or command to compare
                 (e.g. "HS400 timing", "CACHE_CTRL", "Command Queuing support").
        versions: Comma-separated spec versions to compare.
                  Defaults to "4.51,5.0,5.1" (all three versions).
    Returns:
        Version-grouped excerpts formatted as a comparison table.
    """
```

**实现要点**：
- 解析 `versions` 字符串 → 版本列表
- 对每个版本分别调用 `retriever.invoke(feature)` 并过滤对应 version metadata
- 输出格式：
  ```
  ## eMMC 4.51（JESD84-B451）
  [B451 §X.X p.N] ...

  ## eMMC 5.0（JESD84-B50）
  [B50 §X.X p.N] ...

  ## eMMC 5.1（JESD84-B51）
  [B51 §X.X p.N] ...
  ```
- 若某版本无相关内容，明确注明"该版本未定义此特性"

### Tool 4：`calculate` — 规范计算

**用途**：根据 eMMC 规范公式，将寄存器值换算为实际物理量。

**接口**：
```python
@tool
def calculate(formula: str, **kwargs) -> str:
    """Perform eMMC specification calculations using official formulas.

    Supported formulas:
    - boot_size(boot_size_mult)       : Boot partition size
    - rpmb_size(rpmb_size_mult)       : RPMB partition size
    - capacity(sec_count)             : Total device capacity from SEC_COUNT
    - tran_speed(freq_unit, mult)     : CSD TRAN_SPEED → MHz
    - erase_group(hc_erase_grp_size)  : Erase group size
    - wp_group(hc_wp_grp_size, hc_erase_grp_size) : Write protect group size
    - sleep_current(s_c_vcc)          : Sleep mode max current
    - gp_size(gp_size_mult, hc_erase_grp_size, hc_wp_grp_size) : GP partition

    Args:
        formula: Formula name (see list above).
        **kwargs: Formula-specific parameters (register values as integers).

    Example:
        calculate("boot_size", boot_size_mult=16)
        → "Boot partition size = 128 KB × 16 = 2048 KB = 2 MB  [EXT_CSD §7.4.83 p.226]"
    Returns:
        Step-by-step calculation result with spec reference.
    """
```

**内置公式（含规范引用）**：

| 公式名 | 计算逻辑 | 规范依据 |
|--------|---------|---------|
| `boot_size` | `128 KB × BOOT_SIZE_MULT` | EXT_CSD [226] |
| `rpmb_size` | `128 KB × RPMB_SIZE_MULT` (每个分区) | EXT_CSD [168] |
| `capacity` | `SEC_COUNT × 512 bytes` | EXT_CSD [215:212] |
| `tran_speed` | `FREQ_UNIT[freq_unit] × MULT[mult]` | CSD [103:96] |
| `erase_group` | `(HC_ERASE_GRP_SIZE + 1) × 512 KB` | EXT_CSD [224] |
| `wp_group` | `(HC_WP_GRP_SIZE + 1) × ERASE_GRP_SIZE` | EXT_CSD [221] |
| `sleep_current` | `1 µA × 2^(S_C_VCC)` | EXT_CSD [143/142] |
| `gp_size` | `GP_SIZE_MULT × HC_WP_GRP_SIZE × HC_ERASE_GRP_SIZE × 512 KB` | EXT_CSD [154:143] |

`TRAN_SPEED` 解码表（内置常量）：
- 频率单位：`{0: 100e3, 1: 1e6, 2: 10e6, 3: 100e6}` Hz
- 乘数：`{1:1.0, 2:1.2, 3:1.3, 4:1.5, 5:2.0, 6:2.5, 7:3.0, 8:3.5, 9:4.0, 10:4.5, 11:5.0, 12:5.5, 13:6.0, 14:7.0, 15:8.0}`

---

## 5. Agent System Prompt 设计

Agent system prompt 与 QA chain 的 system prompt **分开**维护（`agent/prompt.py`），因为 Agent 的指令侧重于工具调用策略，而 QA chain 的 prompt 侧重于答案格式。

**核心设计原则**：
1. 角色：eMMC 规范专家 + 工具调用者
2. 何时调用哪个工具（明确规则）
3. 保持 Phase 2 的引用格式（`[B51 §X.X p.N]`）
4. 多轮追问时保持上下文

```python
AGENT_SYSTEM = """\
You are an expert on the eMMC (JEDEC JESD84) specification, assisting hardware/firmware engineers.
You have access to four tools:

1. search_emmc_docs   — Use for any factual question about registers, commands, timing,
                        protocols, or spec content. This is your primary tool.
2. explain_term       — Use when the user asks what an abbreviation or term means,
                        BEFORE doing a deeper search.
3. compare_versions   — Use when the question explicitly asks about differences between
                        eMMC versions (e.g. "5.0 vs 5.1", "added in 5.1").
4. calculate          — Use when the question requires converting a register value to
                        a physical quantity (size in KB/MB, frequency in MHz, etc.).

Workflow rules:
- You may call multiple tools in sequence or parallel if the question requires it.
- Always cite sources inline using Cite-as tags from tool output: e.g. [B51 §7.4.111 p.246].
- If a tool returns no relevant content, state clearly that the information is not in the
  retrieved excerpts — do NOT fabricate register names, values, or behaviors.
- For multi-byte EXT_CSD fields: byte order is little-endian (lowest index = LSByte).
- Mirror the language of the question (reply in Chinese if asked in Chinese).
"""
```

---

## 6. 新增文件

```
src/emmc_copilot/agent/
├── __init__.py      （修改：更新 exports）
├── state.py         （新建：AgentState TypedDict）
├── tools.py         （新建：4个工具 + build_tools()）
├── graph.py         （新建：StateGraph + build_agent()）
├── prompt.py        （新建：AGENT_SYSTEM prompt）
└── cli.py           （新建：agent ask / chat 命令）
```

---

## 7. 文件详细设计

### `agent/state.py`（约 15 行）
```python
from typing import Annotated
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
```

### `agent/tools.py`（约 180 行）

关键函数：
```python
def build_tools(
    retriever,          # HybridRetriever | EMMCRetriever
    store,              # EMMCVectorStore（用于 glossary 查询）
    embedder,           # BGEEmbedder（用于 explain_term）
    llm,                # LLM（用于 explain_term 内部的 query expansion）
) -> list[BaseTool]:
    """初始化所有工具并返回列表（工具实例持有 retriever/store 引用）。"""
    ...
    return [search_emmc_docs, explain_term, compare_versions, calculate]
```

每个工具函数通过闭包捕获 retriever/store，而不依赖全局变量。

`compare_versions` 实现思路：
```python
def _compare_impl(feature: str, versions: list[str]) -> str:
    sections = []
    seen_ids: set[str] = set()
    for ver in versions:
        # 临时修改 retriever 的 default_version 或直接传参
        docs = retriever.invoke(f"{feature} version:{ver}")
        ver_docs = [d for d in docs if d.metadata.get("version") == ver]
        # 去重 + 格式化
        ...
    return "\n\n".join(sections)
```

### `agent/graph.py`（约 80 行）

```python
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import MemorySaver

def build_agent():
    """Build and return the compiled LangGraph agent.

    Environment variables (same as build_chain()):
        DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
        CHROMA_PERSIST_DIR, BM25_INDEX_DIR, EMMC_VERSION

    Returns:
        (graph, retriever) — compiled StateGraph and base retriever for debugging.
    """
    # 1. 初始化基础组件（与 build_chain() 相同逻辑）
    embedder = BGEEmbedder()
    store = EMMCVectorStore(chroma_dir)
    retriever = HybridRetriever(...) or EMMCRetriever(...)  # fallback
    llm = ChatOpenAI(...)

    # 2. 构建工具列表
    tools = build_tools(retriever, store, embedder, llm)

    # 3. LLM 绑定工具
    llm_with_tools = llm.bind_tools(tools)

    # 4. 定义节点
    def agent_node(state: AgentState) -> dict:
        messages = [SystemMessage(content=AGENT_SYSTEM)] + state["messages"]
        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}

    # 5. 构建图
    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode(tools))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")

    # 6. 编译（带 MemorySaver 支持多轮）
    checkpointer = MemorySaver()
    compiled = graph.compile(checkpointer=checkpointer)

    return compiled, retriever
```

### `agent/cli.py`（约 120 行）

子命令与 `qa/cli.py` 对齐，使用相同接口风格：

```bash
uv run python -m emmc_copilot.agent.cli ask "eMMC 5.1 和 5.0 在 HS400 模式上有什么区别？"
uv run python -m emmc_copilot.agent.cli chat         # 多轮交互 REPL
uv run python -m emmc_copilot.agent.cli ask "..." --thread-id my-session  # 指定会话ID
```

`chat` 命令特性：
- 相同 `thread_id` → 共享对话历史（`MemorySaver` 持久化）
- 输入 `/clear` 重置当前会话
- 输入 `/tools` 显示可用工具列表
- 输入 `/exit` 或 Ctrl-C 退出

### `agent/__init__.py`（修改）
```python
"""Phase 3 — LangGraph agent orchestration."""

from .graph import build_agent
from .state import AgentState

__all__ = ["build_agent", "AgentState"]
```

---

## 8. 修改文件

### `pyproject.toml`
无需新增依赖：
- `langgraph>=0.2,<0.3` — 已在依赖中 ✅
- `langchain-openai>=0.2,<0.3` — 已在依赖中 ✅

### `docs/dev_process_records.md`
Phase 3 任务项更新（实现后逐项打 ✅）。

---

## 9. 环境变量

Phase 3 沿用 Phase 2 的所有环境变量，无新增：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DEEPSEEK_API_KEY` | —（必填） | DeepSeek API Key |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` | LLM 接口地址 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | 模型名 |
| `CHROMA_PERSIST_DIR` | `data/vectorstore/chroma` | ChromaDB 持久化目录 |
| `BM25_INDEX_DIR` | `data/vectorstore/bm25` | BM25 索引目录 |
| `EMMC_VERSION` | `5.1` | 默认版本过滤（`all` = 不过滤） |

> **注意**：Agent 的 `compare_versions` 工具会忽略 `EMMC_VERSION` 设置，始终使用多版本检索。

---

## 10. 实现顺序

```
Step 1  agent/state.py          ── AgentState（5 分钟）
Step 2  agent/prompt.py         ── AGENT_SYSTEM（10 分钟）
Step 3  agent/tools.py          ── 4 个工具 + build_tools()（主要工作）
          3a  search_emmc_docs  ── 复用已有 retriever 逻辑
          3b  explain_term      ── glossary 查询
          3c  compare_versions  ── 多版本分组检索
          3d  calculate         ── 内置公式库
Step 4  agent/graph.py          ── StateGraph 组装 + build_agent()
Step 5  agent/cli.py            ── ask / chat 命令
Step 6  agent/__init__.py       ── 更新 exports
Step 7  验收测试                 ── 下方测试用例
```

---

## 11. 验收测试

### 单轮测试

```bash
# T1: 跨版本比对（compare_versions）
uv run python -m emmc_copilot.agent.cli ask \
  "eMMC 5.1 和 5.0 在 HS400 模式上有什么区别？分别适用于什么场景？"
# 期望: 工具日志出现 compare_versions，答案对两个版本分别描述

# T2: 术语 + 检索联动（explain_term → search_emmc_docs）
uv run python -m emmc_copilot.agent.cli ask \
  "BKOPS 是什么意思？如何启用自动 BKOPS？"
# 期望: 先调用 explain_term，再调用 search_emmc_docs，给出完整答案

# T3: 规范计算（calculate）
uv run python -m emmc_copilot.agent.cli ask \
  "如果 BOOT_SIZE_MULT 值为 0x10，Boot 分区实际有多大？"
# 期望: 工具日志出现 calculate，答案给出 "128 KB × 16 = 2048 KB = 2 MB"

# T4: 普通检索（search_emmc_docs，与 Phase 2 回归一致）
uv run python -m emmc_copilot.agent.cli ask \
  "EXT_CSD 寄存器索引 185 的字段名是什么？"
# 期望: 正确答出 HS_TIMING，含 [B51 §X.X p.N] 引用
```

### 多轮追问测试

```bash
uv run python -m emmc_copilot.agent.cli chat
> eMMC 5.1 的 CACHE_CTRL [33] 寄存器如何使用？
# 期望: 正常回答 bit 0 的含义，含引用
> 那 4.51 版本有这个寄存器吗？
# 期望: 调用 compare_versions 或 search_emmc_docs with version=4.51，
#        正确回答（有或无）
> 如果有，开启 Cache 需要什么前提条件？
# 期望: 结合上下文继续检索，不需要用户重新说明背景
```

### 验收标准

| 检查项 | 通过条件 |
|--------|---------|
| 工具自动选择 | T1 触发 compare_versions，T2 触发 explain_term，T3 触发 calculate |
| 引用格式 | 所有回答含 `[B51/B50/B451 §X.X p.N]` 格式（不裸 `[N]`）|
| 多轮上下文 | 多轮测试中追问无需重复背景 |
| Phase 2 回归 | T4 回答质量不低于 Phase 2（Q3/Q6/Q7 等原通过题） |
| 无幻觉 | 工具返回无相关内容时，回答明确说明"未检索到"，不编造 |

---

## 12. 已知风险与处理策略

| 风险 | 影响 | 处理方式 |
|------|------|---------|
| DeepSeek 工具调用格式兼容性 | Agent 无法正常调用工具 | 优先验证 `llm.bind_tools()` 是否支持；如不支持则用 `ChatOpenAI` with `tool_choice="auto"` |
| BGE-M3 模型加载慢（~8s）| 首次问答延迟高 | 在 `chat` 命令中仅加载一次；`ask` 命令添加加载进度提示 |
| `compare_versions` 多路召回耗时 | 每个版本独立召回 3 次嵌入查询 | 改为一次 `EMMC_VERSION=all` 召回再按版本分组，减少嵌入次数 |
| `MemorySaver` 内存占用 | 长会话消息列表膨胀 | 在 `chat` 命令中支持 `/clear` 重置；可配置最大历史轮数 |
| LangGraph API 版本差异（0.2.x）| `ToolNode`、`tools_condition` 导入路径不同 | 以 `langgraph 0.2.x` API 为准，实现前检查 `import langgraph; print(langgraph.__version__)` |
