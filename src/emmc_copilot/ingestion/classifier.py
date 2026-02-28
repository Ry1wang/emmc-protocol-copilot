"""Block-level content type classifier for eMMC PDF pages."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .parser import DrawingCluster, ImageBlock, PageModel, TableBlock, TextBlock
from .schema import ContentType
from .structure import SectionNode


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ClassifiedBlock:
    """A content block with its assigned ContentType."""
    content_type: ContentType
    # Only one of the following is set depending on content_type
    text_block: TextBlock | None = None
    table_block: TableBlock | None = None
    drawing_cluster: DrawingCluster | None = None
    image_block: ImageBlock | None = None


# ---------------------------------------------------------------------------
# Patterns for REGISTER detection
# ---------------------------------------------------------------------------

# Matches bit-range references like [13], [9:8], [7:4], [0]
_BIT_RANGE_RE = re.compile(r"\[\d+(?::\d+)?\]")

# Register-field value keywords common in eMMC specs
_REGISTER_KEYWORDS = frozenset({
    "r/w", "r/w/e_p", "r/w/c_p", "r/wp", "otp", "reserved",
    "read/write", "read only", "write once",
})

# Section title fragments that indicate a definition section
_DEFINITION_SECTION_KEYWORDS = frozenset({
    "definition", "abbreviation", "glossary", "terms", "acronym",
})


# ---------------------------------------------------------------------------
# BlockClassifier
# ---------------------------------------------------------------------------

class BlockClassifier:
    """Classify every block on a page into a ContentType.

    Priority order (highest first):
      TABLE  → pdfplumber table present and bbox overlaps the text block
      FIGURE → vector drawing cluster with area > threshold
      BITMAP → raster image block
      DEFINITION → section heading signals a definition section
      REGISTER → text matches register bit-field patterns
      TEXT   → everything else
    """

    def classify_page(
        self,
        page: PageModel,
        section: SectionNode | None,
    ) -> list[ClassifiedBlock]:
        """Return a list of ClassifiedBlocks for *page*, ordered top-to-bottom."""
        results: list[ClassifiedBlock] = []

        # Build a set of bboxes already claimed by tables so we can exclude them
        # from text processing.
        table_bboxes = [tb.bbox for tb in page.table_blocks]

        is_definition_section = self._is_definition_section(section)

        # --- Tables (highest priority) ---
        for tb in page.table_blocks:
            results.append(
                ClassifiedBlock(content_type=ContentType.TABLE, table_block=tb)
            )

        # --- Vector drawing clusters ---
        for dc in page.drawing_clusters:
            results.append(
                ClassifiedBlock(content_type=ContentType.FIGURE, drawing_cluster=dc)
            )

        # --- Raster images ---
        for ib in page.image_blocks:
            results.append(
                ClassifiedBlock(content_type=ContentType.BITMAP, image_block=ib)
            )

        # --- Text blocks ---
        for tb in page.text_blocks:
            # Skip text blocks whose bbox is fully inside a table region
            if self._covered_by_table(tb.bbox, table_bboxes):
                continue

            ctype = self._classify_text_block(tb, is_definition_section)
            results.append(
                ClassifiedBlock(content_type=ctype, text_block=tb)
            )

        # Sort top-to-bottom by y-coordinate of the block
        results.sort(key=lambda b: self._top_y(b))
        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_definition_section(section: SectionNode | None) -> bool:
        if section is None:
            return False
        title_lower = section.title.lower()
        return any(kw in title_lower for kw in _DEFINITION_SECTION_KEYWORDS)

    @staticmethod
    def _covered_by_table(
        bbox: tuple[float, float, float, float],
        table_bboxes: list[tuple[float, float, float, float]],
        padding: float = 2.0,
    ) -> bool:
        """Return True if the centre of *bbox* falls inside any table region.

        Using the centre point (rather than an area-overlap ratio) eliminates
        duplicates caused by PyMuPDF/pdfplumber coordinate discrepancies: a text
        block whose centre is inside a table bbox is unambiguously table content,
        regardless of whether a small edge of it crosses the table boundary.

        *padding* (default 2 pt) absorbs sub-pixel floating-point differences
        between the two libraries' coordinate systems without over-filtering
        legitimate surrounding text (headings, captions, footnotes).
        """
        cx = (bbox[0] + bbox[2]) / 2
        cy = (bbox[1] + bbox[3]) / 2
        for tx0, ty0, tx1, ty1 in table_bboxes:
            if (tx0 - padding <= cx <= tx1 + padding and
                    ty0 - padding <= cy <= ty1 + padding):
                return True
        return False

    @staticmethod
    def _classify_text_block(
        tb: TextBlock, is_definition_section: bool
    ) -> ContentType:
        """Classify a single text block."""
        if is_definition_section:
            return ContentType.DEFINITION

        text = tb.text
        text_lower = text.lower()

        # Register heuristic: bit-range notation + register field keywords
        if _BIT_RANGE_RE.search(text):
            if any(kw in text_lower for kw in _REGISTER_KEYWORDS):
                return ContentType.REGISTER

        return ContentType.TEXT

    @staticmethod
    def _top_y(block: ClassifiedBlock) -> float:
        if block.text_block:
            return block.text_block.bbox[1]
        if block.table_block:
            return block.table_block.bbox[1]
        if block.drawing_cluster:
            return block.drawing_cluster.bbox[1]
        if block.image_block:
            return block.image_block.bbox[1]
        return 0.0
