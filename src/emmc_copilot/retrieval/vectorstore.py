"""ChromaDB client wrapper for the eMMC knowledge base.

Two persistent collections:
  emmc_docs     — all searchable chunks (TEXT, TABLE row-groups, FIGURE,
                  DEFINITION, REGISTER)
  emmc_glossary — DEFINITION chunks only (for fast term lookup)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Collection names
DOCS_COLLECTION = "emmc_docs"
GLOSSARY_COLLECTION = "emmc_glossary"

# Maximum items per ChromaDB upsert call
_UPSERT_BATCH = 500


class EMMCVectorStore:
    """Manages the two Chroma collections for eMMC specification chunks.

    Usage::

        store = EMMCVectorStore("data/vectorstore/chroma")
        store.upsert(chunks, embeddings)
        results = store.query(query_vec, n_results=5)
    """

    def __init__(self, persist_dir: str | Path = "data/vectorstore/chroma") -> None:
        import chromadb

        self._path = Path(persist_dir)
        self._path.mkdir(parents=True, exist_ok=True)

        self._client = chromadb.PersistentClient(path=str(self._path))

        # cosine distance is standard for normalised dense embeddings
        _meta = {"hnsw:space": "cosine"}
        self._docs = self._client.get_or_create_collection(
            name=DOCS_COLLECTION, metadata=_meta
        )
        self._glossary = self._client.get_or_create_collection(
            name=GLOSSARY_COLLECTION, metadata=_meta
        )
        logger.info(
            "VectorStore ready at %s  (docs=%d  glossary=%d)",
            self._path,
            self._docs.count(),
            self._glossary.count(),
        )

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def upsert(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict[str, Any]],
        is_definition: list[bool],
    ) -> None:
        """Upsert a batch of chunks into the appropriate collections.

        *is_definition[i]* controls whether item *i* also goes into the
        glossary collection in addition to docs.
        """
        # --- docs collection (all items) ---
        self._upsert_collection(self._docs, ids, embeddings, documents, metadatas)

        # --- glossary collection (DEFINITION only) ---
        gloss_idx = [i for i, flag in enumerate(is_definition) if flag]
        if gloss_idx:
            self._upsert_collection(
                self._glossary,
                [ids[i] for i in gloss_idx],
                [embeddings[i] for i in gloss_idx],
                [documents[i] for i in gloss_idx],
                [metadatas[i] for i in gloss_idx],
            )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def query(
        self,
        query_embedding: list[float],
        n_results: int = 5,
        where: dict[str, Any] | None = None,
        collection: str = "docs",
    ) -> list[dict[str, Any]]:
        """Return the top-*n_results* chunks closest to *query_embedding*.

        Args:
            query_embedding: Dense vector from BGEEmbedder.embed_query().
            n_results:       Number of results to return.
            where:           Optional ChromaDB metadata filter dict.
            collection:      "docs" or "glossary".

        Returns:
            List of dicts with keys: id, document, metadata, distance.
        """
        coll = self._glossary if collection == "glossary" else self._docs
        kwargs: dict[str, Any] = {
            "query_embeddings": [query_embedding],
            "n_results": min(n_results, coll.count() or 1),
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where

        raw = coll.query(**kwargs)
        results = []
        for i, doc_id in enumerate(raw["ids"][0]):
            results.append(
                {
                    "id": doc_id,
                    "document": raw["documents"][0][i],
                    "metadata": raw["metadatas"][0][i],
                    "distance": raw["distances"][0][i],
                }
            )
        return results

    def get_by_ids(
        self, ids: list[str], collection: str = "docs"
    ) -> list[dict[str, Any]]:
        """Fetch chunks by ID list (no embedding required).

        Returns:
            List of dicts with keys: id, document, metadata.
            Missing IDs are silently omitted.
        """
        if not ids:
            return []
        coll = self._glossary if collection == "glossary" else self._docs
        raw = coll.get(ids=ids, include=["documents", "metadatas"])
        return [
            {"id": rid, "document": doc, "metadata": meta}
            for rid, doc, meta in zip(raw["ids"], raw["documents"], raw["metadatas"])
        ]

    def existing_ids(self, ids: list[str], collection: str = "docs") -> set[str]:
        """Return the subset of *ids* already present in *collection*."""
        if not ids:
            return set()
        coll = self._glossary if collection == "glossary" else self._docs
        result = coll.get(ids=ids, include=[])
        return set(result["ids"])

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, int]:
        return {
            "docs": self._docs.count(),
            "glossary": self._glossary.count(),
        }

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    @staticmethod
    def _upsert_collection(coll, ids, embeddings, documents, metadatas) -> None:
        """Upsert in safe-sized batches."""
        for start in range(0, len(ids), _UPSERT_BATCH):
            sl = slice(start, start + _UPSERT_BATCH)
            coll.upsert(
                ids=ids[sl],
                embeddings=embeddings[sl],
                documents=documents[sl],
                metadatas=metadatas[sl],
            )
