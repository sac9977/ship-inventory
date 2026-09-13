"""End-to-end tests for the security settings page and session registry.

Covers: session registration/validation, revocation via admin password
reset, per-user last-login + session listing, policy card, history,
guards (self-revoke blocked, non-admin blocked).
Runs against the shared dev DB; fixture rows are cleaned for idempotency.
"""
import sys
import re

sys.path.insert(0, '.')
import app as appmod
import database as db

db.update_user_password(1, 'admin')  # dev fixture: clears force-change flag

appmod.app.config['TESTING'] = True
client = appmod.app.test_client()

CREW_NAME = 'ZZ_SecPage_User'


def cleanup():
    with db.db_connection() as conn:
        conn.execute("DELETE FROM crew WHERE name LIKE ?", (CREW_NAME + '%',))
        conn.execute("DELETE FROM crew WHERE username = 'zz_sec_user'")
        conn.execute("DELETE FROM user_sessions WHERE user_id NOT IN (SELECT id FROM crew)")


def login_admin():
    client.get('/logout')
    return client.post('/login', data={'username': 'admin', 'password': 'admin'},
                       follow_redirects=True)


cleanup()

# 1. login registers a session in the registry
r = client.post('/login', data={'username': 'admin', 'password': 'admin'},
                follow_redirects=True)
assert r.status_code == 200
with client.session_transaction() as sess:
    admin_token = sess.get(appmod.SESSION_TOKEN_KEY)
assert admin_token, 'login must set a registry token cookie-side'
assert db.is_session_valid(admin_token, 1), 'token must be registered + active'
sess_row = [s for s in db.get_active_sessions(1) if s['session_token'] == admin_token]
assert sess_row, 'active session row must exist for admin'
print('1. login registers server-side session OK')

# 2. validation hook keeps valid sessions working
r = client.get('/security')
assert r.status_code == 200
body = r.get_data(as_text=True)
assert 'Password Policy' in body and 'Account Security by User' in body
print('2. valid session passes validation hook OK')

# 3. a cookie with an unknown/revoked token is bounced to login
client.get('/logout')
assert not db.is_session_valid(admin_token, 1), 'logout must revoke the row'
r = client.post('/login', data={'username': 'admin', 'password': 'admin'},
                follow_redirects=True)
with client.session_transaction() as sess:
    tok2 = sess.get(appmod.SESSION_TOKEN_KEY)
assert tok2 and tok2 != admin_token, 'each login gets a fresh token'
print('3. logout revokes; fresh token on re-login OK')

# 4. tampered token -> session cleared and redirected to login
with client.session_transaction() as sess:
    sess[appmod.SESSION_TOKEN_KEY] = 'forged-token-not-in-registry'
r = client.get('/stores', follow_redirects=False)
assert r.status_code == 302 and '/login' in r.headers['Location'], \
    'invalid token must bounce to login'
with client.session_transaction() as sess:
    assert 'user_id' not in sess, 'session must be cleared on invalid token'
print('4. forged token rejected, session cleared OK')

# 5. create a user, log them in, then admin reset revokes their session
login_admin()
r = client.post('/crew', data={
    'name': CREW_NAME, 'username': 'zz_sec_user',
    'password': 'Str0ngPass!42', 'role': 'user'}, follow_redirects=True)
uid = db.get_crew_by_username('zz_sec_user')['id']

client.get('/logout')
client.post('/login', data={'username': 'zz_sec_user', 'password': 'Str0ngPass!42'},
            follow_redirects=True)
with client.session_transaction() as sess:
    user_token = sess[appmod.SESSION_TOKEN_KEY]
assert db.is_session_valid(user_token, uid)
# touch so last_seen is populated
client.get('/', follow_redirects=True)

# admin reset -> all target sessions revoked
login_admin()
r = client.post(f'/crew/reset-password/{uid}',
                data={'new_password': 'Temp0rary!99'}, follow_redirects=True)
assert not db.is_session_valid(user_token, uid), \
    'admin reset must revoke the target user sessions'
ll = db.get_last_logins()
assert uid in ll and ll[uid]['last_login'], 'last login recorded for the user'
print('5. admin reset revokes user sessions; last-login recorded OK')

# 6. security page shows the user with sessions none + change-due badge
r = client.get('/security')
body = r.get_data(as_text=True)
assert 'Password change due' in body, 'flagged user badge must show'
assert 'never logged in' not in body, 'user had logins, should show a time'
print('6. page reflects flag + last-login OK')

# 7. history table lists the logins we made
hist = db.get_login_history(limit=20)
assert len(hist) >= 4, f'expected several history rows, got {len(hist)}'
assert any(h['username'] == 'zz_sec_user' for h in hist)
r = client.get('/security')
assert 'Recent Login Activity' in r.get_data(as_text=True)
print('7. login history populated OK')

# 8. self-revoke is blocked
live = [s for s in db.get_active_sessions(1)
        if s['session_token'] == tok2 or s['session_token']]
# find the admin's current session row id
with client.session_transaction() as sess:
    cur_token = sess[appmod.SESSION_TOKEN_KEY]
mine = next(s for s in db.get_active_sessions(1) if s['session_token'] == cur_token)
r = client.post(f'/security/revoke/{mine["id"]}', follow_redirects=True)
assert 'cannot revoke the session' in r.get_data(as_text=True)
assert db.is_session_valid(cur_token, 1), 'own session must survive'
print('8. self-revoke blocked OK')

# 9. revoking another session kills it
# user logs in again (temp password); the client stays as the user from here
client.get('/logout')
client.post('/login', data={'username': 'zz_sec_user', 'password': 'Temp0rary!99'},
            follow_redirects=True)
with client.session_transaction() as sess:
    t2 = sess[appmod.SESSION_TOKEN_KEY]
assert db.is_session_valid(t2, uid)
victim = next(s for s in db.get_active_sessions(uid) if s['session_token'] == t2)

# a second client acts as admin (so the user's session stays alive until revoked)
admin2 = appmod.app.test_client()
r = admin2.post('/login', data={'username': 'admin', 'password': 'admin'},
                follow_redirects=True)
assert r.status_code == 200
r = admin2.post(f'/security/revoke/{victim["id"]}', follow_redirects=True)
assert 'revoked' in r.get_data(as_text=True)
assert not db.is_session_valid(t2, uid), 'revoked session must be invalid'
# the revoked user's very next request is bounced to login
r = client.get('/', follow_redirects=False)
assert r.status_code == 302 and '/login' in r.headers['Location'], \
    'revoked user must be bounced at next request'
print('9. admin revokes another user session; victim bounced OK')

# 10. non-admin cannot reach the page (complete forced change first)
client.post('/login', data={'username': 'zz_sec_user', 'password': 'Temp0rary!99'},
            follow_redirects=True)
client.post('/change-password', data={
    'current_password': 'Temp0rary!99',
    'new_password': 'Br4ndNew!Pass7', 'confirm_password': 'Br4ndNew!Pass7'},
    follow_redirects=True)
r = client.get('/security', follow_redirects=True)
assert 'Admin access required' in r.get_data(as_text=True)
print('10. non-admin blocked OK')

cleanup()
print('ALL SECURITY-PAGE CHECKS PASSED')
