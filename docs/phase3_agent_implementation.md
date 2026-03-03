# Phase 3 Agent 化实现文档

> **文档说明**：本文档为事后补写（Post-hoc Documentation），依据 Phase 3 实际实现反向整理，
> 还原设计决策与实现方案，供维护者和后续开发者参考。

---

## 1. 目标与范围

### 1.1 Phase 目标

在 Phase 2 混合检索（Dense + BM25 + RRF）基础上，用 **LangGraph** 构建具备工具调用能力的 Agent，从"单次 RAG 问答"升级为"有推理能力的多轮智能体"。

**核心假设（本 Phase 需要验证）**：
> LangGraph ReAct Agent + 4 个专用工具，能处理比纯 RAG 更复杂的跨版本比对、规范计算等任务，同时保持 Phase 2 的引用格式。

### 1.2 里程碑

```bash
# 单轮问答
uv run python -m emmc_copilot.agent.cli ask "eMMC 5.1 和 5.0 在 HS400 模式上有什么区别？"

# 多轮对话
uv run python -m emmc_copilot.agent.cli chat
```

### 1.3 不在范围内

- 流式输出 → Phase 5 (Chainlit)
- LangSmith 追踪 → Phase 5
- 前端界面 → Phase 5

---

## 2. 系统架构

### 2.1 整体数据流

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

### 2.2 四个工具

| 工具 | 函数名 | 触发场景 | 核心依赖 |
|------|--------|---------|---------|
| eMMC 文档检索 | `search_emmc_docs` | 规范事实、寄存器定义、命令说明 | `HybridRetriever` |
| 术语解释 | `explain_term` | 缩写/术语含义查询 | `EMMCVectorStore.glossary` |
| 版本对比 | `compare_versions` | "X 与 Y 的区别"、版本演进 | `HybridRetriever` × 多版本 |
| 规范计算 | `calculate` | 容量、时序、编码值换算 | 内置公式库 |

---

## 3. LangGraph 图设计

### 3.1 State 定义

**文件**: `src/emmc_copilot/agent/state.py`

```python
from typing import Annotated
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

class AgentState(TypedDict):
    """Agent 状态，使用 add_messages reducer 支持多轮对话"""
    messages: Annotated[list[BaseMessage], add_messages]
```

**关键设计**：
- 仅包含 `messages` 字段，无需额外状态
- `add_messages` reducer 自动追加消息，天然支持多轮
- 检索结果通过 `ToolMessage` 内嵌在消息链中

### 3.2 节点设计

**文件**: `src/emmc_copilot/agent/graph.py`

**`agent_node`**（决策节点）：
```python
def agent_node(state: AgentState) -> dict:
    messages = [SystemMessage(content=AGENT_SYSTEM)] + state["messages"]
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}
```

**`tools_node`**（工具执行节点）：
- 使用 `langgraph.prebuilt.ToolNode`
- 自动处理并发工具调用
- 输出 `list[ToolMessage]`

### 3.3 边设计

```python
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode, tools_condition

graph = StateGraph(AgentState)
graph.add_node("agent", agent_node)
graph.add_node("tools", ToolNode(tools))
graph.add_edge(START, "agent")
graph.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: END})
graph.add_edge("tools", "agent")
```

**循环路径**: `agent → tools → agent → tools → ... → agent → END`

### 3.4 多轮对话支持

```python
from langgraph.checkpoint.memory import MemorySaver

checkpointer = MemorySaver()
compiled = graph.compile(checkpointer=checkpointer)

# 每次对话用相同 thread_id
config = {"configurable": {"thread_id": "user-session-1"}}
compiled.invoke({"messages": [HumanMessage(content=question)]}, config=config)
```

**注意**：`MemorySaver` 仅支持单进程内存存储，多进程需改用 `SqliteSaver`。

---

## 4. 工具详细设计

### Tool 1：`search_emmc_docs` — eMMC 文档检索

**文件**: `src/emmc_copilot/agent/tools.py:55-102`

```python
@tool
def search_emmc_docs(query: str, version: str = "") -> str:
    """Search the eMMC (JEDEC JESD84) specification for technical content.

    Use for register definitions, command descriptions, timing parameters,
    protocol flows, or any fact from the eMMC specification.

    Args:
        query: Technical query in English, using spec terminology.
        version: Optional version filter. One of "5.1", "5.0", "4.51", or "".

    Returns:
        Formatted excerpts with Cite-as tags.
    """
```

**实现要点**：
- 复用 `format_docs_with_citations()`（与 Phase 2 RAG chain 一致）
- 内部调用 `_expand_queries()` 生成 2 个变体查询
- 临时覆盖 `retriever.default_version` 实现版本过滤
- 三路去重（原查询 + 2 变体）

### Tool 2：`explain_term` — 术语解释

**文件**: `src/emmc_copilot/agent/tools.py:108-132`

