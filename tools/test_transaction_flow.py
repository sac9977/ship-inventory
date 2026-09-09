"""End-to-end test: receipt/usage transactions on the stores catalog."""
import json
import os
import re
import sys

sys.path.insert(0, __file__.rsplit('/tools/', 1)[0])
os.chdir(__file__.rsplit('/tools/', 1)[0])

import app as appmod  # noqa: E402
import database as db  # noqa: E402
db.update_user_password(1, 'admin')  # dev fixture: default login, clears force-change flag


client = appmod.app.test_client()
r = client.post('/login', data={'username': 'admin', 'password': 'admin'},
                follow_redirects=True)
assert r.status_code == 200

con = __import__('sqlite3').connect(db.DB_PATH)
con.row_factory = __import__('sqlite3').Row
item = con.execute(
    "SELECT id, item_code, name, quantity, unit FROM stores ORDER BY id LIMIT 1"
).fetchone()
sid, orig_qty = item['id'], item['quantity']

n_txn_before = con.execute(
    "SELECT COUNT(*) c FROM transactions WHERE item_category='stores' AND item_id=?",
    (sid,)).fetchone()['c']

# 1. receipt adds to ROB and logs a transaction
r = client.post('/transaction', data={
    'transaction_type': 'receipt', 'item_category': 'stores',
    'item_id': f'stores:{sid}', 'quantity': '10',
    'crew_name': 'Test Officer', 'remarks': 'delivery SM-2026-09',
}, follow_redirects=True)
body = r.get_data(as_text=True)
assert f'New ROB: {orig_qty + 10}' in body, 'new-ROB flash missing'
q = con.execute("SELECT quantity FROM stores WHERE id=?", (sid,)).fetchone()[0]
assert q == orig_qty + 10
n = con.execute(
    "SELECT COUNT(*) c FROM transactions WHERE item_category='stores' AND item_id=?",
    (sid,)).fetchone()['c']
assert n == n_txn_before + 1
print(f'1. receipt OK: ROB {orig_qty} -> {q}, transaction logged')

# 2. usage subtracts and floors at zero
r = client.post('/transaction', data={
    'transaction_type': 'usage', 'item_category': 'stores',
    'item_id': f'stores:{sid}', 'quantity': '4',
    'crew_name': 'Test Officer', 'remarks': 'daily use',
}, follow_redirects=True)
q = con.execute("SELECT quantity FROM stores WHERE id=?", (sid,)).fetchone()[0]
assert q == orig_qty + 6, f'expected {orig_qty + 6}, got {q}'
print(f'2. usage OK: ROB now {q}')

# 3. insufficient-stock guard
r = client.post('/transaction', data={
    'transaction_type': 'usage', 'item_category': 'stores',
    'item_id': f'stores:{sid}', 'quantity': '99999',
}, follow_redirects=True)
body = r.get_data(as_text=True)
assert 'Insufficient stock' in body
q2 = con.execute("SELECT quantity FROM stores WHERE id=?", (sid,)).fetchone()[0]
assert q2 == q, 'rejected usage must not change ROB'
print('3. insufficient-stock guard OK')

# 4. lookup API: prefix on code, substring on name, cap at 25
r = client.get(f'/api/stores/lookup?q={item["item_code"][:6]}')
rows = r.get_json()
assert any(x['id'] == sid for x in rows), 'exact code prefix match missing'
r = client.get('/api/stores/lookup?q=alonedried')   # substring of first item
rows = r.get_json()
assert any(x['id'] == sid for x in rows), 'name substring match missing'
r = client.get('/api/stores/lookup?q=a')
assert len(r.get_json()) <= 25
r = client.get('/api/stores/lookup?q=x')
assert r.get_json() == []
print('4. lookup API OK (prefix, substring, cap, empty)')

# 5. form page wiring: search box + carrier field present, giant select gone
r = client.get('/transaction?category=stores')
body = r.get_data(as_text=True)
assert 'stores-search' in body and 'hidden_item_id' in body
assert '/api/stores/lookup' in body
assert body.count('<option') < 50, 'stores dropdown should not be rendered'
print('5. transaction form wiring OK')

# 6. deep-link prefill renders the selected item (carrier carries the raw id;
# JS adds the 'stores:' prefix at runtime)
r = client.get(f'/transaction?category=stores&item_id={sid}')
body = r.get_data(as_text=True)
assert f'value="{sid}"' in body, 'carrier field missing prefill id'
assert "'stores:' + it.id" in body and item['item_code'] in body
print('6. deep-link prefill OK')

# 7. restore
client.post(f'/stores/adjust/{sid}', data=json.dumps({'quantity': orig_qty}),
            content_type='application/json')
con.close()
print('\nALL TESTS PASSED')
