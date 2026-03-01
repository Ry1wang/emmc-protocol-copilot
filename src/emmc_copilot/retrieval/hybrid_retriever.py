"""HybridRetriever: Dense (BGE-M3 + ChromaDB) + BM25 with RRF fusion.

Architecture:
    Query
      ├─ BGE-M3 embed → ChromaDB.query(n_candidates)  → dense_hits
      └─ tokenize     → BM25Corpus.search(n_candidates) → bm25_hits
                               ↓
                      RRF merge (k=60)
                      score = Σ 1/(k+rank)
                               ↓
                      top-n_results Documents → LLM
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict

from .bm25_index import BM25Corpus
from .embedder import BGEEmbedder
from .vectorstore import EMMCVectorStore

logger = logging.getLogger(__name__)


def _rrf_merge(
    dense_hits: list[dict[str, Any]],
    bm25_hits: list[dict[str, Any]],
    k: int,
    n_results: int,
) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion of two ranked hit lists.

    Args:
        dense_hits: Hits from ChromaDB, ordered by ascending distance (best first).
        bm25_hits:  Hits from BM25Corpus, ordered by descending score (best first).
        k:          RRF constant (typically 60).
        n_results:  Number of top results to return.

    Returns:
        List of merged hit dicts, sorted by RRF score descending.
        Each dict retains the original hit fields plus "_rrf_score".
    """
    scores: dict[str, float] = {}
    data: dict[str, dict[str, Any]] = {}

    for rank, hit in enumerate(dense_hits, 1):
        cid = hit["id"]
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
        data[cid] = {**hit, "_rrf_score": scores[cid]}

    for rank, hit in enumerate(bm25_hits, 1):
        cid = hit["id"]
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
        if cid not in data:
            data[cid] = {**hit, "_bm25_score": hit.get("score")}
        # Update RRF score in data
        data[cid]["_rrf_score"] = scores[cid]

    sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)
    return [data[cid] for cid in sorted_ids[:n_results]]


class HybridRetriever(BaseRetriever):
    """LangChain-compatible hybrid retriever (Dense + BM25 + RRF).

    Usage::

        retriever = HybridRetriever(
            embedder=BGEEmbedder(),
            store=EMMCVectorStore(),
            bm25_corpus=BM25Corpus.load(Path("data/vectorstore/bm25/corpus.pkl")),
        )
        docs = retriever.invoke("EXT_CSD register index 33 CACHE_CTRL")
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    embedder: BGEEmbedder
    store: EMMCVectorStore
    bm25_corpus: BM25Corpus
    n_results: int = 5
    n_candidates: int = 20      # per-path candidate count before RRF
    score_threshold: float = 0.85   # Dense cosine distance filter (lower = more similar)
    rrf_k: int = 60
    collection: str = "docs"

    def _get_relevant_documents(self, query: str, *, run_manager) -> list[Document]:
        # --- Dense path ---
        vec = self.embedder.embed_query(query)
        raw_dense = self.store.query(
            vec,
            n_results=self.n_candidates,
            collection=self.collection,
        )
        # Filter by distance threshold
        dense_hits = [h for h in raw_dense if h["distance"] < self.score_threshold]

        # --- BM25 path ---
        bm25_hits = self.bm25_corpus.search(query, n_results=self.n_candidates)

        logger.debug(
            "HybridRetriever: %d dense hits (after threshold), %d bm25 hits",
            len(dense_hits),
            len(bm25_hits),
        )

        # --- RRF fusion ---
        merged = _rrf_merge(dense_hits, bm25_hits, k=self.rrf_k, n_results=self.n_results)

        return [
            Document(
                page_content=hit["document"],
                metadata={
                    **hit["metadata"],
                    "_distance": hit.get("distance"),
                    "_bm25_score": hit.get("_bm25_score"),
                    "_rrf_score": hit.get("_rrf_score"),
                },
            )
            for hit in merged
        ]
