"""DefinitionChunker: two-pass term/abbreviation extraction."""

from __future__ import annotations

import re

from ..schema import ContentType, EMMCChunk
from ..structure import DocumentStructure, SectionNode


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Abbreviation-style:  "ACMD  Application-specific Command"
# or                   "HS200: High Speed 200 MHz interface"
_ABBREV_RE = re.compile(
    r"^([A-Z][A-Z0-9_/\-]{1,20})\s*[:\-\u2013\u2014]\s*(.{10,200})$",
    re.MULTILINE,
)

# Numbered definition:  "3.1.1 eMMC\nAn embedded ..."
_NUMBERED_RE = re.compile(
    r"^\d+(?:\.\d+)+\s+([A-Za-z][^\n]{3,60})\n(.{20,500})",
    re.MULTILINE,
)

# Inline definition patterns
_INLINE_PATTERNS = [
    re.compile(r"([A-Z][A-Za-z0-9_\-\s]{2,40}?)\s+(?:means|is defined as|refers to)\s+(.{10,200})", re.IGNORECASE),
    re.compile(r"([A-Z][A-Za-z0-9_\-\s]{2,40}?)\s+\(abbreviated\s+as\s+([A-Z][A-Z0-9_\-]{1,15})\)", re.IGNORECASE),
]

# Section titles that are dedicated definition sections
_DEFINITION_SECTION_TITLES = frozenset({
    "definition", "abbreviation", "glossary", "terms", "terms and definitions",
    "symbols and abbreviations", "acronyms",
})


def _is_definition_section(title: str) -> bool:
    return title.strip().lower() in _DEFINITION_SECTION_TITLES


# ---------------------------------------------------------------------------
# DefinitionChunker
# ---------------------------------------------------------------------------

class DefinitionChunker:
    """Extract term/abbreviation definitions from eMMC documents.

    Two extraction passes:
      Round 1 — dedicated definition sections (high precision)
      Round 2 — inline definition patterns across the whole document
    """

    def extract_from_section(
        self,
        section_text: str,
        section: SectionNode,
        source: str,
        version: str,
        page_start: int,
        page_end: int,
    ) -> list[EMMCChunk]:
        """Round 1: parse a dedicated definition section."""
        if not _is_definition_section(section.title):
            return []

        chunks: list[EMMCChunk] = []

        # Try abbreviation pattern first
        for m in _ABBREV_RE.finditer(section_text):
            term = m.group(1).strip()
            definition = m.group(2).strip()
            chunks.append(
                self._make_chunk(
                    term=term,
                    definition=definition,
                    source=source,
                    version=version,
                    section=section,
                    page_start=page_start,
                    page_end=page_end,
                    chunk_index=len(chunks),
                )
            )

        # Try numbered definition if no abbreviations found
        if not chunks:
            for m in _NUMBERED_RE.finditer(section_text):
                term = m.group(1).strip()
                definition = m.group(2).strip()
                chunks.append(
                    self._make_chunk(
                        term=term,
                        definition=definition,
                        source=source,
                        version=version,
                        section=section,
                        page_start=page_start,
                        page_end=page_end,
                        chunk_index=len(chunks),
                    )
                )

        return chunks

    def extract_inline(
        self,
        full_text: str,
        source: str,
        version: str,
        structure: DocumentStructure,
        page_start: int = 1,
    ) -> list[EMMCChunk]:
        """Round 2: scan full text for inline definitions.

        *page_start* is used for all inline chunks as a best-effort page ref.
        """
        chunks: list[EMMCChunk] = []
        seen_terms: set[str] = set()

        for pattern in _INLINE_PATTERNS:
            for m in pattern.finditer(full_text):
                term = m.group(1).strip()
                if term.lower() in seen_terms:
                    continue
                seen_terms.add(term.lower())

                definition = m.group(2).strip() if m.lastindex and m.lastindex >= 2 else ""
                section = structure.page_to_section.get(page_start)

                chunks.append(
                    self._make_chunk(
                        term=term,
                        definition=definition,
                        source=source,
                        version=version,
                        section=section,
                        page_start=page_start,
                        page_end=page_start,
                        chunk_index=len(chunks),
                    )
                )

        return chunks

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    @staticmethod
    def _make_chunk(
        term: str,
        definition: str,
        source: str,
        version: str,
        section: SectionNode | None,
        page_start: int,
        page_end: int,
        chunk_index: int,
    ) -> EMMCChunk:
        label = section.label if section else "(front matter)"
        raw = f"{term}: {definition}"
        text = f"[eMMC {version} | {label} | Page {page_start}]\n{raw}"
        return EMMCChunk(
            source=source,
            version=version,
            page_start=page_start,
            page_end=page_end,
            section_path=section.path if section else [],
            section_title=section.title if section else "",
            heading_level=section.level if section else 0,
            content_type=ContentType.DEFINITION,
            is_front_matter=False,   # definitions are always searchable
            chunk_index=chunk_index,
            text=text,
            raw_text=raw,
            term=term,
        )
