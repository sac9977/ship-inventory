"""
Ship Inventory PDF Parser
Extracts spare parts lists from machinery PDF documents (e.g. MAN ES "Plate"
manuals: a drawing number in the page header, a plate title, and a two-column
"Item no | Designation" table where the item number is the balloon reference
on the drawing).

Key behaviours:
- Drawing number capture: a numeric code like 1470-0510-0006 printed in the
  page header (top) and repeated near the plate footer is recorded per page
  and stamped onto every part found on that page.
- Encoded-font recovery: some generator pipelines embed fonts whose glyphs are
  shifted by -0x1E (e.g. '+VGO' renders as 'Item', '\x13\x16\x19' as '147').
  Spans from fonts that emit control characters are decoded back to ASCII.
- Item number splitting: the leftmost small integer on a row becomes the
  part_number (balloon ref); the remaining text is the description.
- Plate titles: the large bold line inside the content area names the section
  ("Crosshead Hydraulic Tools", "Connecting rod", ...) and is carried per part.

Fallback: pdfplumber table/text extraction for conventional PDFs.
"""
import os
import re
import statistics


# ── Encoded-font recovery ────────────────────────────────────────────────────

def _decode_shifted(text):
    """Undo the generator cmap shift: real char = stored code + 0x1E.

    ' ' is stored as 0x02, digits as 0x12-0x1B, '-' as 0x0F, and letters fill
    0x23-0x5C. Codes whose sum is not printable ASCII are dropped.
    """
    out = []
    for ch in text:
        c = ord(ch) + 0x1E
        if 0x20 <= c <= 0x7E:
            out.append(chr(c))
    return ''.join(out)


# A drawing/identity number: two to six digit groups joined by - . / or space.
DRAWING_RE = re.compile(r'^\d{2,6}[.\-/ ]\d{2,6}(?:[.\-/ ]\d{2,6}){0,4}$')

HEADER_TOKEN_RE = re.compile(
    r'(item\s*no|designation|part\s*no|description|identity\s*no|drawing\s*no)',
    re.IGNORECASE)

# Row noise (kept from the legacy extractor)
NOISE_RE = re.compile(
    r'^(\d{4}[-/.]\d{2}[-/.]\d{2}|'          # dates
    r'\d{4}[-/.]\d{2}[-/.]\d{2}\s*[-\u2013\u2014]?\s*[a-z]{0,3}$|'  # date + lang footer
    r'\d[\d\-/.]{6,}|'                        # bare document/part codes
    r'\d+\s*\(\d+\)|'                         # page refs like "2 (2)"
    r'[\d\s.\-/]+)$',                         # pure numbers/punctuation
    re.IGNORECASE)

MIN_BODY_SIZE_RATIO = 1.25   # a title span must be 25% larger than body text
HEADER_ZONE = 0.10           # top 10% of the page: drawing numbers only
FOOTER_ZONE = 0.78           # bottom 22%: plate label, dates, page refs


def parse_pdf(file_path):
    """
    Parse a spare-parts manual PDF into structured data.
    Returns a dict with 'machinery_name', 'drawing_number', 'plates',
    'parts' and 'raw_text_preview'.
    """
    parts, meta, full_text = _parse_manual(file_path)

    if not parts:
        parts, full_text = _parse_legacy(file_path)

    machinery_name = (
        meta.get('machinery_name')
        or _extract_machinery_name(full_text)
        or 'UNKNOWN MACHINERY'
    )
    parts = _deduplicate(parts)

    return {
        'machinery_name': machinery_name,
        'drawing_number': meta.get('drawing_number', ''),
        'plates': meta.get('plates', []),
        'parts': parts,
        'raw_text_preview': (full_text or '')[:3000],
    }


# ── Primary extractor: PyMuPDF spans, position-aware ─────────────────────────

def _page_spans(page):
    """Collect styled spans from a page (skipping invisible artifacts)."""
    spans = []
    for b in page.get_text('dict')['blocks']:
        for l in b.get('lines', []):
            for s in l['spans']:
                t = s.get('text', '')
                if not t.strip():
                    continue
                size = s.get('size', 0) or 0
                if size < 2:          # invisible watermark / artifact glyphs
                    continue
                font = s.get('font', '') or ''
                spans.append({
                    'text': t,
                    'x0': s['bbox'][0], 'y0': s['bbox'][1],
                    'size': size,
                    'font': font,
                    'bold': ('bold' in font.lower() or 'bd' in font.lower()
                             or 'black' in font.lower()),
                })
    return spans


def _decode_encoded_fonts(spans):
    """Decode spans of fonts that emit control characters (shifted cmaps).

    A font is flagged when ANY of its spans contains a control char; all spans
    of that font are then decoded, including clean-text spans like '5ETGY'
    ('Screw'). Fonts that never emit control chars are left untouched.
    """
    flagged = {s['font'] for s in spans
               if any(ord(c) < 0x20 for c in s['text'])}
    for s in spans:
        if s['font'] in flagged:
            s['text'] = _decode_shifted(s['text'])
    return spans


def _cluster_lines(spans, y_tol=3.0):
    """Group spans into visual lines by y position, x-ordered within a line."""
    lines = []
    for s in sorted(spans, key=lambda s: (s['y0'], s['x0'])):
        if lines and abs(s['y0'] - lines[-1]['y0']) <= y_tol:
            lines[-1]['spans'].append(s)
        else:
            lines.append({'y0': s['y0'], 'spans': [s]})
    for ln in lines:
        ln['spans'].sort(key=lambda s: s['x0'])
        ln['text'] = ' '.join(s['text'].strip() for s in ln['spans']).strip()
    return lines


