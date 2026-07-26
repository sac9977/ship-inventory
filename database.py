"""
Ship Inventory Database Layer
Handles all SQLite operations for spares, stores, machinery, and transactions.
"""
import sqlite3
import os
from datetime import datetime, date
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ship_inventory.db')


def get_db():
    """Get a database connection with row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def db_connection():
    """Context manager for database connections."""
    conn = get_db()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Initialize the database schema."""
    with db_connection() as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS machinery (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                manufacturer TEXT DEFAULT '',
                model TEXT DEFAULT '',
                description TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS spare_parts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                machinery_id INTEGER NOT NULL,
                part_number TEXT DEFAULT '',
                drawing_number TEXT DEFAULT '',
                description TEXT NOT NULL,
                quantity INTEGER DEFAULT 0,
                unit TEXT DEFAULT 'pcs',
                min_stock INTEGER DEFAULT 0,
                location TEXT DEFAULT '',
                last_updated TEXT DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (machinery_id) REFERENCES machinery(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS stores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_code TEXT DEFAULT '',
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                category TEXT DEFAULT 'General',
                quantity INTEGER DEFAULT 0,
                unit TEXT DEFAULT 'pcs',
                min_stock INTEGER DEFAULT 0,
                location TEXT DEFAULT '',
                last_updated TEXT DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_type TEXT NOT NULL CHECK(transaction_type IN ('receipt', 'usage')),
                item_category TEXT NOT NULL CHECK(item_category IN ('spares', 'stores', 'oils', 'chemicals', 'greases')),
                item_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                crew_name TEXT DEFAULT '',
                remarks TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS crew (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                rank TEXT DEFAULT '',
                username TEXT DEFAULT '' UNIQUE,
                password_hash TEXT DEFAULT '',
                role TEXT DEFAULT 'user' CHECK(role IN ('admin', 'user')),
                active INTEGER DEFAULT 1
            );

            CREATE INDEX IF NOT EXISTS idx_spare_parts_machinery ON spare_parts(machinery_id);
            CREATE INDEX IF NOT EXISTS idx_transactions_category ON transactions(item_category);
            CREATE INDEX IF NOT EXISTS idx_transactions_type ON transactions(transaction_type);
            CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(created_at);
            CREATE INDEX IF NOT EXISTS idx_transactions_item ON transactions(item_category, item_id);
        ''')

        # Migration: add drawing_number column if missing (for existing databases)
        try:
            conn.execute("ALTER TABLE spare_parts ADD COLUMN drawing_number TEXT DEFAULT ''")
        except Exception:
            pass  # Column already exists

        # ── Lubricating Oils ──
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS lubricating_oils (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                grade TEXT DEFAULT '',
                uses TEXT DEFAULT '',
                quantity REAL DEFAULT 0,
                unit TEXT DEFAULT 'ltr',
                min_stock REAL DEFAULT 0,
                location TEXT DEFAULT '',
                safety_sheet TEXT DEFAULT '',
                last_updated TEXT DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS chemicals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                grade TEXT DEFAULT '',
                uses TEXT DEFAULT '',
                nature TEXT DEFAULT 'neutral' CHECK(nature IN ('neutral', 'acidic', 'alkaline')),
                quantity REAL DEFAULT 0,
                unit TEXT DEFAULT 'ltr',
                min_stock REAL DEFAULT 0,
                location TEXT DEFAULT '',
                safety_sheet TEXT DEFAULT '',
                last_updated TEXT DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS greases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                grade TEXT DEFAULT '',
                uses TEXT DEFAULT '',
                quantity REAL DEFAULT 0,
                unit TEXT DEFAULT 'kg',
                min_stock REAL DEFAULT 0,
                location TEXT DEFAULT '',
                last_updated TEXT DEFAULT (datetime('now', 'localtime'))
            );
        ''')


# ── Machinery CRUD ──

def get_all_machinery():
    with db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM machinery ORDER BY name"
        ).fetchall()
        # Add spare part count to each machinery
        result = []
        for row in rows:
            d = dict(row)
            count = conn.execute(
                "SELECT COUNT(*) as cnt, COALESCE(SUM(quantity), 0) as total_qty "
                "FROM spare_parts WHERE machinery_id = ?", (row['id'],)
            ).fetchone()
            d['spare_count'] = count['cnt']
            d['total_qty'] = count['total_qty']
            result.append(d)
        return result


