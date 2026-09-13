"""End-to-end tests for machinery-manual PDF import.

Feeds the real manual shape (drawing number in the page header, per-page plate
title, "Item no | Designation" rows, +0x1E shifted fonts on later pages)
through parse_pdf() using a synthetic PDF built on the fly, then verifies the
database wiring: drawing_number survives import and smart search matches by
drawing number as well as part number.

Idempotent: test machinery/parts are cleaned up at start and end.
"""
import os
import sys

sys.path.insert(0, '.')
import database as db
from pdf_parser import parse_pdf

import fitz

MACH_NAME = 'ZZ_TEST_MANUAL_MACH'
TMP_PDF = '/tmp/_test_manual.pdf'

CHECKS = []


def check(name, cond, detail=''):
    CHECKS.append((name, bool(cond), detail))
    print(('PASS' if cond else 'FAIL') + f'  {name}' + (f'  [{detail}]' if detail and not cond else ''))


def shift(s):
    """Encode plain text the way the shifted generator fonts store it."""
    return ''.join(chr(ord(c) - 0x1E) for c in s)


def build_manual_pdf(path):
    """Two-page manual: page 1 normal fonts, page 2 shifted fonts."""
    doc = fitz.open()
    H = 792

    # ── Page 1: standard fonts ──
    page = doc.new_page(width=612, height=H)
    page.insert_text((50, 60), '1470-0510-0006', fontsize=13, fontname='hebo')
    page.insert_text((55, 110), 'Crosshead Hydraulic Tools', fontsize=15, fontname='hebo')
    page.insert_text((240, 100), 'Item no', fontsize=8.5)
    page.insert_text((270, 100), 'Designation', fontsize=8.5)
    rows = [
        ('018', 'hydraulic jack, complete'),
        ('020', 'Hydraulic jack, support'),
        ('043', 'Tommy bar'),
        ('055', 'Sealing ring with'),        # + wrapped continuation below
    ]
    y = 130
    for item, desc in rows:
        page.insert_text((240, y), item, fontsize=8.5)
        page.insert_text((270, y), desc, fontsize=8.5)
        y += 13
    page.insert_text((270, y), 'back-up', fontsize=8.5)   # continuation line
    page.insert_text((70, 690), '1470-0510-0006', fontsize=11, fontname='hebo')
    page.insert_text((540, 640), '2011-09-12 - en', fontsize=6)

    # ── Page 2: shifted fonts ──
    page = doc.new_page(width=612, height=H)
    page.insert_text((50, 55), shift('1470-1400-0021'), fontsize=13, fontname='helv')
    page.insert_text((52, 110), shift('Chain Drive Tools'), fontsize=15, fontname='helv')
    page.insert_text((240, 100), shift('Item no.'), fontsize=8.5, fontname='helv')
    page.insert_text((270, 100), shift('Designation'), fontsize=8.5, fontname='helv')
    for item, desc in [('012', 'Panel for tools'), ('024', 'Name plate')]:
        page.insert_text((240, y), shift(item), fontsize=8.5, fontname='helv')
        page.insert_text((270, y), shift(desc), fontsize=8.5, fontname='helv')
        y += 13
    page.insert_text((70, 690), shift('1470-1400-0021'), fontsize=11, fontname='helv')
    page.insert_text((540, 640), shift('2013-11-20 - en'), fontsize=6, fontname='helv')

    doc.save(path)
    doc.close()


# ── Setup: clean slate ──
for m in db.get_all_machinery():
    if m['name'] == MACH_NAME:
        db.delete_machinery(m['id'])

build_manual_pdf(TMP_PDF)
try:
    result = parse_pdf(TMP_PDF)

    parts = result['parts']
    by_item = {p['part_number']: p for p in parts}

    # 1. Structure: machinery from first plate title
    check('machinery name from plate title',
          result['machinery_name'] == 'CROSSHEAD HYDRAULIC TOOLS',
          result['machinery_name'])

    # 2. Both drawing numbers extracted, one per page
    dwgs = {p['drawing_number'] for p in parts}
    check('both drawing numbers captured',
          dwgs == {'1470-0510-0006', '1470-1400-0021'}, str(dwgs))
    check('document drawing_number = majority vote',
          result['drawing_number'] in dwgs, result['drawing_number'])

    # 3. Item numbers split from descriptions, per-page drawing stamped
    p18 = by_item.get('018')
    check('item 018 with page-1 drawing',
          p18 and p18['description'] == 'hydraulic jack, complete'
          and p18['drawing_number'] == '1470-0510-0006',
          str(p18))

    # 4. Wrapped designation merged, not a stray part
    check('continuation line merged into item 055',
          by_item.get('055', {}).get('description') == 'Sealing ring with back-up',
          by_item.get('055', {}).get('description', ''))
    check('no stray "back-up" part', 'back-up' not in by_item)

    # 5. Shifted page fully decoded
    p12 = by_item.get('012')
    check('shifted page decoded (item 012)',
          p12 and p12['description'] == 'Panel for tools'
          and p12['drawing_number'] == '1470-1400-0021', str(p12))
    check('plate title decoded on shifted page',
          any(pl['title'] == 'Chain Drive Tools' and pl['page'] == 2
              for pl in result['plates']),
          str(result['plates']))

    # 6. No footer date pollution
    polluted = [p for p in parts if '2011' in p['description'] or '2013' in p['description']
                or p['description'].endswith('- en')]
    check('footer dates never pollute descriptions', not polluted, str(polluted))

    # 7. Part count: 4 page-1 rows (055 merged) + 2 page-2 rows
    check('part count correct', len(parts) == 6, str(len(parts)))

    # ── DB wiring ──
    mach_id = db.create_machinery(name=MACH_NAME)
    try:
        db.bulk_create_spare_parts(mach_id, parts)
        stored = db.get_spare_parts_by_machinery(mach_id)
        st = {p['part_number']: p for p in stored}

        # 8. drawing_number survives import
        check('drawing_number stored in DB',
              st['018']['drawing_number'] == '1470-0510-0006'
              and st['012']['drawing_number'] == '1470-1400-0021',
              str({k: st[k]['drawing_number'] for k in ('018', '012') if k in st}))

        # 9. Search by drawing number (unpadded/punctuated) finds its parts
        hits = db.search_spare_parts('1470-1400-0021')
        check('search by full drawing number',
              {h['part_number'] for h in hits} == {'012', '024'},
              str([h['part_number'] for h in hits]))

        hits = db.search_spare_parts('1470 1400')      # spaced fragment
        check('search by partial drawing number',
              {h['part_number'] for h in hits} == {'012', '024'},
              str([h['part_number'] for h in hits]))

        # 10. Search by item number still works; name search unaffected
        hits = db.search_spare_parts('024')
        check('search by item number',
              any(h['part_number'] == '024' for h in hits),
              str([h['part_number'] for h in hits]))
        hits = db.search_spare_parts('panel')
        check('name search unchanged',
              any(h['part_number'] == '012' for h in hits),
              str([h['part_number'] for h in hits]))
    finally:
        db.delete_machinery(mach_id)
finally:
    if os.path.exists(TMP_PDF):
        os.unlink(TMP_PDF)
    for m in db.get_all_machinery():
        if m['name'] == MACH_NAME:
            db.delete_machinery(m['id'])

failed = [c for c in CHECKS if not c[1]]
print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
sys.exit(1 if failed else 0)
