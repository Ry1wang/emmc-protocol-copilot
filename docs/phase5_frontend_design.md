# Phase 5：Chainlit 前端 + LangSmith 监控

## Context

Phase 1–4 已完成 PDF 解析、混合检索、LangGraph Agent（4 工具）和 RAGAS 离线评估。
系统目前只有 CLI 入口（`qa/cli.py` + `agent/cli.py`），缺乏 Web 交互界面和线上可观测性。
Phase 5 目标：用 Chainlit 实现流式聊天前端，同时接入 LangSmith 追踪每次对话。

---

## 架构总览

```
浏览器  →  Chainlit (app.py)
              ├─ @on_chat_start      : build_agent() 初始化（每 session 一次）
              ├─ @on_settings_update : 版本切换 (EMMC_VERSION)
              └─ @on_message         : astream_events()
                                          ├─ on_tool_start  → cl.Step（工具调用可见）
                                          ├─ on_tool_end    → cl.Step 输出
                                          └─ on_chat_model_stream → 流式 token（最终答案）

app.py 引用:
  build_agent()  ←  src/emmc_copilot/agent/graph.py:34
  (graph.py / tools.py / chain.py 无需修改)

LangSmith: LANGCHAIN_TRACING_V2=true + 真实 LANGCHAIN_API_KEY → 自动上报所有 trace
  LANGCHAIN_SESSION_ID = cl.context.session.id  （在 on_chat_start 设置，按 session 分组）
```

---

## 新增文件（2个）

### 1. `app.py`（项目根目录）— Chainlit 入口

**完整结构**：

```python
"""Chainlit 前端：eMMC 协议智能问答助手（Phase 5）。"""
import os

import chainlit as cl
from chainlit.input_widget import Select
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

from src.emmc_copilot.agent.graph import build_agent

# ── 初始化 ──────────────────────────────────────────────────────────────

@cl.on_chat_start
async def on_start():
    load_dotenv()
    # 版本选择器（ChatSettings 右上角齿轮）
    settings = await cl.ChatSettings([
        Select(
            id="version",
            label="eMMC 规范版本",
            values=["5.1", "5.0", "4.51", "all"],
            initial_value="5.1",
        )
    ]).send()
    _apply_version(settings["version"])

    # LangSmith：按 Chainlit session 分组 trace
    os.environ["LANGCHAIN_SESSION_ID"] = cl.context.session.id

    # 构建 Agent（每 session 一次，避免重复加载 BGE-M3）
    with cl.Step(name="初始化 Agent", type="run") as step:
        graph, _ = build_agent()
        step.output = "Hybrid RAG Agent 已就绪"

    cl.user_session.set("graph", graph)
    cl.user_session.set("thread_id", cl.context.session.id)
    await cl.Message(content="eMMC 协议助手已就绪，请输入问题。").send()


@cl.on_settings_update
async def on_settings_update(settings: dict):
    _apply_version(settings["version"])
    # 重建 Agent（default_version 变更需重建 retriever）
    graph, _ = build_agent()
    cl.user_session.set("graph", graph)
    await cl.Message(
        content=f"已切换至 eMMC {settings['version']} 规范。"
    ).send()


# ── 消息处理 ─────────────────────────────────────────────────────────────

@cl.on_message
async def on_message(message: cl.Message):
    graph     = cl.user_session.get("graph")
    thread_id = cl.user_session.get("thread_id")
    config    = {"configurable": {"thread_id": thread_id}}

    active_steps: dict[str, cl.Step] = {}
    answer_msg   = cl.Message(content="")
    had_tool_calls = False
    streaming      = False

    async for event in graph.astream_events(
        {"messages": [HumanMessage(content=message.content)]},
        config=config,
        version="v2",
    ):
        kind = event["event"]

        if kind == "on_tool_start":
            had_tool_calls = True
            step = cl.Step(name=event["name"], type="tool")
            step.input = _fmt_input(event["data"].get("input", {}))
            await step.send()
            active_steps[event["run_id"]] = step

        elif kind == "on_tool_end":
            if step := active_steps.pop(event["run_id"], None):
                out = event["data"].get("output", "")
                step.output = _truncate(str(getattr(out, "content", out)), 600)
                await step.update()

        elif kind == "on_chat_model_stream":
            content = event["data"]["chunk"].content
            if isinstance(content, str) and content:
                # 流式显示条件：直接回答（无工具）或所有工具已完成
                if not had_tool_calls or not active_steps:
                    if not streaming:
                        await answer_msg.send()
                        streaming = True
                    await answer_msg.stream_token(content)

    if streaming:
        await answer_msg.update()
    elif not answer_msg.content:
        await answer_msg.send()


# ── 工具函数 ─────────────────────────────────────────────────────────────

def _apply_version(version: str):
    os.environ["EMMC_VERSION"] = "" if version == "all" else version

def _fmt_input(tool_input) -> str:
    if isinstance(tool_input, dict):
        return "\n".join(f"{k}: {v}" for k, v in tool_input.items())
    return str(tool_input)

def _truncate(text: str, max_len: int = 600) -> str:
    return text if len(text) <= max_len else text[:max_len] + "…"
```