def get_machinery(machinery_id):
    with db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM machinery WHERE id = ?", (machinery_id,)
        ).fetchone()
        return dict(row) if row else None


def create_machinery(name, manufacturer='', model='', description=''):
    with db_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO machinery (name, manufacturer, model, description) VALUES (?, ?, ?, ?)",
            (name, manufacturer, model, description)
        )
        return cursor.lastrowid


def update_machinery(machinery_id, name, manufacturer='', model='', description=''):
    with db_connection() as conn:
        conn.execute(
            "UPDATE machinery SET name=?, manufacturer=?, model=?, description=? WHERE id=?",
            (name, manufacturer, model, description, machinery_id)
        )


def delete_machinery(machinery_id):
    with db_connection() as conn:
        conn.execute("DELETE FROM machinery WHERE id=?", (machinery_id,))


# ── Spare Parts CRUD ──

def get_spare_parts_by_machinery(machinery_id):
    with db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM spare_parts WHERE machinery_id = ? ORDER BY part_number, description",
            (machinery_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_spare_part(part_id):
    with db_connection() as conn:
        row = conn.execute(
            "SELECT sp.*, m.name as machinery_name FROM spare_parts sp "
            "JOIN machinery m ON sp.machinery_id = m.id WHERE sp.id = ?",
            (part_id,)
        ).fetchone()
        return dict(row) if row else None


def create_spare_part(machinery_id, part_number, description, quantity=0,
                      unit='pcs', min_stock=0, location='', drawing_number=''):
    with db_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO spare_parts (machinery_id, part_number, drawing_number, description, quantity, unit, min_stock, location) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (machinery_id, part_number, drawing_number, description, quantity, unit, min_stock, location)
        )
        return cursor.lastrowid


def update_spare_part(part_id, part_number, description, quantity,
                      unit, min_stock, location, drawing_number=''):
    with db_connection() as conn:
        conn.execute(
            "UPDATE spare_parts SET part_number=?, drawing_number=?, description=?, quantity=?, "
            "unit=?, min_stock=?, location=?, last_updated=datetime('now','localtime') WHERE id=?",
            (part_number, drawing_number, description, quantity, unit, min_stock, location, part_id)
        )


def delete_spare_part(part_id):
    with db_connection() as conn:
        conn.execute("DELETE FROM spare_parts WHERE id=?", (part_id,))


def bulk_create_spare_parts(machinery_id, parts_list):
    """Insert multiple spare parts at once. parts_list = list of dicts."""
    with db_connection() as conn:
        for p in parts_list:
            conn.execute(
                "INSERT INTO spare_parts (machinery_id, part_number, drawing_number, description, quantity, unit, min_stock, location) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (machinery_id, p.get('part_number', ''), p.get('drawing_number', ''), p['description'],
                 p.get('quantity', 0), p.get('unit', 'pcs'),
                 p.get('min_stock', 0), p.get('location', ''))
            )


def search_spare_parts(query):
    with db_connection() as conn:
        rows = conn.execute(
            "SELECT sp.*, m.name as machinery_name FROM spare_parts sp "
            "JOIN machinery m ON sp.machinery_id = m.id "
            "WHERE sp.description LIKE ? OR sp.part_number LIKE ? "
            "ORDER BY m.name, sp.part_number",
            (f'%{query}%', f'%{query}%')
        ).fetchall()
        return [dict(r) for r in rows]


def get_low_stock_spare_parts():
    with db_connection() as conn:
        rows = conn.execute(
            "SELECT sp.*, m.name as machinery_name FROM spare_parts sp "
            "JOIN machinery m ON sp.machinery_id = m.id "
            "WHERE sp.quantity <= sp.min_stock AND sp.min_stock > 0 "
            "ORDER BY m.name, sp.part_number"
        ).fetchall()
        return [dict(r) for r in rows]


# ── Stores CRUD ──

def get_all_stores(category=None):
    with db_connection() as conn:
        if category:
            rows = conn.execute(
                "SELECT * FROM stores WHERE category = ? ORDER BY name",
                (category,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM stores ORDER BY category, name"
            ).fetchall()
        return [dict(r) for r in rows]


def get_store_item(item_id):
    with db_connection() as conn:
        row = conn.execute("SELECT * FROM stores WHERE id = ?", (item_id,)).fetchone()
        return dict(row) if row else None


def create_store_item(item_code, name, description='', category='General',
                      quantity=0, unit='pcs', min_stock=0, location=''):
    with db_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO stores (item_code, name, description, category, quantity, unit, min_stock, location) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (item_code, name, description, category, quantity, unit, min_stock, location)
        )
        return cursor.lastrowid


