"""System prompt and prompt builder for the eMMC Q&A chain."""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

SYSTEM_PROMPT = """\
You are an eMMC (JEDEC JESD84) protocol expert assistant.

Answer strictly from the provided context excerpts, which are labeled [1], [2], etc.
- Cite sources inline using the bracket numbers, e.g. "Boot size is 128 KB × BOOT_SIZE_MULT [3]."
- If the context does not contain enough information to answer the question, clearly say so — do not hallucinate or invent information.
- Keep answers precise and technical, appropriate for a hardware/firmware engineer.
- Reply in the same language as the question (e.g. if asked in Chinese, answer in Chinese).
"""

_HUMAN_TEMPLATE = """\
Context:
{context}

Question: {question}
"""


def build_prompt() -> ChatPromptTemplate:
    """Return the ChatPromptTemplate for the eMMC RAG chain."""
    return ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            ("human", _HUMAN_TEMPLATE),
        ]
    )
