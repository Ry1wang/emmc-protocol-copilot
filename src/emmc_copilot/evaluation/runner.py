"""Pipeline runners and RAGAS evaluation harness for Phase 4.

Three pipeline runners:
    run_dense_rag   — dense-only (BGE-M3 only, no BM25); baseline
    run_hybrid_rag  — hybrid (BGE-M3 + BM25 + RRF); current production
    run_agent       — LangGraph agent (hybrid retrieval + 4 tools)

Each runner returns (responses, contexts_per_question):
    responses  : list[str]        — one final answer per question
    contexts   : list[list[str]]  — retrieved text chunks per question

Also exports:
    ragas_evaluate  — wraps ragas.evaluate() with DeepSeek judge LLM + BGE embeddings
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, ToolMessage

from ragas import EvaluationDataset, RunConfig, evaluate
from ragas.embeddings import _LangchainEmbeddingsWrapper
from ragas.llms import _LangchainLLMWrapper
# Use ragas.metrics (not ragas.metrics.collections) — these are instances of
# ragas.metrics.base.Metric and are the only type accepted by ragas.evaluate().
from ragas.metrics import (
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
)

if TYPE_CHECKING:
    from ragas import EvaluationResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BGE embeddings adapter  (BGEEmbedder → LangChain Embeddings interface)
# ---------------------------------------------------------------------------

from langchain_core.embeddings import Embeddings as _LCEmbeddings
from ..retrieval.embedder import BGEEmbedder


class _BGEEmbeddingsAdapter(_LCEmbeddings):
    """Wraps BGEEmbedder as a LangChain Embeddings object for RAGAS.

    ragas.evaluate() with old-style metrics (ragas.metrics.*) expects a
    LangchainEmbeddingsWrapper(Embeddings) for the embeddings parameter.
    BGEEmbedder._model is lazy-private — this adapter forwards embed_documents
    and embed_query to the existing instance, avoiding a second model load.
    """

    def __init__(self, embedder: BGEEmbedder) -> None:
        self._e = embedder

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._e.embed(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._e.embed_query(text)


# ---------------------------------------------------------------------------
# Dense-only RAG runner
# ---------------------------------------------------------------------------

def run_dense_rag(
    questions: list[str],
) -> tuple[list[str], list[list[str]]]:
    """Run questions through the dense-only RAG chain (no BM25).

    Forces BM25_INDEX_DIR to a nonexistent path so build_chain() falls back to
    EMMCRetriever (BGE-M3 semantic vector search only).  This is the baseline.

    Returns:
        (responses, contexts_per_question)
    """
    from ..qa.chain import build_chain

    old_bm25 = os.environ.get("BM25_INDEX_DIR")
    os.environ["BM25_INDEX_DIR"] = "__dense_eval_no_bm25_sentinel__"
    try:
        chain, retriever = build_chain()
        logger.info("Dense-only RAG chain built (BM25 disabled).")
    finally:
        if old_bm25 is None:
            os.environ.pop("BM25_INDEX_DIR", None)
        else:
            os.environ["BM25_INDEX_DIR"] = old_bm25

    responses: list[str] = []
    contexts_list: list[list[str]] = []
    for i, q in enumerate(questions, 1):
        logger.info("[dense %d/%d] %s", i, len(questions), q[:60])
        resp = chain.invoke(q)
        docs = retriever.invoke(q)
        responses.append(resp)
        contexts_list.append([d.page_content for d in docs[:5]])

    return responses, contexts_list


# ---------------------------------------------------------------------------
# Hybrid RAG runner
# ---------------------------------------------------------------------------

def run_hybrid_rag(
    questions: list[str],
) -> tuple[list[str], list[list[str]]]:
    """Run questions through the Hybrid RAG chain (BGE-M3 + BM25 + RRF).

    Uses the default environment (expects BM25 index at data/vectorstore/bm25/).

    Returns:
        (responses, contexts_per_question)
    """
    from ..qa.chain import build_chain

    chain, retriever = build_chain()
    logger.info("Hybrid RAG chain built.")

    responses: list[str] = []
    contexts_list: list[list[str]] = []
    for i, q in enumerate(questions, 1):
        logger.info("[hybrid %d/%d] %s", i, len(questions), q[:60])
        resp = chain.invoke(q)
        docs = retriever.invoke(q)
        responses.append(resp)
        contexts_list.append([d.page_content for d in docs[:5]])

    return responses, contexts_list


# ---------------------------------------------------------------------------
# Agent runner
# ---------------------------------------------------------------------------

def run_agent(
    questions: list[str],
) -> tuple[list[str], list[list[str]]]:
    """Run questions through the LangGraph agent.

    For each question the agent is invoked in a fresh thread so there is no
    cross-question memory contamination.  Contexts are extracted post-hoc from
    ToolMessage objects in the final state — this captures outputs from ALL tools
    (search_emmc_docs, explain_term, compare_versions, calculate) as they are the
    actual evidence used by the LLM when composing the answer.

    Returns:
        (responses, contexts_per_question)
    """
    from ..agent.graph import build_agent

    graph, _ = build_agent()
    logger.info("Agent graph built.")

    responses: list[str] = []
    contexts_list: list[list[str]] = []

    for i, q in enumerate(questions, 1):
        logger.info("[agent %d/%d] %s", i, len(questions), q[:60])
        thread_id = f"ragas-eval-{i:03d}"
        config = {"configurable": {"thread_id": thread_id}}

        result = graph.invoke(
            {"messages": [HumanMessage(content=q)]},
            config=config,
        )

        msgs = result["messages"]
        # Final answer is the last AIMessage
        response = msgs[-1].content

        # Collect all ToolMessage outputs as retrieved contexts.
        # Including calculate / explain_term outputs ensures RAGAS Faithfulness
        # can verify arithmetic answers and terminology definitions too.
        tool_contexts = [
            str(msg.content)
            for msg in msgs
            if isinstance(msg, ToolMessage) and str(msg.content).strip()
        ]

        responses.append(response)
        contexts_list.append(tool_contexts if tool_contexts else [""])

    return responses, contexts_list


# ---------------------------------------------------------------------------
# RAGAS evaluation wrapper
# ---------------------------------------------------------------------------

def ragas_evaluate(
    dataset: EvaluationDataset,
    embedder: BGEEmbedder,
    run_config: RunConfig | None = None,
) -> "EvaluationResult":
    """Run RAGAS evaluation on a pipeline's EvaluationDataset.

    Uses DeepSeek as the judge LLM (via _LangchainLLMWrapper, compatible with
    ragas.metrics.*) and BGEEmbedder wrapped as a LangChain Embeddings adapter.

    ragas.metrics.* (faithfulness, answer_relevancy, context_precision, context_recall)
    are the correct choice here — they are instances of ragas.metrics.base.Metric
    and are the only type accepted by ragas.evaluate().

    Args:
        dataset:    EvaluationDataset assembled by dataset.to_ragas_dataset().
        embedder:   BGEEmbedder instance (already loaded; avoids double model load).
        run_config: Optional RAGAS RunConfig.  Defaults to max_workers=2, max_retries=10.

    Returns:
        RAGAS EvaluationResult (pandas DataFrame accessible via .to_pandas()).
    """
    from dotenv import load_dotenv
    from langchain_openai import ChatOpenAI

    load_dotenv()

    llm = ChatOpenAI(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        temperature=0,
    )
    judge_llm = _LangchainLLMWrapper(llm)
    judge_embeddings = _LangchainEmbeddingsWrapper(_BGEEmbeddingsAdapter(embedder))

    if run_config is None:
        run_config = RunConfig(max_workers=2, max_retries=10, timeout=180)

    # Assign judge to each metric instance (ragas.metrics are module-level singletons)
    faithfulness.llm = judge_llm
    answer_relevancy.llm = judge_llm
    answer_relevancy.embeddings = judge_embeddings
    answer_relevancy.strictness = 1  # DeepSeek only supports n=1 in chat completions
    context_precision.llm = judge_llm
    context_recall.llm = judge_llm

    metrics = [faithfulness, answer_relevancy, context_precision, context_recall]

    logger.info("Running RAGAS evaluate() on %d samples…", len(dataset.samples))
    result = evaluate(
        dataset=dataset,
        metrics=metrics,
        run_config=run_config,
        raise_exceptions=False,
    )
    return result
