"""EMMCRetriever: wraps BGEEmbedder + EMMCVectorStore as a LangChain BaseRetriever."""

from __future__ import annotations

from pydantic import ConfigDict

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from ..retrieval.embedder import BGEEmbedder
from ..retrieval.vectorstore import EMMCVectorStore


class EMMCRetriever(BaseRetriever):
    """LangChain-compatible retriever backed by BGE-M3 embeddings and ChromaDB.

    Usage::

        retriever = EMMCRetriever(embedder=BGEEmbedder(), store=EMMCVectorStore())
        docs = retriever.invoke("eMMC boot partition size")
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)  # BGEEmbedder is not a Pydantic model

    embedder: BGEEmbedder
    store: EMMCVectorStore
    n_results: int = 15
    collection: str = "docs"
    score_threshold: float = 0.85  # cosine distance < 0.85 → keep (lower = more similar)

    def _get_relevant_documents(self, query: str, *, run_manager) -> list[Document]:
        vec = self.embedder.embed_query(query)
        hits = self.store.query(vec, n_results=self.n_results, collection=self.collection)
        return [
            Document(
                page_content=h["document"],
                metadata={**h["metadata"], "_id": h["id"], "_distance": h["distance"]},
            )
            for h in hits
            if h["distance"] < self.score_threshold
        ]