def _parse_manual(file_path):
    """Unified extractor for manual-style pages (normal or encoded fonts)."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return [], {}, ''

    all_parts = []
    plates = []
    drawing_votes = {}
    full_text = ''
    title_sizes = []

    doc = fitz.open(file_path)
    try:
        for page_no, page in enumerate(doc, start=1):
            h = page.rect.height or 792
            spans = _decode_encoded_fonts(_page_spans(page))
            lines = _cluster_lines(spans)
            body_size = statistics.median(
                [s['size'] for s in spans if s['size']] or [8.5])

            page_parts = []
            page_drawing = ''
            plate_title = ''
            last_part = None       # (part_dict, line_index) for continuations

            for idx, ln in enumerate(lines):
                y = ln['y0']
                text = ln['text']
                full_text += text + '\n'

                # Drawing numbers in header or footer zones
                if y < h * HEADER_ZONE or y > h * FOOTER_ZONE:
                    if not page_drawing and DRAWING_RE.match(text.strip()):
                        page_drawing = text.strip()
                    continue

                # Header rows ("Item no. Designation") and noise
                if HEADER_TOKEN_RE.search(text) and not re.search(
                        r'[a-z]{4}\s+[a-z]{4}\s+[a-z]{4}', text):
                    continue
                if DRAWING_RE.match(text.strip()):
                    if not page_drawing:
                        page_drawing = text.strip()
                    continue

                # Plate titles: big bold text inside the content area
                big = [s for s in ln['spans']
                       if s['size'] > body_size * MIN_BODY_SIZE_RATIO]
                if big and len(text) > 3:
                    if not plate_title:
                        plate_title = text
                        title_sizes.append(page_no)
                    continue

                if NOISE_RE.match(text):
                    continue

                # Data row: leftmost small integer = item no (balloon ref)
                spans_txt = [s['text'].strip() for s in ln['spans']]
                item_no = ''
                if spans_txt and re.match(r'^\d{1,4}[.)]?$', spans_txt[0]):
                    item_no = spans_txt[0].rstrip('.)')
                    spans_txt = spans_txt[1:]
                desc = ' '.join(t for t in spans_txt if t).strip()

                if item_no:
                    part = {
                        'part_number': item_no,
                        'description': desc,
                        'drawing_number': page_drawing,
                        'plate_title': plate_title,
                        'quantity': 0,
                        'unit': 'pcs',
                        'min_stock': 0,
                    }
                    page_parts.append(part)
                    last_part = (part, idx)
                elif desc and len(desc) > 2 and last_part \
                        and idx - last_part[1] == 1 \
                        and not NOISE_RE.match(desc):
                    # Wrapped continuation of the previous designation
                    prev = last_part[0]['description']
                    last_part[0]['description'] = (prev + ' ' + desc).strip()

            if plate_title:
                plates.append({
                    'page': page_no,
                    'title': plate_title,
                    'drawing_number': page_drawing,
                })
            if page_drawing:
                drawing_votes[page_drawing] = drawing_votes.get(page_drawing, 0) + 1
            for p in page_parts:
                p['plate_title'] = p['plate_title'] or plate_title
                p['drawing_number'] = p['drawing_number'] or page_drawing
            all_parts.extend(page_parts)
    finally:
        doc.close()

    meta = {
        'plates': plates,
        'drawing_number': (max(drawing_votes, key=drawing_votes.get)
                           if drawing_votes else ''),
        'machinery_name': (plates[0]['title'].upper() if plates else ''),
    }
    return all_parts, meta, full_text


# ── Legacy fallback: pdfplumber tables / text ────────────────────────────────

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


def _parse_legacy(file_path):
    """Conventional PDFs: pdfplumber tables first, raw text second."""
    try:
        import pdfplumber
    except ImportError:
        return [], ''

    full_text = ''
    all_tables = []
    has_cid = False

    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ''
            full_text += text + '\n'
            if '(cid:' in text:
                has_cid = True
            tables = _extract_tables(page)
            if tables:
                all_tables.extend(tables)

    if has_cid:
        return [], full_text

    parts = _extract_from_tables(all_tables)
    if not parts:
        parts = _extract_from_text(full_text)

    return parts, full_text


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
    return ''


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
    part = {'part_number': '', 'description': '', 'quantity': 0,
            'unit': 'pcs', 'min_stock': 0, 'drawing_number': ''}
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
        r'([A-Z0-9][\w\-./\s]{2,30})\s+'
        r'(.+?)\s+'
        r'(\d[\d,.]*)\s*'
        r'((?:pcs?|sets?|ea|kg|ltr?|mm|cm|nos?|pr)?)\s*$',
        re.IGNORECASE
    )
    line_pattern_2 = re.compile(
        r'^\s*\d+\s+'
        r'([A-Z0-9][\w\-./\s]{2,30})\s+'
        r'(.+?)\s+'
        r'(\d[\d,.]*)\s*$',
        re.IGNORECASE
    )
    line_pattern_3 = re.compile(
        r'^\s*'
        r'([A-Z][\w\s.\-]{5,60})\s+'
        r'(\d[\d,.]*)\s*$',
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
                    'quantity': quantity or 0, 'unit': unit or 'pcs',
                    'min_stock': 0, 'drawing_number': '',
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
                    'quantity': quantity or 0, 'unit': 'pcs',
                    'min_stock': 0, 'drawing_number': '',
                })
            continue

        match = line_pattern_3.match(line)
        if match:
            description = match.group(1).strip()
            quantity = _parse_quantity(match.group(2))
            if description and len(description) > 3 and not SKIP_PATTERNS.search(description):
                parts.append({
                    'part_number': '', 'description': description,
                    'quantity': quantity or 0, 'unit': 'pcs',
                    'min_stock': 0, 'drawing_number': '',
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
    if re.match(r'^[A-Z0-9][\w\-./]{2,30}$', text, re.IGNORECASE):
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
