"""CLI entry point for the eMMC LangGraph agent.

Subcommands:
    ask   — single question (one-shot), then exit
    chat  — interactive multi-turn REPL with MemorySaver context

Usage::

    uv run python -m emmc_copilot.agent.cli ask "eMMC 5.1 和 5.0 在 HS400 上有什么区别？"
    uv run python -m emmc_copilot.agent.cli chat
    uv run python -m emmc_copilot.agent.cli ask "..." --thread-id my-session

REPL commands (during chat):
    /clear   — reset conversation history for current thread
    /tools   — list available tools
    /exit    — quit (also Ctrl-C / Ctrl-D)
"""

from __future__ import annotations

import argparse
import sys
import uuid


def _stream_or_invoke(graph, question: str, config: dict) -> str:
    """Invoke the agent and return the final AI text response."""
    from langchain_core.messages import HumanMessage

    result = graph.invoke({"messages": [HumanMessage(content=question)]}, config=config)
    # Last message is always the final AIMessage (no tool_calls)
    return result["messages"][-1].content


def _print_tool_calls(messages) -> None:
    """Print a summary of tool calls made in the last agent turn."""
    from langchain_core.messages import AIMessage, ToolMessage

    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                args_preview = str(tc.get("args", {}))[:80]
                print(f"  [tool] {tc['name']}({args_preview})")
        elif isinstance(msg, ToolMessage):
            preview = str(msg.content)[:120].replace("\n", " ")
            print(f"  [tool result] {preview}…")


def _run_ask(question: str, thread_id: str, verbose: bool) -> None:
    print("Loading model and vectorstore…", flush=True)
    from .graph import build_agent

    graph, _ = build_agent()
    config = {"configurable": {"thread_id": thread_id}}

    answer = _stream_or_invoke(graph, question, config)

    if verbose:
        state = graph.get_state(config)
        _print_tool_calls(state.values["messages"])

    print("\n[回答]")
    print(answer)


def _run_chat(thread_id: str, verbose: bool) -> None:
    print("Loading model and vectorstore…", flush=True)
    from .graph import build_agent

    graph, _ = build_agent()

    _TOOLS_HELP = (
        "Available tools:\n"
        "  search_emmc_docs  — eMMC spec retrieval (primary)\n"
        "  explain_term      — abbreviation / term lookup\n"
        "  compare_versions  — side-by-side version comparison\n"
        "  calculate         — spec formula calculations\n"
    )

    print("Ready. Type your question (or /clear /tools /exit).\n")
    config = {"configurable": {"thread_id": thread_id}}

    while True:
        try:
            question = input("Q: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not question:
            continue

        if question == "/exit":
            print("Bye.")
            break

        if question == "/tools":
            print(_TOOLS_HELP)
            continue

        if question == "/clear":
            thread_id = str(uuid.uuid4())
            config = {"configurable": {"thread_id": thread_id}}
            print(f"[会话已重置，new thread_id={thread_id}]\n")
            continue

        try:
            answer = _stream_or_invoke(graph, question, config)
        except Exception as exc:
            print(f"[Error] {exc}")
            continue

        if verbose:
            state = graph.get_state(config)
            _print_tool_calls(state.values["messages"])

        print("\n[回答]")
        print(answer)
        print()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="emmc_copilot.agent.cli",
        description="eMMC Protocol Agent — LangGraph + DeepSeek",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- ask ---
    ask_p = sub.add_parser("ask", help="Answer a single question and exit")
    ask_p.add_argument("question", help="The question to ask")
    ask_p.add_argument(
        "--thread-id",
        default=str(uuid.uuid4()),
        help="Session thread ID for MemorySaver (default: random UUID)",
    )
    ask_p.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print tool calls made during reasoning",
    )

    # --- chat ---
    chat_p = sub.add_parser("chat", help="Interactive multi-turn REPL")
    chat_p.add_argument(
        "--thread-id",
        default=str(uuid.uuid4()),
        help="Session thread ID (default: random UUID per chat session)",
    )
    chat_p.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print tool calls made during reasoning",
    )

    args = parser.parse_args(argv)

    if args.command == "ask":
        _run_ask(args.question, args.thread_id, args.verbose)
    elif args.command == "chat":
        _run_chat(args.thread_id, args.verbose)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
