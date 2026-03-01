"""EMMCIndexer: load JSONL chunks → embed with BGE-M3 → upsert into ChromaDB."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..ingestion.schema import ContentType, EMMCChunk
from .embedder import BGEEmbedder
from .vectorstore import EMMCVectorStore

logger = logging.getLogger(__name__)

# Minimum raw content length per content type (mirrors pipeline._MIN_RAW_CHARS_BY_TYPE)
_MIN_RAW_CHARS: dict[str, int] = {
    ContentType.TEXT: 20,
    ContentType.TABLE: 25,   # row-group chunks are small by design
    ContentType.FIGURE: 30,
    ContentType.BITMAP: 30,
    ContentType.DEFINITION: 8,
    ContentType.REGISTER: 40,
}

# Embedding batch size (chunks per BGE-M3 inference call)
_EMBED_BATCH = 32


def _is_searchable(chunk: EMMCChunk) -> bool:
    """Replicate IngestionResult.searchable_chunks filtering for JSONL-loaded chunks."""
    # 1. Skip front matter
    if chunk.is_front_matter:
        return False

    # 2. Skip full-table chunks (non-row-group), except register map tables
    if chunk.content_type == ContentType.TABLE and not chunk.is_row_chunk:
        is_reg = any(
            kw in chunk.section_title.upper()
            for kw in ("CSD", "CID", "DSR", "OCR", "EXT_CSD")
        )
        if not is_reg:
            return False

    # 3. Skip chunks with insufficient content
    min_chars = _MIN_RAW_CHARS.get(chunk.content_type, 30)
    if len(chunk.raw_text.strip()) < min_chars:
        return False

    return True


def _load_chunks(jsonl_path: Path) -> list[EMMCChunk]:
    """Load and validate all EMMCChunk objects from a JSONL file."""
    chunks: list[EMMCChunk] = []
    with jsonl_path.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                chunks.append(EMMCChunk.model_validate(data))
            except Exception as exc:
                logger.warning("Skipping malformed line %d in %s: %s", lineno, jsonl_path.name, exc)
    return chunks


class EMMCIndexer:
    """Orchestrate the JSONL → embed → ChromaDB pipeline.

    Usage::

        embedder = BGEEmbedder()
        store    = EMMCVectorStore("data/vectorstore/chroma")
        indexer  = EMMCIndexer(embedder, store)

        # Index a single JSONL file
        indexer.index_file(Path("data/processed/JESD84-B51_chunks.jsonl"))

        # Or index all *_chunks.jsonl files in a directory
        indexer.index_directory(Path("data/processed/"))
    """

    def __init__(self, embedder: BGEEmbedder, store: EMMCVectorStore) -> None:
        self._embedder = embedder
        self._store = store

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def index_file(self, jsonl_path: Path) -> dict[str, int]:
        """Index one JSONL chunk file.

        Returns a stats dict: total / searchable / skipped_existing / indexed.
        """
        logger.info("Loading %s …", jsonl_path.name)
        all_chunks = _load_chunks(jsonl_path)
        searchable = [c for c in all_chunks if _is_searchable(c)]

        stats = {
            "total": len(all_chunks),
            "searchable": len(searchable),
            "skipped_existing": 0,
            "indexed": 0,
        }

        if not searchable:
            logger.info("No searchable chunks in %s", jsonl_path.name)
            return stats

        # Identify which IDs are already in the store (skip re-embedding)
        all_ids = [c.chunk_id for c in searchable]
        existing = self._store.existing_ids(all_ids)
        new_chunks = [c for c in searchable if c.chunk_id not in existing]
        stats["skipped_existing"] = len(existing)

        logger.info(
            "%s: %d total  %d searchable  %d already indexed  %d to embed",
            jsonl_path.name,
            stats["total"],
            stats["searchable"],
            stats["skipped_existing"],
            len(new_chunks),
        )

        if not new_chunks:
            return stats

        # Embed in batches and upsert
        self._embed_and_upsert(new_chunks)
        stats["indexed"] = len(new_chunks)
        return stats

    def index_directory(self, processed_dir: Path) -> None:
        """Index all *_chunks.jsonl files found in *processed_dir*."""
        jsonl_files = sorted(processed_dir.glob("*_chunks.jsonl"))
        if not jsonl_files:
            logger.warning("No *_chunks.jsonl files found in %s", processed_dir)
            return

        grand_total = grand_indexed = 0
        for path in jsonl_files:
            s = self.index_file(path)
            grand_total += s["total"]
            grand_indexed += s["indexed"]

        final = self._store.stats()
        logger.info(
            "Done. Processed %d chunks total, indexed %d new. "
            "Store: docs=%d  glossary=%d",
            grand_total,
            grand_indexed,
            final["docs"],
            final["glossary"],
        )

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _embed_and_upsert(self, chunks: list[EMMCChunk]) -> None:
        """Embed *chunks* in batches and upsert into ChromaDB."""
        total = len(chunks)
        for start in range(0, total, _EMBED_BATCH):
            batch = chunks[start : start + _EMBED_BATCH]
            texts = [c.text for c in batch]

            logger.debug("Embedding batch %d–%d / %d …", start + 1, start + len(batch), total)
            embeddings = self._embedder.embed(texts)

            # Prepare ChromaDB payload
            ids, docs, metas, is_def = [], [], [], []
            for chunk, vec in zip(batch, embeddings):
                chroma = chunk.to_chroma_document()
                ids.append(chroma["id"])
                docs.append(chroma["document"])
                metas.append(chroma["metadata"])
                is_def.append(chunk.content_type == ContentType.DEFINITION)

            self._store.upsert(
                ids=ids,
                embeddings=embeddings,
                documents=docs,
                metadatas=metas,
                is_definition=is_def,
            )
            logger.info("Upserted %d / %d chunks", min(start + _EMBED_BATCH, total), total)