def update_store_item(item_id, item_code, name, description, category,
                      quantity, unit, min_stock, location):
    with db_connection() as conn:
        conn.execute(
            "UPDATE stores SET item_code=?, name=?, description=?, category=?, "
            "quantity=?, unit=?, min_stock=?, location=?, "
            "last_updated=datetime('now','localtime') WHERE id=?",
            (item_code, name, description, category, quantity, unit,
             min_stock, location, item_id)
        )


def delete_store_item(item_id):
    with db_connection() as conn:
        conn.execute("DELETE FROM stores WHERE id=?", (item_id,))


def get_store_categories():
    with db_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT category FROM stores ORDER BY category"
        ).fetchall()
        return [r['category'] for r in rows]


def get_low_stock_stores():
    with db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM stores WHERE quantity <= min_stock AND min_stock > 0 "
            "ORDER BY category, name"
        ).fetchall()
        return [dict(r) for r in rows]


def search_stores(query):
    with db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM stores WHERE name LIKE ? OR description LIKE ? OR item_code LIKE ? "
            "ORDER BY category, name",
            (f'%{query}%', f'%{query}%', f'%{query}%')
        ).fetchall()
        return [dict(r) for r in rows]


# ── Transactions ──

def record_transaction(transaction_type, item_category, item_id, quantity,
                       crew_name='', remarks=''):
    """Record a receipt or usage transaction and update stock."""
    with db_connection() as conn:
        # Insert transaction
        conn.execute(
            "INSERT INTO transactions (transaction_type, item_category, item_id, quantity, crew_name, remarks) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (transaction_type, item_category, item_id, quantity, crew_name, remarks)
        )

        # Update quantity based on category
        table_map = {
            'spares': 'spare_parts',
            'stores': 'stores',
            'oils': 'lubricating_oils',
            'chemicals': 'chemicals',
            'greases': 'greases',
        }
        table = table_map.get(item_category)
        if table:
            if transaction_type == 'receipt':
                conn.execute(
                    f"UPDATE {table} SET quantity = quantity + ?, "
                    f"last_updated=datetime('now','localtime') WHERE id = ?",
                    (quantity, item_id)
                )
            else:  # usage
                conn.execute(
                    f"UPDATE {table} SET quantity = MAX(0, quantity - ?), "
                    f"last_updated=datetime('now','localtime') WHERE id = ?",
                    (quantity, item_id)
                )


