import re
import fitz  # PyMuPDF
import pdfplumber
from typing import List, Optional, Tuple, Dict
from pydantic import BaseModel, Field

# ==========================================
# 1. Data Models (Pydantic)
# ==========================================

class PDFChunk(BaseModel):
    """
    Core Data Model for RAG
    Attributes:
        chunk_id: Unique identifier
        page_num: Physical page number
        content: The actual text/markdown content
        content_type: "text" | "table" | "image"
        caption: The bound caption (e.g., "Table 12: Device Status")
        image_path: Path to the saved image (if type=='image')
        metadata: Originalbbox, structural info, etc.
    """
    chunk_id: int
    page_num: int
    content: str
    content_type: str = Field(..., description="text | table | image")
    caption: str = Field(default="", description="Bound caption text")
    image_path: Optional[str] = None
    metadata: Dict = Field(default_factory=dict)

class ProcessingContext(BaseModel):
    """
    Context object to pass around during processing
    
    Why two page objects? (Hybrid Strategy)
    1. page_obj_plumber: Best for TABLE extraction. Its `find_tables()` and strict coordinate system are superior.
    2. page_obj_fitz: Best for IMAGE/TEXT extraction. It is 10x faster and handles image masks/cropping better.
    """
    page_num: int
    page_obj_plumber: object  # pdfplumber page
    page_obj_fitz: object     # fitz page
    ignore_bboxes: List[Tuple[float, float, float, float]] = [] # Areas to skip
    output_dir: str  # Output directory for saving images


# ==========================================
# 2. Processor Class
# ==========================================

