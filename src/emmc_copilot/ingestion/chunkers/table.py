"""TableChunker: pdfplumber table → Markdown → EMMCChunk."""

from __future__ import annotations

import re

from ..parser import TableBlock
from ..schema import ContentType, EMMCChunk
from ..structure import SectionNode


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Maximum Markdown length before splitting a large table into sub-chunks.
# ~1500 tokens × 4 chars/token = 6000 chars.
_MAX_TABLE_CHARS = 6_000

# Pattern to find table captions like "Table 49 —" near a table
_TABLE_CAPTION_RE = re.compile(
    r"Table\s+\d+[\s\u2014\-]+[^\n]{5,80}", re.IGNORECASE
)

# A note row starts with "NOTE" (optionally followed by a number or space)
_NOTE_ROW_RE = re.compile(r"^NOTE\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Pre-processing helpers
# ---------------------------------------------------------------------------

def _cell(value: str | None) -> str:
    """Normalise a table cell value: collapse whitespace, strip."""
    if value is None:
        return ""
    # pdfplumber uses "\n" for in-cell line breaks; replace with a space
    return " ".join(value.split())


def _find_data_start(rows: list[list[str | None]], col_count: int) -> int:
    """Return the index of the first 'complete data row'.

    A complete data row satisfies both:
      - Column 0 is non-empty
      - At least ⌈col_count / 2⌉ cells are non-empty

    Everything before this index constitutes the *header zone* — rows that
    pdfplumber has split from multi-line header cells.

    If no such row is found, returns 1 (treat only the first row as header).
    """
    min_filled = max(1, (col_count + 1) // 2)
    for i, row in enumerate(rows):
        col0 = _cell(row[0] if row else None)
        non_empty = sum(1 for c in row if _cell(c))
        if col0 and non_empty >= min_filled:
            return i
    return 1


def _merge_header_zone(
    header_rows: list[list[str | None]], col_count: int
) -> list[str]:
    """Collapse multi-row header fragments into a single header row.

    pdfplumber emits a cell like "CMD\\nINDEX" as two separate rows:
      Row 0: ['CMD',   '',    '',          '',     '',              ''              ]
      Row 1: [None,    'Type','Argument',  'Resp', 'Abbreviation',  'Command Desc.' ]
      Row 2: ['INDEX', None,  None,        None,   None,            None            ]

    This function merges them into:
      ['CMD INDEX', 'Type', 'Argument', 'Resp', 'Abbreviation', 'Command Description']

    Strategy: for each column, concatenate non-empty values from all header
    rows (joined by a space).
    """
    buckets: list[list[str]] = [[] for _ in range(col_count)]

    for row in header_rows:
        padded = list(row) + [None] * (col_count - len(row))
        for col_idx, cell in enumerate(padded[:col_count]):
            text = _cell(cell)
            if text:
                buckets[col_idx].append(text)

    return [" ".join(parts) if parts else "" for parts in buckets]


def _extract_notes(
    data_rows: list[list[str]],
) -> tuple[list[list[str]], str]:
    """Separate NOTE rows from the bottom of the table body.

    A row is treated as a note row when:
      - Only the first cell contains text (the rest are empty), AND
      - That first cell begins with "NOTE" (case-insensitive).

    Note rows are consumed from the bottom upward so that multi-row note
    blocks are all captured.

    Returns:
        (body_rows, notes_text)   where notes_text may be empty.
    """
    note_texts: list[str] = []
    cutoff = len(data_rows)

    for i in range(len(data_rows) - 1, -1, -1):
        row = data_rows[i]
        first = row[0] if row else ""
        rest_empty = all(not c for c in row[1:])
        if first and rest_empty and _NOTE_ROW_RE.match(first):
            # pdfplumber collapses multi-note cells with "\n"; after _cell()
            # those become spaces.  Restore line breaks between numbered notes
            # so each "NOTE N …" appears on its own line.
            restored = re.sub(r" (NOTE \d)", r"\n\1", first, flags=re.IGNORECASE)
            note_texts.append(restored)
            cutoff = i
        else:
            break  # stop at the first non-note row from the bottom

    # Restore reading order (we scanned bottom-up)
    notes_text = "\n".join(reversed(note_texts))
    return data_rows[:cutoff], notes_text


def _forward_fill_key(body: list[list[str]]) -> list[list[str]]:
    """Repeat the primary-key value (col 0) into continuation rows.

    pdfplumber represents vertically-merged cells by leaving col 0 empty in
    sub-rows.  For example, CMD0 spans three rows but only the first carries
    'CMD0' in col 0; the others have an empty string.

    Filling forward makes every row self-contained, which is essential for
    RAG retrieval: a retrieved sub-row must still carry its CMD identifier.
    Only col 0 is filled; other columns are left as-is.
    """
    result = [row[:] for row in body]
    last_key = ""
    for row in result:
        if row:
            if row[0]:
                last_key = row[0]
            elif last_key:
                row[0] = last_key
    return result


def _preprocess_table(
    raw_rows: list[list[str | None]],
) -> tuple[list[str], list[list[str]], str]:
    """Full pre-processing pipeline for raw pdfplumber rows.

    Returns:
        header   – single merged header row (list of cell strings)
        body     – data rows, each a list of cell strings; notes removed,
                   primary key forward-filled into continuation rows
        notes    – extracted notes text (empty string if none)
    """
    if not raw_rows:
        return [], [], ""

    col_count = max(len(r) for r in raw_rows)

    # 1. Find where the header zone ends
    data_start = _find_data_start(raw_rows, col_count)

    # 2. Merge multi-line header fragments
    header = _merge_header_zone(raw_rows[:data_start], col_count)

    # 3. Clean + pad data rows
    cleaned_body: list[list[str]] = []
    for row in raw_rows[data_start:]:
        cleaned = [_cell(c) for c in row]
        cleaned += [""] * (col_count - len(cleaned))
        cleaned_body.append(cleaned)

    # 4. Separate NOTE rows from the bottom
    body, notes = _extract_notes(cleaned_body)

    # 5. Forward-fill the primary key so every row is self-contained
    body = _forward_fill_key(body)

    return header, body, notes


# ---------------------------------------------------------------------------
# Markdown serialisation
# ---------------------------------------------------------------------------

def _rows_to_markdown(raw_rows: list[list[str | None]]) -> str:
    """Convert raw pdfplumber rows to a well-formed Markdown table.

    Enhancements over a naïve row-by-row conversion:
    - Multi-line header cells are merged into a single header row.
    - NOTE rows at the bottom are moved to a dedicated **Notes:** section.
    """
    header, body, notes = _preprocess_table(raw_rows)
    if not header:
        return ""

    separator = ["-" * max(len(h), 3) for h in header]

    def _row_str(cells: list[str]) -> str:
        return "| " + " | ".join(cells) + " |"

    lines = [_row_str(header), _row_str(separator)]
    lines += [_row_str(row) for row in body]

    md = "\n".join(lines)
    if notes:
        md += f"\n\n**Notes:**\n{notes}"
    return md


def _find_caption(nearby_text: str) -> str:
    """Extract a table caption from nearby text blocks."""
    m = _TABLE_CAPTION_RE.search(nearby_text)
    return m.group(0).strip() if m else ""


def _make_prefix(
    version: str,
    section: SectionNode | None,
    page: int,
    caption: str,
) -> str:
    label = section.label if section else "(front matter)"
    lines = [f"[eMMC {version} | {label} | Page {page}]"]
    if caption:
        lines.append(caption)
    lines.append("")   # blank line before table
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# TableChunker
# ---------------------------------------------------------------------------

class TableChunker:
    """Convert pdfplumber TableBlocks into EMMCChunks.

    Two public methods:

    chunk()
        Returns full-table (or large-table-split) chunks.  These preserve the
        complete table for LLM context display.  They are *not* embedded in the
        vector store directly — row-group chunks serve that role.

    chunk_row_groups()
        Returns one small chunk per primary-key group (e.g. one chunk per CMD
        index).  Each chunk contains only the merged header + the rows belonging
        to that key, so the embedding is dense and precise for retrieval.
        Every row-group chunk carries parent_chunk_id referencing the
        corresponding full-table chunk from chunk().
    """

    def chunk(
        self,
        table: TableBlock,
        nearby_text: str,       # text from same page (used for caption lookup)
        source: str,
        version: str,
        section: SectionNode | None,
        page_start: int,
        page_end: int,
    ) -> list[EMMCChunk]:
        if not table.rows:
            return []

        caption = _find_caption(nearby_text)
        prefix = _make_prefix(version, section, page_start, caption)
        markdown = _rows_to_markdown(table.rows)

        if not markdown.strip():
            return []

        is_front_matter = section.is_front_matter if section else True

        # Small enough table → single chunk
        if len(prefix) + len(markdown) <= _MAX_TABLE_CHARS:
            return [self._make_chunk(
                prefix=prefix,
                markdown=markdown,
                caption=caption,
                source=source,
                version=version,
                section=section,
                page_start=page_start,
                page_end=page_end,
                chunk_index=0,
                is_front_matter=is_front_matter,
            )]

        # Large table → split by row groups, re-prepend header on each chunk
        return self._split_large_table(
            table=table,
            prefix_template=prefix,
            caption=caption,
            source=source,
            version=version,
            section=section,
            page_start=page_start,
            page_end=page_end,
            is_front_matter=is_front_matter,
        )

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    @staticmethod
    def _make_chunk(
        prefix: str,
        markdown: str,
        caption: str,
        source: str,
        version: str,
        section: SectionNode | None,
        page_start: int,
        page_end: int,
        chunk_index: int,
        is_front_matter: bool,
    ) -> EMMCChunk:
        return EMMCChunk(
            source=source,
            version=version,
            page_start=page_start,
            page_end=page_end,
            section_path=section.path if section else [],
            section_title=section.title if section else "",
            heading_level=section.level if section else 0,
            content_type=ContentType.TABLE,
            is_front_matter=is_front_matter,
            chunk_index=chunk_index,
            text=prefix + markdown,
            raw_text=markdown,
            table_markdown=markdown,
            figure_caption=caption or None,
        )

    def _split_large_table(
        self,
        table: TableBlock,
        prefix_template: str,
        caption: str,
        source: str,
        version: str,
        section: SectionNode | None,
        page_start: int,
        page_end: int,
        is_front_matter: bool,
    ) -> list[EMMCChunk]:
        """Split a large table into row-group chunks.

        Each chunk reuses the merged header row.  Notes (if any) are appended
        only to the last chunk, which is where they appear in the PDF.
        """
        # Pre-process once so all chunks share the same merged header / notes
        header, body, notes = _preprocess_table(table.rows)
        if not header:
            return []

        col_count = len(header)
        header_md = "| " + " | ".join(header) + " |\n"
        separator_md = "| " + " | ".join("-" * max(len(h), 3) for h in header) + " |\n"

        def _body_md(rows: list[list[str]]) -> str:
            return "".join(
                "| " + " | ".join(r[:col_count] + [""] * (col_count - len(r))) + " |\n"
                for r in rows
            )

        chunks: list[EMMCChunk] = []
        current_body: list[list[str]] = []

        for data_row in body:
            current_body.append(data_row)
            trial = header_md + separator_md + _body_md(current_body)
            if len(prefix_template) + len(trial) > _MAX_TABLE_CHARS and len(current_body) > 1:
                # Flush all but the last row
                flush = current_body[:-1]
                md = (header_md + separator_md + _body_md(flush)).rstrip("\n")
                chunks.append(self._make_chunk(
                    prefix=prefix_template,
                    markdown=md,
                    caption=caption,
                    source=source,
                    version=version,
                    section=section,
                    page_start=page_start,
                    page_end=page_end,
                    chunk_index=len(chunks),
                    is_front_matter=is_front_matter,
                ))
                current_body = [data_row]

        # Final chunk (append notes here)
        if current_body:
            md = (header_md + separator_md + _body_md(current_body)).rstrip("\n")
            if notes:
                md += f"\n\n**Notes:**\n{notes}"
            chunks.append(self._make_chunk(
                prefix=prefix_template,
                markdown=md,
                caption=caption,
                source=source,
                version=version,
                section=section,
                page_start=page_start,
                page_end=page_end,
                chunk_index=len(chunks),
                is_front_matter=is_front_matter,
            ))

        return chunks

    # ------------------------------------------------------------------
    # Row-group chunking (for high-precision vector retrieval)
    # ------------------------------------------------------------------

    def chunk_row_groups(
        self,
        table: "TableBlock",
        nearby_text: str,
        source: str,
        version: str,
        section: "SectionNode | None",
        page_start: int,
        page_end: int,
        parent_chunk_id: str,
    ) -> list[EMMCChunk]:
        """Return one small chunk per primary-key group in the table.

        Each row-group chunk contains only the merged header row + the subset
        of body rows that share the same col-0 value (after forward-fill).
        This makes the embedding dense and specific, eliminating the dilution
        that occurs when an entire table is encoded as a single vector.

        All returned chunks carry parent_chunk_id so the retriever can
        expand to the full table context when needed.

        Tables whose primary key is empty throughout (e.g. state-transition
        matrices without a CMD column) are treated as a single group.
        """
        if not table.rows:
            return []

        header, body, notes = _preprocess_table(table.rows)
        if not header or not body:
            return []

        caption = _find_caption(nearby_text)
        prefix = _make_prefix(version, section, page_start, caption)
        is_front_matter = section.is_front_matter if section else True
        col_count = len(header)
        
        # P1 Fix: Detect if this is a register map table to avoid fragmentation loss.
        # Usually col 0 is "Bit" or "Index".
        is_reg_table = any(kw in header[0].lower() for kw in ("bit", "index", "byte", "offset"))
        reg_context = ""
        if is_reg_table:
            reg_name = caption or (section.title if section else "Register")
            reg_context = f"**Register Context: {reg_name}**\n\n"

        header_md = "| " + " | ".join(header) + " |\n"
        separator_md = "| " + " | ".join("-" * max(len(h), 3) for h in header) + " |\n"

        def _row_md(row: list[str]) -> str:
            padded = row[:col_count] + [""] * (col_count - len(row))
            return "| " + " | ".join(padded) + " |\n"

        # Group rows by primary key (col 0)
        groups: dict[str, list[list[str]]] = {}
        order: list[str] = []  # preserve insertion order
        for row in body:
            key = row[0] if row else ""
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(row)

        row_chunks: list[EMMCChunk] = []
        for group_idx, key in enumerate(order):
            group_rows = groups[key]
            # Prepend context for register bits so the embedding knows WHICH register this bit belongs to
            md = reg_context + (header_md + separator_md + "".join(_row_md(r) for r in group_rows)).rstrip("\n")

            # Append notes only to the last group (same position as in the PDF)
            if group_idx == len(order) - 1 and notes:
                md += f"\n\n**Notes:**\n{notes}"

            chunk = EMMCChunk(
                source=source,
                version=version,
                page_start=page_start,
                page_end=page_end,
                section_path=section.path if section else [],
                section_title=section.title if section else "",
                heading_level=section.level if section else 0,
                content_type=ContentType.TABLE,
                is_front_matter=is_front_matter,
                chunk_index=group_idx,
                text=prefix + md,
                raw_text=md,
                table_markdown=md,
                figure_caption=caption or None,
                parent_chunk_id=parent_chunk_id,
                is_row_chunk=True,
            )
            row_chunks.append(chunk)

        return row_chunks
