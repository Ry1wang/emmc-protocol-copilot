"""Chainlit 前端：eMMC 协议智能问答助手（Phase 5）。"""
import asyncio
import os

import chainlit as cl
from chainlit.input_widget import Select
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

from src.emmc_copilot.agent.graph import build_agent

# 修复5：load_dotenv 移至模块级，只执行一次
load_dotenv()

# ── 初始化 ──────────────────────────────────────────────────────────────

@cl.on_chat_start
async def on_start():
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

    # 修复1：手动 send/update + run_in_executor，避免阻塞事件循环
    # 修复3：移除 os.environ["LANGCHAIN_SESSION_ID"]，改用 metadata 传递（见 on_message）
    step = cl.Step(name="初始化 Agent", type="run")
    await step.send()
    graph, _ = await asyncio.get_event_loop().run_in_executor(None, build_agent)
    step.output = "Hybrid RAG Agent 已就绪"
    await step.update()

    cl.user_session.set("graph", graph)
    cl.user_session.set("thread_id", cl.context.session.id)
    await cl.Message(content="eMMC 协议助手已就绪，请输入问题。").send()


@cl.on_settings_update
async def on_settings_update(settings: dict):
    _apply_version(settings["version"])
    # 修复1：run_in_executor 避免阻塞事件循环
    # 修复6：告知用户对话上下文已重置
    # 修复7：捕获 build_agent() 异常，防止状态不一致
    try:
        graph, _ = await asyncio.get_event_loop().run_in_executor(None, build_agent)
        cl.user_session.set("graph", graph)
        await cl.Message(
            content=f"已切换至 eMMC {settings['version']} 规范，对话上下文已重置。"
        ).send()
    except Exception as e:
        await cl.Message(content=f"版本切换失败：{e}").send()


# ── 消息处理 ─────────────────────────────────────────────────────────────

@cl.on_message
async def on_message(message: cl.Message):
    # 修复4：graph None 防护
    graph = cl.user_session.get("graph")
    if graph is None:
        await cl.Message(content="会话未初始化，请刷新页面重试。").send()
        return

    thread_id = cl.user_session.get("thread_id")
    # 修复3：通过 metadata 传递 session_id，避免进程级环境变量竞争条件
    config = {
        "configurable": {"thread_id": thread_id},
        "metadata": {"session_id": thread_id},
        "tags": [f"session:{thread_id}"],
    }

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
    else:
        # 修复2：去掉永远为 True 的 elif，改为明确的兜底提示
        await cl.Message(content="未能生成有效回答，请重试。").send()


# ── 工具函数 ─────────────────────────────────────────────────────────────

def _apply_version(version: str):
    os.environ["EMMC_VERSION"] = "" if version == "all" else version

def _fmt_input(tool_input) -> str:
    if isinstance(tool_input, dict):
        return "\n".join(f"{k}: {v}" for k, v in tool_input.items())
    return str(tool_input)

def _truncate(text: str, max_len: int = 600) -> str:
    return text if len(text) <= max_len else text[:max_len] + "…"
