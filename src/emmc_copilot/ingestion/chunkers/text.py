"""TextChunker: section-aware recursive character splitting with context prefix."""

from __future__ import annotations

from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..schema import ContentType, EMMCChunk
from ..structure import SectionNode


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Approximate token count for BGE-M3 optimal embedding range.
# We use characters as proxy: ~4 chars/token for English technical text.
_CHUNK_CHARS = 2800      # ~700 tokens
_CHUNK_OVERLAP = 400     # ~100 tokens

# Splitter delimiters ordered from coarsest to finest
_SEPARATORS = ["\n\n", "\n", ". ", " ", ""]


def _make_context_prefix(version: str, section: SectionNode | None, page: int) -> str:
    label = section.label if section else "(front matter)"
    return f"[eMMC {version} | {label} | Page {page}]\n"


class TextChunker:
    """Chunk plain text and register-description blocks.

    Each output EMMCChunk:
    - Respects section boundaries (no cross-section splits)
    - Carries a context prefix for retrieval quality
    - Uses RecursiveCharacterTextSplitter for sub-section splitting
    """

    def __init__(
        self,
        chunk_chars: int = _CHUNK_CHARS,
        chunk_overlap: int = _CHUNK_OVERLAP,
    ) -> None:
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_chars,
            chunk_overlap=chunk_overlap,
            separators=_SEPARATORS,
            length_function=len,
        )

    def chunk_section(
        self,
        raw_text: str,
        source: str,
        version: str,
        section: SectionNode | None,
        page_start: int,
        page_end: int,
        content_type: ContentType = ContentType.TEXT,
    ) -> list[EMMCChunk]:
        """Split *raw_text* into one or more EMMCChunks.

        For REGISTER content_type the text is treated as an atomic unit and
        only split if it exceeds 1.5× the normal chunk size.
        """
        if not raw_text.strip():
            return []

        is_front_matter = section.is_front_matter if section else True
        section_path = section.path if section else []
        section_title = section.title if section else ""
        heading_level = section.level if section else 0

        prefix = _make_context_prefix(version, section, page_start)

        # Register definitions: keep as atomic unit unless extremely large
        if content_type == ContentType.REGISTER:
            max_atomic = int(_CHUNK_CHARS * 1.5)
            if len(raw_text) <= max_atomic:
                return [
                    EMMCChunk(
                        source=source,
                        version=version,
                        page_start=page_start,
                        page_end=page_end,
                        section_path=section_path,
                        section_title=section_title,
                        heading_level=heading_level,
                        content_type=content_type,
                        is_front_matter=is_front_matter,
                        chunk_index=0,
                        text=prefix + raw_text,
                        raw_text=raw_text,
                    )
                ]

        # Normal recursive split
        sub_texts = self._splitter.split_text(raw_text)
        chunks: list[EMMCChunk] = []
        for idx, sub in enumerate(sub_texts):
            sub = sub.strip()
            if not sub:
                continue
            chunks.append(
                EMMCChunk(
                    source=source,
                    version=version,
                    page_start=page_start,
                    page_end=page_end,
                    section_path=section_path,
                    section_title=section_title,
                    heading_level=heading_level,
                    content_type=content_type,
                    is_front_matter=is_front_matter,
                    chunk_index=idx,
                    text=prefix + sub,
                    raw_text=sub,
                )
            )
        return chunks
