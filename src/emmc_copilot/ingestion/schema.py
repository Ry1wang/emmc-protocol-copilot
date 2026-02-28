"""Unified metadata schema for all eMMC document chunks."""

from __future__ import annotations

import uuid
from enum import Enum

from pydantic import BaseModel, Field


class ContentType(str, Enum):
    TEXT = "text"
    TABLE = "table"
    FIGURE = "figure"        # vector drawing
    BITMAP = "bitmap"        # raster image
    DEFINITION = "definition"  # term/abbreviation definition
    REGISTER = "register"    # register bit-field definition


class EMMCChunk(BaseModel):
    """A single chunk extracted from an eMMC specification PDF."""

    chunk_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
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

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def section_label(self) -> str:
        """Human-readable section label, e.g. '6.10.4 Detailed command description'."""
        prefix = ".".join(self.section_path) if self.section_path else ""
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
