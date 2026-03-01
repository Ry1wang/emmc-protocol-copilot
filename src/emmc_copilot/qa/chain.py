"""LCEL RAG chain for eMMC Q&A: retriever → format → prompt → LLM → answer."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough

from .prompt import build_prompt
from .retriever import EMMCRetriever

logger = logging.getLogger(__name__)


def format_docs_with_citations(docs: list[Document]) -> str:
    """Format retrieved documents as a numbered context block for the LLM prompt.

    Each document gets a citation header [N] that the LLM uses for inline references.
    The section_path stored as "6/6.3/6.3.2" is displayed as "6.3.2".

    Example output::

        [1] Source: JESD84-B51.pdf | Pages: 49 | Section: 6.3.2 Boot partition
        [eMMC 5.1 | 6.3.2 | Page 49]
        The boot partition size is 128 KB × BOOT_SIZE_MULT...

        [2] Source: JESD84-B451.pdf | Pages: 179 | Section: 7.4.24 BOOT_SIZE_MULT
        ...
    """
    parts: list[str] = []
    for i, doc in enumerate(docs, start=1):
        m = doc.metadata
        source = m.get("source", "unknown")
        page_start = m.get("page_start", "?")
        page_end = m.get("page_end", page_start)
        pages = str(page_start) if page_start == page_end else f"{page_start}–{page_end}"

        raw_path = m.get("section_path", "")
        # section_path is stored as "6/6.3/6.3.2"; take the last segment and replace / with .
        section_num = raw_path.split("/")[-1].replace("/", ".") if raw_path else ""
        section_title = m.get("section_title", "")
        section_label = f"{section_num} {section_title}".strip() if section_num else section_title

        header = f"[{i}] Source: {source} | Pages: {pages} | Section: {section_label}"
        parts.append(f"{header}\n{doc.page_content}")

    return "\n\n".join(parts)


def build_chain():
    """Build and return the eMMC RAG chain together with its retriever.

    Environment variables read at call time (not import time) via dotenv:
        DEEPSEEK_API_KEY    — required
        DEEPSEEK_BASE_URL   — optional, defaults to https://api.deepseek.com/v1
        DEEPSEEK_MODEL      — optional, defaults to deepseek-chat
        CHROMA_PERSIST_DIR  — optional, defaults to data/vectorstore/chroma
        BM25_INDEX_DIR      — optional, defaults to data/vectorstore/bm25

    Returns:
        (chain, retriever) — the LCEL chain and the retriever instance.
        The retriever is a HybridRetriever when the BM25 index is present,
        or an EMMCRetriever (dense-only) otherwise.
    """
    from dotenv import load_dotenv
    from langchain_openai import ChatOpenAI

    from ..retrieval.bm25_index import BM25Corpus
    from ..retrieval.embedder import BGEEmbedder
    from ..retrieval.hybrid_retriever import HybridRetriever
    from ..retrieval.vectorstore import EMMCVectorStore

    load_dotenv()

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    chroma_dir = os.environ.get("CHROMA_PERSIST_DIR", "data/vectorstore/chroma")
    bm25_dir = Path(os.environ.get("BM25_INDEX_DIR", "data/vectorstore/bm25"))

    embedder = BGEEmbedder()
    store = EMMCVectorStore(chroma_dir)

    bm25_pkl = bm25_dir / "corpus.pkl"
    try:
        bm25_corpus = BM25Corpus.load(bm25_pkl)
        retriever = HybridRetriever(embedder=embedder, store=store, bm25_corpus=bm25_corpus)
        logger.info("Hybrid retriever enabled (BM25 index: %s, %d chunks)", bm25_pkl, len(bm25_corpus))
    except FileNotFoundError:
        logger.warning(
            "BM25 index not found at %s, using dense-only retriever. "
            "Run: uv run python -m emmc_copilot.retrieval.cli build-bm25",
            bm25_pkl,
        )
        retriever = EMMCRetriever(embedder=embedder, store=store)

    llm = ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=0.1,
    )

    chain = (
        {
            "context": retriever | format_docs_with_citations,
            "question": RunnablePassthrough(),
        }
        | build_prompt()
        | llm
        | StrOutputParser()
    )

    return chain, retriever