```python
@tool
def explain_term(term: str) -> str:
    """Look up the definition of an eMMC technical term or abbreviation.

    Use when asking what an abbreviation means (e.g. BKOPS, FFU, CMDQ, HPI, RPMB).

    Args:
        term: The term or abbreviation to look up.

    Returns:
        Definition(s) found in the eMMC glossary, or a message if not found.
    """
    vec = embedder.embed_query(term)
    hits = store.query(vec, n_results=5, collection="glossary")
    # ... format results
```

**实现要点**：
- 直接查询 `emmc_glossary` collection
- 返回纯文本（无需 Cite-as，定义较短）
- 无结果时提示尝试 `search_emmc_docs`

### Tool 3：`compare_versions` — 版本对比

**文件**: `src/emmc_copilot/agent/tools.py:138-187`

```python
@tool
def compare_versions(feature: str, versions: str = "4.51,5.0,5.1") -> str:
    """Compare an eMMC feature across multiple spec versions.

    Use when asking about differences between eMMC versions.

    Args:
        feature: The feature, register, or command to compare.
        versions: Comma-separated spec versions (defaults to "4.51,5.0,5.1").

    Returns:
        Version-grouped excerpts formatted as a comparison table.
    """
```

**输出格式**：
```
## eMMC 4.51 (JESD84-B451)
[B451 §X.X p.N] ...

## eMMC 5.0 (JESD84-B50)
[B50 §X.X p.N] ...

## eMMC 5.1 (JESD84-B51)
[B51 §X.X p.N] ...
```

### Tool 4：`calculate` — 规范计算

**文件**: `src/emmc_copilot/agent/tools.py:193-223`

**⚠️ 关键实现差异**：

```python
@tool
def calculate(formula: str, parameters: dict) -> str:
    """Perform eMMC specification calculations.

    Args:
        formula: Formula name (e.g. "boot_size", "capacity").
        parameters: Dict of register values (e.g. {"boot_size_mult": 16}).

    Returns:
        Step-by-step calculation with spec reference.
    """
```

**为什么不用 `**kwargs`**？

设计文档原方案 `def calculate(formula: str, **kwargs)` 会导致 LangChain 生成错误的 JSON schema：

```python
# 错误的 schema（导致 KeyError）
{"properties": {"kwargs": {"type": "object"}}}

# 正确的 schema
{"properties": {"formula": {"type": "string"}, "parameters": {"type": "object"}}}
```

**内置公式**：

| 公式名 | 计算逻辑 | 规范依据 |
|--------|---------|---------|
| `boot_size` | `128 KB × BOOT_SIZE_MULT` | EXT_CSD [226] |
| `rpmb_size` | `128 KB × RPMB_SIZE_MULT` | EXT_CSD [168] |
| `capacity` | `SEC_COUNT × 512 bytes` | EXT_CSD [215:212] |
| `tran_speed` | `FREQ_UNIT[freq_unit] × MULT[mult]` | CSD [103:96] |
| `erase_group` | `(HC_ERASE_GRP_SIZE + 1) × 512 KB` | EXT_CSD [224] |
| `wp_group` | `(HC_WP_GRP_SIZE + 1) × ERASE_GRP_SIZE` | EXT_CSD [221] |
| `sleep_current` | `1 µA × 2^(S_C_VCC)` | EXT_CSD [143] |
| `gp_size` | `GP_SIZE_MULT × WP_GRP_SIZE` | EXT_CSD [154:143] |

---

## 5. Agent System Prompt

**文件**: `src/emmc_copilot/agent/prompt.py`

```python
AGENT_SYSTEM = """\
You are an expert on the eMMC (JEDEC JESD84) specification, assisting hardware/firmware engineers.
You have access to four tools:

1. search_emmc_docs   — Use for any factual question about registers, commands, timing,
                        protocols, or spec content. This is your primary tool.
2. explain_term       — Use when the user asks what an abbreviation or term means,
                        BEFORE doing a deeper search if the term meaning is unclear.
3. compare_versions   — Use when the question explicitly asks about differences between
                        eMMC versions (e.g. "5.0 vs 5.1", "added in 5.1", "which version").
4. calculate          — Use when the question requires converting a register value to
                        a physical quantity (size in KB/MB, frequency in MHz, etc.).

Workflow rules:
- You may call multiple tools in sequence or parallel if the question requires it.
- Always cite sources inline using Cite-as tags from tool output: e.g. [B51 §7.4.111 p.246].
- If a tool returns no relevant content, state clearly that the information is not in the
  retrieved excerpts — do NOT fabricate register names, values, or behaviors.
- For multi-byte EXT_CSD fields: byte order is little-endian (lowest index = LSByte).
- When a register or field name is not found in tool output, explicitly state it does NOT
  exist in the eMMC specification rather than saying "not enough information".
- Mirror the language of the question (reply in Chinese if asked in Chinese).
"""
```