def get_transactions(item_category=None, transaction_type=None,
                     date_from=None, date_to=None, limit=200):
    with db_connection() as conn:
        query = "SELECT t.*, "
        conditions = []
        params = []

        if item_category == 'spares':
            query += (
                "sp.description as item_name, sp.part_number, m.name as machinery_name "
                "FROM transactions t "
                "LEFT JOIN spare_parts sp ON t.item_id = sp.id "
                "LEFT JOIN machinery m ON sp.machinery_id = m.id "
            )
        elif item_category == 'stores':
            query += (
                "st.name as item_name, st.item_code, '' as machinery_name "
                "FROM transactions t "
                "LEFT JOIN stores st ON t.item_id = st.id "
            )
        elif item_category == 'oils':
            query += (
                "lo.name as item_name, lo.grade as item_code, '' as machinery_name "
                "FROM transactions t "
                "LEFT JOIN lubricating_oils lo ON t.item_id = lo.id "
            )
        elif item_category == 'chemicals':
            query += (
                "ch.name as item_name, ch.grade as item_code, '' as machinery_name "
                "FROM transactions t "
                "LEFT JOIN chemicals ch ON t.item_id = ch.id "
            )
        elif item_category == 'greases':
            query += (
                "gr.name as item_name, gr.grade as item_code, '' as machinery_name "
                "FROM transactions t "
                "LEFT JOIN greases gr ON t.item_id = gr.id "
            )
        else:
            query += (
                "CASE t.item_category "
                "  WHEN 'spares' THEN (SELECT sp.description FROM spare_parts sp WHERE sp.id = t.item_id) "
                "  WHEN 'stores' THEN (SELECT st.name FROM stores st WHERE st.id = t.item_id) "
                "  WHEN 'oils' THEN (SELECT lo.name FROM lubricating_oils lo WHERE lo.id = t.item_id) "
                "  WHEN 'chemicals' THEN (SELECT ch.name FROM chemicals ch WHERE ch.id = t.item_id) "
                "  WHEN 'greases' THEN (SELECT gr.name FROM greases gr WHERE gr.id = t.item_id) "
                "END as item_name, "
                "CASE t.item_category "
                "  WHEN 'spares' THEN (SELECT sp.part_number FROM spare_parts sp WHERE sp.id = t.item_id) "
                "  WHEN 'stores' THEN (SELECT st.item_code FROM stores st WHERE st.id = t.item_id) "
                "  WHEN 'oils' THEN (SELECT lo.grade FROM lubricating_oils lo WHERE lo.id = t.item_id) "
                "  WHEN 'chemicals' THEN (SELECT ch.grade FROM chemicals ch WHERE ch.id = t.item_id) "
                "  WHEN 'greases' THEN (SELECT gr.grade FROM greases gr WHERE gr.id = t.item_id) "
                "END as item_code, "
                "'' as machinery_name "
                "FROM transactions t "
            )

        if item_category:
            conditions.append("t.item_category = ?")
            params.append(item_category)
        if transaction_type:
            conditions.append("t.transaction_type = ?")
            params.append(transaction_type)
        if date_from:
            conditions.append("t.created_at >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("t.created_at <= ?")
            params.append(date_to + ' 23:59:59')

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY t.created_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_report_data(year=None, month=None, date_from=None, date_to=None):
    """
    Get transaction data for reports.
    Supports year/month OR custom date_from/date_to (YYYY-MM-DD strings).
    Returns four separate datasets: spares_received, spares_used, stores_received, stores_used.
    """
    with db_connection() as conn:
        # Build date filter
        if date_from and date_to:
            # Custom date range
            where_clause = "t.created_at >= ? AND t.created_at <= ?"
            date_params = (date_from + ' 00:00:00', date_to + ' 23:59:59')
        elif date_from:
            where_clause = "t.created_at >= ?"
            date_params = (date_from + ' 00:00:00',)
        elif date_to:
            where_clause = "t.created_at <= ?"
            date_params = (date_to + ' 23:59:59',)
        elif year and month:
            where_clause = "t.created_at LIKE ?"
            date_params = (f'{year}-{month:02d}%',)
        elif year:
            where_clause = "t.created_at LIKE ?"
            date_params = (f'{year}%',)
        else:
            where_clause = "1=1"
            date_params = ()

        # ── Spares Received ──
        spares_received = conn.execute(
            "SELECT sp.part_number, sp.description, m.name as machinery_name, "
            "SUM(t.quantity) as total_qty "
            "FROM transactions t "
            "JOIN spare_parts sp ON t.item_id = sp.id "
            "JOIN machinery m ON sp.machinery_id = m.id "
            f"WHERE t.item_category = 'spares' AND t.transaction_type = 'receipt' AND {where_clause} "
            "GROUP BY sp.id ORDER BY m.name, sp.description",
            date_params
        ).fetchall()

        # ── Spares Used ──
        spares_used = conn.execute(
            "SELECT sp.part_number, sp.description, m.name as machinery_name, "
            "SUM(t.quantity) as total_qty "
            "FROM transactions t "
            "JOIN spare_parts sp ON t.item_id = sp.id "
            "JOIN machinery m ON sp.machinery_id = m.id "
            f"WHERE t.item_category = 'spares' AND t.transaction_type = 'usage' AND {where_clause} "
            "GROUP BY sp.id ORDER BY m.name, sp.description",
            date_params
        ).fetchall()

        # ── Stores Received ──
        stores_received = conn.execute(
            "SELECT st.item_code, st.name, st.category, "
            "SUM(t.quantity) as total_qty "
            "FROM transactions t "
            "JOIN stores st ON t.item_id = st.id "
            f"WHERE t.item_category = 'stores' AND t.transaction_type = 'receipt' AND {where_clause} "
            "GROUP BY st.id ORDER BY st.category, st.name",
            date_params
        ).fetchall()

        # ── Stores Used ──
        stores_used = conn.execute(
            "SELECT st.item_code, st.name, st.category, "
            "SUM(t.quantity) as total_qty "
            "FROM transactions t "
            "JOIN stores st ON t.item_id = st.id "
            f"WHERE t.item_category = 'stores' AND t.transaction_type = 'usage' AND {where_clause} "
            "GROUP BY st.id ORDER BY st.category, st.name",
            date_params
        ).fetchall()

        # ── Summary stats ──
        total_receipts = conn.execute(
            f"SELECT COALESCE(SUM(quantity), 0) as total FROM transactions t "
            f"WHERE t.transaction_type = 'receipt' AND {where_clause}",
            date_params
        ).fetchone()['total']

        total_usage = conn.execute(
            f"SELECT COALESCE(SUM(quantity), 0) as total FROM transactions t "
            f"WHERE t.transaction_type = 'usage' AND {where_clause}",
            date_params
        ).fetchone()['total']

        spares_receipt_qty = conn.execute(
            f"SELECT COALESCE(SUM(quantity), 0) as total FROM transactions t "
            f"WHERE t.item_category = 'spares' AND t.transaction_type = 'receipt' AND {where_clause}",
            date_params
        ).fetchone()['total']

        spares_usage_qty = conn.execute(
            f"SELECT COALESCE(SUM(quantity), 0) as total FROM transactions t "
            f"WHERE t.item_category = 'spares' AND t.transaction_type = 'usage' AND {where_clause}",
            date_params
        ).fetchone()['total']

        stores_receipt_qty = conn.execute(
            f"SELECT COALESCE(SUM(quantity), 0) as total FROM transactions t "
            f"WHERE t.item_category = 'stores' AND t.transaction_type = 'receipt' AND {where_clause}",
            date_params
        ).fetchone()['total']

        stores_usage_qty = conn.execute(
            f"SELECT COALESCE(SUM(quantity), 0) as total FROM transactions t "
            f"WHERE t.item_category = 'stores' AND t.transaction_type = 'usage' AND {where_clause}",
            date_params
        ).fetchone()['total']

        return {
            'spares_received': [dict(r) for r in spares_received],
            'spares_used': [dict(r) for r in spares_used],
            'stores_received': [dict(r) for r in stores_received],
            'stores_used': [dict(r) for r in stores_used],
            'total_receipts': total_receipts,
            'total_usage': total_usage,
            'spares_receipt_qty': spares_receipt_qty,
            'spares_usage_qty': spares_usage_qty,
            'stores_receipt_qty': stores_receipt_qty,
            'stores_usage_qty': stores_usage_qty,
        }


# ── Crew ──

def get_all_crew():
    with db_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, rank, username, role, active FROM crew WHERE active = 1 ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]


