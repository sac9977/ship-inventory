"""
Ship Inventory PDF Parser
Extracts spare parts lists from machinery PDF documents.
Handles standard fonts via pdfplumber, CID-encoded fonts via PyMuPDF fallback.
"""
import re
import os
import pdfplumber


HEADER_PATTERNS = {
    'part_number': re.compile(
        r'(part\s*(no|num|number|code)|drawing\s*no|item\s*no|ref\s*no|serial\s*no|'
        r'model\s*no|article\s*no|catalog\s*no|p/?n|prod(?:uct)?\s*no|material\s*no|'
        r'dwg\s*no|part\s*id|code|identifier|stock\s*no|sap\s*no)',
        re.IGNORECASE
    ),
    'description': re.compile(
        r'(description|name|part\s*name|item|component|detail|specification|spec|'
        r'denomination|particulars|designation|remarks|note|comment)',
        re.IGNORECASE
    ),
    'quantity': re.compile(
        r'(qty|quantity|pieces|pcs|nos|no\.?\s*of|amount|per\s*set|per\s*unit|'
        r'per\s*vessel|total\s*qty|required|on\s*board)',
        re.IGNORECASE
    ),
    'unit': re.compile(
        r'(unit|u/?m|measure|uom|each|set|kit|pair)',
        re.IGNORECASE
    ),
    'min_stock': re.compile(
        r'(min|minimum|reorder|safety|par\s*level|stock\s*level|replenish|'
        r'min(?:imum)?\s*(?:stock|qty|quantity)|par\s*stock)',
        re.IGNORECASE
    ),
}

SKIP_PATTERNS = re.compile(
    r'(page\s*\d|total\s*items|continued|next\s*page|spare\s*parts\s*list|'
    r'index|contents|table\s*of|revision|rev\.|date\s*:|sheet\s*\d|'
    r'figure\s*\d|drawing\s*\d|subject\s*:|approved|checked|drawn|'
    r'company|vessel|ship|project|document\s*no|doc\s*no|rev\s*|'
    r'confidential|proprietary|all\s*rights)',
    re.IGNORECASE
)


def parse_pdf(file_path):
    """
    Parse a spare parts PDF and extract structured data.
    Returns a dict with 'machinery_name', 'parts' list, and 'raw_text_preview'.
    """
    # Try pdfplumber first (works for standard fonts)
    parts, full_text = _parse_with_pdfplumber(file_path)

    # Fallback: try PyMuPDF for CID-encoded fonts
    if not parts:
        parts, pymupdf_text = _parse_with_pymupdf(file_path)
        if pymupdf_text:
            full_text = pymupdf_text

    machinery_name = _extract_machinery_name(full_text) if full_text else 'UNKNOWN MACHINERY'
    parts = _deduplicate(parts)

    return {
        'machinery_name': machinery_name,
        'parts': parts,
        'raw_text_preview': (full_text or '')[:3000],
    }


def _parse_with_pdfplumber(file_path):
    """Try parsing with pdfplumber (standard fonts)."""
    full_text = ''
    all_tables = []
    has_cid = False

    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ''
            full_text += text + '\n'
            # Check for CID-encoded text
            if '(cid:' in text:
                has_cid = True
            tables = _extract_tables(page)
            if tables:
                all_tables.extend(tables)

    # If CID text detected, skip pdfplumber results (they'll be garbage)
    if has_cid:
        return [], full_text

    parts = _extract_from_tables(all_tables)
    if not parts:
        parts = _extract_from_text(full_text)

    return parts, full_text