class PDFProcessorV3:
    def __init__(self, file_path: str, output_dir: str, skip_pages: List[int] = None):
        self.file_path = file_path
        self.output_dir = output_dir
        self.skip_pages = skip_pages or []
        self.chunks: List[PDFChunk] = []
        
        # Buffer for cross-page text continuity
        # Why? A sentence might start on Page 1 and end on Page 2.
        # We hold the incomplete text here until we hit a "Stop Sequence" (like \n\n)
        self.text_buffer: str = ""

    def process(self):
        """
        Main Loop: Iterate through pages
        """
        # Step 1: Initialize PDF objects
        with pdfplumber.open(self.file_path) as plumber_pdf, fitz.open(self.file_path) as fitz_pdf:
            
            total_pages = len(plumber_pdf.pages)
            print(f"Processing {self.file_path} ({total_pages} pages)...")
            if self.skip_pages:
                print(f"Skipping {len(self.skip_pages)} pages: {sorted(self.skip_pages)}")

            for i, plumber_page in enumerate(plumber_pdf.pages):
                page_num = i + 1
                
                # Step 2: Skip specified pages
                if page_num in self.skip_pages:
                    continue
                
                fitz_page = fitz_pdf[i]

                # Step 3: Process the page (Context is passed in)
                # results will be appended to self.chunks AND self.text_buffer will be updated
                self._process_page(page_num, plumber_page, fitz_page)
                
                # Optional: Streaming Save (not strictly necessary for files < 100MB text)
                # If you really fear memory crash, you can append to a JSONL file here.
                # But keeping 10MB of text in memory is perfectly fine for modern machines.

        # Step 4: Flush remaining text buffer
        if self.text_buffer.strip():
            self._create_text_chunk(self.text_buffer, page_num=total_pages)

        # Step 5: Save All (Atomic Write is safer for JSON validity)
        self._save_to_json()

    def _process_page(self, page_num: int, plumber_page, fitz_page):
        """
        Coordinate-Based Exclusion Strategy & Text Buffering
        """
        # 1. Init Context
        context = ProcessingContext(
            page_num=page_num,
            page_obj_plumber=plumber_page,
            page_obj_fitz=fitz_page,
            ignore_bboxes=[],
            output_dir=self.output_dir
        )

        # 2. Extract Tables (High Priority)
        table_chunks = extract_tables_with_caption(context)
        self.chunks.extend(table_chunks)
        
        # 2.5. Extract Vector Figures (High Priority - BEFORE text extraction)
        # This prevents flow diagram text from being fragmented
        vector_figure_chunks = extract_vector_figures_with_caption(context)
        self.chunks.extend(vector_figure_chunks)
        
        # 3. Extract Raster Images (Medium Priority)
        image_chunks = extract_images_with_caption(context)
        self.chunks.extend(image_chunks)
        
        # 4. Extract Text (Low Priority but Contextual)
        # Instead of getting chunks directly, we get RAW TEXT excluding tables
        page_text = extract_raw_text_with_exclusion(context)
        
        # 5. Update Buffer & Smart Chunking
        # We append new text to buffer, then try to "peel off" complete paragraphs
        self.text_buffer += "\n" + page_text
        self._flush_buffer_to_chunks(page_num)
        
        # 6. Smart Buffer Flush at Page Boundary
        # Only flush if the text appears complete (not ending with a list item)
        # This preserves cross-page list continuity
        if self.text_buffer.strip():
            if not is_incomplete_list(self.text_buffer):
                self._create_text_chunk(self.text_buffer.strip(), page_num)
                self.text_buffer = ""  # Reset buffer for next page
            # Otherwise, keep buffer for next page to merge cross-page lists

    def _flush_buffer_to_chunks(self, current_page_num: int):
        """
        Split buffer by double-newline (\n\n). 
        Keep the last segment in buffer (it might be incomplete).
        Move the rest to self.chunks.
        """
        paragraphs = re.split(r'\n\s*\n', self.text_buffer)
        
        # The last paragraph is potentially incomplete (spanning to next page)
        # So we keep it in the buffer, UNLESS it ends with a clear stop (.!?)
        incomplete_segment = paragraphs.pop() 
        
        for p in paragraphs:
            if p.strip():
                self._create_text_chunk(p.strip(), current_page_num)
        
        self.text_buffer = incomplete_segment

    def _create_text_chunk(self, content, page_num):
        # Apply cleaning rules
        cleaned_content = self._clean_content(content)
        
        # Skip if empty after cleaning
        if not cleaned_content:
            return

        self.chunks.append(PDFChunk(
            chunk_id=len(self.chunks),
            page_num=page_num,
            content=cleaned_content,
            content_type="text"
        ))

    def _clean_content(self, text: str) -> str:
        """
        Apply user-defined cleaning rules:
        1. Remove Header/Footer patterns (e.g., "JEDEC Standard... Page X")
        2. Filter out short/invalid content
        """
        if not text:
            return ""
            
        # Rule 1: Skip block if it matches specific patterns ENTIRELY
        # - "Page \d+"
        # - "0\n(start)"
        # - "Page \d+ ..."
        stripped = text.strip()
        if re.match(r'^Page \d+$', stripped, re.IGNORECASE):
            return ""
        if "0\n(start)" in text or "0\\n(start)" in text: # Handle escaped or real newlines
            return ""
        if stripped == "Forward":
             return ""

        # Rule 3: Remove Header/Footer (JEDEC Standard No. 84-B51 \nPage \d+)
        # Pattern: JEDEC ... followed by Page number lines
        # We replace it with nothing
        # Modified to handle "Page \d+" appearing after JEDEC string more robustly
        text = re.sub(r'JEDEC Standard No\. 84-B51.*Page \d+', '', text, flags=re.DOTALL | re.IGNORECASE)
        # Also handle cases where they might be split or appear alone
        text = re.sub(r'JEDEC Standard No\. 84-B51', '', text, flags=re.IGNORECASE)
        
        # Start cleaning whitespace
        cleaned = text.strip()
        
        # Rule 2: Filter short/invalid content
        # - "Forward", "Page 1", "cont'd"
        lower_text = cleaned.lower()
        
        # Filter specific keywords/phrases
        if "cont'd" in lower_text:
             return ""
        
        # Filter very short content (1-2 words)
        words = cleaned.split()
        if len(words) <= 2:
            return ""
            
        return cleaned

    def _save_to_json(self):
        import json
        output_path = f"{self.output_dir}/clean_data.json"
        data = [chunk.model_dump() for chunk in self.chunks]
        with open(output_path, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"Saved {len(self.chunks)} chunks to {output_path}")


# ==========================================
# 3. Helper Functions (The "How-To")
# ==========================================

# --- 3.1 Table Processing ---

