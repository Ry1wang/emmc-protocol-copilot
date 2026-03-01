"""BM25Corpus: keyword-based retrieval index over eMMC chunk JSONL files.

Tokenizer: re.findall(r'[a-z0-9_]+', text.lower())
  - Preserves underscores so EXT_CSD -> ext_csd, BOOT_SIZE_MULT -> boot_size_mult
  - EXT_CSD[33] -> ["ext_csd", "33"], CMD6 -> ["cmd6"], 52MHz -> ["52mhz"]

Index text per chunk: f"{section_title} {raw_text}"
  (raw_text avoids context-prefix noise from the text field)

Front-matter chunks (is_front_matter=True) are skipped, matching ChromaDB behavior.
"""

from __future__ import annotations

import json
import logging
import pickle
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


class BM25Corpus:
    """BM25 index over eMMC chunk JSONL files.

    Usage::

        corpus = BM25Corpus.build_from_jsonl([Path("data/processed/JESD84-B51_chunks.jsonl")])
        hits = corpus.search("EXT_CSD register index 33", n_results=20)
        corpus.save(Path("data/vectorstore/bm25/corpus.pkl"))

        # Later:
        corpus = BM25Corpus.load(Path("data/vectorstore/bm25/corpus.pkl"))
    """

    def __init__(self) -> None:
        self._bm25: Any = None          # BM25Okapi instance
        self._ids: list[str] = []
        self._documents: list[str] = [] # text field (with context prefix, for LangChain)
        self._metadatas: list[dict] = []
        self._id_to_pos: dict[str, int] = {}  # chunk_id → position in _ids list

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    @classmethod
    def build_from_jsonl(cls, jsonl_paths: list[Path]) -> "BM25Corpus":
        """Build a BM25 index from one or more JSONL chunk files.

        Args:
            jsonl_paths: List of paths to *_chunks.jsonl files.

        Returns:
            A ready-to-use BM25Corpus instance.
        """
        from rank_bm25 import BM25Okapi

        corpus = cls()
        tokenized_corpus: list[list[str]] = []
        indexed = skipped = 0

        for path in jsonl_paths:
            logger.info("BM25: loading %s …", path.name)
            with path.open(encoding="utf-8") as f:
                for lineno, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError as exc:
                        logger.warning("Skipping malformed line %d in %s: %s", lineno, path.name, exc)
                        continue

                    # Skip front matter (mirrors EMMCIndexer._is_searchable)
                    if data.get("is_front_matter", False):
                        skipped += 1
                        continue

                    chunk_id = data.get("chunk_id", "")
                    section_title = data.get("section_title", "")
                    raw_text = data.get("raw_text", "")
                    text = data.get("text", raw_text)  # fallback to raw_text if text absent

                    # BM25 index text: title + raw content (no context prefix noise)
                    index_text = f"{section_title} {raw_text}"
                    tokens = _tokenize(index_text)

                    corpus._id_to_pos[chunk_id] = len(corpus._ids)
                    tokenized_corpus.append(tokens)
                    corpus._ids.append(chunk_id)
                    corpus._documents.append(text)

                    # Build metadata dict from JSONL fields
                    metadata: dict[str, Any] = {
                        "source": data.get("source", ""),
                        "version": data.get("version", ""),
                        "page_start": data.get("page_start", 0),
                        "page_end": data.get("page_end", 0),
                        "section_path": "/".join(data.get("section_path", [])),
                        "section_title": section_title,
                        "heading_level": data.get("heading_level", 0),
                        "content_type": data.get("content_type", ""),
                        "is_front_matter": False,
                        "chunk_index": data.get("chunk_index", 0),
                    }
                    # Optional fields
                    for opt in ("table_markdown", "figure_caption", "term",
                                "parent_chunk_id", "is_row_chunk"):
                        val = data.get(opt)
                        if val is not None:
                            metadata[opt] = val

                    corpus._metadatas.append(metadata)
                    indexed += 1

        logger.info("BM25: indexed %d chunks, skipped %d front-matter", indexed, skipped)

        if not tokenized_corpus:
            raise ValueError("No searchable chunks found in the provided JSONL files.")

        corpus._bm25 = BM25Okapi(tokenized_corpus)
        return corpus

    # ------------------------------------------------------------------
    # Neighbor lookup
    # ------------------------------------------------------------------

    def get_neighbor_ids(self, chunk_id: str, n: int = 1) -> list[str]:
        """Return up to *n* document-order neighbor IDs on each side of *chunk_id*.

        Neighbors are determined by their position in the JSONL loading order,
        which reflects physical document order (page / section sequence).
        The caller is responsible for filtering by section if cross-section
        bleed is undesirable.

        Args:
            chunk_id: Target chunk ID.
            n:        Number of neighbors to return on each side (default 1).

        Returns:
            List of neighbor chunk IDs (excludes chunk_id itself).
            Empty list if chunk_id is not in the index.
        """
        pos = self._id_to_pos.get(chunk_id)
        if pos is None:
            return []
        lo = max(0, pos - n)
        hi = min(len(self._ids), pos + n + 1)
        return [self._ids[i] for i in range(lo, hi) if i != pos]

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query: str, n_results: int = 20) -> list[dict[str, Any]]:
        """Return top-n BM25 hits for *query*.

        Args:
            query:     Natural-language or technical query string.
            n_results: Maximum number of results to return.

        Returns:
            List of dicts with keys: id, document, metadata, score.
            Sorted by score descending (highest = most relevant).
        """
        if self._bm25 is None:
            raise RuntimeError("BM25Corpus is not built yet. Call build_from_jsonl() first.")

        tokens = _tokenize(query)
        scores = self._bm25.get_scores(tokens)

        # Pair scores with indices and sort descending
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)

        results: list[dict[str, Any]] = []
        for idx, score in ranked[:n_results]:
            results.append(
                {
                    "id": self._ids[idx],
                    "document": self._documents[idx],
                    "metadata": self._metadatas[idx],
                    "score": float(score),
                }
            )
        return results

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: Path) -> None:
        """Pickle the corpus to *path*."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            pickle.dump(
                {
                    "bm25": self._bm25,
                    "ids": self._ids,
                    "documents": self._documents,
                    "metadatas": self._metadatas,
                    "id_to_pos": self._id_to_pos,
                },
                f,
                protocol=pickle.HIGHEST_PROTOCOL,
            )
        logger.info("BM25 corpus saved to %s (%d chunks)", path, len(self._ids))

    @classmethod
    def load(cls, path: Path) -> "BM25Corpus":
        """Load a pickled corpus from *path*."""
        with path.open("rb") as f:
            data = pickle.load(f)
        corpus = cls()
        corpus._bm25 = data["bm25"]
        corpus._ids = data["ids"]
        corpus._documents = data["documents"]
        corpus._metadatas = data["metadatas"]
        # Rebuild _id_to_pos if missing (backward compat with older pickle files)
        corpus._id_to_pos = data.get("id_to_pos") or {
            cid: i for i, cid in enumerate(corpus._ids)
        }
        logger.info("BM25 corpus loaded from %s (%d chunks)", path, len(corpus._ids))
        return corpus

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._ids)
