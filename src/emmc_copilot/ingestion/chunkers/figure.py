"""FigureChunker: vector drawing / bitmap → caption + text labels → EMMCChunk."""

from __future__ import annotations

import re

from ..parser import DrawingCluster, ImageBlock, PageModel, TextBlock
from ..schema import ContentType, EMMCChunk
from ..structure import SectionNode


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Vertical distance (pt) to search above/below a figure bbox for a caption
_CAPTION_SEARCH_MARGIN = 40.0

_FIGURE_CAPTION_RE = re.compile(
    r"Figure\s+\d+[\s\u2014\-]+[^\n]{3,120}", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bbox_vertical_distance(
    bbox_a: tuple[float, float, float, float],
    bbox_b: tuple[float, float, float, float],
) -> float:
    """Vertical gap between two bboxes (negative if they overlap)."""
    # bbox = (x0, y0, x1, y1); y increases downward in PDF coords
    a_top, a_bot = bbox_a[1], bbox_a[3]
    b_top, b_bot = bbox_b[1], bbox_b[3]
    if a_bot <= b_top:
        return b_top - a_bot   # a is above b
    if b_bot <= a_top:
        return a_top - b_bot   # b is above a
    return -1.0               # overlapping


def _text_inside_bbox(
    text_blocks: list[TextBlock],
    bbox: tuple[float, float, float, float],
) -> list[str]:
    """Return texts of blocks whose centre lies inside *bbox*."""
    x0, y0, x1, y1 = bbox
    result: list[str] = []
    for tb in text_blocks:
        cx = (tb.bbox[0] + tb.bbox[2]) / 2
        cy = (tb.bbox[1] + tb.bbox[3]) / 2
        if x0 <= cx <= x1 and y0 <= cy <= y1:
            result.append(tb.text.strip())
    return result


def _find_caption(
    text_blocks: list[TextBlock],
    figure_bbox: tuple[float, float, float, float],
) -> str:
    """Search for the nearest caption text above or below the figure."""
    candidates: list[tuple[float, str]] = []  # (distance, text)
    for tb in text_blocks:
        dist = _bbox_vertical_distance(figure_bbox, tb.bbox)
        if 0 <= dist <= _CAPTION_SEARCH_MARGIN:
            m = _FIGURE_CAPTION_RE.search(tb.text)
            if m:
                candidates.append((dist, m.group(0).strip()))
    if candidates:
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]
    return ""


def _make_prefix(
    version: str,
    section: SectionNode | None,
    page: int,
) -> str:
    label = section.label if section else "(front matter)"
    return f"[eMMC {version} | {label} | Page {page}]\n"


# ---------------------------------------------------------------------------
# FigureChunker
# ---------------------------------------------------------------------------

class FigureChunker:
    """Create EMMCChunks for vector drawings and raster images."""

    def chunk_figure(
        self,
        cluster: DrawingCluster,
        page: PageModel,
        source: str,
        version: str,
        section: SectionNode | None,
        page_start: int,
        page_end: int,
    ) -> EMMCChunk | None:
        """Build a chunk for a vector-drawing cluster."""
        caption = _find_caption(page.text_blocks, cluster.bbox)
        labels = _text_inside_bbox(page.text_blocks, cluster.bbox)

        # A figure with no caption and no text labels has little retrieval value
        if not caption and not labels:
            return None

        prefix = _make_prefix(version, section, page_start)
        caption_line = f"[Figure: {caption}]" if caption else "[Figure: (no caption)]"
        body = caption_line
        if labels:
            body += "\n" + "\n".join(labels)

        return EMMCChunk(
            source=source,
            version=version,
            page_start=page_start,
            page_end=page_end,
            section_path=section.path if section else [],
            section_title=section.title if section else "",
            heading_level=section.level if section else 0,
            content_type=ContentType.FIGURE,
            is_front_matter=section.is_front_matter if section else True,
            chunk_index=0,
            text=prefix + body,
            raw_text=body,
            figure_caption=caption or None,
        )

    def chunk_bitmap(
        self,
        image: ImageBlock,
        page: PageModel,
        source: str,
        version: str,
        section: SectionNode | None,
        page_start: int,
        page_end: int,
    ) -> EMMCChunk | None:
        """Build a chunk for a raster image."""
        caption = _find_caption(page.text_blocks, image.bbox)
        surrounding = _text_inside_bbox(page.text_blocks, (
            image.bbox[0],
            max(0, image.bbox[1] - _CAPTION_SEARCH_MARGIN),
            image.bbox[2],
            image.bbox[3] + _CAPTION_SEARCH_MARGIN,
        ))

        if not caption and not surrounding:
            return None

        prefix = _make_prefix(version, section, page_start)
        caption_line = f"[Figure: {caption}]" if caption else "[Figure: bitmap image]"
        body = caption_line
        if surrounding:
            body += "\n" + "\n".join(surrounding)

        return EMMCChunk(
            source=source,
            version=version,
            page_start=page_start,
            page_end=page_end,
            section_path=section.path if section else [],
            section_title=section.title if section else "",
            heading_level=section.level if section else 0,
            content_type=ContentType.BITMAP,
            is_front_matter=section.is_front_matter if section else True,
            chunk_index=0,
            text=prefix + body,
            raw_text=body,
            figure_caption=caption or None,
        )
