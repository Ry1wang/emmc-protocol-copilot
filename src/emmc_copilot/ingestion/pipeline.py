"""IngestionPipeline: orchestrate parsing, classification, and chunking for one PDF."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from .chunkers.definition import DefinitionChunker
from .chunkers.figure import FigureChunker
from .chunkers.table import TableChunker
from .chunkers.text import TextChunker
from .classifier import BlockClassifier
from .parser import PDFParser, PageModel
from .schema import ContentType, EMMCChunk
from .structure import DocumentStructure, SectionNode, StructureExtractor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants for chunk validation
# ---------------------------------------------------------------------------

# Minimum raw content length (excluding the header prefix) for each content type.
# These values are tuned based on 50-chunk sampling analysis to filter out
# "stub" chunks (e.g. only a header, only "cont'd", or only a few noise chars).
_MIN_RAW_CHARS_BY_TYPE = {
    ContentType.TEXT: 40,       # At least a full sentence or bullet point
    ContentType.TABLE: 80,      # Enough to contain header + at least one data row
    ContentType.FIGURE: 30,     # Caption or detailed label
    ContentType.BITMAP: 30,     # Caption or technical label
    ContentType.DEFINITION: 8,  # Short terms like "CMD: Command" are valid
    ContentType.REGISTER: 40,   # Register name + base address/bit range
}

# Patterns to detect pure continuation markers or watermark leftovers
_NOISE_PATTERNS = [
    re.compile(r"^(cont'd|continued|continued\s+on\s+next\s+page|to\s+be\s+continued)\.?$", re.IGNORECASE),
    re.compile(r"^(downloaded\s+by|ruyi|jEDEC\s+Standard).*$", re.IGNORECASE),
]

def _is_valid_chunk(chunk: EMMCChunk) -> bool:
    """Check if a chunk has meaningful content by excluding metadata prefix.
    
    A chunk is valid if its main content body (excluding the generated 
    header prefix) meets the technical threshold for its type and is 
    not a known noise pattern.
    """
    # 1. Extract the main content body from the combined text.
    # The first line is always the generated prefix: [eMMC 5.1 | Section | Page]
    lines = chunk.text.strip().split('\n')
    if len(lines) <= 1:
        # No content body, just a header
        content_body = ""
    else:
        content_body = "\n".join(lines[1:]).strip()
    
    content_len = len(content_body)

    # 2. Check length against type-specific thresholds
    min_chars = _MIN_RAW_CHARS_BY_TYPE.get(chunk.content_type, 30)
    if content_len < min_chars:
        # Special case: Register bits can be short (e.g. "[187]"), allow if in Register context
        if chunk.content_type == ContentType.REGISTER and content_len > 5:
            pass 
        else:
            return False

    # 3. Filter out pure continuation markers or margin noise
    if any(p.match(content_body) for p in _NOISE_PATTERNS):
        return False

    return True


def _normalize_heading(text: str) -> str:
    """Normalize a potential heading text from a PDF block."""
    text = text.strip().lower()
    # Remove common PDF extraction artifacts in headings
    text = re.sub(r"\s+", " ", text)
    text = text.strip(". ")
    return text


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class IngestionResult:
    source: str
    version: str
    total_pages: int
    chunks: list[EMMCChunk] = field(default_factory=list)

    @property
    def searchable_chunks(self) -> list[EMMCChunk]:
        result = []
        for c in self.chunks:
            # 1. Skip front matter
            if c.is_front_matter:
                continue

            # 2. Skip full-table chunks (only row-group chunks for retrieval)
            # EXCEPTION: If the table is a Register Map or Overview, keep the full table too
            # to provide macro-context (P1 Issue 5).
            if c.content_type == ContentType.TABLE and not c.is_row_chunk:
                is_reg_section = any(kw in c.section_title.upper() for kw in ("CSD", "CID", "DSR", "OCR", "EXT_CSD"))
                if not is_reg_section:
                    continue

            # 3. Skip invalid short chunks (insufficient meaningful content)
            if not _is_valid_chunk(c):
                continue

            result.append(c)
        return result

    def stats(self) -> dict[str, int]:
        from collections import Counter

        # Count chunks filtered out due to insufficient content
        short_filtered = sum(
            1 for c in self.chunks
            if not _is_valid_chunk(c) and not c.is_front_matter
        )

        # Count content types in searchable chunks
        ctype_counts = Counter(c.content_type for c in self.searchable_chunks)

        # Front matter = total - searchable - short_filtered
        front_matter_count = (
            len(self.chunks) - len(self.searchable_chunks) - short_filtered
        )

        return {
            "total": len(self.chunks),
            "searchable": len(self.searchable_chunks),
            "front_matter": front_matter_count,
            "short_filtered": short_filtered,
            **{str(k): v for k, v in ctype_counts.items()},
        }


# ---------------------------------------------------------------------------
# IngestionPipeline
# ---------------------------------------------------------------------------

class IngestionPipeline:
    """End-to-end pipeline: PDF → List[EMMCChunk].

    Text is accumulated across page boundaries within the same section so
    that cross-page paragraphs and lists are not artificially split.  The
    accumulator is only flushed when:
      - the active section changes, OR
      - a non-text block (TABLE / FIGURE / BITMAP) interrupts the text flow,
        OR the content type switches between TEXT and REGISTER.
    """

    def __init__(self) -> None:
        self._text_chunker = TextChunker()
        self._table_chunker = TableChunker()
        self._figure_chunker = FigureChunker()
        self._definition_chunker = DefinitionChunker()
        self._classifier = BlockClassifier()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run(self, pdf_path: str | Path) -> IngestionResult:
        """Process a single PDF and return all extracted chunks."""
        pdf_path = Path(pdf_path)
        logger.info("Ingesting %s", pdf_path.name)

        with PDFParser(pdf_path) as parser:
            toc = parser.toc
            source = parser.source
            version = parser.version
            total_pages = parser.page_count

            # 1. Build document structure
            structure = StructureExtractor(
                toc, source, version, total_pages
            ).extract()
            logger.info(
                "body_start=%d, sections=%d",
                structure.body_start_page,
                len(structure.sections),
            )

            # 2. Parse all pages
            pages = parser.pages()

        # 3. Classify and chunk
        all_chunks: list[EMMCChunk] = []

        # Accumulate text per section for definition extraction (Round 1)
        section_texts: dict[int, list[str]] = {}  # section.page_start → texts

        # ---------------------------------------------------------------
        # Cross-page text accumulation state.
        #
        # text_accumulator holds raw text blocks not yet chunked.  It is
        # intentionally NOT flushed at the end of each page — flushing only
        # happens at section transitions or non-text block interruptions so
        # that paragraphs / lists that span a page boundary remain intact.
        # ---------------------------------------------------------------
        text_accumulator: list[str] = []
        text_ctype: ContentType = ContentType.TEXT
        current_section: SectionNode | None = None
        accum_page_start: int = 1
        accum_page_end: int = 1

        def _flush_text() -> None:
            if not text_accumulator:
                return
            combined = "\n".join(text_accumulator)
            new_chunks = self._text_chunker.chunk_section(
                raw_text=combined,
                source=source,
                version=version,
                section=current_section,
                page_start=accum_page_start,
                page_end=accum_page_end,
                content_type=text_ctype,
            )
            all_chunks.extend(new_chunks)
            text_accumulator.clear()

        for page in pages:
            page_num = page.page_num
            # Fallback section for this page (from TOC)
            page_default_section = structure.page_to_section.get(page_num)
            
            # Text from all blocks on this page for nearby-text lookups
            page_raw_text = " ".join(tb.text for tb in page.text_blocks)

            # Classify all blocks on the page
            classified = self._classifier.classify_page(page, current_section or page_default_section)

            # Collect raw text for definition extraction (Round 1)
            # Use current_section if already switched, otherwise fallback
            for cb in classified:
                section_for_def = current_section or page_default_section
                if section_for_def and not section_for_def.is_front_matter:
                    bucket = section_texts.setdefault(section_for_def.page_start, [])
                    if cb.text_block:
                        bucket.append(cb.text_block.text)

            for cb in classified:
                # P1: Sub-page section detection
                # If this text block matches a TOC heading, switch section immediately
                if cb.text_block and cb.content_type == ContentType.TEXT:
                    # Heuristic: Headings are usually larger or bold
                    # font_flags: bold=20; but also check exact text match against TOC
                    norm_text = _normalize_heading(cb.text_block.text)
                    hit_section = structure.label_to_section.get(norm_text)
                    
                    if hit_section and hit_section is not current_section:
                        # Flush accumulated content from the OLD section
                        if text_accumulator:
                            _flush_text()
                        
                        # Switch to the NEW section
                        current_section = hit_section
                        accum_page_start = page_num
                        logger.debug("Switched section at p%d: %s", page_num, hit_section.label)

                # Initialize current_section if not yet set
                if current_section is None:
                    current_section = page_default_section

                if cb.content_type in (ContentType.TEXT, ContentType.REGISTER):
                    # Content-type switch (TEXT ↔ REGISTER) → flush first
                    if text_accumulator and cb.content_type != text_ctype:
                        _flush_text()
                    
                    text_ctype = cb.content_type
                    if cb.text_block:
                        if not text_accumulator:
                            accum_page_start = page_num
                        text_accumulator.append(cb.text_block.text)
                        accum_page_end = page_num

                elif cb.content_type == ContentType.TABLE:
                    _flush_text()
                    if cb.table_block:
                        table_chunks = self._table_chunker.chunk(
                            table=cb.table_block,
                            nearby_text=page_raw_text,
                            source=source,
                            version=version,
                            section=current_section,
                            page_start=page_num,
                            page_end=page_num,
                        )
                        all_chunks.extend(table_chunks)
                        if table_chunks:
                            row_chunks = self._table_chunker.chunk_row_groups(
                                table=cb.table_block,
                                nearby_text=page_raw_text,
                                source=source,
                                version=version,
                                section=current_section,
                                page_start=page_num,
                                page_end=page_num,
                                parent_chunk_id=table_chunks[0].chunk_id,
                            )
                            all_chunks.extend(row_chunks)

                elif cb.content_type == ContentType.FIGURE:
                    _flush_text()
                    if cb.drawing_cluster:
                        fig_chunk = self._figure_chunker.chunk_figure(
                            cluster=cb.drawing_cluster,
                            page=page,
                            source=source,
                            version=version,
                            section=current_section,
                            page_start=page_num,
                            page_end=page_num,
                        )
                        if fig_chunk:
                            all_chunks.append(fig_chunk)

                elif cb.content_type == ContentType.BITMAP:
                    _flush_text()
                    if cb.image_block:
                        bmp_chunk = self._figure_chunker.chunk_bitmap(
                            image=cb.image_block,
                            page=page,
                            source=source,
                            version=version,
                            section=current_section,
                            page_start=page_num,
                            page_end=page_num,
                        )
                        if bmp_chunk:
                            all_chunks.append(bmp_chunk)

                elif cb.content_type == ContentType.DEFINITION:
                    # Handled globally in Round 1; skip inline to avoid duplicates
                    pass

            # *** Do NOT flush text_accumulator here at page end ***
            # Text continues to accumulate across page boundaries within the
            # same section so cross-page paragraphs and lists stay intact.

        # Final flush for any remaining accumulated text
        _flush_text()

        # 4. Definition extraction: Round 1 (dedicated sections)
        for section in structure.sections:
            if not section.is_front_matter:
                text = " \n".join(section_texts.get(section.page_start, []))
                def_chunks = self._definition_chunker.extract_from_section(
                    section_text=text,
                    section=section,
                    source=source,
                    version=version,
                    page_start=section.page_start,
                    page_end=section.page_end,
                )
                all_chunks.extend(def_chunks)

        logger.info("Total chunks: %d", len(all_chunks))
        return IngestionResult(
            source=source,
            version=version,
            total_pages=total_pages,
            chunks=all_chunks,
        )