def extract_tables_with_caption(context: ProcessingContext) -> List[PDFChunk]:
    """
    1. plumber_page.find_tables()
    2. For each table:
       - Get bbox
       - Scan UPWARDS for Caption (find_caption_text)
       - Sanitize Header (sanitize_table_header)
       - Generate Content (generate_dynamic_table_chunk)
       - Add bbox to context.ignore_bboxes
    """
    chunks = []
    tables = context.page_obj_plumber.find_tables()
    
    for table_obj in tables:
        # Get table bbox
        bbox = table_obj.bbox  # (x0, top, x1, bottom)
        
        # Extract table data
        table_data = table_obj.extract()
        if not table_data or len(table_data) < 2:  # Need at least header + 1 row
            continue
            
        # Find caption (search upwards)
        caption = find_caption_text(context.page_obj_plumber, bbox, direction="up")
        
        # Sanitize header (Smart Merge)
        header_raw, table_rows = smart_header_merge(table_data)
        header = sanitize_table_header(header_raw)
        
        # Generate chunks for each row (Zipped Dict Strategy)
        row_chunks = generate_dynamic_table_chunk(header, table_rows)
        
        # Create PDFChunk for each row
        for i, row_content in enumerate(row_chunks):
            chunk = PDFChunk(
                chunk_id=0,  # Will be reassigned later
                page_num=context.page_num,
                content=row_content,
                content_type="table",
                caption=caption,
                metadata={"bbox": list(bbox), "row_index": i}
            )
            chunks.append(chunk)
        
        # Add bbox to ignore list
        context.ignore_bboxes.append(bbox)
    
    return chunks


def smart_header_merge(table_data: List[List[str]]) -> Tuple[List[str], List[List[str]]]:
    """
    Merge first two rows if they form a composite header (e.g. split headers).
    Returns (merged_header, remaining_rows)
    """
    if not table_data:
        return [], []
    if len(table_data) < 2:
        return table_data[0], []
        
    row0 = [str(cell or "").strip() for cell in table_data[0]]
    row1 = [str(cell or "").strip() for cell in table_data[1]]
    
    # If row lengths differ significantly, don't merge (safe guard)
    if len(row0) != len(row1):
        return row0, table_data[1:]
        
    # Count non-empty cells
    # count0 = sum(1 for c in row0 if c)
    # count1 = sum(1 for c in row1 if c)
    
    # Create merged header
    merged_header = []
    for c0, c1 in zip(row0, row1):
        if c0 and c1:
            merged_header.append(f"{c0} {c1}")
        elif c0:
            merged_header.append(c0)
        elif c1:
            merged_header.append(c1)
        else:
            merged_header.append("")
            
    count_merged = sum(1 for c in merged_header if c)
    
    # Heuristic: If merging results in more non-empty columns than row0 alone, use it.
    # In our specific case: Row0 has 1 col, Row1 has 5 cols. Merged has 6 cols.
    if count_merged > sum(1 for c in row0 if c):
        # Additional check: Row1 shouldn't look like data (e.g. starting with CMD25)
        # But for strictly header reconstruction, if it fills the gaps, it's likely a header part.
        return merged_header, table_data[2:]
        
    return row0, table_data[1:]

def sanitize_table_header(row: List[str]) -> List[str]:
    """
    Handle 'CMD\nIndex' -> 'CMD Index'
    """
    return [str(cell).replace("\n", " ").strip() if cell else "" for cell in row]

def generate_dynamic_table_chunk(header: List[str], rows: List[List[str]]) -> List[str]:
    """
    Zipped Dict Strategy with Smart Column Matching
    
    Problem: Complex PDFs may have misaligned headers/values due to merged cells.
    Example: header = ['', 'Name', '', '', 'Type', '', 'Desc', '']
             row    = ['CLK', None, None, 'I', None, 'Clock', None, None]
    
    Solution: For each non-empty header, find the nearest non-empty value in the row.
    """
    chunks = []
    
    # First, identify non-empty header positions
    header_positions = [(i, h.strip()) for i, h in enumerate(header) if h and h.strip()]
    
    if not header_positions:
        # Fallback: if no valid headers, skip this table
        return []
    
    for row in rows:
        chunk_content = ""
        
        for header_idx, header_name in header_positions:
            # Strategy: Look for non-empty value in a window around the header index
            # Priority: Exact match -> Right -> Left
            # This prevents stealing value from left column (e.g. Type taking CMD's value)
            value = None
            search_indices = [header_idx, header_idx + 1, header_idx - 1]
            
            for idx in search_indices:
                if 0 <= idx < len(row) and row[idx] and str(row[idx]).strip():
                    value = str(row[idx]).strip().replace("\n", " ")
                    break
            
            # Add to chunk if we found a value
            if value:
                chunk_content += f"**{header_name}**: {value}\n"
        
        if chunk_content.strip():
            chunks.append(chunk_content.strip())
    
    return chunks


