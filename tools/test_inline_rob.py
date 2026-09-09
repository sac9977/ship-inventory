"""End-to-end test: inline ROB editing endpoint + audit trail + page wiring."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as appmod  # noqa: E402
import database as db  # noqa: E402
db.update_user_password(1, 'admin')  # dev fixture: default login, clears force-change flag


client = appmod.app.test_client()

# unauthenticated is rejected
r = client.post('/stores/adjust/1', data=json.dumps({'quantity': 3}),
                content_type='application/json')
assert r.status_code == 302, f'expected login redirect, got {r.status_code}'
print('1. unauthenticated adjust blocked (302)')

# login
r = client.post('/login', data={'username': 'admin', 'password': 'admin'},
                follow_redirects=True)
assert r.status_code == 200

con = __import__('sqlite3').connect(db.DB_PATH)
con.row_factory = __import__('sqlite3').Row
row = con.execute(
    "SELECT id, quantity, min_stock FROM stores ORDER BY id LIMIT 1").fetchone()
sid, old_qty, min_stock = row['id'], row['quantity'], row['min_stock']

# 2. successful adjust
r = client.post(f'/stores/adjust/{sid}',
                data=json.dumps({'quantity': 7, 'reason': 'count correction'}),
                content_type='application/json')
d = r.get_json()
assert r.status_code == 200 and d['ok'], d
assert d['old_quantity'] == old_qty and d['quantity'] == 7
assert d['low'] == (7 <= min_stock and min_stock > 0)
print(f"2. adjust OK: {old_qty} -> 7 (low={d['low']})")

# 3. audit row logged with user attribution
audit = con.execute(
    "SELECT * FROM stock_corrections WHERE item_id = ? "
    "ORDER BY id DESC LIMIT 1", (sid,)).fetchone()
assert audit and audit['old_quantity'] == old_qty and audit['new_quantity'] == 7
assert audit['corrected_by'] == 'Administrator'
assert audit['reason'] == 'count correction'
print('3. audit row logged:', dict(audit))

# 4. validation errors
for payload, desc in [({'quantity': -1}, 'negative'),
                      ({'quantity': 'abc'}, 'non-integer'),
                      ({}, 'missing quantity')]:
    r = client.post(f'/stores/adjust/{sid}', data=json.dumps(payload),
                    content_type='application/json')
    d = r.get_json()
    assert r.status_code == 400 and not d['ok'], (desc, d)
    print(f"4. {desc} rejected: {d['error']}")

# 5. unknown item
r = client.post('/stores/adjust/999999', data=json.dumps({'quantity': 1}),
                content_type='application/json')
assert r.status_code == 400 and r.get_json()['error'] == 'Item not found'
print('5. unknown item rejected')

# 6. same-value no-op succeeds without new audit row
count_before = con.execute("SELECT COUNT(*) FROM stock_corrections").fetchone()[0]
r = client.post(f'/stores/adjust/{sid}', data=json.dumps({'quantity': 7}),
                content_type='application/json')
assert r.status_code == 200 and r.get_json()['ok']
con2 = __import__('sqlite3').connect(db.DB_PATH)
count_after = con2.execute("SELECT COUNT(*) FROM stock_corrections").fetchone()[0]
assert count_after == count_before, 'no-op should not log audit row'
print('6. same-value no-op does not log audit')

# 7. pages carry the inline editor hooks
r = client.get('/stores')
assert b'rob-cell' in r.get_data() and b'data-id=' in r.get_data()
assert b'inline_rob.js' in r.get_data()
r = client.get('/')
assert b'rob-cell' in r.get_data() and b'inline_rob.js' in r.get_data()
assert b'data-rob-autorefresh' in r.get_data()
print('7. stores list + dashboard wired for inline editing')

# cleanup: restore original quantity
client.post(f'/stores/adjust/{sid}', data=json.dumps({'quantity': old_qty}),
            content_type='application/json')
con2.close()
con.close()
print('\nALL TESTS PASSED')
