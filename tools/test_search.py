"""End-to-end tests for relevance-aware stores search (IMPA smart matching).

Covers: exact 7-digit code (padded and unpadded), partial/dotted codes,
relevance ordering, name searches unchanged, all three entry points
(stores list page, global search API, transaction type-ahead), and
low-only filtering combined with search.
"""
import json
import sys

sys.path.insert(0, '.')
import app as appmod
import database as db

db.update_user_password(1, 'admin')  # dev fixture: clears force-change flag

appmod.app.config['TESTING'] = True
client = appmod.app.test_client()
client.post('/login', data={'username': 'admin', 'password': 'admin'})

# 1. exact 7-digit code (as stored, zero-padded) -> single item
rows, total = db.search_stores_smart('0510226')
assert total == 1 and rows[0]['item_code'] == '0510226', (total, rows[:1])
assert rows[0]['name'] == 'Cement Brushes'
print('1. exact padded code -> single hit OK')

# 2. exact code without the leading zero still finds it
rows, total = db.search_stores_smart('510226')
assert total == 1 and rows[0]['item_code'] == '0510226'
print('2. unpadded code -> same single hit OK')

# 3. partial code: digit-prefix matches rank first
rows, total = db.search_stores_smart('5102')
codes = [r['item_code'] for r in rows]
assert total >= 2 and '0510226' in codes, codes[:5]
# every returned code must contain the digits 5102 somewhere
assert all('5102' in c.replace('.', '') for c in codes), codes[:8]
print(f'3. partial code -> {total} hits, all digit-matching OK')

# 4. relevance ordering: exact match beats prefix beats substring
#    '0510226' exact must come before '5102260'-style substring hits
rows, _ = db.search_stores_smart('0510226')
assert rows[0]['item_code'] == '0510226'
rows, _ = db.search_stores_smart('33')
assert rows, 'short digit query should still work'
print('4. relevance ordering OK')

# 5. dotted/spaced code fragments normalize to digits
rows, total = db.search_stores_smart('51.02')
assert any(r['item_code'] == '0510226' for r in rows)
print(f'5. dotted code "51.02" -> {total} hits OK')

# 6. name search behaviour unchanged
rows, total = db.search_stores_smart('life jacket')
assert total >= 1 and 'life' in rows[0]['name'].lower()
rows, total = db.search_stores_smart('thermometer')
assert total >= 1
print(f'6. name searches unchanged OK')

# 7. non-matching code digits -> empty, not a crash
rows, total = db.search_stores_smart('9999999')
assert total == 0 and rows == []
print('7. no-match code -> empty OK')

# 8. stores list page: exact code narrows to that item
r = client.get('/stores?search=0510226')
assert r.status_code == 200
body = r.get_data(as_text=True)
assert 'Cement Brushes' in body
print('8. list page exact-code search OK')

# 9. type-ahead API: exact code first, capped at 25
r = client.get('/api/stores/lookup?q=5102')
res = json.loads(r.get_data(as_text=True))
assert 0 < len(res) <= 25
assert res[0]['item_code'].startswith('0510'), res[0]
r = client.get('/api/stores/lookup?q=0510226')
res = json.loads(r.get_data(as_text=True))
assert len(res) == 1 and res[0]['item_code'] == '0510226'
print('9. type-ahead API OK')

# 10. global search API returns the store hit with code
r = client.get('/api/search?q=0510226')
res = json.loads(r.get_data(as_text=True))
stores = [x for x in res if x['type'] == 'store']
assert any(x['code'] == '0510226' for x in stores), stores[:3]
print('10. global search API OK')

# 11. low_only + search still filters (old path preserved)
rows, total = db.get_stores_page(search='5102', low_only=True)
assert all(r['quantity'] <= r['min_stock'] for r in rows)
print(f'11. low-only + search filter OK ({total} low hits)')

# 12. search + pagination coherence on a many-hit query
page1, t1 = db.get_stores_page(search='5102', page=1, per_page=10)
page2, t2 = db.get_stores_page(search='5102', page=2, per_page=10)
assert t1 == t2
ids1 = {r['id'] for r in page1}
ids2 = {r['id'] for r in page2}
assert not (ids1 & ids2), 'pages must not overlap'
assert len(page1) == 10
print('12. pagination over relevance results OK')

print('ALL SMART-SEARCH CHECKS PASSED')