# --- 3.2 Image Processing ---

def extract_images_with_caption(context: ProcessingContext) -> List[PDFChunk]:
    """
    Direct Image Extraction Strategy (No caption dependency)
    
    1. Use fitz_page.get_images() to find all images
    2. Get image bbox from page.get_image_bbox()
    3. Try to find caption nearby (optional)
    4. Save image to disk
    5. Add bbox to context.ignore_bboxes
    """
    chunks = []
    
    # Get all images on the page
    image_list = context.page_obj_fitz.get_images()
    
    for img_index, img in enumerate(image_list):
        xref = img[0]  # Image xref number
        
        # Get all locations where this image appears on the page
        img_rects = context.page_obj_fitz.get_image_rects(xref)
        
        for rect_index, rect in enumerate(img_rects):
            # Convert fitz.Rect to tuple (x0, y0, x1, y1)
            bbox = (rect.x0, rect.y0, rect.x1, rect.y1)
            
            # Filter 1: Ignore small images (likely icons or noise)
            width = rect.x1 - rect.x0
            height = rect.y1 - rect.y0
            if width < 50 or height < 50:
                continue
                
            # Filter 2: Ignore images inside already processed regions (Tables, Vector Figures)
            is_ignored = False
            for ignore_bbox in context.ignore_bboxes:
                if bboxes_overlap(bbox, ignore_bbox):
                    is_ignored = True
                    break
            if is_ignored:
                continue
            
            # Try to find caption below the image
            caption = find_caption_text(context.page_obj_plumber, bbox, direction="down", offset=30)
            
            # If no caption found, use a generic description
            if not caption:
                caption = f"Image on page {context.page_num}"
            
            # Save image to disk
            image_path = save_image(context.page_obj_fitz, xref, context.page_num, img_index, rect_index, output_root=context.output_dir)
            
            chunk = PDFChunk(
                chunk_id=0,
                page_num=context.page_num,
                content=f"[Image: {caption}]",
                content_type="image",
                caption=caption,
                image_path=image_path,
                metadata={"bbox": list(bbox), "xref": xref}
            )
            chunks.append(chunk)
            
            # Add bbox to ignore list
            context.ignore_bboxes.append(bbox)
    
    return chunks


