"""
IMPA Index PDF Parser
Extracts IMPA codes and descriptions from the IMPA Index PDF.
Uses PyMuPDF (fitz) as primary parser with CID-aware extraction.
Handles garbled/reversed text on odd pages gracefully.

Readable pages (even 1-indexed: 2, 4, 6, 8...) have clean text.
Garbled pages (odd 1-indexed: 1, 3, 5, 7...) have reversed/scrambled text.
"""
import sys
sys.path = [p for p in sys.path if 'hermes' not in p.lower()]

import re
import os


# IMPA code pattern: XX-YY or XX-YY-ZZ (1-2 digits each)
IMPA_CODE_RE = re.compile(r'(\d{1,2}-\d{1,2}(?:-\d{1,2})?)')

# Noise patterns to filter out
NOISE_RE = re.compile(
    r'(INTERNATIONAL\s+MARINE\s+PURCHASING\s+ASSOCIATION|'
    r'IMPA\s+Index|'
    r'^\d+$|'
    r'^[\d\s\-\.]+$|'
    r'page\s*\d|'
    r'continued|'
    r'next\s*page|'
    r'IMPA\s+CODES?)',
    re.IGNORECASE
)


def parse_impa_pdf(pdf_path=None):
    """
    Parse the IMPA Index PDF and extract IMPA codes with descriptions.
    
    Returns a list of dicts:
        [{'impa_code': 'XX-YY', 'description': '...', 'name': '...'}]
    """
    if pdf_path is None:
        pdf_path = _find_impa_pdf()
    
    if not pdf_path or not os.path.exists(pdf_path):
        print(f"[IMPA Parser] PDF not found at {pdf_path}")
        return []
    
    try:
        import fitz  # PyMuPDF
    except ImportError:
        print("[IMPA Parser] PyMuPDF not installed. Run: pip install PyMuPDF")
        return []
    
    print(f"[IMPA Parser] Opening {pdf_path}")
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    print(f"[IMPA Parser] Total pages: {total_pages}")
    
    # code -> {description, source_page, quality}
    all_entries = {}
    
    for page_num in range(total_pages):
        page = doc[page_num]
        text = page.get_text("text")
        if not text:
            continue
        
        is_readable = (page_num % 2 == 1)  # odd 0-indexed = even page number = readable
        
        if is_readable:
            # Readable page - extract normally
            page_entries = _extract_readable_page(text, page_num + 1)
        else:
            # Garbled page - try reversed text
            reversed_text = text[::-1]
            page_entries = _extract_garbled_page(reversed_text, text, page_num + 1)
        
        for code, info in page_entries.items():
            if code not in all_entries:
                all_entries[code] = info
            elif info['quality'] > all_entries[code]['quality']:
                all_entries[code] = info
            elif (info['quality'] == all_entries[code]['quality'] and 
                  len(info['desc']) > len(all_entries[code]['desc'])):
                all_entries[code] = info
    
    doc.close()
    
    # Build final results - prioritize quality
    results = []
    for code, info in all_entries.items():
        desc = _clean_description(info['desc'])
        if not desc or _is_noise(desc, code):
            continue
        
        # Filter out low-quality entries from garbled pages
        if info['quality'] < 2 and _looks_garbled(desc):
            continue
        
        results.append({
            'impa_code': code,
            'description': desc,
            'name': desc,
        })
    
    results.sort(key=lambda x: _sort_key(x['impa_code']))
    print(f"[IMPA Parser] Extracted {len(results)} unique IMPA entries")
    return results


def _find_impa_pdf():
    """Search for IMPA Index PDF in common locations."""
    search_paths = [
        os.path.expanduser("~/Desktop/IMPA Index.pdf"),
        os.path.expanduser("~/Desktop/IMPA_Index.pdf"),
        os.path.expanduser("~/Downloads/IMPA Index.pdf"),
        os.path.expanduser("~/Downloads/IMPA_Index.pdf"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "IMPA Index.pdf"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "IMPA_Index.pdf"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "IMPA Index.pdf"),
    ]
    for path in search_paths:
        if os.path.exists(path):
            return path
    return None


