"""End-to-end test: printable requisition from low-ROB items.

The catalog has ~15k low items, so unfiltered views cap at the worst 500 —
tests scope with search/category filters the same way a user would.
"""
import json
import os
import re
import sys

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
items = con.execute(
    "SELECT id, item_code, name, quantity, min_stock, category FROM stores "
    "ORDER BY id LIMIT 3").fetchall()
ids = [i['id'] for i in items]
orig = {i['id']: i['quantity'] for i in items}

# Fixture: make item0 low (ROB 1), item1 healthy (ROB 50)
client.post(f'/stores/adjust/{ids[0]}', data=json.dumps({'quantity': 1}),
            content_type='application/json')
client.post(f'/stores/adjust/{ids[1]}', data=json.dumps({'quantity': 50}),
            content_type='application/json')
i0 = items[0]
sugg0 = i0['min_stock'] - 1

# 1. search-scoped view shows the low item with correct row math
r = client.get(f'/requisition?search={i0["item_code"]}')
body = r.get_data(as_text=True)
assert r.status_code == 200
assert i0['item_code'] in body, 'low item missing'
row_m = re.search(
    rf'<td class="part-num">{re.escape(i0["item_code"])}</td>.*?'
    rf'<td class="text-end" style="color:#e74c3c[^"]*;">1</td>\s*'
    rf'<td class="text-end">{i0["min_stock"]}</td>\s*'
    rf'<td class="text-end">{sugg0}</td>', body, re.S)
assert row_m, f'row math (ROB 1 / Min {i0["min_stock"]} / Suggested {sugg0}) not found'
print(f'1. row math OK: ROB 1 / Min {i0["min_stock"]} / Suggested {sugg0}')

# 2. healthy item (ROB 50 vs its min) must not be requisitioned
i1 = con.execute("SELECT name, quantity, min_stock FROM stores WHERE id=?",
                 (ids[1],)).fetchone()
assert i1['quantity'] > i1['min_stock'] and i1['name'] not in body
print('2. healthy item excluded')

# 3. blank handwriting columns + signature block
assert 'order-blank' in body and 'Order Qty' in body and 'Remarks' in body
assert 'sign-line' in body and 'Chief Engineer' in body
print('3. blank order/remarks columns + signature block present')

# 4. category grouping renders with per-category counts
assert i0['category'] in body and 'requisition-cat' in body
print('4. category grouping present')

# 5. category filter yields that category's full low list
r = client.get(f'/requisition?category={i0["category"]}')
body2 = r.get_data(as_text=True)
assert r.status_code == 200 and i0['category'] in body2
print('5. category filter OK')

# 6. truncation note when capped
r = client.get('/requisition?limit=1')
body3 = r.get_data(as_text=True)
assert 'Showing the worst' in body3 and 'include all' in body3
print('6. truncation cap note OK')

# 7. entry points wired (dashboard low-ROB panel + sidebar)
home = client.get('/').get_data(as_text=True)
assert '/requisition' in home
print('7. dashboard requisition link present')

# restore quantities
for i in items:
    client.post(f'/stores/adjust/{i["id"]}',
                data=json.dumps({'quantity': orig[i['id']]}),
                content_type='application/json')
con.close()
print('\nALL TESTS PASSED')