def extract_vector_figures_with_caption(context: ProcessingContext) -> List[PDFChunk]:
    """
    Extract vector-based figures (flow diagrams, etc.) by detecting captions
    and rendering the figure region as an image.
    
    Strategy:
    1. Find "Figure X" captions in page text
    2. Estimate figure region (below caption)
    3. Render region as image using fitz.get_pixmap()
    4. Add to ignore_bboxes to prevent text extraction
    """
    chunks = []
    
    # 1. Extract all text to find captions
    text = context.page_obj_plumber.extract_text()
    if not text:
        return chunks
    
    # 2. Find all "Figure X" patterns
    import re
    caption_pattern = r'Figure \d+[^\n]*'
    captions = re.findall(caption_pattern, text)
    
    if not captions:
        return chunks
    
    # Get page dimensions
    page_height = context.page_obj_fitz.rect.height
    page_width = context.page_obj_fitz.rect.width
    
    # Deduplicate captions (e.g., "Figure 28 illustrates..." and "Figure 28 — ...")
    # Keep only the first occurrence of each figure number
    seen_figures = set()
    unique_captions = []
    for caption in captions:
        # Extract figure number
        match = re.match(r'Figure (\d+)', caption)
        if match:
            fig_num = match.group(1)
            if fig_num not in seen_figures:
                seen_figures.add(fig_num)
                unique_captions.append(caption)
    
    for caption in unique_captions:
        # Filter 1: Check for TOC pattern (e.g., "Figure 28 ... 45")
        # Match 3+ dots followed by optional whitespace and digits at the end
        if re.search(r'\.{3,}\s*\d+$', caption):
            continue
        
        # Filter 2: Skip intro text (e.g., "Figure 12 shows...")
        # We only want standard captions like "Figure 12 — Title"
        # Intro text usually contains verbs like "shows", "illustrates", "describes"
        if re.search(r'(shows|illustrates|describes|is used|define)', caption, re.IGNORECASE):
            continue
            
        # Filter 3: Require standard caption format with em-dash or colon
        # Standard format: "Figure X — Title" or "Figure X: Title"
        if not re.search(r'Figure \d+\s*[—:—-]', caption):
            continue
            
        # 3. Find caption bbox
        caption_bbox = find_text_bbox(context.page_obj_plumber, caption)
        if not caption_bbox:
            continue
        
        x0, y0, x1, y1 = caption_bbox
        
        # 4. Estimate figure region using vector drawings
        # Strategy:
        # - Get all vector drawings on the page
        # - Filter for drawings ABOVE the caption
        # - Calculate union bbox
        
        drawings = context.page_obj_fitz.get_drawings()
        
        # Collect rects of drawings that are strictly ABOVE the caption
        # We also want to respect a "search window" to avoid picking up header text/lines
        # Search window: Top of page (plus margin) to Top of Caption
        search_top = 50 
        search_bottom = y0 # Top of caption
        
        figure_rects = []
        for draw in drawings:
            r = draw["rect"] # fitz.Rect
            # Check if drawing is within vertical search window
            if r.y1 <= search_bottom and r.y0 >= search_top:
                # Also check horizontal margins? Or just take everything?
                # Let's take everything within page margins
                if r.x0 >= 20 and r.x1 <= page_width - 20:
                     figure_rects.append(r)
        
        if figure_rects:
            # Calculate union bbox
            min_x = min(r.x0 for r in figure_rects)
            min_y = min(r.y0 for r in figure_rects)
            max_x = max(r.x1 for r in figure_rects)
            max_y = max(r.y1 for r in figure_rects)
            
            # Add small padding
            figure_bbox = (
                max(0, min_x - 5),
                max(0, min_y - 5),
                min(page_width, max_x + 5),
                min(page_height, max_y + 5)
            )
        else:
            # Fallback if no drawings found (e.g., maybe it's just text or image not paths)
            # Use a conservative heuristic: 300pt above caption
            print(f"Warning: No vector drawings found for Figure '{caption}' on Page {context.page_num}. using heuristic.")
            figure_top = max(y1 - 300, 50)
            figure_bottom = y1
            figure_bbox = (50, figure_top, page_width - 50, figure_bottom)
        
        # 5. Render region as image
        try:
            import fitz
            clip_rect = fitz.Rect(figure_bbox)
            pix = context.page_obj_fitz.get_pixmap(clip=clip_rect, matrix=fitz.Matrix(2, 2))  # 2x resolution
            
            # Save pixmap
            image_path = save_pixmap(pix, context.page_num, caption, context.output_dir)
            
            # 6. Create chunk
            chunk = PDFChunk(
                chunk_id=0,
                page_num=context.page_num,
                content=f"[Figure: {caption}]",
                content_type="image",
                caption=caption,
                image_path=image_path,
                metadata={"bbox": list(figure_bbox), "type": "vector_figure"}
            )
            chunks.append(chunk)
            
            # 7. Add to ignore list
            context.ignore_bboxes.append(figure_bbox)
            
        except Exception as e:
            print(f"Warning: Failed to render figure '{caption}' on page {context.page_num}: {e}")
    
    return chunks


def find_text_bbox(plumber_page, text: str) -> Optional[Tuple[float, float, float, float]]:
    """
    Find the bounding box of a text string in the page.
    Returns (x0, top, x1, bottom) or None if not found.
    """
    words = plumber_page.extract_words()
    
    # Try to find the start of the text
    text_start = text.split()[0] if text.split() else text
    
    for word in words:
        if text.startswith(word['text']) or word['text'] in text[:20]:
            # Found the caption start, estimate full bbox
            # For simplicity, use the first word's bbox
            return (word['x0'], word['top'], word['x1'], word['bottom'])
    
    return None


