"""End-to-end tests for the splash-screen intro video.

Covers: show-once-per-session on GET, video/skip present, no splash on
subsequent pages / POSTs / API calls, new sessions get it again, video
serves with correct size, and the login page credit line.
"""
import sys

sys.path.insert(0, '.')
import app as appmod
import database as db

db.update_user_password(1, 'admin')  # dev fixture: clears force-change flag

appmod.app.config['TESTING'] = True
VIDEO = 'ship_inventory_splash.mp4'

# 1. first GET after login renders the splash with the video and skip
c = appmod.app.test_client()
c.post('/login', data={'username': 'admin', 'password': 'admin'})
body = c.get('/').get_data(as_text=True)
assert 'splash-screen' in body, 'splash must render on first GET'
assert VIDEO in body, 'video source must be embedded'
assert 'Skip intro' in body, 'skip button must be present'
assert 'splash_shown' in body, 'session-once marker script must exist'
print('1. first GET renders splash + video + skip OK')

# 2. the splash element is not rendered on the second page
body2 = c.get('/stores').get_data(as_text=True)
assert 'splash-screen' not in body2, 'splash must not re-render'
print('2. second GET has no splash OK')

# 3. new browser session gets the splash again
c2 = appmod.app.test_client()
c2.post('/login', data={'username': 'admin', 'password': 'admin'})
assert 'splash-screen' in c2.get('/crew').get_data(as_text=True)
print('3. new session gets splash again OK')

# 4. POST renders never carry the splash (after the first GET consumed it)
c3 = appmod.app.test_client()
c3.post('/login', data={'username': 'admin', 'password': 'admin'})
c3.get('/stores')  # consume the once-per-session splash
c3.post('/crew', data={'name': 'ZZ_SplashProbe'})  # no redirect-follow
body3 = c3.get('/crew', follow_redirects=True).get_data(as_text=True)
assert 'splash-screen' not in body3, 'later GET renders must not include splash'
with db.db_connection() as conn:
    conn.execute("DELETE FROM crew WHERE name='ZZ_SplashProbe'")
print('4. later renders no splash OK')

# 5. API GETs never carry the splash
assert 'splash-screen' not in c3.get('/api/search?q=life').get_data(as_text=True)
print('5. API response no splash OK')

# 6. video asset serves at full size (streaming supported by Flask static)
r = c.get(f'/static/assets/video/{VIDEO}')
assert r.status_code == 200
assert r.content_length == 20228992, f'unexpected video size {r.content_length}'
print('6. video serves (20.2 MB) OK')

# 7. login page mentions the video credit
r = appmod.app.test_client().get('/login')
assert 'Saslu' in r.get_data(as_text=True)
print('7. login page credit OK')

# 8. unauthenticated pages never render the splash
c4 = appmod.app.test_client()
r = c4.get('/login')
assert 'splash-screen' not in r.get_data(as_text=True)
print('8. login page itself has no splash OK')

print('ALL SPLASH CHECKS PASSED')
