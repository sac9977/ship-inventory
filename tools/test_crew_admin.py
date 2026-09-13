"""End-to-end tests for crew account management (create/reset/deactivate).

Runs against the shared dev DB like the other suites; fixture rows are
cleaned up at start so the suite is idempotent across repeated runs.
"""
import sys

sys.path.insert(0, '.')
import app as appmod
import database as db

db.update_user_password(1, 'admin')  # dev fixture: clears force-change flag

appmod.app.config['TESTING'] = True
client = appmod.app.test_client()

CREW_NAME = 'ZZ_TestSailor_CrewAdmin'


def cleanup():
    with db.db_connection() as conn:
        conn.execute("DELETE FROM crew WHERE name LIKE ?", (CREW_NAME + '%',))
        conn.execute("DELETE FROM crew WHERE username IN ('zz_test_sailor', 'zz_weak_pw')")


cleanup()


def login_admin():
    client.get('/logout')
    return client.post('/login', data={'username': 'admin', 'password': 'admin'},
                       follow_redirects=True)


# 1. login as admin
r = login_admin()
assert r.status_code == 200, r.status_code
print('1. admin login OK')

# 2. create a crew member with login
r = client.post('/crew', data={
    'name': CREW_NAME, 'rank': 'AB', 'username': 'zz_test_sailor',
    'password': 'Str0ngPass!42', 'role': 'user'}, follow_redirects=True)
assert r.status_code == 200, r.status_code
assert 'added' in r.get_data(as_text=True)
row = db.get_crew_by_username('zz_test_sailor')
assert row and row['active'] == 1, 'crew member should be created active'
assert row['password_hash'], 'password should be set'
print('2. create with login OK')

# 3. duplicate username is rejected (with helpful message)
r = client.post('/crew', data={
    'name': CREW_NAME + '2', 'username': 'zz_test_sailor',
    'role': 'user'}, follow_redirects=True)
body = r.get_data(as_text=True)
assert 'already belongs' in body, 'duplicate username should be flagged'
assert db.get_crew_by_username('zz_test_sailor')['name'] == CREW_NAME, \
    'no second account should be created'
print('3. duplicate username rejected OK')

# 4. weak password on create is rejected
r = client.post('/crew', data={
    'name': CREW_NAME + '3', 'username': 'zz_weak_pw',
    'password': 'password', 'role': 'user'}, follow_redirects=True)
body = r.get_data(as_text=True)
assert 'at least 8 characters' in body, 'weak password should be flagged'
assert db.get_crew_by_username('zz_weak_pw') is None, 'weak-pw account must not exist'
print('4. weak password rejected OK')

# 5. new user can log in with the created credentials
client.get('/logout')
r = client.post('/login', data={'username': 'zz_test_sailor',
                                'password': 'Str0ngPass!42'},
                follow_redirects=True)
body = r.get_data(as_text=True)
assert 'dashboard' in body.lower(), 'new crew login should reach the dashboard'
print('5. new user login OK')

# 6. admin resets the user's password -> forced change at next login
login_admin()
uid = row['id']
r = client.post(f'/crew/reset-password/{uid}',
                data={'new_password': 'Temp0rary!Pass'}, follow_redirects=True)
body = r.get_data(as_text=True)
assert 'must change it at next login' in body, 'reset flash missing'
target = db.get_user(uid)
assert target['must_change_password'] == 1, 'flag should be set after reset'
old_hash = target['password_hash']

# reset user cannot use the temp password without changing it
client.get('/logout')
r = client.post('/login', data={'username': 'zz_test_sailor',
                                'password': 'Temp0rary!Pass'},
                follow_redirects=True)
assert '/change-password' in r.request.path, \
    'flagged user must be confined to the change-password form'
print('6. reset forces change at next login OK')

# 7. reset to the current password is rejected
login_admin()
r = client.post(f'/crew/reset-password/{uid}',
                data={'new_password': 'Temp0rary!Pass'}, follow_redirects=True)
body = r.get_data(as_text=True)
assert 'must differ' in body, 'same-as-current reset should be rejected'
assert db.get_user(uid)['password_hash'] == old_hash, 'hash must be unchanged'
print('7. same-password reset rejected OK')

# complete the forced change to keep state tidy
client.get('/logout')
r = client.post('/login', data={'username': 'zz_test_sailor',
                                'password': 'Temp0rary!Pass'},
                follow_redirects=True)
r = client.post('/change-password', data={
    'current_password': 'Temp0rary!Pass',
    'new_password': 'Br4ndNew!Pass9', 'confirm_password': 'Br4ndNew!Pass9'},
    follow_redirects=True)
assert db.get_user(uid)['must_change_password'] == 0

# 8. deactivated user cannot log in
login_admin()
r = client.post(f'/crew/delete/{uid}', follow_redirects=True)
body = r.get_data(as_text=True)
assert 'deactivated' in body, 'deactivate flash missing'
assert db.get_user(uid)['active'] == 0
client.get('/logout')
r = client.post('/login', data={'username': 'zz_test_sailor',
                                'password': 'Br4ndNew!Pass9'})
body = r.get_data(as_text=True)
assert 'Invalid username or password' in body, 'deactivated login must fail'
print('8. deactivated login blocked OK')

# 9. self-deactivation guard
login_admin()
r = client.post('/crew/delete/1', follow_redirects=True)
body = r.get_data(as_text=True)
assert 'cannot deactivate your own account' in body.lower(), \
    'self-deactivation should be blocked'
assert db.get_user(1)['active'] == 1, 'admin must remain active'
print('9. self-deactivation guard OK')

# 10. re-enable restores login
r = client.post(f'/crew/toggle-active/{uid}', follow_redirects=True)
body = r.get_data(as_text=True)
assert 're-enabled' in body, 're-enable flash missing'
assert db.get_user(uid)['active'] == 1
client.get('/logout')
r = client.post('/login', data={'username': 'zz_test_sailor',
                                'password': 'Br4ndNew!Pass9'},
                follow_redirects=True)
assert r.request.path == '/', 're-enabled user should reach dashboard'
print('10. re-enable + login OK')

# 11. non-admin cannot access crew management
client.get('/logout')
r = client.post('/login', data={'username': 'zz_test_sailor',
                                'password': 'Br4ndNew!Pass9'},
                follow_redirects=True)
r = client.get('/crew', follow_redirects=True)
body = r.get_data(as_text=True)
assert 'Admin access required' in body, 'non-admin must be blocked from /crew'
print('11. non-admin blocked OK')

cleanup()
print('ALL CREW-ADMIN CHECKS PASSED')
