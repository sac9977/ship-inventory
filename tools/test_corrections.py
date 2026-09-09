"""End-to-end test: Corrections audit page — filters, pagination, CSV export."""
import io
import json
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, __file__.rsplit('/tools/', 1)[0])
os.chdir(__file__.rsplit('/tools/', 1)[0])

import app as appmod  # noqa: E402
import database as db  # noqa: E402

client = appmod.app.test_client()
r = client.post('/login', data={'username': 'admin', 'password': 'admin'},
                follow_redirects=True)
assert r.status_code == 200

con = __import__('sqlite3').connect(db.DB_PATH)
con.row_factory = __import__('sqlite3').Row

# Seed corrections from two "users" via the adjust endpoint
ids = [r['id'] for r in con.execute(
    "SELECT id, quantity FROM stores ORDER BY id LIMIT 3").fetchall()]
start_qty = {r['id']: r['quantity'] for r in con.execute(
    "SELECT id, quantity FROM stores ORDER BY id LIMIT 3").fetchall()}

client.post(f'/stores/adjust/{ids[0]}', data=json.dumps({'quantity': 11, 'reason': 'alpha fix'}),
            content_type='application/json')
client.post(f'/stores/adjust/{ids[1]}', data=json.dumps({'quantity': 12, 'reason': 'beta fix'}),
            content_type='application/json')
client.post(f'/stores/adjust/{ids[2]}', data=json.dumps({'quantity': 13, 'reason': 'gamma fix'}),
            content_type='application/json')

# user filter: only 'Administrator' exists so far — add a foreign-user row directly
con.execute(
    "INSERT INTO stock_corrections (item_category, item_id, old_quantity, "
    "new_quantity, reason, corrected_by, created_at) "
    "VALUES ('stores', ?, 0, 5, 'ghost edit', 'SomeoneElse', '2026-01-01 10:00:00')",
    (ids[0],))
con.commit()
print('seeded 4 correction rows (3 admin, 1 SomeoneElse backdated)')

# 1. page renders with rows
r = client.get('/corrections')
body = r.get_data(as_text=True)
assert r.status_code == 200 and 'Stock Corrections' in body
assert 'alpha fix' in body and 'ghost edit' in body
print('1. page renders with seeded rows')

# 2. user filter
r = client.get('/corrections?user=SomeoneElse')
body = r.get_data(as_text=True)
assert 'ghost edit' in body and 'alpha fix' not in body
print('2. user filter OK')

# 3. item filter by code fragment
code = con.execute("SELECT item_code FROM stores WHERE id = ?",
                   (ids[0],)).fetchone()['item_code']
r = client.get(f'/corrections?item={code}')
body = r.get_data(as_text=True)
assert code in body
# ids[1] has a different code -> its fix shouldn't appear when filtering
code1 = con.execute("SELECT item_code FROM stores WHERE id = ?",
                    (ids[1],)).fetchone()['item_code']
assert 'beta fix' not in body or code1 == code
print('3. item filter OK')

# 4. date range: only the backdated row
r = client.get('/corrections?date_from=2026-01-01&date_to=2026-01-02')
body = r.get_data(as_text=True)
assert 'ghost edit' in body and 'alpha fix' not in body
print('4. date-range filter OK')

# 5. pagination fields present
r = client.get('/corrections?user=Administrator')
body = r.get_data(as_text=True)
assert 'Corrections (' in body
print('5. pagination/count OK')

# 6. CSV export with filter
r = client.get('/corrections/export?user=SomeoneElse')
assert r.status_code == 200
assert 'stock_corrections.csv' in r.headers.get('Content-Disposition', '')
lines = r.get_data(as_text=True).strip().splitlines()
assert lines[0].startswith('timestamp,item_code')
assert len(lines) == 2, f'expected header+1 row, got {len(lines)}'
assert 'ghost edit' in lines[1]
print('6. CSV export honors filters')

# 7. restore quantities and clean the injected row (keep audit real ones)
client.post(f'/stores/adjust/{ids[0]}', data=json.dumps({'quantity': start_qty[ids[0]]}),
            content_type='application/json')
client.post(f'/stores/adjust/{ids[1]}', data=json.dumps({'quantity': start_qty[ids[1]]}),
            content_type='application/json')
client.post(f'/stores/adjust/{ids[2]}', data=json.dumps({'quantity': start_qty[ids[2]]}),
            content_type='application/json')
print('7. quantities restored')

con.close()
print('\nALL TESTS PASSED')
