"""Multi-turn REPL acceptance test for Phase 3 agent.

Executes two conversation groups from phase3_test_plan.md Section 4
in a single process so MemorySaver context is preserved across turns.

Usage:
    uv run python tools/run_multiturn_test.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


def _tool_calls_since(messages: list, since: int) -> list[str]:
    lines = []
    for msg in messages[since:]:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                args_str = str(tc.get("args", {}))[:100]
                lines.append(f"  [tool] {tc['name']}({args_str})")
        elif isinstance(msg, ToolMessage):
            preview = str(msg.content)[:120].replace("\n", " ")
            lines.append(f"  [tool result] {preview}…")
    return lines


def ask(graph, question: str, config: dict, prev_len: int = 0):
    result = graph.invoke(
        {"messages": [HumanMessage(content=question)]}, config=config
    )
    msgs = result["messages"]
    tool_lines = _tool_calls_since(msgs, prev_len)
    answer = msgs[-1].content
    return answer, tool_lines, len(msgs)


def run_group(graph, title: str, turns: list[str], thread_id: str) -> list[dict]:
    print(f"\n{'=' * 65}")
    print(f"  {title}")
    print(f"{'=' * 65}")
    config = {"configurable": {"thread_id": thread_id}}
    prev_len = 0
    records = []
    for q in turns:
        print(f"\nUser: {q}")
        answer, tool_lines, prev_len = ask(graph, q, config, prev_len)
        for line in tool_lines:
            print(line)
        print(f"\nAI: {answer}\n")
        records.append({"question": q, "tools": tool_lines, "answer": answer})
    return records


def main():
    print("Loading model and vectorstore…", flush=True)
    from emmc_copilot.agent.graph import build_agent
    graph, _ = build_agent()
    print("Ready.\n")

    group1 = run_group(
        graph,
        title="连续追问组 1：上下文继承与记忆 (FFU)",
        turns=[
            "什么是 FFU？",
            "进入这种模式需要配置哪个寄存器的哪个位？",
            "那这个操作最大需要等待多久（即超时时间怎么算）？",
        ],
        thread_id="phase3-multiturn-ffu",
    )

    group2 = run_group(
        graph,
        title="连续追问组 2：从单点事实发散为版本比对 (CACHE_CTRL)",
        turns=[
            "CACHE_CTRL [33] 寄存器有什么用？",
            "eMMC 4.51 版本也有这个功能吗？",
        ],
        thread_id="phase3-multiturn-cache",
    )

    return group1, group2


if __name__ == "__main__":
    main()