def create_crew_member(name, rank='', username='', password='', role='user'):
    with db_connection() as conn:
        password_hash = ''
        if password:
            import hashlib, secrets
            salt = secrets.token_hex(16)
            h = hashlib.sha256((salt + password).encode()).hexdigest()
            password_hash = f"{salt}${h}"
        cursor = conn.execute(
            "INSERT INTO crew (name, rank, username, password_hash, role) VALUES (?, ?, ?, ?, ?)",
            (name, rank, username, password_hash, role)
        )
        return cursor.lastrowid


def delete_crew_member(crew_id):
    with db_connection() as conn:
        conn.execute("UPDATE crew SET active = 0 WHERE id = ?", (crew_id,))


# ── Authentication ──

def authenticate_user(username, password):
    """Authenticate a crew member by username and password."""
    import hashlib
    with db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM crew WHERE username = ? AND active = 1 AND password_hash != ''",
            (username,)
        ).fetchone()
        if not row:
            return None
        stored = row['password_hash']
        if '$' not in stored:
            return None
        salt, h = stored.split('$', 1)
        if hashlib.sha256((salt + password).encode()).hexdigest() == h:
            return dict(row)
        return None


def verify_user_password(user_id, current_password):
    """Verify a user's current password."""
    import hashlib
    with db_connection() as conn:
        row = conn.execute(
            "SELECT password_hash FROM crew WHERE id = ?", (user_id,)
        ).fetchone()
        if not row or not row['password_hash']:
            return False
        stored = row['password_hash']
        if '$' not in stored:
            return False
        salt, h = stored.split('$', 1)
        return hashlib.sha256((salt + current_password).encode()).hexdigest() == h