def _extract_readable_page(text, page_num):
    """Extract entries from a readable page. Returns {code: {desc, quality}}."""
    lines = text.split('\n')
    entries = {}
    
    for i, line in enumerate(lines):
        line = line.strip()
        if not line or len(line) < 2:
            continue
        
        # Find valid codes in this line
        codes = _find_valid_codes(line)
        if not codes:
            continue
        
        for code in codes:
            if code in entries:
                continue
            
            # Get description from this line
            desc = _get_desc_from_line(line, code, lines, i, quality=3)
            if desc:
                entries[code] = {'desc': desc, 'quality': 3}
            else:
                # Look back for description
                desc = _look_back_for_desc(lines, i)
                if desc:
                    entries[code] = {'desc': desc, 'quality': 2}
    
    return entries


def _extract_garbled_page(reversed_text, original_text, page_num):
    """Extract entries from a garbled page using reversed text."""
    lines = reversed_text.split('\n')
    entries = {}
    
    for i, line in enumerate(lines):
        line = line.strip()
        if not line or len(line) < 2:
            continue
        
        codes = _find_valid_codes(line)
        if not codes:
            continue
        
        for code in codes:
            if code in entries:
                continue
            
            desc = _get_desc_from_line(line, code, lines, i, quality=1)
            if desc:
                entries[code] = {'desc': desc, 'quality': 1}
            else:
                desc = _look_back_for_desc(lines, i)
                if desc:
                    entries[code] = {'desc': desc, 'quality': 1}
    
    return entries


def _find_valid_codes(text):
    """Find all valid IMPA codes in text."""
    codes = []
    for match in IMPA_CODE_RE.finditer(text):
        code = match.group(1)
        parts = code.split('-')
        if all(1 <= len(p) <= 2 and p.isdigit() and 1 <= int(p) <= 99 for p in parts):
            codes.append(code)
    return codes


def _get_desc_from_line(line, code, all_lines, line_idx, quality=3):
    """Get description for a code from its line."""
    # Strategy 1: Description before code
    desc = _desc_before_code(line, code)
    if desc:
        return desc
    
    # Strategy 2: Description after code
    desc = _desc_after_code(line, code)
    if desc:
        return desc
    
    return ''


def _look_back_for_desc(lines, current_idx):
    """Look back for a description, skipping past stacked code-only lines."""
    max_lookback = min(8, current_idx + 1)  # Look up to 8 lines back
    code_only_streak = 0
    
    for lookback in range(1, max_lookback):
        prev_idx = current_idx - lookback
        if prev_idx < 0:
            break
        prev_line = lines[prev_idx].strip()
        if not prev_line or len(prev_line) < 2:
            code_only_streak = 0
            continue
        
        # If this line has only codes (no description text), skip past it
        prev_codes = _find_valid_codes(prev_line)
        if prev_codes:
            # Check if line is ONLY a code (no description text)
            test_line = prev_line
            for c in prev_codes:
                test_line = test_line.replace(c, '')
            test_line = re.sub(r'[\s.\-,\'\"`„""..]+', '', test_line).strip()
            if not test_line or len(test_line) < 3:
                code_only_streak += 1
                continue
            # Has both code and text - check if text is a description
        
        # Skip noise
        if NOISE_RE.search(prev_line):
            continue
        
        # Skip category headers (all uppercase, short, no lowercase)
        if re.match(r'^[A-Z][A-Z\s\-]{2,30}$', prev_line):
            break
        
        # Skip lines that look like garbled text
        if _looks_garbled(prev_line):
            continue
        
        # Must contain letters
        if not re.search(r'[A-Za-z]', prev_line):
            continue
        
        # If we've passed multiple code-only lines, this is likely the description
        cleaned = _clean_description(prev_line)
        if cleaned and len(cleaned) > 2:
            return cleaned
    
    return ''


def _desc_before_code(line, code):
    """Extract description from text before the code."""
    idx = line.find(code)
    if idx < 0:
        return ''
    
    before = line[:idx].strip()
    if not before:
        return ''
    
    # Remove trailing dots, spaces, special chars
    before = re.sub(r'[\s.\-,\'\"`„""..]+$', '', before).strip()
    before = re.sub(r'^[\s.\-,\'\"`„""..]+', '', before).strip()
    
    if not before or len(before) < 2:
        return ''
    
    # Must contain at least one letter
    if not re.search(r'[A-Za-z]', before):
        return ''
    
    return before


