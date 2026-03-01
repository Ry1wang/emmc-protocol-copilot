"""CLI entry point for the eMMC Q&A chain.

Subcommands:
    ask   — single question, then exit
    chat  — interactive REPL (model loaded once, loop until 'exit'/'quit')

Usage::

    uv run python -m emmc_copilot.qa.cli ask "eMMC的Boot分区大小是多少？" --show-sources
    uv run python -m emmc_copilot.qa.cli chat --show-sources
"""

from __future__ import annotations

import argparse
import sys


def _print_sources(docs) -> None:
    """Print the retrieved source documents in a human-readable format."""
    print("\n[来源]")
    for i, doc in enumerate(docs, start=1):
        m = doc.metadata
        source = m.get("source", "unknown")
        page_start = m.get("page_start", "?")
        page_end = m.get("page_end", page_start)
        pages = str(page_start) if page_start == page_end else f"{page_start}–{page_end}"

        raw_path = m.get("section_path", "")
        section_num = raw_path.split("/")[-1] if raw_path else ""
        section_title = m.get("section_title", "")
        section_label = f"{section_num} {section_title}".strip() if section_num else section_title

        # _distance is None for BM25-only hits (not present in dense results)
        dist = m.get("_distance")
        rrf = m.get("_rrf_score")
        score_str = f"dist={dist:.3f}" if dist is not None else f"rrf={rrf:.4f}" if rrf is not None else "bm25-only"
        print(f"[{i}] {source} | p.{pages} | {section_label}  ({score_str})")


def _run_ask(question: str, show_sources: bool) -> None:
    """Load the chain, answer one question, then exit."""
    print("Loading model and vectorstore…", flush=True)
    from .chain import build_chain

    chain, retriever = build_chain()

    if show_sources:
        docs = retriever.invoke(question)
        _print_sources(docs)

    print("\n[回答]")
    answer = chain.invoke(question)
    print(answer)


def _run_chat(show_sources: bool) -> None:
    """Interactive REPL — load model once, loop until the user quits."""
    print("Loading model and vectorstore…", flush=True)
    from .chain import build_chain

    chain, retriever = build_chain()
    print("Ready. Type your question (or 'exit' / 'quit' to stop).\n")

    while True:
        try:
            question = input("Q: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not question:
            continue
        if question.lower() in {"exit", "quit", "q"}:
            print("Bye.")
            break

        if show_sources:
            docs = retriever.invoke(question)
            _print_sources(docs)

        print("\n[回答]")
        answer = chain.invoke(question)
        print(answer)
        print()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="emmc_copilot.qa.cli",
        description="eMMC Protocol Q&A — powered by RAG + DeepSeek",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- ask subcommand ---
    ask_parser = sub.add_parser("ask", help="Answer a single question and exit")
    ask_parser.add_argument("question", help="The question to ask")
    ask_parser.add_argument(
        "--show-sources",
        action="store_true",
        help="Print retrieved source documents before the answer",
    )

    # --- chat subcommand ---
    chat_parser = sub.add_parser("chat", help="Interactive REPL")
    chat_parser.add_argument(
        "--show-sources",
        action="store_true",
        help="Print retrieved source documents before each answer",
    )

    args = parser.parse_args(argv)

    if args.command == "ask":
        _run_ask(args.question, args.show_sources)
    elif args.command == "chat":
        _run_chat(args.show_sources)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