def save_pixmap(pix, page_num: int, caption: str, output_root: str) -> str:
    """
    Save a fitz.Pixmap to disk.
    
    Args:
        pix: fitz.Pixmap object
        page_num: Page number
        caption: Figure caption (used for filename)
        output_root: Output directory root
    
    Returns:
        Relative path to saved image
    """
    import os
    
    # Create images directory
    output_dir = os.path.join(output_root, "images")
    os.makedirs(output_dir, exist_ok=True)
    
    # Generate filename (sanitize caption for filename)
    safe_caption = "".join(c if c.isalnum() or c in (' ', '_') else '_' for c in caption)
    safe_caption = safe_caption.replace(' ', '_')[:50]  # Limit length
    filename = f"page{page_num}_figure_{safe_caption}.png"
    filepath = os.path.join(output_dir, filename)
    
    # Save pixmap
    pix.save(filepath)
    
    # Return relative path
    return f"./images/{filename}"


# --- 3.3 Text Processing ---

def extract_raw_text_with_exclusion(context: ProcessingContext) -> str:
    """
    1. fitz_page.get_text("blocks")
    2. Filter blocks:
       if is_inside_bbox(block_rect, context.ignore_bboxes):
           continue
    3. Return RAW text (no smart chunking yet - that happens in _process_page buffer)
    """
    blocks = context.page_obj_fitz.get_text("blocks")
    clean_text = []
    
    for block in blocks:
        # Block structure: (x0, y0, x1, y1, text, block_no, block_type)
        x0, y0, x1, y1, text, block_no, block_type = block
        
        # Skip image blocks
        if block_type != 0:
            continue
            
        # Check if block overlaps with any ignored area
        # Use bbox overlap instead of center-point check to catch all text in figures
        block_bbox = (x0, y0, x1, y1)
        is_ignored = False
        for ignore_bbox in context.ignore_bboxes:
            if bboxes_overlap(block_bbox, ignore_bbox):
                is_ignored = True
                break
        
        if not is_ignored and text.strip():
            clean_text.append(text.strip())
    
    
    # Coarse-grained list merging: merge entire bulleted lists into single chunks
    # Strategy: detect list blocks and their context to merge complete list structures
    merged_text = []
    i = 0
    
    def is_list_block(text):
        """Check if block contains list items with sub-items"""
        return '\no ' in text or text.strip().startswith('o ')
    
    def is_list_context(text):
        """Check if block looks like a list item (short, no ending punctuation)"""
        stripped = text.strip()
        if not stripped or len(stripped) > 150:
            return False
        # Check if it's a short line that could be a list item
        lines = stripped.split('\n')
        if len(lines) > 3:  # Too many lines, probably not a list item
            return False
        # Check if ends with typical list item patterns (no period, or ends with specific keywords)
        last_line = lines[-1].strip()
        if last_line.endswith(('.', '!', '?')):
            return False
        return True
    
    while i < len(clean_text):
        text = clean_text[i]
        
        if is_list_block(text):
            # This is a list block with sub-items, start collecting the entire list
            list_group = [text]
            i += 1
            
            # Keep collecting blocks that are part of the same list structure
            while i < len(clean_text):
                next_text = clean_text[i]
                
                # Include if it's a list block OR if it looks like a list item in context
                if is_list_block(next_text) or is_list_context(next_text):
                    list_group.append(next_text)
                    i += 1
                else:
                    break
            
            # Merge all list blocks with single newline
            if merged_text:
                merged_text.append('\n\n')
            merged_text.append('\n'.join(list_group))
        else:
            # Regular paragraph
            if merged_text:
                merged_text.append('\n\n')
            merged_text.append(text)
            i += 1
    
    return ''.join(merged_text)


# --- 3.4 Utilities ---

def find_caption_text(page, ref_bbox, direction="up", offset=50) -> str:
    """
    Crop area above/below ref_bbox and extract text
    """
    x0, top, x1, bottom = ref_bbox
    
    if direction == "up":
        # Search above the table
        search_rect = (x0, max(0, top - offset), x1, top)
    else:
        # Search below (for figures)
        search_rect = (x0, bottom, x1, min(page.height, bottom + offset))
    
    try:
        # Crop the search area and extract text
        cropped = page.crop(search_rect)
        text = cropped.extract_text()
        
        if not text:
            return ""
        
        # Look for "Table X:" or "Figure X:" patterns
        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            if direction == "up" and re.match(r'^Table\s+\d+', line):
                return line
            elif direction == "down" and re.match(r'^Figure\s+\d+', line):
                return line
    except Exception as e:
        pass
    
    return ""