def _parse_with_pymupdf(file_path):
    """Fallback: try PyMuPDF for CID-encoded fonts."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return [], ''

    full_text = ''
    all_parts = []
    has_cid = False

    doc = fitz.open(file_path)
    for page_num, page in enumerate(doc):
        blocks = page.get_text('dict')['blocks']
        page_lines = []

        for b in blocks:
            if 'lines' not in b:
                continue
            for line in b['lines']:
                for span in line['spans']:
                    t = span['text'].strip()
                    if not t:
                        continue
                    # Check for CID-encoded text (control characters)
                    has_ctrl = any(ord(c) < 0x20 for c in t)
                    if has_ctrl:
                        has_cid = True
                    page_lines.append(t)

        page_text = '\n'.join(page_lines)
        full_text += page_text + '\n'

        # Extract parts using CID-aware parser
        parts = _extract_from_cid_spans(page)
        all_parts.extend(parts)

    doc.close()

    # Only return CID-decoded parts if we actually found CID text
    if has_cid:
        return all_parts, full_text
    return [], full_text


def _extract_from_cid_spans(page):
    """Extract parts from page spans, handling CID-encoded item numbers."""
    parts = []
    blocks = page.get_text('dict')['blocks']

    # Collect all spans with position info
    spans = []
    for b in blocks:
        if 'lines' not in b:
            continue
        for line in b['lines']:
            for span in line['spans']:
                t = span['text'].strip()
                if t:
                    spans.append({
                        'text': t,
                        'bbox': span['bbox'],
                        'font': span['font'],
                        'has_ctrl': any(ord(c) < 0x20 for c in t),
                    })

    # Group spans by vertical position (same line)
    lines_by_y = {}
    for s in spans:
        y = round(s['bbox'][1], 0)
        if y not in lines_by_y:
            lines_by_y[y] = []
        lines_by_y[y].append(s)

    # Process each line
    for y in sorted(lines_by_y.keys()):
        line_spans = sorted(lines_by_y[y], key=lambda s: s['bbox'][0])

        # Decode item numbers from control characters
        item_no = ''
        desc_parts = []

        for s in line_spans:
            text = s['text']
            if s['has_ctrl']:
                decoded = _decode_cid_digits(text)
                if decoded and re.match(r'^\d{3}$', decoded):
                    item_no = decoded
                elif decoded:
                    desc_parts.append(decoded)
            else:
                # Regular text - could be description
                if not re.match(r'^(SPARE|PARTS|CROSS|HEAD|PLATE|ITEM|DESIGNATION)', text, re.IGNORECASE):
                    desc_parts.append(text)

        desc = ' '.join(desc_parts).strip()

        # Skip header/footer lines
        if not item_no and not desc:
            continue
        if SKIP_PATTERNS.search(desc):
            continue
        if desc and re.match(r'^(SPARE|PARTS|CROSS|HEAD|PLATE|ITEM|DESIGNATION)', desc, re.IGNORECASE):
            continue

        # Skip noise: dates, document numbers, page refs, pure numbers
        if re.match(r'^\d{4}[-/]\d{2}[-/]\d{2}', desc):  # dates
            continue
        if re.match(r'^\d[\d\-]{6,}$', desc):  # document/part numbers without description
            continue
        if re.match(r'^\d+\s*\(\d+\)$', desc):  # page refs like "2 (2)"
            continue
        if re.match(r'^[\d\s\-\.]+$', desc):  # pure numbers/spaces
            continue
        if len(desc) > 5 and not item_no and re.match(r'^[A-Z][\d\s\-]{4,}$', desc):
            # Looks like a document code, not a description
            continue
        # Skip CID-garbled headers (all uppercase, short, no spaces between words)
        if not item_no and len(desc) < 25 and ' ' not in desc and desc == desc.upper():
            continue

        # Must have at least an item number or a meaningful description
        if item_no or (desc and len(desc) > 3):
            parts.append({
                'part_number': item_no,
                'description': desc,
                'quantity': 0,
                'unit': 'pcs',
                'min_stock': 0,
            })

    return parts


def _decode_cid_digits(text):
    """Convert CID control characters to readable digits/text."""
    result = []
    for ch in text:
        code = ord(ch)
        # CID digit range: 0x12-0x1B (18-27) maps to 0-9
        if 0x12 <= code <= 0x1B:
            result.append(str(code - 18))
        # Space (0x02) maps to space
        elif code == 0x02:
            result.append(' ')
        # Regular printable ASCII (but not control chars)
        elif 0x20 <= code <= 0x7E:
            result.append(ch)
        # Skip other control chars (like 0x03, 0x0F etc.)
        else:
            continue

    decoded = ''.join(result).strip()
    return decoded if decoded else None


def _extract_tables(page):
    """Try multiple table extraction strategies."""
    strategies = [
        {"vertical_strategy": "text", "horizontal_strategy": "text",
         "snap_tolerance": 5, "join_tolerance": 5, "edge_min_length": 10},
        {"vertical_strategy": "lines", "horizontal_strategy": "lines",
         "snap_tolerance": 5, "join_tolerance": 5, "edge_min_length": 10},
        {"vertical_strategy": "text", "horizontal_strategy": "text",
         "snap_tolerance": 10, "join_tolerance": 10, "edge_min_length": 5},
    ]
    for strat in strategies:
        try:
            tables = page.extract_tables(strat)
            if tables and any(t and len(t) >= 2 for t in tables):
                return tables
        except Exception:
            continue
    return []


def _extract_machinery_name(text):
    """Try to identify the machinery name from PDF text."""
    lines = text.strip().split('\n')
    for line in lines[:20]:
        line = line.strip()
        if not line or len(line) < 3:
            continue
        if re.search(r'spare\s*parts?\s*list', line, re.IGNORECASE):
            name = re.split(r'\s*[-–—:]\s*.*spare\s*parts', line, flags=re.IGNORECASE)[0]
            name = re.split(r'\s+spare\s*parts', line, flags=re.IGNORECASE)[0]
            name = name.strip()
            if name and len(name) > 2:
                return name.upper()
        match = re.search(r'parts?\s*list\s*(for|of)\s+(.+)', line, re.IGNORECASE)
        if match:
            return match.group(2).strip().upper()
        match = re.search(r'(.+?)\s*[-–—]\s*(?:parts?\s*(?:list|catalog|schedule))', line, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            if len(name) > 2:
                return name.upper()
    for line in lines[:8]:
        line = line.strip()
        if line and len(line) > 3 and not re.match(r'^(page|date|rev|sheet|doc)', line, re.IGNORECASE):
            name = re.sub(r'[^\w\s\-/]', '', line).strip()
            if len(name) > 3:
                return name.upper()
    return 'UNKNOWN MACHINERY'


def _extract_from_tables(tables):
    """Extract parts from PDF tables with flexible header detection."""
    parts = []
    for table in tables:
        if not table or len(table) < 2:
            continue
        found_header = False
        header_map = {}
        table_start = 0
        for i, row in enumerate(table):
            if not row:
                continue
            row_text = ' '.join(str(cell or '') for cell in row).lower()
            has_part = bool(HEADER_PATTERNS['part_number'].search(row_text))
            has_desc = bool(HEADER_PATTERNS['description'].search(row_text))
            if has_part or has_desc:
                header_map = _map_columns(row)
                found_header = True
                table_start = i + 1
                break
        if not found_header:
            if table[0] and len(table[0]) >= 3:
                header_map = {0: 'part_number', 1: 'description', 2: 'quantity'}
                if len(table[0]) >= 4:
                    header_map[3] = 'unit'
                table_start = 0
            elif table[0] and len(table[0]) >= 2:
                header_map = {0: 'part_number', 1: 'description'}
                table_start = 0
            else:
                continue
        for row in table[table_start:]:
            if not row:
                continue
            part = _row_to_part(row, header_map)
            if part and part.get('description'):
                parts.append(part)
    return parts


def _map_columns(header_row):
    mapping = {}
    for i, cell in enumerate(header_row):
        if not cell:
            continue
        cell_text = str(cell).strip()
        for field, pattern in HEADER_PATTERNS.items():
            if pattern.search(cell_text):
                mapping[i] = field
                break
    return mapping


def _row_to_part(row, header_map):
    part = {'part_number': '', 'description': '', 'quantity': 0, 'unit': 'pcs', 'min_stock': 0}
    for i, cell in enumerate(row):
        if cell is None:
            continue
        cell_text = str(cell).strip()
        if not cell_text:
            continue
        field = header_map.get(i)
        if field == 'part_number':
            part['part_number'] = cell_text
        elif field == 'description':
            part['description'] = cell_text
        elif field == 'quantity':
            qty = _parse_quantity(cell_text)
            if qty is not None:
                part['quantity'] = qty
        elif field == 'unit':
            part['unit'] = cell_text if cell_text else 'pcs'
        elif field == 'min_stock':
            qty = _parse_quantity(cell_text)
            if qty is not None:
                part['min_stock'] = qty
        else:
            if not part['part_number'] and _looks_like_part_number(cell_text):
                part['part_number'] = cell_text
            elif not part['description'] and len(cell_text) > 2 and not cell_text.isdigit():
                part['description'] = cell_text
            elif part['description'] and _parse_quantity(cell_text) is not None:
                if part['quantity'] == 0:
                    part['quantity'] = _parse_quantity(cell_text)
    desc = part.get('description', '')
    if desc and SKIP_PATTERNS.search(desc):
        return None
    if not desc and not part['part_number']:
        return None
    return part


def _extract_from_text(text):
    """Fallback: extract parts from raw text using multiple patterns."""
    parts = []
    lines = text.split('\n')

    line_pattern_1 = re.compile(
        r'^\s*'
        r'([A-Z0-9][\w\-\.\/\s]{2,30})\s+'
        r'(.+?)\s+'
        r'(\d[\d,\.]*)\s*'
        r'((?:pcs?|sets?|ea|kg|ltr?|mm|cm|nos?|pr)?)\s*$',
        re.IGNORECASE
    )
    line_pattern_2 = re.compile(
        r'^\s*\d+\s+'
        r'([A-Z0-9][\w\-\.\/\s]{2,30})\s+'
        r'(.+?)\s+'
        r'(\d[\d,\.]*)\s*$',
        re.IGNORECASE
    )
    line_pattern_3 = re.compile(
        r'^\s*'
        r'([A-Z][\w\s\-\.]{5,60})\s+'
        r'(\d[\d,\.]*)\s*$',
        re.IGNORECASE
    )

    for line in lines:
        line = line.strip()
        if not line or len(line) < 5:
            continue
        if SKIP_PATTERNS.search(line):
            continue

        match = line_pattern_1.match(line)
        if match:
            part_number = match.group(1).strip()
            description = match.group(2).strip()
            quantity = _parse_quantity(match.group(3))
            unit = match.group(4) or 'pcs'
            if description and len(description) > 1 and not SKIP_PATTERNS.search(description):
                parts.append({
                    'part_number': part_number, 'description': description,
                    'quantity': quantity or 0, 'unit': unit or 'pcs', 'min_stock': 0,
                })
            continue

        match = line_pattern_2.match(line)
        if match:
            part_number = match.group(1).strip()
            description = match.group(2).strip()
            quantity = _parse_quantity(match.group(3))
            if description and len(description) > 1 and not SKIP_PATTERNS.search(description):
                parts.append({
                    'part_number': part_number, 'description': description,
                    'quantity': quantity or 0, 'unit': 'pcs', 'min_stock': 0,
                })
            continue

        match = line_pattern_3.match(line)
        if match:
            description = match.group(1).strip()
            quantity = _parse_quantity(match.group(2))
            if description and len(description) > 3 and not SKIP_PATTERNS.search(description):
                parts.append({
                    'part_number': '', 'description': description,
                    'quantity': quantity or 0, 'unit': 'pcs', 'min_stock': 0,
                })

    return parts


def _parse_quantity(text):
    text = str(text).strip()
    text = re.sub(r'\s*(pcs?|sets?|ea|kg|ltr?|m|mm|cm|nos?|pr|pairs?)\s*$', '', text, flags=re.IGNORECASE)
    text = text.strip().replace(',', '')
    try:
        return int(float(text))
    except (ValueError, TypeError):
        return None


def _looks_like_part_number(text):
    if re.match(r'^[A-Z0-9][\w\-\.\/]{2,30}$', text, re.IGNORECASE):
        if not re.match(r'^[a-z]+$', text, re.IGNORECASE):
            return True
    return False


def _deduplicate(parts):
    seen = set()
    result = []
    for p in parts:
        key = p.get('part_number', '').strip().upper()
        if not key:
            key = p.get('description', '').strip().upper()
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        result.append(p)
    return result
