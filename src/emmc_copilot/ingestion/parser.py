"""PDF document parser: wraps PyMuPDF + pdfplumber to produce per-page PageModels."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF
import pdfplumber

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes — intermediate page representation
# ---------------------------------------------------------------------------

@dataclass
class TextBlock:
    """A single text block extracted from a PDF page."""
    bbox: tuple[float, float, float, float]   # (x0, y0, x1, y1)
    text: str
    font_size: float
    font_flags: int   # PyMuPDF flags: bold=20, italic=22
    block_no: int


@dataclass
class DrawingCluster:
    """A cluster of vector drawing elements (e.g. a figure or diagram)."""
    bbox: tuple[float, float, float, float]
    area: float
    element_count: int


@dataclass
class ImageBlock:
    """A raster image embedded in a PDF page."""
    bbox: tuple[float, float, float, float]
    xref: int           # PyMuPDF cross-reference number (unique per image)
    width: int
    height: int


@dataclass
class TableBlock:
    """A table extracted by pdfplumber."""
    bbox: tuple[float, float, float, float]
    rows: list[list[str | None]]   # raw cell data; None = empty cell


@dataclass
class PageModel:
    """All extracted content for a single PDF page."""
    page_num: int                              # 1-indexed physical page number
    width: float
    height: float
    text_blocks: list[TextBlock] = field(default_factory=list)
    drawing_clusters: list[DrawingCluster] = field(default_factory=list)
    image_blocks: list[ImageBlock] = field(default_factory=list)
    table_blocks: list[TableBlock] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Minimum bounding-box area (pt²) for a drawing cluster to be considered
# a significant figure (filters out hairlines, separators, cell borders).
_MIN_FIGURE_AREA = 5_000.0

# Padding (pt) used when merging drawing element bboxes into clusters.
_CLUSTER_PADDING = 4.0

# Define page margins to ignore (pt). Standard eMMC spec has fixed header/footer.
# Top margin usually contains "JEDEC Standard No. 84-B51" + Page number.
# Bottom margin usually contains Download info/Watermarks.
_HEADER_MARGIN = 60.0  # pt from top
_FOOTER_MARGIN = 60.0  # pt from bottom


# Watermark patterns to clean from extracted text (ordered by specificity)
_WATERMARK_PATTERNS = [
    # Complete download declaration lines
    re.compile(r"Downloaded\s+by\s+.*?ry_lang@outlook\.com.*?$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"Downloaded\s+by\s+.*?\(ry_lang@outlook\.com\).*?$", re.IGNORECASE | re.MULTILINE),
    # Watermark names and emails
    re.compile(r"ry_lang@outlook\.com", re.IGNORECASE),
    re.compile(r"\bryi\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"\bruyi\b", re.IGNORECASE),
    re.compile(r"\bru\s+yi\b", re.IGNORECASE),
    re.compile(r"\bry_lang\b", re.IGNORECASE),
    # JEDEC standard header noise
    re.compile(r"JEDEC\s+Standard\s+No\.\s+84-B51", re.IGNORECASE),
    re.compile(r"Page\s+\d+", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_in_margin(bbox: tuple[float, float, float, float], page_height: float) -> bool:
    """Check if a block is entirely within the top or bottom margin."""
    # bbox is (x0, y0, x1, y1) where y0 is top, y1 is bottom
    y0, y1 = bbox[1], bbox[3]
    if y1 < _HEADER_MARGIN:
        return True
    if y0 > (page_height - _FOOTER_MARGIN):
        return True
    return False


def _merge_bboxes(
    bboxes: list[tuple[float, float, float, float]],
) -> tuple[float, float, float, float]:
    """Return the bounding box that contains all given bboxes."""
    x0 = min(b[0] for b in bboxes)
    y0 = min(b[1] for b in bboxes)
    x1 = max(b[2] for b in bboxes)
    y1 = max(b[3] for b in bboxes)
    return (x0, y0, x1, y1)


def _bbox_overlaps(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    padding: float = _CLUSTER_PADDING,
) -> bool:
    """Return True if two bboxes overlap or are within *padding* points of each other."""
    return (
        a[0] - padding < b[2]
        and a[2] + padding > b[0]
        and a[1] - padding < b[3]
        and a[3] + padding > b[1]
    )


def _cluster_drawings(
    raw_bboxes: list[tuple[float, float, float, float]],
) -> list[DrawingCluster]:
    """Merge drawing-element bboxes into clusters using iterative union-merge.

    Returns only clusters whose area >= _MIN_FIGURE_AREA.
    """
    if not raw_bboxes:
        return []

    clusters: list[list[tuple[float, float, float, float]]] = [
        [b] for b in raw_bboxes
    ]

    changed = True
    while changed:
        changed = False
        merged: list[list[tuple[float, float, float, float]]] = []
        used = [False] * len(clusters)
        for i, ci in enumerate(clusters):
            if used[i]:
                continue
            bb_i = _merge_bboxes(ci)
            group = ci[:]
            for j, cj in enumerate(clusters):
                if i == j or used[j]:
                    continue
                bb_j = _merge_bboxes(cj)
                if _bbox_overlaps(bb_i, bb_j):
                    group.extend(cj)
                    bb_i = _merge_bboxes(group)
                    used[j] = True
                    changed = True
            merged.append(group)
            used[i] = True
        clusters = merged

    result: list[DrawingCluster] = []
    for group in clusters:
        bb = _merge_bboxes(group)
        area = (bb[2] - bb[0]) * (bb[3] - bb[1])
        if area >= _MIN_FIGURE_AREA:
            result.append(DrawingCluster(bbox=bb, area=area, element_count=len(group)))

    return result


def _extract_version(filename: str) -> str:
    """Derive eMMC spec version string from filename.

    Examples:
        JESD84-B51  → "5.1"
        JESD84-B50  → "5.0"
        JESD84-B451 → "4.51"
    """
    m = re.search(r"B(\d)(\d+)", filename, re.IGNORECASE)
    if m:
        return f"{m.group(1)}.{m.group(2)}"
    return "unknown"


def _has_heading_decorations(plumber_page: object, page_width: float) -> bool:
    """Return True if the page contains JEDEC chapter-heading decorations.

    Each major section heading in the eMMC spec is wrapped by two full-width solid
    horizontal lines spaced ~22 pt apart (the heading title sits in that gap).
    These decorative lines are NOT table borders, but pdfplumber's text-alignment
    vertical strategy mistakes them for table borders and generates spurious tables.

    Detection: find a pair of wide horizontal edges (>= 60% page width) whose
    inner vertical gap is between 10 and 30 pt.
    """
    h_edges = [e for e in plumber_page.edges if e.get("orientation") == "h"]  # type: ignore[attr-defined]
    wide = sorted(
        [e for e in h_edges if abs(e["x1"] - e["x0"]) > page_width * 0.60],
        key=lambda e: e["top"],
    )
    for i in range(len(wide) - 1):
        gap = wide[i + 1]["top"] - wide[i]["bottom"]
        if 10.0 <= gap <= 30.0:
            return True
    return False


def _is_plausible_table(
    rows: list[list[str | None]],
    bbox: tuple[float, float, float, float],
    page_width: float,
) -> bool:
    """Return False for false-positive tables caused by decorative heading lines + text strategy.

    Chapter heading decorations in JEDEC eMMC specs consist of two full-width horizontal
    solid lines spaced ~22 pt apart.  When pdfplumber's text-alignment vertical strategy
    is applied, these lines become the table's horizontal borders and the natural word
    spacing within the heading text creates 15-20 spurious vertical "columns".

    Rejection criteria (both must be true):
      - ncols > 8  : genuine eMMC tables never exceed 8-9 columns
      - fill_rate < 35%: real column-aligned tables consistently fill > 50% of cells
    """
    if not rows:
        return False

    ncols = max((len(row) for row in rows), default=0)
    if ncols <= 8:
        return True  # column count is reasonable — keep without further checks

    # Check 1: "lone heading row" pattern.
    # In a heading-decoration false table the first and/or last row contains exactly
    # one non-empty cell (the heading title) while all other cells are empty.
    # This is an unambiguous signature — no genuine data table has this structure.
    def _is_lone_heading_row(row: list[str | None]) -> bool:
        non_empty = sum(1 for c in row if c and c.strip())
        return non_empty == 1

    if _is_lone_heading_row(rows[0]) or _is_lone_heading_row(rows[-1]):
        logger.debug(
            "Rejected false table (lone heading-row pattern): "
            "ncols=%d bbox=(%.0f,%.0f,%.0f,%.0f)",
            ncols, *bbox,
        )
        return False

    # Check 2: overall fill rate.
    # Real high-column tables (e.g. capability matrices) have consistent column fill.
    total_cells = sum(len(row) for row in rows)
    non_empty = sum(1 for row in rows for c in row if c and c.strip())
    fill_rate = non_empty / total_cells if total_cells > 0 else 0

    if fill_rate < 0.40:
        logger.debug(
            "Rejected false table (low fill rate): "
            "ncols=%d fill_rate=%.0f%% bbox=(%.0f,%.0f,%.0f,%.0f)",
            ncols, fill_rate * 100, *bbox,
        )
        return False

    return True


def _clean_text(text: str) -> str:
    """Clean watermark noise and normalise whitespace.

    - Removes download declarations (e.g., "Downloaded by ...")
    - Normalises whitespace, dashes, and special Unicode symbols
    - Consolidates eMMC variant spellings
    """
    # 1. Remove watermark patterns
    for pattern in _WATERMARK_PATTERNS:
        text = pattern.sub("", text)

    # 2. Global Unicode character mappings (Consistency)
    # This prevents fragmentation in retrieval where the same term is 
    # represented by different Unicode characters in different pages.
    char_map = {
        "\u00A0": " ",          # Non-breaking space
        "\u2013": "-",          # en-dash
        "\u2014": "-",          # em-dash
        "\u2212": "-",          # Minus sign
        "\u2018": "'",          # Left single quote
        "\u2019": "'",          # Right single quote
        "\u201C": '"',          # Left double quote
        "\u201D": '"',          # Right double quote
        "\u00B5": "u",          # Micro (e.g. us, uA)
        "\u00B1": "+/-",        # Plus-minus
        "\u00B0": "deg",        # Degree
        "\u2264": "<=",         # Less-than or equal
        "\u2265": ">=",         # Greater-than or equal
        "\u00D7": "x",          # Multiplication sign
        "\u2022": "*",          # Bullet point
        "\u2026": "...",        # Ellipsis
    }
    for char, replacement in char_map.items():
        text = text.replace(char, replacement)

    # 3. Consolidate eMMC specific variants
    # Common PDF/OCR artifacts: "e •MMC", "e.MMC", "e-MMC", "e 2 •MMC"
    text = re.sub(r"e\s*[•∙\-.]\s*MMC", "eMMC", text, flags=re.IGNORECASE)
    text = re.sub(r"e\s*2\s*[•∙\-.]\s*MMC", "e.MMC", text, flags=re.IGNORECASE) # HS200 variant
    text = text.replace("∆", "Delta")

    # 4. Normalise whitespace (tabs/multiple spaces → single space)
    text = re.sub(r"[ \t]+", " ", text)

    # 5. Normalise line breaks (3+ consecutive newlines → 2)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 6. Remove empty parentheses/brackets left after watermark removal
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"\[\s*\]", "", text)
    text = re.sub(r"\(\s*\.\s*\)", "", text)

    return text.strip()


# ---------------------------------------------------------------------------
# PDFParser
# ---------------------------------------------------------------------------

class PDFParser:
    """Parse an eMMC PDF and expose per-page PageModels.

    Usage::

        parser = PDFParser("docs/protocol/JESD84-B51.pdf")
        for page_model in parser.pages():
            ...
        toc = parser.toc   # list[tuple[level, title, page_num]]
    """

    def __init__(self, pdf_path: str | Path) -> None:
        self.path = Path(pdf_path)
        if not self.path.exists():
            raise FileNotFoundError(self.path)

        self.source = self.path.name
        self.version = _extract_version(self.source)

        # Open with both libraries; keep handles open for the lifetime of this object.
        self._fitz_doc = fitz.open(str(self.path))
        self._plumber_doc = pdfplumber.open(str(self.path))

        self._page_count = len(self._fitz_doc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def page_count(self) -> int:
        return self._page_count

    @property
    def toc(self) -> list[tuple[int, str, int]]:
        """Return the document TOC as a list of (level, title, page_1indexed)."""
        raw = self._fitz_doc.get_toc()
        # fitz returns 0-indexed page numbers; convert to 1-indexed
        return [(level, title, page + 1) for level, title, page in raw]

    def pages(self) -> list[PageModel]:
        """Parse every page and return a list of PageModels (1-indexed)."""
        models: list[PageModel] = []
        for idx in range(self._page_count):
            models.append(self._parse_page(idx))
        return models

    def parse_page(self, page_num: int) -> PageModel:
        """Parse a single page by 1-indexed page number."""
        return self._parse_page(page_num - 1)

    def close(self) -> None:
        self._fitz_doc.close()
        self._plumber_doc.close()

    def __enter__(self) -> "PDFParser":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_page(self, idx: int) -> PageModel:
        """Parse page at 0-based index *idx*."""
        fitz_page = self._fitz_doc[idx]
        page_num = idx + 1
        width = fitz_page.rect.width
        height = fitz_page.rect.height

        text_blocks = self._extract_text_blocks(fitz_page)
        drawing_clusters = self._extract_drawing_clusters(fitz_page)
        image_blocks = self._extract_image_blocks(fitz_page)
        table_blocks = self._extract_table_blocks(idx, width)

        return PageModel(
            page_num=page_num,
            width=width,
            height=height,
            text_blocks=text_blocks,
            drawing_clusters=drawing_clusters,
            image_blocks=image_blocks,
            table_blocks=table_blocks,
        )

    def _extract_text_blocks(self, fitz_page: fitz.Page) -> list[TextBlock]:
        """Extract text blocks with font metadata using PyMuPDF."""
        blocks: list[TextBlock] = []
        page_height = fitz_page.rect.height
        raw = fitz_page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)

        for block in raw.get("blocks", []):
            if block.get("type") != 0:  # 0 = text block
                continue

            bbox = tuple(block["bbox"])  # type: ignore[arg-type]
            
            # P0: Filter out blocks in margins (Header/Footer)
            if _is_in_margin(bbox, page_height):
                continue

            block_text_parts: list[str] = []
            dominant_size = 0.0
            dominant_flags = 0
            span_count = 0

            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    span_text = _clean_text(span.get("text", ""))
                    if not span_text:
                        continue
                    block_text_parts.append(span_text)
                    dominant_size += span.get("size", 0.0)
                    dominant_flags = span.get("flags", 0)  # last span wins
                    span_count += 1

            full_text = " ".join(block_text_parts).strip()
            if not full_text:
                continue

            avg_size = dominant_size / span_count if span_count else 0.0

            blocks.append(
                TextBlock(
                    bbox=bbox,
                    text=full_text,
                    font_size=round(avg_size, 1),
                    font_flags=dominant_flags,
                    block_no=block.get("number", 0),
                )
            )

        return blocks

    def _extract_drawing_clusters(self, fitz_page: fitz.Page) -> list[DrawingCluster]:
        """Cluster vector drawing elements into figure regions."""
        drawings = fitz_page.get_drawings()
        bboxes: list[tuple[float, float, float, float]] = []
        for d in drawings:
            r = d.get("rect")
            if r and r.width > 0 and r.height > 0:
                bboxes.append((r.x0, r.y0, r.x1, r.y1))
        return _cluster_drawings(bboxes)

    def _extract_image_blocks(self, fitz_page: fitz.Page) -> list[ImageBlock]:
        """Extract embedded raster images."""
        images: list[ImageBlock] = []
        for img_info in fitz_page.get_images(full=True):
            xref = img_info[0]
            width = img_info[2]
            height = img_info[3]
            # Locate the image bbox on the page
            for block in fitz_page.get_text("dict").get("blocks", []):
                if block.get("type") == 1 and block.get("number") == xref:
                    bbox = tuple(block["bbox"])  # type: ignore[arg-type]
                    break
            else:
                # Fallback: search image list on page
                rects = fitz_page.get_image_rects(xref)
                if rects:
                    r = rects[0]
                    bbox = (r.x0, r.y0, r.x1, r.y1)
                else:
                    continue
            images.append(ImageBlock(bbox=bbox, xref=xref, width=width, height=height))
        return images

    def _extract_table_blocks(self, idx: int, page_width: float) -> list[TableBlock]:
        """Extract tables using pdfplumber with expert-tuned settings for eMMC spec."""
        tables: list[TableBlock] = []
        try:
            plumber_page = self._plumber_doc.pages[idx]

            # P0: Optimized table_settings for technical specs (handles gapped borders)
            table_settings = {
                "vertical_strategy": "lines",
                "horizontal_strategy": "lines",
                "snap_tolerance": 8,       # High tolerance for broken lines
                "join_tolerance": 8,       # Join segments that nearly touch
                "edge_min_length": 3,
                "min_words_vertical": 1,   # Allow single bit columns (0/1)
                "min_words_horizontal": 1,
            }

            # Try primary strategy (lines)
            found_tables = plumber_page.find_tables(table_settings=table_settings)
            
            # P1 fallback: If no tables found by lines, try text-alignment strategy
            # (useful for register bit definition tables aligned by text position).
            # Guard: skip this fallback on pages with chapter-heading decorations
            # (two full-width horizontal rules ~22pt apart) because those decorative
            # lines are misread as table borders by the text strategy, producing
            # spurious 15-20-column tables.
            if not found_tables and not _has_heading_decorations(plumber_page, page_width):
                table_settings["vertical_strategy"] = "text"
                found_tables = plumber_page.find_tables(table_settings=table_settings)

            for table in found_tables:
                bbox_raw = table.bbox  # (x0, top, x1, bottom)
                bbox = (bbox_raw[0], bbox_raw[1], bbox_raw[2], bbox_raw[3])
                rows = table.extract()

                # Reject false-positive tables produced by decorative heading lines
                # (two full-width horizontal rules misread by the text strategy as a table)
                if not _is_plausible_table(rows, bbox, page_width):
                    continue

                # Cleanup cell data: strip and filter out line noise
                if rows:
                    clean_rows = []
                    for row in rows:
                        if not any(row): continue
                        clean_row = []
                        for cell in row:
                            if cell is None:
                                clean_row.append(None)
                            else:
                                c = cell.strip()
                                # Filter only 'i' — the sole character reliably produced
                                # by pdfplumber misreading vertical table-border lines.
                                # Do NOT filter 'y'/'n'/'u'/'r'/'w' etc.: these are
                                # valid single-char cell values in eMMC spec tables
                                # (Y/N = supported/not-supported, U = undefined, etc.).
                                if c == 'i':
                                    clean_row.append(None)
                                else:
                                    clean_row.append(_clean_text(c))
                        if any(clean_row):
                            clean_rows.append(clean_row)
                    
                    if clean_rows:
                        tables.append(TableBlock(bbox=bbox, rows=clean_rows))
        except Exception as exc:
            logger.warning("pdfplumber failed on page %d: %s", idx + 1, exc)
        return tables