def _desc_after_code(line, code):
    """Extract description from text after the code."""
    idx = line.find(code)
    if idx < 0:
        return ''
    
    after = line[idx + len(code):].strip()
    if not after:
        return ''
    
    # Remove leading dots, commas, spaces
    after = re.sub(r'^[\s.\-,\'\"`„""..]+', '', after).strip()
    
    if not after or len(after) < 2:
        return ''
    
    # Must contain at least one letter
    if not re.search(r'[A-Za-z]', after):
        return ''
    
    # Don't take text that looks like another code
    if re.match(r'^\d{1,2}-\d{1,2}', after):
        return ''
    
    return after


def _looks_garbled(text):
    """Check if text looks garbled/unreadable."""
    if not text:
        return True
    
    # Check for unusual characters
    unusual = sum(1 for c in text if c in '|}{\[\]~`§®™©')
    if unusual > len(text) * 0.1:
        return True
    
    # Check for long consonant sequences (garbled text marker)
    if re.search(r'[bcdfghjklmnpqrstvwxyz]{6,}', text, re.IGNORECASE):
        return True
    
    # Check vowel ratio (English text typically has ~40% vowels)
    vowels = sum(1 for c in text.lower() if c in 'aeiou')
    alpha = sum(1 for c in text if c.isalpha())
    if alpha > 10 and vowels / alpha < 0.15:
        return True
    
    return False


def _clean_description(desc):
    """Clean up a description string."""
    if not desc:
        return ''
    
    desc = desc.strip()
    
    # Remove common wrapper characters
    for ch in ['.', '_', '`', "'", '"', '„', '"', '"', '®', '™']:
        desc = desc.strip(ch)
    
    desc = desc.strip()
    
    # Remove trailing dots and special chars
    desc = re.sub(r'[.\s,]+$', '', desc)
    
    # Remove leading special chars but keep letters
    desc = re.sub(r'^[^A-Za-z0-9]+', '', desc)
    
    # Normalize whitespace
    desc = re.sub(r'\s+', ' ', desc).strip()
    
    # Remove lines that are just numbers or codes
    if re.match(r'^[\d\-\s]+$', desc):
        return ''
    
    # Remove descriptions that are too short
    if len(desc) < 2:
        return ''
    
    # Remove descriptions that look like page numbers
    if re.match(r'^\d+$', desc):
        return ''
    
    # Clean up garbled characters but keep readable text
    desc = re.sub(r'[^\w\s,\-\'\"&/\.()®™/]', ' ', desc)
    desc = re.sub(r'\s+', ' ', desc).strip()
    
    return desc


def _is_noise(desc, code):
    """Check if a description is noise or garbled."""
    if not desc:
        return True
    if NOISE_RE.search(desc):
        return True
    if desc.strip() == code:
        return True
    if len(desc) < 3:
        return True
    
    # Filter descriptions that are mostly non-alpha
    alpha_count = sum(1 for c in desc if c.isalpha())
    if alpha_count < max(1, len(desc) * 0.2):
        return True
    
    # Filter garbled text using the garbled detector
    if _looks_garbled(desc):
        return True
    
    # Filter descriptions with too many special characters
    special_count = sum(1 for c in desc if not c.isalnum() and not c.isspace())
    if special_count > len(desc) * 0.3:
        return True
    
    # Filter descriptions that look like they have garbled words
    words = desc.split()
    if len(words) >= 2:
        # Check if most words look like garbled text (no common English patterns)
        garbled_words = 0
        for w in words:
            w_clean = w.strip('.,;:!?-\'"')
            if len(w_clean) <= 2:
                garbled_words += 1
            elif not any(c in w_clean.lower() for c in 'aeiou'):
                garbled_words += 1
        if garbled_words > len(words) * 0.5:
            return True
    
    return False


def _sort_key(code):
    """Sort key for IMPA codes."""
    parts = code.split('-')
    return tuple(int(p) for p in parts)


# --- Main entry point for direct execution ---
if __name__ == '__main__':
    import json
    results = parse_impa_pdf()
    print(f"\n{'='*60}")
    print(f"Total IMPA entries extracted: {len(results)}")
    print(f"{'='*60}")
    print("\nFirst 30 entries:")
    for entry in results[:30]:
        print(f"  {entry['impa_code']:>8s}  {entry['description']}")
    if len(results) > 30:
        print(f"\n... and {len(results) - 30} more entries")
    
    # Save to JSON
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'impa_codes.json')
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved to {output_path}")