def is_incomplete_list(text: str) -> bool:
    """
    检查文本是否以未完成的列表项结尾
    
    用于判断是否应该保留 buffer 等待下一页的内容
    
    Returns:
        True if text ends with a list item (likely continues on next page)
        False if text appears complete
    """
    # Fix: Empty text should not block flush
    if not text or not text.strip():
        return False
    
    lines = text.strip().split('\n')
    if not lines:
        return False
    
    last_line = lines[-1].strip()
    
    # 检查是否以列表标记开头
    list_markers = [
        r'^○',      # Circle bullet
        r'^•',      # Bullet
        r'^-\s',    # Dash with space
        r'^\d+\.', # Numbered list (1., 2., etc.)
        r'^o\s',    # Lowercase o with space
    ]
    
    for marker in list_markers:
        if re.match(marker, last_line):
            return True
    
    # 检查是否以完整句子结尾
    if last_line.endswith(('.', '!', '?')):
        return False
    
    # 如果最后一行很短且没有标点，可能是列表项
    if len(last_line) < 100 and not last_line.endswith((',', ';', ':')):
        return True
    
    return False

def save_image(fitz_page, xref: int, page_num: int, img_index: int, rect_index: int, output_root: str) -> str:
    """
    Extract and save image from PDF
    
    Args:
        fitz_page: PyMuPDF page object
        xref: Image xref number
        page_num: Page number
        img_index: Image index on the page
        rect_index: Rectangle index (if image appears multiple times)
    
    Returns:
        Relative path to saved image
    """
    import os
    
    # Get the PDF document from the page
    doc = fitz_page.parent
    
    # Extract image data
    base_image = doc.extract_image(xref)
    image_bytes = base_image["image"]
    image_ext = base_image["ext"]  # png, jpeg, etc.
    
    # Create images directory using the provided output_root
    output_dir = os.path.join(output_root, "images")
    os.makedirs(output_dir, exist_ok=True)
    
    # Generate filename
    filename = f"page{page_num}_img{img_index}_rect{rect_index}.{image_ext}"
    filepath = os.path.join(output_dir, filename)
    
    # Save image
    with open(filepath, "wb") as f:
        f.write(image_bytes)
    
    # Return relative path
    return f"./images/{filename}"


def is_in_bbox(point: Tuple[float, float], bbox: Tuple[float, float, float, float]) -> bool:
    """
    Check if a point (center of text block) is inside any ignored area
    bbox format: (x0, top, x1, bottom)
    """
    x, y = point
    x0, top, x1, bottom = bbox
    return (x0 <= x <= x1) and (top <= y <= bottom)


def bboxes_overlap(bbox1: Tuple[float, float, float, float], bbox2: Tuple[float, float, float, float]) -> bool:
    """
    Check if two bounding boxes overlap.
    bbox format: (x0, y0, x1, y1)
    """
    x0_1, y0_1, x1_1, y1_1 = bbox1
    x0_2, y0_2, x1_2, y1_2 = bbox2
    
    # No overlap if one bbox is completely to the left/right/above/below the other
    if x1_1 < x0_2 or x1_2 < x0_1:  # Horizontally separated
        return False
    if y1_1 < y0_2 or y1_2 < y0_1:  # Vertically separated
        return False
    
    return True

# ==========================================
# 4. Entry Point
# ==========================================

def main():
    import os
    
    # Example usage
    pdf_path = "./docs/emmc5.1-protocol-JESD84-B51.pdf"
    output_dir = "./output"
    
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Define pages to skip (e.g., Intro, TOC)
    # User Request: Skip pages 1-19
    skip_pages = list(range(1, 20))
    
    # Process the PDF
    processor = PDFProcessorV3(pdf_path, output_dir, skip_pages=skip_pages)
    processor.process()
    
    print(f"Processing complete! Generated {len(processor.chunks)} chunks.")

if __name__ == "__main__":
    main()