**与 Phase 2 prompt 的区别**：
- Phase 2 prompt 侧重答案格式（引用格式）
- Agent prompt 侧重**工具选择策略**（何时用哪个工具）

---

## 6. 文件结构

```
src/emmc_copilot/agent/
├── __init__.py      # 导出 build_agent, AgentState
├── state.py         # AgentState TypedDict（~20 行）
├── prompt.py        # AGENT_SYSTEM prompt（~30 行）
├── tools.py         # 4 个工具 + build_tools()（~330 行）
├── graph.py         # StateGraph + build_agent()（~110 行）
└── cli.py           # ask / chat 命令（~170 行）
```

---

## 7. CLI 接口

### 单次问答

```bash
uv run python -m emmc_copilot.agent.cli ask \
  "eMMC 5.1 和 5.0 在 HS400 模式上有什么区别？"

# 带工具调用日志
uv run python -m emmc_copilot.agent.cli ask "..." --verbose
```

### 多轮对话

```bash
uv run python -m emmc_copilot.agent.cli chat

# REPL 命令
/clear   # 重置会话
/tools   # 显示可用工具
/exit    # 退出
```

### thread-id 管理

```bash
# 指定会话 ID（用于跨进程恢复）
uv run python -m emmc_copilot.agent.cli ask "..." --thread-id my-session
```

---

## 8. 环境变量

Phase 3 沿用 Phase 2 的所有环境变量，无新增：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DEEPSEEK_API_KEY` | —（必填） | DeepSeek API Key |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` | LLM 接口 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | 模型名 |
| `CHROMA_PERSIST_DIR` | `data/vectorstore/chroma` | ChromaDB 路径 |
| `BM25_INDEX_DIR` | `data/vectorstore/bm25` | BM25 索引 |
| `EMMC_VERSION` | `5.1` | 默认版本（`all` = 不过滤） |

---

## 9. 关键风险与应对

| 风险 | 描述 | 应对策略 | 状态 |
|------|------|---------|:----:|
| **calculate 工具序列化** | `**kwargs` 导致 JSON schema 错误 | 改用 `parameters: dict` | ✅ 已解决 |
| DeepSeek 工具调用兼容性 | `bind_tools()` 可能不支持 | 已验证兼容 DeepSeek | ✅ 无问题 |
| BGE-M3 首次加载慢（~8s） | 首次问答延迟高 | CLI 添加加载提示 | ✅ 已缓解 |
| `compare_versions` 耗时 | 多版本独立召回 | 当前实现可接受 | ⚠️ 后续优化 |
| `MemorySaver` 内存占用 | 长会话消息膨胀 | `/clear` 重置 | ✅ 已缓解 |

---

## 10. 验收测试结果

### 单轮测试

| 测试用例 | 期望工具 | 实际结果 | 状态 |
|---------|---------|---------|:----:|
| "eMMC 5.1 和 5.0 在 HS400 上有什么区别？" | `compare_versions` | 正确调用，输出对比表 | ✅ |
| "BKOPS 是什么意思？如何启用？" | `explain_term` + `search_emmc_docs` | 正确调用两次 | ✅ |
| "BOOT_SIZE_MULT=0x10 时 Boot 分区多大？" | `calculate` | 正确计算：2048 KB = 2 MB | ✅ |
| "EXT_CSD[185] 寄存器名？" | `search_emmc_docs` | 正确回答 HS_TIMING | ✅ |

### 多轮测试

```
Q: eMMC 5.1 的 CACHE_CTRL [33] 寄存器如何使用？
A: [回答 bit 0 含义，含引用]

Q: 那 4.51 版本有这个寄存器吗？
A: [调用 compare_versions 或 search_emmc_docs with version=4.51]

Q: 如果有，开启 Cache 需要什么前提条件？
A: [结合上下文继续检索]
```

**测试结果**：多轮 5/5 通过 ✅

---

## 11. 与设计文档的关键差异

| 设计文档 | 实际实现 | 原因 |
|---------|---------|------|
| `calculate(formula, **kwargs)` | `calculate(formula, parameters)` | LangChain 序列化 `**kwargs` 有 bug |

---

## 12. 交付给 Phase 4/5 的接口

```python
# Agent 调用接口（Phase 5 Chainlit 可直接使用）
from emmc_copilot.agent import build_agent

graph, retriever = build_agent()
config = {"configurable": {"thread_id": "session-1"}}

result = graph.invoke(
    {"messages": [HumanMessage(content=question)]},
    config=config
)
answer = result["messages"][-1].content
```

**数据契约**：
- `result["messages"]` 为完整消息历史（`HumanMessage` → `AIMessage` → `ToolMessage` → ...）
- 最后一条 `AIMessage.content` 为最终答案
- 可通过 `graph.get_state(config)` 访问中间状态

---

*Phase 3 Implementation Document — eMMC Protocol Copilot*
*文档类型：Post-hoc Documentation（事后补写）*
*基于实际实现反向整理，版本对应 Phase 3 最终实现状态*
