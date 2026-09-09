"""End-to-end test: count-sheet import — reconcile, review, apply, audit."""
import html
import io
import json
import re
import sys

sys.path.insert(0, __file__.rsplit('/tools/', 1)[0])
import os  # noqa: E402
os.chdir(__file__.rsplit('/tools/', 1)[0])
sys.path.insert(0, os.getcwd())

import app as appmod  # noqa: E402
import database as db  # noqa: E402

client = appmod.app.test_client()
r = client.post('/login', data={'username': 'admin', 'password': 'admin'},
                follow_redirects=True)
assert r.status_code == 200

con = __import__('sqlite3').connect(db.DB_PATH)
con.row_factory = __import__('sqlite3').Row
rows = con.execute(
    "SELECT id, item_code, quantity FROM stores ORDER BY id LIMIT 5").fetchall()
ids = [r['id'] for r in rows]
codes = [r['item_code'] for r in rows]
cur_qty = [r['quantity'] for r in rows]

# Fixture: give item 3 a healthy book stock so a small delta stays under the
# 10% flag threshold (delta 5 on 100 = 5% -> not flagged).
con.execute("UPDATE stores SET quantity = 100 WHERE id = ?", (ids[2],))
con.commit()
cur_qty[2] = 100

# Count sheet:
#  row0: +1 on book qty 5  -> 20% off  -> FLAGGED
#  row1: 3x book qty       -> huge off -> FLAGGED
#  row2: +5 on book qty 100 -> 5% off  -> not flagged
#  row3: exact match row   -> no change
#  row4: dotted code variant +2 (book 0 -> 100% off -> flagged)
#  plus one unknown code, one unreadable qty, one duplicate row (first wins)
big = (cur_qty[1] * 3) if cur_qty[1] > 0 else 50
dotted = f'{codes[4][:2]}.{codes[4][2:5]}.{codes[4][5:]}'
cs = io.StringIO()
cs.write('impa_code,counted_qty,remarks\n')
cs.write(f'{codes[0]},{cur_qty[0] + 1},small locker, big pct\n')
cs.write(f'{codes[1]},{big},counted three pallets\n')
cs.write(f'{codes[2]},{cur_qty[2] + 5},within tolerance\n')
cs.write(f'{codes[3]},{cur_qty[3]},confirmed as listed\n')
cs.write(f'{dotted},{cur_qty[4] + 2},dotted code variant\n')
cs.write('NOTACODE,5,unknown item\n')
cs.write(f'{codes[0]},abc,bad qty\n')
cs.write(f'{codes[0]},{cur_qty[0] + 9},duplicate row must lose\n')
csv_bytes = cs.getvalue().encode()


def upload(threshold='10'):
    r = client.post('/import-count-sheet',
                    data={'csv_file': (io.BytesIO(csv_bytes), 'count.csv'),
                          'threshold': threshold},
                    content_type='multipart/form-data')
    assert r.status_code == 200, r.status_code
    body = r.get_data(as_text=True)
    assert 'Review Changes' in body and 'Unmatched' in body
    m = re.search(r"id=\"rowsJson\" value='(.*?)'>", body, re.S)
    return json.loads(html.unescape(m.group(1))), body


# 1. preview + classification
rows_json, body = upload()
by_code = {r['code']: r for r in rows_json}
assert len(rows_json) == 4, f'expected 4 matched rows, got {len(rows_json)}'
assert by_code[codes[0]]['counted'] == cur_qty[0] + 1, 'duplicate row won'
assert by_code[codes[0]]['flagged'] is True, '20% off should flag at 10%'
assert by_code[codes[1]]['flagged'] is True
assert by_code[codes[2]]['counted'] == cur_qty[2] + 5
assert by_code[codes[2]]['flagged'] is False, '5% off should NOT flag at 10%'
assert by_code[codes[4]]['counted'] == cur_qty[4] + 2, 'dotted code failed'
assert codes[3] not in by_code, 'exact-match row must not appear in apply list'
assert codes[3] in body, 'exact-match row should be listed under Already Match'
print('1. classification OK (flag/no-flag, dotted match, first-wins dedupe)')
assert 'NOTACODE' in body and 'unreadable' in body
print('2. unmatched + unreadable rows listed')

# 3. confirm: apply all
max_audit_before = con.execute(
    "SELECT COALESCE(MAX(id), 0) AS m FROM stock_corrections").fetchone()['m']
payload = [{**r, 'selected': True} for r in rows_json]
r = client.post('/import-count-sheet-confirm',
                data={'rows_json': json.dumps(payload)}, follow_redirects=True)
assert r.status_code == 200
q = {row['id']: row['quantity'] for row in
     con.execute(f"SELECT id, quantity FROM stores WHERE id IN "
                 f"({','.join('?' * 5)})", ids).fetchall()}
assert q[ids[0]] == cur_qty[0] + 1
assert q[ids[1]] == big
assert q[ids[2]] == cur_qty[2] + 5
assert q[ids[3]] == cur_qty[3], 'no-change row must not be touched'
assert q[ids[4]] == cur_qty[4] + 2
print('3. apply OK: quantities set exactly')

# 4. audit rows written as stock-take (4 changes, no-change excluded)
n_audits = con.execute(
    f"SELECT COUNT(*) c FROM stock_corrections "
    f"WHERE item_id IN ({','.join('?' * 5)}) AND reason LIKE 'stock take%' "
    f"AND id > ?", [*ids, max_audit_before]).fetchone()['c']
assert n_audits == 4, f'expected 4 audit rows, got {n_audits}'
print('4. audit rows logged for every applied change')

# 5. deselected rows are not applied
rows_json2, _ = upload()
for rj in rows_json2:
    rj['selected'] = False
r = client.post('/import-count-sheet-confirm',
                data={'rows_json': json.dumps(rows_json2)},
                follow_redirects=True)
q2 = con.execute("SELECT quantity FROM stores WHERE id = ?",
                 (ids[0],)).fetchone()['quantity']
assert q2 == cur_qty[0] + 1, 'deselected rows must not be applied'
print('5. deselect-all applies nothing')

# 6. pages wired
assert b'count-sheet' in client.get('/import-count-sheet').get_data()
assert b'impa_code,counted_qty,remarks' in \
    client.get('/download-sample/count-sheet').get_data()
assert 'Import Count Sheet' in client.get('/').get_data(as_text=True)
print('6. upload page, sample CSV, sidebar link OK')

con.close()
print('\nALL TESTS PASSED')
