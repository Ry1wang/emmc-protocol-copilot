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
from .parser import PDFParser
from .schema import ContentType, EMMCChunk
from .structure import DocumentStructure, SectionNode, StructureExtractor, _normalize_label

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants for chunk validation
# ---------------------------------------------------------------------------

# Minimum raw content length (excluding the header prefix) for each content type.
# These values are tuned based on 50-chunk sampling analysis to filter out
# "stub" chunks (e.g. only a header, only "cont'd", or only a few noise chars).
_MIN_RAW_CHARS_BY_TYPE = {
    ContentType.TEXT: 20,       # Allow shorter technical lists/signal names
    ContentType.TABLE: 80,      # Full-table chunk: header + separator + ≥1 data row
    ContentType.FIGURE: 30,     # Caption or detailed label
    ContentType.BITMAP: 30,     # Caption or technical label
    ContentType.DEFINITION: 8,  # Short terms like "CMD: Command" are valid
    ContentType.REGISTER: 40,   # Register name + base address/bit range
}

# Row-group chunks are intentionally small (header + separator + 1 key's rows).
# The absolute minimum is: one header cell + separator + one data cell ≈ 25 chars.
_MIN_RAW_CHARS_ROW_CHUNK = 25

# Patterns to detect pure continuation markers or watermark leftovers
_NOISE_PATTERNS = [
    re.compile(r"^(cont'd|continued|continued\s+on\s+next\s+page|to\s+be\s+continued)\.?$", re.IGNORECASE),
    re.compile(r"^(downloaded\s+by|ruyi|JEDEC\s+Standard).*$", re.IGNORECASE),
]

def _is_valid_chunk(chunk: EMMCChunk) -> bool:
    """Check if a chunk has meaningful content.

    Uses raw_text (content without the generated prefix) so the check is
    independent of prefix format and works correctly for all content types.

    Row-group TABLE chunks use a lower threshold than full-table chunks because
    they are intentionally small (one primary-key group + header ≈ 25–80 chars).
    """
    content = chunk.raw_text.strip()
    content_len = len(content)

    # Pick the applicable minimum length
    if chunk.is_row_chunk:
        min_chars = _MIN_RAW_CHARS_ROW_CHUNK
    else:
        min_chars = _MIN_RAW_CHARS_BY_TYPE.get(chunk.content_type, 30)

    if content_len < min_chars:
        return False

    # Filter out pure continuation markers or margin noise
    if any(p.match(content) for p in _NOISE_PATTERNS):
        return False

    return True



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

        searchable = self.searchable_chunks
        ctype_counts = Counter(c.content_type for c in searchable)

        front_matter_count = sum(1 for c in self.chunks if c.is_front_matter)
        short_filtered = sum(
            1 for c in self.chunks
            if not c.is_front_matter and not _is_valid_chunk(c)
        )

        return {
            "total": len(self.chunks),
            "searchable": len(searchable),
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
            page_toc_section = structure.page_to_section.get(page_num)

            # --- Page-level section boundary (TOC-based, coarse-grained) ---
            #
            # When the TOC assigns a different section to this page, flush any
            # accumulated text from the previous section and switch.  This is the
            # primary mechanism that ensures every page is attributed to the
            # correct section even when no heading text block is present.
            #
            # Sub-page detection (inside the block loop) provides finer-grained
            # updates within a page when multiple sections share the same page.
            if page_toc_section is not current_section:
                if text_accumulator:
                    _flush_text()
                current_section = page_toc_section

            # Text from all blocks on this page for nearby-text lookups
            page_raw_text = " ".join(tb.text for tb in page.text_blocks)

            # Classify all blocks on the page
            classified = self._classifier.classify_page(page, current_section)

            for cb in classified:
                # --- Step 1: sub-page section detection (fine-grained) ---
                #
                # Two matching strategies:
                # a) Exact match: block text == TOC label (standalone heading).
                # b) Prefix match: block text STARTS WITH a TOC label followed by
                #    a word boundary.  This handles the common case where PyMuPDF
                #    merges a section heading with its first paragraph into a single
                #    text block (e.g. "5.1 eMMC System Overview The eMMC spec...").
                if cb.text_block and cb.content_type == ContentType.TEXT:
                    norm = _normalize_label(cb.text_block.text)
                    hit_section = structure.label_to_section.get(norm)

                    # Prefix match fallback (only for blocks longer than any label)
                    if hit_section is None:
                        for label, candidate in structure.label_to_section.items():
                            # Require at least one extra character after label
                            if (
                                len(norm) > len(label)
                                and norm.startswith(label)
                                and norm[len(label)] in " \n\t"
                            ):
                                hit_section = candidate
                                break

                    if hit_section and hit_section is not current_section:
                        if text_accumulator:
                            _flush_text()
                        current_section = hit_section
                        accum_page_start = page_num
                        logger.debug("Switched section at p%d: %s", page_num, hit_section.label)

                # --- Step 2: collect text for definition Round-1 ---
                #
                # Done AFTER current_section is updated (both page-level and
                # sub-page-level) so text is always bucketed into the correct
                # section.
                if cb.text_block:
                    if current_section and not current_section.is_front_matter:
                        bucket = section_texts.setdefault(current_section.page_start, [])
                        bucket.append(cb.text_block.text)

                # --- Step 3: route block to the appropriate chunker ---

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
