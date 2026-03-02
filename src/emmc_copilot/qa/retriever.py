"""EMMCRetriever: wraps BGEEmbedder + EMMCVectorStore as a LangChain BaseRetriever."""

from __future__ import annotations

from pydantic import ConfigDict

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from ..retrieval.embedder import BGEEmbedder
from ..retrieval.vectorstore import EMMCVectorStore
from ..retrieval.version_filter import DEFAULT_VERSION, build_version_where, detect_versions


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
    default_version: str = DEFAULT_VERSION  # fallback when query has no version mention
                                            # set to "" to disable filtering (all versions)

    def _get_relevant_documents(self, query: str, *, run_manager) -> list[Document]:
        detected = detect_versions(query)
        target_versions = detected or ([self.default_version] if self.default_version else [])
        where = build_version_where(target_versions) if target_versions else None

        vec = self.embedder.embed_query(query)
        hits = self.store.query(vec, n_results=self.n_results, where=where, collection=self.collection)
        return [
            Document(
                page_content=h["document"],
                metadata={**h["metadata"], "_id": h["id"], "_distance": h["distance"]},
            )
            for h in hits
            if h["distance"] < self.score_threshold
        ]
