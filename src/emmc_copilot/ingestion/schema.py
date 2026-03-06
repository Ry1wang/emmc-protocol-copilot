"""Unified metadata schema for all eMMC document chunks."""

from __future__ import annotations

import hashlib
import uuid
from enum import Enum

from pydantic import BaseModel, Field, model_validator

# Fixed namespace for deterministic chunk IDs (UUID v5).
# Changing this value would invalidate all existing stored IDs — do not modify.
_CHUNK_ID_NAMESPACE = uuid.UUID("c7a3f2e1-84b0-5d9e-a012-3456789abcde")


def _make_chunk_id(
    source: str,
    version: str,
    content_type: str,
    page_start: int,
    section_path: list[str],
    chunk_index: int,
    raw_text: str,
) -> str:
    """Return a stable UUID v5 derived from the chunk's identity fields.

    raw_text is included (as a short SHA-256 prefix) to disambiguate chunks
    that share the same position fields — e.g. multiple figures in the same
    section on the same page, which all get chunk_index=0.

    The same logical chunk will always produce the same ID regardless of when
    or how many times the ingestion pipeline is run, enabling idempotent indexing.
    """
    text_hash = hashlib.sha256(raw_text.encode()).hexdigest()[:16]
    key = "|".join([source, version, str(content_type), str(page_start), "/".join(section_path), str(chunk_index), text_hash])
    return str(uuid.uuid5(_CHUNK_ID_NAMESPACE, key))


class ContentType(str, Enum):
    TEXT = "text"
    TABLE = "table"
    FIGURE = "figure"        # vector drawing
    BITMAP = "bitmap"        # raster image
    DEFINITION = "definition"  # term/abbreviation definition
    REGISTER = "register"    # register bit-field definition


class EMMCChunk(BaseModel):
    """A single chunk extracted from an eMMC specification PDF."""

    chunk_id: str = ""  # Set deterministically by _assign_chunk_id validator below
    source: str                       # e.g. "JESD84-B51.pdf"
    version: str                      # e.g. "5.1", "5.0", "4.51"
    page_start: int                   # 1-indexed physical PDF page
    page_end: int                     # same as page_start for single-page chunks

    # Section hierarchy from TOC
    section_path: list[str] = Field(default_factory=list)   # ["6", "6.10", "6.10.4"]
    section_title: str = ""           # "Detailed command description"
    heading_level: int = 0            # 1–5, matching TOC depth; 0 = front matter

    content_type: ContentType
    is_front_matter: bool = False     # True → excluded from vector search

    chunk_index: int = 0              # ordinal within its section

    # Text fields
    text: str                         # final text written to vectorstore (with context prefix)
    raw_text: str = ""                # original extracted text without prefix

    # Type-specific fields (None when not applicable)
    table_markdown: str | None = None   # TABLE only
    figure_caption: str | None = None   # FIGURE / BITMAP only
    term: str | None = None             # DEFINITION only

    # Two-level table indexing: row-group chunks reference their parent table chunk.
    # parent_chunk_id is set only on row-group chunks (is_row_chunk=True).
    # Full table chunks leave both fields at their defaults.
    parent_chunk_id: str | None = None  # non-None → this is a row-group sub-chunk
    is_row_chunk: bool = False          # True for row-group retrieval chunks

    model_config = {"use_enum_values": True}

    @model_validator(mode="after")
    def _assign_chunk_id(self) -> "EMMCChunk":
        """Assign a deterministic chunk_id if one was not loaded from storage."""
        if not self.chunk_id:
            self.chunk_id = _make_chunk_id(
                self.source,
                self.version,
                self.content_type,
                self.page_start,
                self.section_path,
                self.chunk_index,
                self.raw_text,
            )
        return self

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def section_label(self) -> str:
        """Human-readable section label, e.g. '6.10.4 Detailed command description'."""
        prefix = self.section_path[-1] if self.section_path else ""
        if prefix and self.section_title:
            return f"{prefix} {self.section_title}"
        return self.section_title or prefix or "(front matter)"

    def to_chroma_document(self) -> dict:
        """Convert to a dict suitable for ChromaDB `add()`.

        Returns a dict with keys: id, document, metadata.
        """
        metadata = {
            "source": self.source,
            "version": self.version,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "section_path": "/".join(self.section_path),
            "section_title": self.section_title,
            "heading_level": self.heading_level,
            "content_type": self.content_type,
            "is_front_matter": self.is_front_matter,
            "chunk_index": self.chunk_index,
        }
        # Add optional fields only when present to keep metadata lean
        if self.table_markdown is not None:
            metadata["table_markdown"] = self.table_markdown
        if self.figure_caption is not None:
            metadata["figure_caption"] = self.figure_caption
        if self.term is not None:
            metadata["term"] = self.term
        if self.parent_chunk_id is not None:
            metadata["parent_chunk_id"] = self.parent_chunk_id
        if self.is_row_chunk:
            metadata["is_row_chunk"] = True

        return {
            "id": self.chunk_id,
            "document": self.text,
            "metadata": metadata,
        }
