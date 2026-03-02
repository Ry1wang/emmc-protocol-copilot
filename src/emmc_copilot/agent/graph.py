"""LangGraph agent graph for the eMMC Q&A agent.

Build the compiled StateGraph with:
    agent_node  — DeepSeek LLM with tool bindings (reasoning + tool dispatch)
    tools_node  — ToolNode (parallel tool execution)

Edges:
    START → agent
    agent → tools  (if AIMessage contains tool_calls)
    agent → END    (if AIMessage has no tool_calls)
    tools → agent  (loop back after tool results)

Multi-turn support via MemorySaver checkpoint (in-process; pass same thread_id across turns).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from langchain_core.messages import SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from .prompt import AGENT_SYSTEM
from .state import AgentState
from .tools import build_tools

logger = logging.getLogger(__name__)


def build_agent():
    """Build and return the compiled eMMC LangGraph agent.

    Environment variables (shared with qa/chain.py):
        DEEPSEEK_API_KEY    — required
        DEEPSEEK_BASE_URL   — optional, defaults to https://api.deepseek.com/v1
        DEEPSEEK_MODEL      — optional, defaults to deepseek-chat
        CHROMA_PERSIST_DIR  — optional, defaults to data/vectorstore/chroma
        BM25_INDEX_DIR      — optional, defaults to data/vectorstore/bm25
        EMMC_VERSION        — default version filter; "5.1" (default) | "5.0" | "4.51" | "all"

    Returns:
        (compiled_graph, retriever) — the compiled StateGraph and base retriever.
        Pass the retriever to inspect retrieved docs independently of the agent loop.
    """
    from dotenv import load_dotenv
    from langchain_openai import ChatOpenAI

    from ..retrieval.bm25_index import BM25Corpus
    from ..retrieval.embedder import BGEEmbedder
    from ..retrieval.hybrid_retriever import HybridRetriever
    from ..retrieval.vectorstore import EMMCVectorStore
    from ..qa.retriever import EMMCRetriever

    load_dotenv()

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    chroma_dir = os.environ.get("CHROMA_PERSIST_DIR", "data/vectorstore/chroma")
    bm25_dir = Path(os.environ.get("BM25_INDEX_DIR", "data/vectorstore/bm25"))
    _ver_env = os.environ.get("EMMC_VERSION", "5.1").strip()
    default_version = "" if _ver_env.lower() == "all" else _ver_env

    embedder = BGEEmbedder()
    store = EMMCVectorStore(chroma_dir)

    bm25_pkl = bm25_dir / "corpus.pkl"
    try:
        bm25_corpus = BM25Corpus.load(bm25_pkl)
        retriever = HybridRetriever(
            embedder=embedder, store=store, bm25_corpus=bm25_corpus,
            default_version=default_version,
        )
        logger.info("Agent: Hybrid retriever enabled (%d chunks)", len(bm25_corpus))
    except FileNotFoundError:
        logger.warning(
            "BM25 index not found at %s, using dense-only retriever.", bm25_pkl
        )
        retriever = EMMCRetriever(embedder=embedder, store=store, default_version=default_version)

    llm = ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=0.1,
    )

    tools = build_tools(retriever, store, embedder, llm)
    llm_with_tools = llm.bind_tools(tools)

    def agent_node(state: AgentState) -> dict:
        messages = [SystemMessage(content=AGENT_SYSTEM)] + state["messages"]
        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode(tools))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")

    checkpointer = MemorySaver()
    compiled = graph.compile(checkpointer=checkpointer)

    logger.info("Agent graph compiled (version filter default=%r)", default_version or "all")
    return compiled, retriever