def update_user_password(user_id, new_password):
    """Update a user's password."""
    import hashlib, secrets
    salt = secrets.token_hex(16)
    h = hashlib.sha256((salt + new_password).encode()).hexdigest()
    password_hash = f"{salt}${h}"
    with db_connection() as conn:
        conn.execute(
            "UPDATE crew SET password_hash = ? WHERE id = ?",
            (password_hash, user_id)
        )


def ensure_admin_user():
    """Create a default admin user if no users with login exist."""
    with db_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) as c FROM crew WHERE active = 1 AND password_hash != ''"
        ).fetchone()['c']
        if count == 0:
            import hashlib, secrets
            salt = secrets.token_hex(16)
            h = hashlib.sha256((salt + 'admin').encode()).hexdigest()
            password_hash = f"{salt}${h}"
            try:
                conn.execute(
                    "INSERT INTO crew (name, rank, username, password_hash, role) VALUES (?, ?, ?, ?, ?)",
                    ('Administrator', 'Chief Engineer', 'admin', password_hash, 'admin')
                )
            except Exception:
                pass  # Already exists


# ── Dashboard Stats ──

def get_dashboard_stats():
    with db_connection() as conn:
        machinery_count = conn.execute("SELECT COUNT(*) as c FROM machinery").fetchone()['c']
        spare_count = conn.execute("SELECT COUNT(*) as c FROM spare_parts").fetchone()['c']
        spare_qty = conn.execute("SELECT COALESCE(SUM(quantity), 0) as c FROM spare_parts").fetchone()['c']
        store_count = conn.execute("SELECT COUNT(*) as c FROM stores").fetchone()['c']
        store_qty = conn.execute("SELECT COALESCE(SUM(quantity), 0) as c FROM stores").fetchone()['c']
        oil_count = conn.execute("SELECT COUNT(*) as c FROM lubricating_oils").fetchone()['c']
        chemical_count = conn.execute("SELECT COUNT(*) as c FROM chemicals").fetchone()['c']
        grease_count = conn.execute("SELECT COUNT(*) as c FROM greases").fetchone()['c']

        low_spares = conn.execute(
            "SELECT COUNT(*) as c FROM spare_parts WHERE quantity <= min_stock AND min_stock > 0"
        ).fetchone()['c']
        low_stores = conn.execute(
            "SELECT COUNT(*) as c FROM stores WHERE quantity <= min_stock AND min_stock > 0"
        ).fetchone()['c']

        # Recent transactions (last 10)
        recent = conn.execute(
            "SELECT t.*, "
            "CASE t.item_category "
            "  WHEN 'spares' THEN (SELECT sp.description FROM spare_parts sp WHERE sp.id = t.item_id) "
            "  WHEN 'stores' THEN (SELECT st.name FROM stores st WHERE st.id = t.item_id) "
            "  WHEN 'oils' THEN (SELECT lo.name FROM lubricating_oils lo WHERE lo.id = t.item_id) "
            "  WHEN 'chemicals' THEN (SELECT ch.name FROM chemicals ch WHERE ch.id = t.item_id) "
            "  WHEN 'greases' THEN (SELECT gr.name FROM greases gr WHERE gr.id = t.item_id) "
            "END as item_name "
            "FROM transactions t ORDER BY t.created_at DESC LIMIT 10"
        ).fetchall()

        # Monthly usage for current year
        now = datetime.now()
        monthly_usage = conn.execute(
            "SELECT strftime('%m', created_at) as month, "
            "SUM(CASE WHEN transaction_type = 'receipt' THEN quantity ELSE 0 END) as receipts, "
            "SUM(CASE WHEN transaction_type = 'usage' THEN quantity ELSE 0 END) as usage "
            "FROM transactions WHERE strftime('%Y', created_at) = ? "
            "GROUP BY month ORDER BY month",
            (str(now.year),)
        ).fetchall()

        return {
            'machinery_count': machinery_count,
            'spare_count': spare_count,
            'spare_qty': spare_qty,
            'store_count': store_count,
            'store_qty': store_qty,
            'oil_count': oil_count,
            'chemical_count': chemical_count,
            'grease_count': grease_count,
            'low_spares': low_spares,
            'low_stores': low_stores,
            'recent_transactions': [dict(r) for r in recent],
            'monthly_usage': [dict(r) for r in monthly_usage],
            'current_year': now.year,
        }


