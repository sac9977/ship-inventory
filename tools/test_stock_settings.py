"""End-to-end test: min-stock settings page, default application, low-ROB alerts."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as appmod  # noqa: E402
import database as db  # noqa: E402

client = appmod.app.test_client()

# login as admin
r = client.post('/login', data={'username': 'admin', 'password': 'admin'},
                follow_redirects=True)
assert r.status_code == 200
print('1. login OK')

con = __import__('sqlite3').connect(db.DB_PATH)
con.row_factory = __import__('sqlite3').Row

# 2. settings table seeded with defaults
s = db.get_stock_settings()
assert s['default'] >= 0 and isinstance(s['categories'], dict), s
assert 'Provisions' in s['categories']
print(f"2. settings OK (default={s['default']}, {len(s['categories'])} categories)")

# 3. apply defaults: all 14862 items had min_stock=0
updated = db.apply_min_stock_defaults()
total_unset = con.execute("SELECT COUNT(*) FROM stores WHERE min_stock = 0").fetchone()[0]
print(f'3. applied defaults: {updated} rows updated, {total_unset} still unset')
assert total_unset == 0, 'some rows missed'

# distribution sanity
dist = con.execute(
    "SELECT min_stock, COUNT(*) c FROM stores GROUP BY min_stock ORDER BY c DESC"
).fetchall()
print('   min-stock distribution (top 6):',
      [(r['min_stock'], r['c']) for r in dist[:6]])

# 4. manual min-stock survives re-apply
con.execute("UPDATE stores SET min_stock = 9 WHERE id = 1")
con.commit()
db.apply_min_stock_defaults()
val = con.execute("SELECT min_stock FROM stores WHERE id = 1").fetchone()[0]
assert val == 9, f'manual edit clobbered: {val}'
print('4. manual min-stock edit survives re-apply')

# 5. low-ROB detection: set some quantities
con.execute("UPDATE stores SET quantity = 0 WHERE id IN (1, 2, 3)")
con.commit()
low = db.get_low_stock_stores()
low_count = db.count_low_stock_stores()
print(f'5. low-ROB: {low_count} items, first: {low[0]["name"] if low else None}')
assert low_count >= 3
assert all(i['quantity'] <= i['min_stock'] for i in low), 'ordering/filter broken'
# worst-first ordering (lowest ratio first)
ratios = [i['quantity'] / i['min_stock'] for i in low]
assert ratios == sorted(ratios), 'not sorted worst-first'

# 6. dashboard renders with low panel
r = client.get('/')
body = r.get_data(as_text=True)
assert 'Low ROB' in body and '/stores?low=1' in body, 'dashboard panel missing'
print('6. dashboard low-ROB panel renders')

# 7. low-only stores view
r = client.get('/stores?low=1')
body = r.get_data(as_text=True)
assert 'Low ROB view' in body
print('7. /stores?low=1 view renders')

# 8. stock settings page renders and saves
r = client.get('/stock-settings')
assert r.status_code == 200 and b'Global default' in r.get_data()
r = client.post('/stock-settings', data={
    'default_min': '3',
    'cat_Provisions': '7',
}, follow_redirects=True)
s2 = db.get_stock_settings()
assert s2['default'] == 3 and s2['categories']['Provisions'] == 7
print('8. stock settings page: render + save OK')

# restore settings
db.save_stock_settings(s['default'], s['categories'])
con.close()
print('\nALL TESTS PASSED')