---

### 2. `chainlit.md`（项目根目录）— 欢迎页

```markdown
# eMMC 协议智能问答助手

基于 JEDEC JESD84 规范（4.51 / 5.0 / 5.1），提供：

- **寄存器/字段查询**：EXT_CSD、CSD、CID 任意字段含义与位定义
- **命令与流程**：CMD6、CMD46、HS200/HS400 调谐、RPMB 访问流程等
- **跨版本对比**：自动检索多版本规范并并排比较
- **公式计算**：Boot 分区大小、RPMB 容量、TRAN_SPEED 解码等
- **术语解释**：BKOPS、FFU、HPI、CMDQ 等缩写一键查询

## 示例问题

- `EXT_CSD[33] CACHE_CTRL 第 0 位的含义是什么？`
- `eMMC 5.0 和 5.1 在 Command Queuing 上有何区别？`
- `EXT_CSD[226]=32 时 Boot 分区有多大？`

右上角 ⚙️ 可切换规范版本（默认 5.1）。
```

---

## 修改文件（0个）

**无需修改任何现有业务代码**。

LangSmith 监控通过在 `.env` 中填入真实 key 激活（`.env` 中已有变量定义，仅需填值）：

```
LANGCHAIN_API_KEY=<从 https://smith.langchain.com 获取>
LANGCHAIN_TRACING_V2=true          # 已有，无需改
LANGCHAIN_PROJECT=emmc-copilot     # 已有，无需改
```

---

## 关键文件路径参考

| 文件 | 用途 |
|------|------|
| `src/emmc_copilot/agent/graph.py:34` | `build_agent()` — app.py 直接调用 |
| `src/emmc_copilot/agent/tools.py` | 4 工具名称（search_emmc_docs / explain_term / compare_versions / calculate） |
| `src/emmc_copilot/agent/prompt.py` | AGENT_SYSTEM（不修改） |
| `pyproject.toml` | chainlit>=1.2 已在主依赖中 |
| `.env` | LANGCHAIN_API_KEY 需填真实值 |

---

## 流式输出设计说明

`astream_events v2` 事件过滤逻辑：

```
on_tool_start   → 创建 cl.Step，active_steps[run_id] = step
on_tool_end     → 关闭 step，写入输出，active_steps.pop(run_id)
on_chat_model_stream → 满足以下任一条件时流式输出到 answer_msg：
    (1) 本轮没有工具调用（LLM 直接回答）
    (2) had_tool_calls=True 且 active_steps 已清空（所有工具执行完毕，LLM 生成最终答案）
```

此策略避免了将 LLM"决策哪个工具"的 reasoning tokens 展示给用户。

---

## 实现顺序

1. `chainlit.md` — 静态欢迎页
2. `app.py` — 主要工作量（on_start / on_settings_update / on_message）
3. 本地验证（`uv run chainlit run app.py --watch`）

---

## 验收验证

```bash
# 启动服务
uv run chainlit run app.py --watch
# 浏览器打开 http://localhost:8000

# 验收 1：欢迎页与版本选择器
#   页面显示 chainlit.md 内容；右上角齿轮可切换版本

# 验收 2：流式输出
#   输入："EXT_CSD[33] CACHE_CTRL 第 0 位的含义是什么？"
#   期望：search_emmc_docs Step 可见 → 答案 token 逐字流出

# 验收 3：工具调用展示
#   输入："计算 EXT_CSD[226]=16 时的 Boot 分区大小"
#   期望：calculate Step（input: formula: boot_size, boot_size_mult: 16）可见

# 验收 4：多工具调用
#   输入："对比 eMMC 4.51、5.0、5.1 的 Command Queuing 支持情况"
#   期望：compare_versions Step 可见，答案包含三版本对比

# 验收 5：多轮对话
#   轮1："HS200 是什么？"
#   轮2："它和 HS400 有什么区别？"
#   期望：第 2 轮能引用第 1 轮上下文

# 验收 6：版本切换
#   右上角切换到 4.51 → 询问 HS200 相关问题
#   期望：系统说明该功能在 4.51 中不支持（5.0 引入）

# 验收 7：LangSmith（需真实 key）
#   访问 https://smith.langchain.com → 项目 emmc-copilot
#   确认 trace 已上报，可查看每步 token 用量和延迟
```
