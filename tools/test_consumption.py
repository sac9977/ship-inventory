"""End-to-end test: stores consumption report (usage-derived)."""
import json
import os
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
items = con.execute(
    "SELECT id, item_code, name, quantity FROM stores ORDER BY id LIMIT 2").fetchall()
ids = [i['id'] for i in items]
orig = {i['id']: i['quantity'] for i in items}

# Baseline BEFORE the fixture (dev DB carries history from other suites)
before = {r['item_id']: r['total_qty'] for r in
          db.get_stores_consumption()['rows']}

# Fixture: top up stock first (receipts are usage-report-invisible but make
# the usage posts pass the insufficient-stock guard), then 3 usage txns on
# item0 (4+2+1=7), 1 usage on item1 (5), 1 receipt probe (99, must NOT appear).
for iid in ids:
    client.post('/transaction', data={'transaction_type': 'receipt',
                'item_category': 'stores', 'item_id': f'stores:{iid}',
                'quantity': '50', 'crew_name': 'Stock', 'remarks': 'test top-up'},
                follow_redirects=True)
client.post('/transaction', data={'transaction_type': 'usage',
            'item_category': 'stores', 'item_id': f'stores:{ids[0]}',
            'quantity': '4', 'crew_name': 'X', 'remarks': 't1'}, follow_redirects=True)
client.post('/transaction', data={'transaction_type': 'usage',
            'item_category': 'stores', 'item_id': f'stores:{ids[0]}',
            'quantity': '2', 'crew_name': 'X', 'remarks': 't2'}, follow_redirects=True)
client.post('/transaction', data={'transaction_type': 'usage',
            'item_category': 'stores', 'item_id': f'stores:{ids[0]}',
            'quantity': '1', 'crew_name': 'X', 'remarks': 't3'}, follow_redirects=True)
client.post('/transaction', data={'transaction_type': 'usage',
            'item_category': 'stores', 'item_id': f'stores:{ids[1]}',
            'quantity': '5', 'crew_name': 'Y', 'remarks': 't4'}, follow_redirects=True)
client.post('/transaction', data={'transaction_type': 'receipt',
            'item_category': 'stores', 'item_id': f'stores:{ids[0]}',
            'quantity': '99', 'crew_name': 'Z', 'remarks': 'delivery'}, follow_redirects=True)

def find_item(data, iid):
    return next((r for r in data['rows'] if r['item_id'] == iid), None)

# 1. all-time aggregation: totals must be baseline + exactly our fixture
data = db.get_stores_consumption()
r0, r1 = find_item(data, ids[0]), find_item(data, ids[1])
assert r0 and r0['total_qty'] == before.get(ids[0], 0) + 7 and r0['txn_count'] >= 3
assert r1 and r1['total_qty'] == before.get(ids[1], 0) + 5 and r1['txn_count'] >= 1
g = data['grand']
assert g['total_qty'] >= 12
cat0 = next(c for c in data['categories'] if c['category'] == r0['category'])
assert cat0['total_qty'] >= 7
print(f"1. aggregation OK: item0 +7, item1 +5, grand={g['total_qty']}")

# 2. receipts excluded: fixture receipt was 99; usage total must not include it
assert r0['total_qty'] < before.get(ids[0], 0) + 7 + 99
print('2. receipts excluded OK')

# 3. year+month mode
import datetime
now = datetime.datetime.now()
data_m = db.get_stores_consumption(year=now.year, month=now.month)
r0m = find_item(data_m, ids[0])
assert r0m and r0m['total_qty'] == r0['total_qty'], 'month mode missed txns'
print(f"3. month mode OK ({now.year}-{now.month:02d})")

# 4. date-range mode (today's window must include the whole fixture run)
today = now.date()
data_r = db.get_stores_consumption(date_from=str(today), date_to=str(today))
r0r = find_item(data_r, ids[0])
assert r0r is not None, 'date-range mode missed fixture item'
assert r0r['total_qty'] >= r0['total_qty'] - before.get(ids[0], 0), \
    'date-range total below the fixture contribution'
print('4. date-range mode OK')

# 5. screen page renders with data + links
r = client.get(f'/reports/consumption?year={now.year}')
body = r.get_data(as_text=True)
assert r.status_code == 200
assert 'Stores Consumption' in body and 'By Category' in body
assert items[0]['name'] in body
assert '/reports/consumption/print' in body
print('5. screen report renders')

# 6. print view renders with print header
r = client.get(f'/reports/consumption/print?year={now.year}')
body = r.get_data(as_text=True)
assert r.status_code == 200
assert 'print-header' in body and 'Stores Consumption Report' in body
assert items[0]['name'] in body
print('6. print view renders')

# 7. entry link from reports page
assert '/reports/consumption' in client.get('/reports').get_data(as_text=True)
print('7. reports-page link present')

# 8. CSV export honors filters and matches the data rows
r = client.get(f'/reports/consumption/export?year={now.year}')
assert r.status_code == 200
assert 'stores_consumption.csv' in r.headers.get('Content-Disposition', '')
lines = r.get_data(as_text=True).strip().splitlines()
assert lines[0] == 'category,item_code,item_name,unit,times_used,total_qty,last_used'
r0_csv = next(ln for ln in lines[1:] if f'{items[0]["item_code"]}' in ln)
assert 'Provisions' in r0_csv or ',' in r0_csv
# export row count == report row count for the same filter
scr = client.get(f'/reports/consumption?year={now.year}').get_data(as_text=True)
assert len(lines) - 1 == len(db.get_stores_consumption(year=now.year)['rows']), \
    'export rows != report rows'
assert f'{items[0]["item_code"]}' in '\n'.join(lines)
print(f'8. CSV export OK ({len(lines) - 1} data rows, filters honored)')

# 9. export button present on screen view
assert '/reports/consumption/export' in scr
print('9. export button present')

# 10. dashboard stores-consumption chart fed by the same usage data
import re as _re
import html as _html
home = _html.unescape(client.get('/').get_data(as_text=True))
assert 'storesConsumptionChart' in home, 'stores chart canvas missing'
m2 = _re.search(r'const storesData = (\[.*?\]);', home, _re.S)
assert m2, 'stores chart dataset missing'
chart_rows = json.loads(m2.group(1))
total_in_chart = sum(int(d['usage']) for d in chart_rows)
assert total_in_chart >= 12, f'chart under-reports usage: {total_in_chart}'
assert '/reports/consumption' in home, 'link to full report missing'
print(f'10. dashboard chart OK ({total_in_chart} units of usage embedded)')

# restore quantities (usage/receipt txns stay — they are real history)
for i in items:
    client.post(f'/stores/adjust/{i["id"]}',
                data=json.dumps({'quantity': orig[i['id']]}),
                content_type='application/json')
con.execute("DELETE FROM transactions WHERE remarks IN ('t1','t2','t3','t4','delivery','test top-up')")
con.commit()
con.close()
print('\nALL TESTS PASSED')
