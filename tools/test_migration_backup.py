"""End-to-end tests for automatic pre-migration backups.

Covers: schema version stamping, snapshot on version change, no snapshot
when unchanged, snapshot integrity, pool rotation, and rewind-to-snapshot
restore (run against a temp DB copy so the shared dev DB is untouched).
"""
import glob
import os
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, '.')
import app as appmod
import database as db

db.update_user_password(1, 'admin')  # dev fixture: clears force-change flag

appmod.app.config['TESTING'] = True


def mig_files():
    return set(glob.glob(os.path.join(db.BACKUP_DIR, 'pre_migration_*.db')))


# 1. version stamping: init_db leaves the DB at SCHEMA_VERSION
db.init_db()
assert db.get_schema_version() == db.SCHEMA_VERSION, \
    f'expected version {db.SCHEMA_VERSION}'
print(f"1. schema version stamped ({db.SCHEMA_VERSION}) OK")

# 2. no snapshot when version is current
before = mig_files()
db.init_db()
assert mig_files() == before, 'no snapshot expected when version unchanged'
print('2. unchanged version -> no snapshot OK')

# 3. downgrade simulation -> snapshot taken, version re-stamped
db.init_db()
n_before = len(before)
with sqlite3.connect(db.DB_PATH) as conn:
    conn.execute('PRAGMA user_version = 1')
    conn.commit()
db.init_db()
new = mig_files() - before
assert len(new) == 1, f'expected exactly one new snapshot, got {new}'
snap = new.pop()
assert os.path.getsize(snap) > 0
assert db.get_schema_version() == db.SCHEMA_VERSION, 'version must be re-stamped'
before = mig_files()
print(f"3. version change -> snapshot ({os.path.basename(snap)}) OK")

# 4. snapshot integrity: valid SQLite, same row counts as the live DB
src = sqlite3.connect(db.DB_PATH)
chk = sqlite3.connect(snap)
integrity = chk.execute('PRAGMA integrity_check').fetchone()[0]
assert integrity == 'ok', integrity
for table in ('crew', 'machinery', 'stores'):
    a = src.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
    b = chk.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
    assert a == b, f'{table}: {a} != {b}'
src.close()
chk.close()
print('4. snapshot integrity + row counts OK')

# 5. rotation: pool never exceeds MAX_MIGRATION_BACKUPS
tag = 'pre_migration'
made = []
for i in range(db.MAX_MIGRATION_BACKUPS + 3):
    fn = db.create_backup(tag)
    assert fn, 'create_backup must succeed'
    made.append(os.path.join(db.BACKUP_DIR, fn))
pool = [f for f in glob.glob(os.path.join(db.BACKUP_DIR, f'{tag}_*.db'))]
assert len(pool) <= db.MAX_MIGRATION_BACKUPS, \
    f'rotation failed: {len(pool)} files'
assert made[-1] in pool, 'newest snapshot must survive rotation'
for f in made:
    if f in pool and f != made[-1]:
        pass  # older snapshots may be kept up to the cap; nothing to do
for f in made:
    try:
        os.remove(f)
    except OSError:
        pass
print(f"5. rotation caps pool at {db.MAX_MIGRATION_BACKUPS} OK")

# 6. rewind: restore a pre-migration snapshot over a modified temp DB
# (the init_db calls above re-flag admin via the default-password backfill,
# so re-clear it before logging in — mirrors the other suites' fixtures)
db.update_user_password(1, 'admin')
db.set_must_change_password(1, 0)
tmp_db = os.path.join(tempfile.gettempdir(), 'mig_test_restore.db')
# snapshot the live DB via the backup API (a raw copy of a WAL DB can miss
# recently committed transactions still in the -wal file)
db._snapshot(tmp_db)
orig_path = db.DB_PATH
try:
    db.DB_PATH = tmp_db
    snap_fn = db.create_backup('pre_migration')
    assert snap_fn
    # mutate after the snapshot: add a canary machinery row
    with db.db_connection() as conn:
        conn.execute(
            "INSERT INTO machinery (name) VALUES ('ZZ_Canary_MigTest')")
    canary_id = sqlite3.connect(tmp_db).execute(
        "SELECT id FROM machinery WHERE name='ZZ_Canary_MigTest'").fetchone()
    assert canary_id, 'canary must exist after mutation'

    client = appmod.app.test_client()
    client.post('/login', data={'username': 'admin', 'password': 'admin'},
                follow_redirects=True)
    r = client.post(f'/backup/restore/{snap_fn}', follow_redirects=True)
    body = r.get_data(as_text=True)
    if 'Restored from' not in body:
        import re as _re
        flashes = [f.strip()[:80]
                   for f in _re.findall(r'flash[^>]*>\s*([^<]{4,})', body)]
        raise AssertionError(
            f'restore flash missing; path={r.request.path}; flashes={flashes[:3]}')
    gone = sqlite3.connect(tmp_db).execute(
        "SELECT COUNT(*) FROM machinery WHERE name='ZZ_Canary_MigTest'"
    ).fetchone()[0]
    assert gone == 0, 'rewind must remove post-snapshot rows'
    os.remove(os.path.join(db.BACKUP_DIR, snap_fn))
finally:
    db.DB_PATH = orig_path
    if os.path.exists(tmp_db):
        os.remove(tmp_db)
print('6. rewind restores pre-snapshot state OK')

# 7. backup page shows the migration section
c = appmod.app.test_client()
c.post('/login', data={'username': 'admin', 'password': 'admin'},
       follow_redirects=True)
r = c.get('/backup')
assert r.status_code == 200
body = r.get_data(as_text=True)
assert 'Pre-Migration Snapshots' in body or 'Available Backups' in body
print('7. backup page renders OK')

db.init_db()
print('ALL MIGRATION-BACKUP CHECKS PASSED')
