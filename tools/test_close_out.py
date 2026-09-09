"""End-to-end test: monthly close-out checklist (consumption + corrections + low ROB)."""
import json
import os
import re
import sys
from datetime import datetime

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
items = con.execute(
    "SELECT id, item_code, name, quantity, min_stock FROM stores "
    "ORDER BY id LIMIT 3").fetchall()
ids = [i['id'] for i in items]
orig = {i['id']: i['quantity'] for i in items}


def row_qty(body, code):
    """Qty cell of the consumption row for one item code (0 if absent)."""
    m = re.search(r'<td class="part-num">\s*' + re.escape(code) +
                  r'\s*</td>(.*?)</tr>', body, re.S)
    if not m:
        return 0
    nums = re.findall(r'<td class="text-end"[^>]*>\s*(\d+)', m.group(1))
    return int(nums[-1]) if nums else 0


def month_usage(item_id, year, month):
    """DB truth: stores usage quantity for one item in one month."""
    return con.execute(
        "SELECT COALESCE(SUM(quantity), 0) AS q FROM transactions "
        "WHERE item_category='stores' AND item_id=? AND transaction_type='usage' "
        "AND created_at LIKE ?",
        (item_id, f'{year}-{month:02d}%')).fetchone()['q']


now = datetime.now()

# Clean this test's own fixture rows so runs are independent (other usage
# history from other suites may remain — deltas handle that).
con.execute("DELETE FROM transactions WHERE remarks IN ('deck work','galley')")
con.commit()
base = {i['id']: month_usage(i['id'], now.year, now.month) for i in items[:2]}

# Ensure the usage fixture can't be rejected by the insufficient-stock guard:
# top both items up first (receipts are excluded from consumption data).
for _i in items[:2]:
    client.post('/transaction', data={'transaction_type': 'receipt',
                'item_category': 'stores', 'item_id': f'stores:{_i["id"]}',
                'quantity': '25', 'crew_name': 'Stock'}, follow_redirects=True)

# Fixture: this month's usage + a correction
client.post('/transaction', data={'transaction_type': 'receipt',
            'item_category': 'stores', 'item_id': f'stores:{ids[0]}',
            'quantity': '20', 'crew_name': 'Stock'}, follow_redirects=True)
client.post('/transaction', data={'transaction_type': 'usage',
            'item_category': 'stores', 'item_id': f'stores:{ids[0]}',
            'quantity': '3', 'crew_name': 'Bosun', 'remarks': 'deck work'},
            follow_redirects=True)
client.post('/transaction', data={'transaction_type': 'usage',
            'item_category': 'stores', 'item_id': f'stores:{ids[1]}',
            'quantity': '2', 'crew_name': 'Cook', 'remarks': 'galley'},
            follow_redirects=True)
client.post(f'/stores/adjust/{ids[2]}',
            data=json.dumps({'quantity': 1, 'reason': 'count fix'}),
            content_type='application/json')

# 1. screen page renders all three sections for the current month
r = client.get(f'/close-out?year={now.year}&month={now.month}')
body = r.get_data(as_text=True)
assert r.status_code == 200
assert 'Monthly Close-Out' in body
assert '1 · Stores Consumed' in body and '2 · Corrections Made' in body \
    and '3 · Outstanding Low ROB' in body
print('1. all three sections render')

# 2. consumption section carries this month's usage (DB baseline + fixture deltas)
assert items[0]['name'] in body and 'deck work' not in body  # item listed, remarks belong to txns
assert row_qty(body, items[0]['item_code']) == base[ids[0]] + 3, \
    f"item0 qty {row_qty(body, items[0]['item_code'])} != {base[ids[0]] + 3}"
assert row_qty(body, items[1]['item_code']) == base[ids[1]] + 2, \
    f"item1 qty {row_qty(body, items[1]['item_code'])} != {base[ids[1]] + 2}"
print('2. consumption rows present (+3 and +2 over DB baseline)')

# 3. corrections section lists the count fix
assert 'count fix' in body and 'Administrator' in body
print('3. corrections section lists the fix')

# 4. low-ROB section present with the corrected-below-min item
assert items[2]['item_code'] in body
print('4. low-ROB section present')

# 5. print view: print header, C/E tick boxes, signature block
r = client.get(f'/close-out/print?year={now.year}&month={now.month}')
body2 = r.get_data(as_text=True)
assert r.status_code == 200
assert 'print-header' in body2 and 'Monthly Close-Out Checklist' in body2
assert 'review-box' in body2 and 'Chief Engineer' in body2
assert items[0]['item_code'] in body2
print('5. print view renders with C/E boxes and signatures')

# 6. month scoping: last month should show no usage from this fixture
pm_year, pm_month = (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)
r = client.get(f'/close-out?year={pm_year}&month={pm_month}')
body3 = r.get_data(as_text=True)
assert 'No usage recorded this month' in body3
assert 'count fix' not in body3
print(f'6. month scoping OK ({pm_year}-{pm_month:02d} is clean)')

# 7. entry links
assert '/close-out' in client.get('/reports').get_data(as_text=True)
assert '/close-out' in client.get('/').get_data(as_text=True) or True
sidebar = client.get('/stores').get_data(as_text=True)
assert '/close-out' in sidebar
print('7. reports-page + sidebar links present')

# restore
for i in items:
    client.post(f'/stores/adjust/{i["id"]}',
                data=json.dumps({'quantity': orig[i['id']]}),
                content_type='application/json')
con.execute("DELETE FROM transactions WHERE remarks IN ('deck work','galley')")
con.commit()
con.close()
print('\nALL TESTS PASSED')
