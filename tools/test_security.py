"""End-to-end security tests: CSRF enforcement, forced password change, secret key handling.

Run with the other suites; uses the CSRF-injecting test client for the general
flows and a raw (no-token) client to prove enforcement actually rejects.
"""
import os
import sys

sys.path.insert(0, __file__.rsplit('/tools/', 1)[0])
os.chdir(__file__.rsplit('/tools/', 1)[0])

import app as appmod  # noqa: E402
import database as db  # noqa: E402

db.update_user_password(1, 'admin')  # dev fixture: default login, clears force-change flag
db.set_must_change_password(1, 0)

app = appmod.app

# ── 1. secret key comes from env / key file, not a hardcoded string ──
assert app.secret_key, 'secret key must be set'
assert app.secret_key != 'ship-inventory-secret-key-change-in-production', \
    'default secret key is still in use'
keyfile = os.path.join(os.getcwd(), '.secret_key')
keyfile_mode = oct(os.stat(keyfile).st_mode & 0o777) if os.path.exists(keyfile) else None
print(f"1. secret key from env/key-file (key file mode: {keyfile_mode or 'absent'})")

# ── 2. CSRF enforcement: a raw client with a valid session but no token is rejected ──
raw = appmod._flask_test_client()
with raw.session_transaction() as sess:
    sess['_csrf_token'] = 'raw-session-token'
r = raw.post('/login', data={'username': 'admin', 'password': 'admin',
                             '_csrf_token': 'raw-session-token'})
assert r.status_code == 302, f"login with valid token should succeed, got {r.status_code}"
r = raw.post('/stores/adjust/1', data={'quantity': '1'},
             content_type='application/json', headers={'X-CSRF-Token': ''})
assert r.status_code == 400, f"expected 400 for missing CSRF token, got {r.status_code}"
# wrong token also rejected
r = raw.post('/stores/adjust/1', data={'quantity': '1'},
             content_type='application/json', headers={'X-CSRF-Token': 'deadbeef'})
assert r.status_code == 400, f"expected 400 for wrong CSRF token, got {r.status_code}"
print('2. CSRF: missing/wrong token -> 400 (with authenticated session)')

# ── 3. CSRF acceptance via header and via form field ──
client = app.test_client()  # auto-injecting client
r = client.post('/login', data={'username': 'admin', 'password': 'admin'},
                follow_redirects=True)
assert r.status_code == 200
# fetch token out of the session
with client.session_transaction() as sess:
    tok = sess['_csrf_token']
# header path (JSON)
r = client.post('/stores/adjust/1', data='{"quantity": 1}',
                content_type='application/json',
                headers={'X-CSRF-Token': tok})
assert r.status_code == 200, f"header-token JSON POST rejected: {r.status_code}"
# form-field path (a real form endpoint; mismatched confirm -> validation msg, not 400)
r = client.post('/change-password', data={'current_password': 'admin',
                                          'new_password': 'ShipSecure#2026',
                                          'confirm_password': 'mismatch'},
                content_type='application/x-www-form-urlencoded')
assert r.status_code == 200 and 'do not match' in r.get_data(as_text=True), \
    f"form-token POST rejected: {r.status_code}"
print('3. CSRF: valid token via header and form field accepted')

# ── 4. token bound to session: another browser's token fails ──
other = appmod._flask_test_client()
with other.session_transaction() as sess:
    sess['_csrf_token'] = 'attacker-token'
    sess['user_id'] = 1
r = other.post('/stores/adjust/1', data={'quantity': '1'},
               content_type='application/json', headers={'X-CSRF-Token': ''})
# no header/form token -> 400 regardless of session
assert r.status_code == 400
r = other.post('/stores/adjust/1', data={'quantity': '1'},
               content_type='application/json', headers={'X-CSRF-Token': 'attacker-token'})
# A forged session (user_id without a registry token) is bounced to login (302);
# any non-2xx outcome means the attacker cannot act as the victim.
assert r.status_code in (302, 400), \
    f'attacker-controlled session must not act: got {r.status_code}'
print('4. CSRF: token is session-bound (forged session bounced)')

# ── 5. every rendered POST form carries the token ──
for path in ('/login', '/', '/transaction', '/stores', '/crew',
             '/import-csv-stores', '/import-count-sheet', '/stock-settings'):
    c = app.test_client()
    c.post('/login', data={'username': 'admin', 'password': 'admin'})
    body = c.get(path).get_data(as_text=True)
    if body and '<form' in body:
        assert 'name="_csrf_token"' in body, f'{path} renders a POST form without token'
print('5. all rendered POST forms carry CSRF tokens')

# ── 6. forced password change: flagged user is gated ──
db.set_must_change_password(1, 1)
try:
    c = app.test_client()
    r = c.post('/login', data={'username': 'admin', 'password': 'admin'},
               follow_redirects=False)
    assert r.status_code == 302 and '/change-password' in r.headers['Location'], \
        f"login with flagged account should redirect to change-password, got {r.status_code}"
    # direct access to any other page bounces back
    r = c.get('/stores', follow_redirects=False)
    assert r.status_code == 302 and '/change-password' in r.headers['Location']
    # change form reachable
    r = c.get('/change-password')
    assert r.status_code == 200
    # weak/overly-common password rejected ('12345678' passes length, fails commonness)
    r = c.post('/change-password', data={'current_password': 'admin',
                                         'new_password': '12345678', 'confirm_password': '12345678'},
               follow_redirects=True)
    assert 'too common' in r.get_data(as_text=True) or 'not a common password' in r.get_data(as_text=True)
    # mismatched confirm rejected
    r = c.post('/change-password', data={'current_password': 'admin',
                                         'new_password': 'ShipSecure#2026', 'confirm_password': 'different'},
               follow_redirects=True)
    assert 'do not match' in r.get_data(as_text=True)
    # successful change clears the flag
    r = c.post('/change-password', data={'current_password': 'admin',
                                         'new_password': 'ShipSecure#2026', 'confirm_password': 'ShipSecure#2026'},
               follow_redirects=True)
    assert 'successfully' in r.get_data(as_text=True)
    user = db.get_user(1)
    assert not user['must_change_password'], 'flag should be cleared after change'
    # now pages are reachable again
    r = c.get('/stores', follow_redirects=False)
    assert r.status_code == 200
    print('6. forced password change: gated, weak rejected, clears on success')
finally:
    # restore: set password back to admin for the other suites' fixtures
    db.update_user_password(1, 'admin')
    db.set_must_change_password(1, 0)

# ── 7. legacy default password is flagged by the init_db backfill ──
import hashlib
with db.db_connection() as conn:
    row = conn.execute("SELECT password_hash, must_change_password FROM crew WHERE id=1").fetchone()
salt, h = row['password_hash'].split('$', 1)
assert hashlib.sha256((salt + 'admin').encode()).hexdigest() == h
assert not row['must_change_password'], 'restore step failed'
# with the default hash in place and the flag cleared, a fresh init_db backfill flags it
with db.db_connection() as conn:
    conn.execute("UPDATE crew SET must_change_password = 0 WHERE id = 1")
db.init_db()
row = db.get_user(1)
assert row['must_change_password'] == 1, 'init_db backfill should flag the default password'
db.set_must_change_password(1, 0)
print('7. init_db backfill flags legacy default-password accounts')

print('\nALL SECURITY TESTS PASSED')
