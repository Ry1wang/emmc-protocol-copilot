"""Document structure extraction: TOC parsing, section mapping, front matter detection."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SectionNode:
    """Represents a single TOC entry mapped to a page range."""
    level: int               # 1–5
    title: str               # e.g. "Detailed command description"
    page_start: int          # 1-indexed first page of this section
    page_end: int            # 1-indexed last page (exclusive upper bound of next sibling)
    number: str              # numeric prefix extracted from title, e.g. "6.10.4"
    path: list[str]          # ["6", "6.10", "6.10.4"]
    is_front_matter: bool = False

    @property
    def label(self) -> str:
        # self.path = ["6", "6.3", "6.3.4"]; use the last element as the prefix
        number = self.path[-1] if self.path else ""
        if number and self.title:
            return f"{number} {self.title}"
        return self.title


@dataclass
class DocumentStructure:
    """Full structure of a parsed PDF."""
    source: str
    version: str
    total_pages: int
    body_start_page: int           # first page that is NOT front matter
    sections: list[SectionNode] = field(default_factory=list)
    # page_num (1-indexed) → deepest SectionNode that covers it
    page_to_section: dict[int, SectionNode] = field(default_factory=dict)
    # Normalized full label (e.g. "6.6.1 manual mode") -> SectionNode
    label_to_section: dict[str, SectionNode] = field(default_factory=dict)
    # figure_map[page_1idx] = list of "Figure N — caption" strings from TOC figures list
    figure_map: dict[int, list[str]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Headings that are part of JEDEC front matter even if listed in TOC
_FRONT_MATTER_KEYWORDS = {
    "cover", "contents", "figures", "tables", "foreword",
    "introduction", "scope", "normative references", "terms",
    "definitions", "symbols", "abbreviations", "bibliography",
}

_SECTION_NUMBER_RE = re.compile(r"^(\d+(?:\.\d+)*)\s*(.*)")


def _parse_section_number(title: str) -> tuple[str, str]:
    """Split 'X.Y.Z Title text' into (number_string, bare_title).

    Returns ("", title) if no leading number is found.
    """
    m = _SECTION_NUMBER_RE.match(title.strip())
    if m:
        return m.group(1), m.group(2).strip()
    return "", title.strip()


def _build_path(number: str) -> list[str]:
    """Turn '6.10.4' into ['6', '6.10', '6.10.4']."""
    if not number:
        return []
    parts = number.split(".")
    return [".".join(parts[: i + 1]) for i in range(len(parts))]


def _is_front_matter_title(title: str) -> bool:
    return title.strip().lower() in _FRONT_MATTER_KEYWORDS


def _normalize_label(text: str) -> str:
    """Normalize a heading label for lookup (lowercase, single spaces, eMMC unified).

    The eMMC bullet character (U+2022 •) appears in TOC bookmarks extracted by
    fitz, while the same character is rendered as an ASCII asterisk ' *' in page
    body text extracted by PyMuPDF.  Both variants must map to the same key so
    that label_to_section lookups work regardless of the extraction source.
    """
    text = text.strip().lower()
    # Unify eMMC variant spellings before whitespace collapse:
    #   TOC:  "e•mmc"  (U+2022 bullet, possibly with surrounding spaces)
    #   body: "e *mmc" (ASCII asterisk, space before)
    #   other variants: "e∙mmc", "e.mmc", "e-mmc"
    text = re.sub(r"e[\s]*[•∙*.‐\-]+[\s]*mmc", "emmc", text)
    text = re.sub(r"\s+", " ", text)
    # Remove trailing/leading punctuation
    text = text.strip(". ")
    return text


# ---------------------------------------------------------------------------
# StructureExtractor
# ---------------------------------------------------------------------------

class StructureExtractor:
    """Extract section hierarchy and page metadata from a PDF's TOC.

    Usage::

        parser = PDFParser("JESD84-B51.pdf")
        extractor = StructureExtractor(parser.toc, parser.source, parser.version, parser.page_count)
        structure = extractor.extract()
    """

    def __init__(
        self,
        toc: list[tuple[int, str, int]],   # (level, title, page_1indexed)
        source: str,
        version: str,
        total_pages: int,
    ) -> None:
        self._toc = toc
        self.source = source
        self.version = version
        self.total_pages = total_pages

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def extract(self) -> DocumentStructure:
        sections = self._build_sections()
        body_start = self._find_body_start(sections)
        self._mark_front_matter(sections, body_start)
        page_to_section = self._build_page_map(sections)

        # First-seen wins: if two sections share the same normalised label
        # (e.g. multiple "General" sub-sections), keep the first occurrence so
        # that sub-page detection in the pipeline always hits a deterministic
        # section rather than silently jumping to the last duplicate.
        label_map: dict[str, SectionNode] = {}
        for s in sections:
            key = _normalize_label(s.label)
            if key not in label_map:
                label_map[key] = s

        return DocumentStructure(
            source=self.source,
            version=self.version,
            total_pages=self.total_pages,
            body_start_page=body_start,
            sections=sections,
            page_to_section=page_to_section,
            label_to_section=label_map,
        )

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _build_sections(self) -> list[SectionNode]:
        """Convert raw TOC entries into SectionNode objects with page ranges."""
        nodes: list[SectionNode] = []

        for level, title, page_start in self._toc:
            number, bare_title = _parse_section_number(title)
            path = _build_path(number)

            nodes.append(
                SectionNode(
                    level=level,
                    title=bare_title or title,
                    page_start=page_start,
                    page_end=self.total_pages,  # will be fixed below
                    number=number,
                    path=path,
                )
            )

        # Fix page_end: each section ends where the next sibling/parent starts.
        # Ensure page_end >= page_start (multiple entries can share the same page).
        for i, node in enumerate(nodes):
            for j in range(i + 1, len(nodes)):
                candidate = nodes[j]
                if candidate.level <= node.level:
                    node.page_end = max(node.page_start, candidate.page_start - 1)
                    break

        return nodes

    def _find_body_start(self, sections: list[SectionNode]) -> int:
        """Return the page number where body content begins.

        Strategy: find the first Level-1 section whose title is NOT a
        known front-matter keyword. This is typically 'Scope' or the
        first numbered section.
        """
        # First pass: numbered sections (most reliable)
        for node in sections:
            if node.level == 1 and node.number:
                return node.page_start

        # Second pass: first non-front-matter level-1 heading
        for node in sections:
            if node.level == 1 and not _is_front_matter_title(node.title):
                return node.page_start

        # Fallback: use page 1
        return 1

    def _mark_front_matter(
        self, sections: list[SectionNode], body_start: int
    ) -> None:
        # A section is front matter only if it starts before the body.
        # Numbered sections (e.g. "1 Scope") that happen to have front-matter-like
        # titles are still body content once they are at or after body_start_page.
        for node in sections:
            if node.page_start < body_start:
                node.is_front_matter = True

    def _build_page_map(
        self, sections: list[SectionNode]
    ) -> dict[int, SectionNode]:
        """Map each physical page number to the deepest covering SectionNode.

        Tie-breaking rule (same level):
          Use >= so that when multiple sections of the same level all start on
          the same page (e.g. "1 Scope", "2 Normative reference", "3 Terms and
          definitions" all at page_start=22), the LAST one in TOC order wins.
          This reflects the "most recently active" section at that page boundary,
          which is the correct section for content that continues on the next page.
        """
        page_to_section: dict[int, SectionNode] = {}

        for page_num in range(1, self.total_pages + 1):
            best: SectionNode | None = None
            for node in sections:
                if node.page_start <= page_num <= node.page_end:
                    if best is None:
                        best = node
                    elif node.level > best.level:
                        # Deeper (more specific) section always wins
                        best = node
                    elif node.level == best.level:
                        # Same level: prefer the section that starts LATER.
                        # When multiple siblings share the same page (e.g. "1 Scope",
                        # "2 Normative reference", "3 Terms and definitions" all at
                        # page_start=22), the last-starting one is the "most recently
                        # active" section for content that continues on subsequent pages.
                        # A section with a much earlier page_start (e.g. a document-wide
                        # catch-all entry) correctly loses to a later-starting sibling.
                        if node.page_start >= best.page_start:
                            best = node
            if best is not None:
                page_to_section[page_num] = best

        return page_to_section