# ── Lubricating Oils CRUD ──

def get_all_oils():
    with db_connection() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM lubricating_oils ORDER BY name"
        ).fetchall()]

def get_oil(item_id):
    with db_connection() as conn:
        r = conn.execute("SELECT * FROM lubricating_oils WHERE id=?", (item_id,)).fetchone()
        return dict(r) if r else None

def create_oil(name, grade='', uses='', quantity=0, unit='ltr', min_stock=0, location='', safety_sheet=''):
    with db_connection() as conn:
        cur = conn.execute(
            "INSERT INTO lubricating_oils (name, grade, uses, quantity, unit, min_stock, location, safety_sheet) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, grade, uses, quantity, unit, min_stock, location, safety_sheet)
        )
        return cur.lastrowid

def update_oil(item_id, name, grade='', uses='', quantity=0, unit='ltr', min_stock=0, location='', safety_sheet=''):
    with db_connection() as conn:
        conn.execute(
            "UPDATE lubricating_oils SET name=?, grade=?, uses=?, quantity=?, unit=?, min_stock=?, "
            "location=?, safety_sheet=?, last_updated=datetime('now','localtime') WHERE id=?",
            (name, grade, uses, quantity, unit, min_stock, location, safety_sheet, item_id)
        )

def delete_oil(item_id):
    with db_connection() as conn:
        conn.execute("DELETE FROM lubricating_oils WHERE id=?", (item_id,))


# ── Chemicals CRUD ──

def get_all_chemicals():
    with db_connection() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM chemicals ORDER BY name"
        ).fetchall()]

def get_chemical(item_id):
    with db_connection() as conn:
        r = conn.execute("SELECT * FROM chemicals WHERE id=?", (item_id,)).fetchone()
        return dict(r) if r else None

def create_chemical(name, grade='', uses='', nature='neutral', quantity=0, unit='ltr', min_stock=0, location='', safety_sheet=''):
    with db_connection() as conn:
        cur = conn.execute(
            "INSERT INTO chemicals (name, grade, uses, nature, quantity, unit, min_stock, location, safety_sheet) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, grade, uses, nature, quantity, unit, min_stock, location, safety_sheet)
        )
        return cur.lastrowid

def update_chemical(item_id, name, grade='', uses='', nature='neutral', quantity=0, unit='ltr', min_stock=0, location='', safety_sheet=''):
    with db_connection() as conn:
        conn.execute(
            "UPDATE chemicals SET name=?, grade=?, uses=?, nature=?, quantity=?, unit=?, min_stock=?, "
            "location=?, safety_sheet=?, last_updated=datetime('now','localtime') WHERE id=?",
            (name, grade, uses, nature, quantity, unit, min_stock, location, safety_sheet, item_id)
        )

def delete_chemical(item_id):
    with db_connection() as conn:
        conn.execute("DELETE FROM chemicals WHERE id=?", (item_id,))


# ── Greases CRUD ──

def get_all_greases():
    with db_connection() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM greases ORDER BY name"
        ).fetchall()]

def get_grease(item_id):
    with db_connection() as conn:
        r = conn.execute("SELECT * FROM greases WHERE id=?", (item_id,)).fetchone()
        return dict(r) if r else None

def create_grease(name, grade='', uses='', quantity=0, unit='kg', min_stock=0, location=''):
    with db_connection() as conn:
        cur = conn.execute(
            "INSERT INTO greases (name, grade, uses, quantity, unit, min_stock, location) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, grade, uses, quantity, unit, min_stock, location)
        )
        return cur.lastrowid

def update_grease(item_id, name, grade='', uses='', quantity=0, unit='kg', min_stock=0, location=''):
    with db_connection() as conn:
        conn.execute(
            "UPDATE greases SET name=?, grade=?, uses=?, quantity=?, unit=?, min_stock=?, "
            "location=?, last_updated=datetime('now','localtime') WHERE id=?",
            (name, grade, uses, quantity, unit, min_stock, location, item_id)
        )

def delete_grease(item_id):
    with db_connection() as conn:
        conn.execute("DELETE FROM greases WHERE id=?", (item_id,))
