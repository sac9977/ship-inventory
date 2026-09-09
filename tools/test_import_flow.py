"""End-to-end test: login -> batch CSV import -> paginated list -> search -> edit."""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as appmod  # noqa: E402
import database as db  # noqa: E402

client = appmod.app.test_client()

# 1. login
r = client.post('/login', data={'username': 'admin', 'password': 'admin'},
                follow_redirects=True)
assert r.status_code == 200, r.status_code
print('1. login OK')

# 2. import the prepared IMPA CSV
csv_path = '/tmp/impa_import.csv'
if not os.path.exists(csv_path):
    sys.exit('run prepare_impa_csv.py first')
with open(csv_path, 'rb') as f:
    data = f.read()
r = client.post('/import-csv-stores',
                data={'csv_file': (io.BytesIO(data), 'impa_import.csv')},
                content_type='multipart/form-data',
                follow_redirects=True)
assert r.status_code == 200, r.status_code
body = r.get_data(as_text=True)
import re
m = re.search(r'Imported (\d[\d,]*) store items \((\d[\d,]*) skipped\)', body)
print('2. import flash:', m.group(0) if m else 'NOT FOUND')
assert m, 'import flash missing'
imp, skp = (int(m.group(i).replace(',', '')) for i in (1, 2))
assert (imp, skp) in [(14862, 0), (0, 14862)], 'unexpected import split'

# 3. counts + zero ROB
con = __import__('sqlite3').connect(db.DB_PATH)
total, zero = con.execute(
    "SELECT COUNT(*), SUM(quantity = 0) FROM stores").fetchone()
batches = con.execute("SELECT DISTINCT import_batch FROM stores").fetchall()
con.close()
print(f'3. rows: {total}, zero-ROB: {zero}, batches: {batches}')
assert total == 14862 and zero == 14862, 'row/zero counts wrong'

# 4. paginated list (page 1, page 2, huge page number clamps)
r = client.get('/stores')
assert b'14,862 items' in r.get_data() or b'14862 items' in r.get_data(), 'total label missing'
r2 = client.get('/stores?page=2')
assert r2.status_code == 200 and r2.get_data() != r.get_data(), 'page 2 identical'
r3 = client.get('/stores?page=99999')
assert r3.status_code == 200, 'clamp failed'
print('4. pagination OK (page 1/2 distinct, page 99999 clamped)')

# 5. search
r = client.get('/stores?search=lifejacket')
assert r.status_code == 200
r = client.get('/stores?search=zinc')
body = r.get_data(as_text=True)
assert 'Edit' in body, 'search returned no editable rows'
print('5. search OK')

# 6. category filter
r = client.get('/stores?category=Provisions')
assert r.status_code == 200
print('6. category filter OK')

# 7. edit one entry end-to-end
con = __import__('sqlite3').connect(db.DB_PATH)
row = con.execute(
    "SELECT id, item_code, name FROM stores ORDER BY id LIMIT 1").fetchone()
con.close()
sid, code, name = row
r = client.get(f'/stores/edit/{sid}')
assert r.status_code == 200, 'edit form missing'
r = client.post(f'/stores/edit/{sid}', data={
    'item_code': code, 'name': name + ' (corrected)',
    'description': 'edited description', 'category': 'Provisions',
    'quantity': '5', 'unit': 'pcs', 'min_stock': '2', 'location': 'STORE A',
}, follow_redirects=True)
assert r.status_code == 200
con = __import__('sqlite3').connect(db.DB_PATH)
row = con.execute(
    "SELECT name, quantity, category FROM stores WHERE id = ?", (sid,)).fetchone()
con.close()
print(f'7. edit OK: {row}')
assert row[1] == 5 and row[0].endswith('(corrected)')

print('\nALL TESTS PASSED')
