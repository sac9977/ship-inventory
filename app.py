"""
Ship Inventory Management System
Main Flask application with all routes for spares, stores, transactions, and reports.
"""
import sys
import os

# ── Fix: Remove hermes-agent venv paths that cause architecture conflicts ──
sys.path = [p for p in sys.path if 'hermes' not in p.lower()]

import json
import calendar
import tempfile
import hashlib
import secrets
from datetime import datetime, date
from functools import wraps
from flask import (Flask, render_template, request, redirect, url_for,
                   flash, jsonify, session, abort)
from werkzeug.utils import secure_filename
import database as db
from pdf_parser import parse_pdf

app = Flask(__name__)
app.secret_key = 'ship-inventory-secret-key-change-in-production'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 86400 * 7  # 7 days

# ── Initialize Database ──
db.init_db()
db.ensure_admin_user()  # Create default admin login if none exists

# ── Auto-backup on startup ──
db.auto_backup()


# ══════════════════════════════════════════════════════════════
#  AUTHENTICATION SYSTEM
# ══════════════════════════════════════════════════════════════

def hash_password(password):
    """Hash a password with a random salt using SHA-256."""
    salt = secrets.token_hex(16)
    h = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}${h}"


def verify_password(stored, password):
    """Verify a password against its stored hash."""
    if '$' not in stored:
        return False
    salt, h = stored.split('$', 1)
    return hashlib.sha256((salt + password).encode()).hexdigest() == h


def login_required(f):
    """Decorator — redirects to login if not authenticated."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Decorator — requires admin role."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login', next=request.url))
        if session.get('user_role') != 'admin':
            flash('Admin access required.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated


# ── Auth Routes ──

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember = request.form.get('remember') == 'on'

        user = db.authenticate_user(username, password)
        if user:
            session.permanent = remember
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            session['user_rank'] = user['rank']
            session['user_role'] = user.get('role', 'user')
            next_url = request.args.get('next', url_for('dashboard'))
            flash(f'Welcome, {user["name"]}!', 'success')
            return redirect(next_url)
        else:
            flash('Invalid username or password.', 'danger')

    return render_template('login.html')


@app.route('/logout')
def logout():
    name = session.get('user_name', 'User')
    session.clear()
    flash(f'Goodbye, {name}.', 'success')
    return redirect(url_for('login'))


@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current = request.form.get('current_password', '')
        new_pass = request.form.get('new_password', '')
        confirm = request.form.get('confirm_password', '')

        if not db.verify_user_password(session['user_id'], current):
            flash('Current password is incorrect.', 'danger')
        elif len(new_pass) < 4:
            flash('New password must be at least 4 characters.', 'danger')
        elif new_pass != confirm:
            flash('New passwords do not match.', 'danger')
        else:
            db.update_user_password(session['user_id'], new_pass)
            flash('Password changed successfully.', 'success')
            return redirect(url_for('dashboard'))

    return render_template('change_password.html')


# ── Dashboard ──

@app.route('/')
@login_required
def dashboard():
    stats = db.get_dashboard_stats()
    return render_template('dashboard.html', stats=stats)


# ── Machinery Routes ──

@app.route('/machinery')
@login_required
def machinery_list():
    machinery = db.get_all_machinery()
    return render_template('machinery_list.html', machinery=machinery)


@app.route('/machinery/add', methods=['GET', 'POST'])
@admin_required
def machinery_add():
    if request.method == 'POST':
        name = request.form['name'].strip()
        if not name:
            flash('Machinery name is required.', 'danger')
            return redirect(url_for('machinery_add'))
        mid = db.create_machinery(
            name=name,
            manufacturer=request.form.get('manufacturer', '').strip(),
            model=request.form.get('model', '').strip(),
            description=request.form.get('description', '').strip(),
        )
        flash(f'Machinery "{name}" added successfully.', 'success')
        return redirect(url_for('machinery_view', machinery_id=mid))
    return render_template('machinery_form.html', machinery=None)


@app.route('/machinery/<int:machinery_id>')
@login_required
def machinery_view(machinery_id):
    machinery = db.get_machinery(machinery_id)
    if not machinery:
        flash('Machinery not found.', 'danger')
        return redirect(url_for('machinery_list'))
    parts = db.get_spare_parts_by_machinery(machinery_id)
    return render_template('machinery_view.html', machinery=machinery, parts=parts)


@app.route('/machinery/<int:machinery_id>/edit', methods=['GET', 'POST'])
@admin_required
def machinery_edit(machinery_id):
    machinery = db.get_machinery(machinery_id)
    if not machinery:
        flash('Machinery not found.', 'danger')
        return redirect(url_for('machinery_list'))
    if request.method == 'POST':
        name = request.form['name'].strip()
        if not name:
            flash('Machinery name is required.', 'danger')
            return redirect(url_for('machinery_edit', machinery_id=machinery_id))
        db.update_machinery(
            machinery_id, name=name,
            manufacturer=request.form.get('manufacturer', '').strip(),
            model=request.form.get('model', '').strip(),
            description=request.form.get('description', '').strip(),
        )
        flash('Machinery updated.', 'success')
        return redirect(url_for('machinery_view', machinery_id=machinery_id))
    return render_template('machinery_form.html', machinery=machinery)


@app.route('/machinery/<int:machinery_id>/delete', methods=['POST'])
@admin_required
def machinery_delete(machinery_id):
    m = db.get_machinery(machinery_id)
    if m:
        db.delete_machinery(machinery_id)
        flash(f'Machinery "{m["name"]}" deleted.', 'success')
    return redirect(url_for('machinery_list'))


# ── Spare Parts Routes ──

@app.route('/spares')
@login_required
def spares_overview():
    """Show all machinery with their spare parts counts."""
    machinery = db.get_all_machinery()
    low_stock = db.get_low_stock_spare_parts()
    return render_template('spares_overview.html', machinery=machinery, low_stock=low_stock)


@app.route('/spares/machinery/<int:machinery_id>')
@login_required
def spares_by_machinery(machinery_id):
    machinery = db.get_machinery(machinery_id)
    if not machinery:
        flash('Machinery not found.', 'danger')
        return redirect(url_for('spares_overview'))
    parts = db.get_spare_parts_by_machinery(machinery_id)
    return render_template('spares_list.html', machinery=machinery, parts=parts)


@app.route('/spares/machinery/<int:machinery_id>/add', methods=['GET', 'POST'])
@login_required
def spare_add(machinery_id):
    machinery = db.get_machinery(machinery_id)
    if not machinery:
        flash('Machinery not found.', 'danger')
        return redirect(url_for('spares_overview'))
    if request.method == 'POST':
        try:
            desc = request.form.get('description', '').strip()
            if not desc:
                flash('Description is required.', 'danger')
                return redirect(url_for('spare_add', machinery_id=machinery_id))
            qty_raw = request.form.get('quantity', '0').strip()
            min_raw = request.form.get('min_stock', '0').strip()
            pid = db.create_spare_part(
                machinery_id=machinery_id,
                part_number=request.form.get('part_number', '').strip(),
                drawing_number=request.form.get('drawing_number', '').strip(),
                description=desc,
                quantity=int(qty_raw) if qty_raw else 0,
                unit=request.form.get('unit', 'pcs').strip() or 'pcs',
                min_stock=int(min_raw) if min_raw else 0,
                location=request.form.get('location', '').strip(),
            )
            flash('Spare part added.', 'success')
            return redirect(url_for('spares_by_machinery', machinery_id=machinery_id))
        except Exception as e:
            flash(f'Error adding spare part: {str(e)}', 'danger')
            return redirect(url_for('spare_add', machinery_id=machinery_id))
    return render_template('spare_form.html', machinery=machinery, part=None)


@app.route('/spares/edit/<int:part_id>', methods=['GET', 'POST'])
@login_required
def spare_edit(part_id):
    part = db.get_spare_part(part_id)
    if not part:
        flash('Spare part not found.', 'danger')
        return redirect(url_for('spares_overview'))
    if request.method == 'POST':
        try:
            desc = request.form.get('description', '').strip()
            if not desc:
                flash('Description is required.', 'danger')
                return redirect(url_for('spare_edit', part_id=part_id))
            qty_raw = request.form.get('quantity', '0').strip()
            min_raw = request.form.get('min_stock', '0').strip()
            db.update_spare_part(
                part_id,
                part_number=request.form.get('part_number', '').strip(),
                drawing_number=request.form.get('drawing_number', '').strip(),
                description=desc,
                quantity=int(qty_raw) if qty_raw else 0,
                unit=request.form.get('unit', 'pcs').strip() or 'pcs',
                min_stock=int(min_raw) if min_raw else 0,
                location=request.form.get('location', '').strip(),
            )
            flash('Spare part updated.', 'success')
            return redirect(url_for('spares_by_machinery', machinery_id=part['machinery_id']))
        except Exception as e:
            flash(f'Error updating spare part: {str(e)}', 'danger')
            return redirect(url_for('spare_edit', part_id=part_id))
    machinery = db.get_machinery(part['machinery_id'])
    return render_template('spare_form.html', machinery=machinery, part=part)


@app.route('/spares/delete/<int:part_id>', methods=['POST'])
@login_required
def spare_delete(part_id):
    try:
        part = db.get_spare_part(part_id)
        if part:
            mid = part['machinery_id']
            db.delete_spare_part(part_id)
            flash('Spare part deleted.', 'success')
            return redirect(url_for('spares_by_machinery', machinery_id=mid))
        flash('Spare part not found.', 'danger')
    except Exception as e:
        flash(f'Error deleting spare part: {str(e)}', 'danger')
    return redirect(url_for('spares_overview'))


# ── Stores Routes ──

@app.route('/stores')
@login_required
def stores_list():
    category = request.args.get('category', '')
    search = request.args.get('search', '').strip()
    low_only = request.args.get('low', '') == '1'
    try:
        page = max(1, int(request.args.get('page', 1)))
    except ValueError:
        page = 1
    PER_PAGE = 50
    items, total = db.get_stores_page(
        category=category if category else None,
        search=search,
        page=page,
        per_page=PER_PAGE,
        low_only=low_only,
    )
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    categories = db.get_store_categories()
    low_stock = db.get_low_stock_stores(limit=8)
    return render_template('stores_list.html', items=items, categories=categories,
                           current_category=category, search=search, low_stock=low_stock,
                           page=page, total_pages=total_pages, total_items=total,
                           per_page=PER_PAGE, low_only=low_only)


@app.route('/stores/add', methods=['GET', 'POST'])
@login_required
def store_add():
    if request.method == 'POST':
        name = request.form['name'].strip()
        if not name:
            flash('Item name is required.', 'danger')
            return redirect(url_for('store_add'))
        iid = db.create_store_item(
            item_code=request.form.get('item_code', '').strip(),
            name=name,
            description=request.form.get('description', '').strip(),
            category=request.form.get('category', 'General').strip() or 'General',
            quantity=int(request.form.get('quantity', 0) or 0),
            unit=request.form.get('unit', 'pcs').strip() or 'pcs',
            min_stock=int(request.form.get('min_stock', 0) or 0)
            or db.default_min_stock_for(request.form.get('category', 'General').strip() or 'General'),
            location=request.form.get('location', '').strip(),
        )
        flash(f'Store item "{name}" added.', 'success')
        return redirect(url_for('stores_list'))
    categories = db.get_store_categories()
    return render_template('store_form.html', item=None, categories=categories)


@app.route('/stores/edit/<int:item_id>', methods=['GET', 'POST'])
@login_required
def store_edit(item_id):
    item = db.get_store_item(item_id)
    if not item:
        flash('Store item not found.', 'danger')
        return redirect(url_for('stores_list'))
    if request.method == 'POST':
        name = request.form['name'].strip()
        if not name:
            flash('Item name is required.', 'danger')
            return redirect(url_for('store_edit', item_id=item_id))
        db.update_store_item(
            item_id,
            item_code=request.form.get('item_code', '').strip(),
            name=name,
            description=request.form.get('description', '').strip(),
            category=request.form.get('category', 'General').strip() or 'General',
            quantity=int(request.form.get('quantity', 0) or 0),
            unit=request.form.get('unit', 'pcs').strip() or 'pcs',
            min_stock=int(request.form.get('min_stock', 0) or 0),
            location=request.form.get('location', '').strip(),
        )
        flash('Store item updated.', 'success')
        return redirect(url_for('stores_list'))
    categories = db.get_store_categories()
    return render_template('store_form.html', item=item, categories=categories)


@app.route('/stores/adjust/<int:item_id>', methods=['POST'])
@login_required
def store_adjust(item_id):
    """Inline ROB correction: set an exact quantity and log an audit row."""
    data = request.get_json(silent=True) or {}
    if 'quantity' not in data:
        return {'ok': False, 'error': 'quantity is required'}, 400
    ok, result = db.adjust_store_quantity(
        item_id,
        data.get('quantity'),
        reason=(data.get('reason') or '').strip(),
        corrected_by=session.get('user_name', ''),
    )
    if not ok:
        return {'ok': False, 'error': result}, 400
    item = db.get_store_item(item_id)
    low = bool(item and item['min_stock'] and item['quantity'] <= item['min_stock'])
    return {'ok': True, 'old_quantity': result, 'quantity': item['quantity'],
            'min_stock': item['min_stock'], 'low': low}


@app.route('/stores/delete/<int:item_id>', methods=['POST'])
@login_required
def store_delete(item_id):
    item = db.get_store_item(item_id)
    if item:
        db.delete_store_item(item_id)
        flash(f'Store item "{item["name"]}" deleted.', 'success')
    return redirect(url_for('stores_list'))


# ── Lubricating Oils Routes ──

@app.route('/oils')
@login_required
def oils_list():
    items = db.get_all_oils()
    return render_template('oils_list.html', items=items)

@app.route('/oils/add', methods=['GET', 'POST'])
@admin_required
def oil_add():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Oil name is required.', 'danger')
            return redirect(url_for('oil_add'))
        # Handle safety sheet upload
        ss = ''
        if 'safety_sheet' in request.files:
            f = request.files['safety_sheet']
            if f.filename:
                os.makedirs(os.path.join(app.static_folder, 'safety_sheets'), exist_ok=True)
                ss = f'safety_sheets/oil_{name.replace(" ","_")}_{f.filename}'
                f.save(os.path.join(app.static_folder, ss))
        db.create_oil(
            name=name,
            grade=request.form.get('grade', '').strip(),
            uses=request.form.get('uses', '').strip(),
            quantity=float(request.form.get('quantity', 0) or 0),
            unit=request.form.get('unit', 'ltr').strip() or 'ltr',
            min_stock=float(request.form.get('min_stock', 0) or 0),
            location=request.form.get('location', '').strip(),
            safety_sheet=ss,
        )
        flash(f'Lubricating oil "{name}" added.', 'success')
        return redirect(url_for('oils_list'))
    return render_template('oil_form.html')

@app.route('/oils/edit/<int:item_id>', methods=['GET', 'POST'])
@admin_required
def oil_edit(item_id):
    item = db.get_oil(item_id)
    if not item:
        flash('Item not found.', 'danger')
        return redirect(url_for('oils_list'))
    if request.method == 'POST':
        ss = item.get('safety_sheet', '')
        if 'safety_sheet' in request.files:
            f = request.files['safety_sheet']
            if f.filename:
                os.makedirs(os.path.join(app.static_folder, 'safety_sheets'), exist_ok=True)
                ss = f'safety_sheets/oil_{item["name"].replace(" ","_")}_{f.filename}'
                f.save(os.path.join(app.static_folder, ss))
        db.update_oil(
            item_id,
            name=request.form.get('name', '').strip(),
            grade=request.form.get('grade', '').strip(),
            uses=request.form.get('uses', '').strip(),
            quantity=float(request.form.get('quantity', 0) or 0),
            unit=request.form.get('unit', 'ltr').strip() or 'ltr',
            min_stock=float(request.form.get('min_stock', 0) or 0),
            location=request.form.get('location', '').strip(),
            safety_sheet=ss,
        )
        flash('Oil updated.', 'success')
        return redirect(url_for('oils_list'))
    return render_template('oil_form.html', item=item)

@app.route('/oils/delete/<int:item_id>', methods=['POST'])
@admin_required
def oil_delete(item_id):
    item = db.get_oil(item_id)
    if item:
        db.delete_oil(item_id)
        flash(f'"{item["name"]}" deleted.', 'success')
    return redirect(url_for('oils_list'))


# ── Chemicals Routes ──

@app.route('/chemicals')
@login_required
def chemicals_list():
    items = db.get_all_chemicals()
    return render_template('chemicals_list.html', items=items)

@app.route('/chemicals/add', methods=['GET', 'POST'])
@admin_required
def chemical_add():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Chemical name is required.', 'danger')
            return redirect(url_for('chemical_add'))
        ss = ''
        if 'safety_sheet' in request.files:
            f = request.files['safety_sheet']
            if f.filename:
                os.makedirs(os.path.join(app.static_folder, 'safety_sheets'), exist_ok=True)
                ss = f'safety_sheets/chem_{name.replace(" ","_")}_{f.filename}'
                f.save(os.path.join(app.static_folder, ss))
        db.create_chemical(
            name=name,
            grade=request.form.get('grade', '').strip(),
            uses=request.form.get('uses', '').strip(),
            nature=request.form.get('nature', 'neutral').strip() or 'neutral',
            quantity=float(request.form.get('quantity', 0) or 0),
            unit=request.form.get('unit', 'ltr').strip() or 'ltr',
            min_stock=float(request.form.get('min_stock', 0) or 0),
            location=request.form.get('location', '').strip(),
            safety_sheet=ss,
        )
        flash(f'Chemical "{name}" added.', 'success')
        return redirect(url_for('chemicals_list'))
    return render_template('chemical_form.html')

@app.route('/chemicals/edit/<int:item_id>', methods=['GET', 'POST'])
@admin_required
def chemical_edit(item_id):
    item = db.get_chemical(item_id)
    if not item:
        flash('Item not found.', 'danger')
        return redirect(url_for('chemicals_list'))
    if request.method == 'POST':
        ss = item.get('safety_sheet', '')
        if 'safety_sheet' in request.files:
            f = request.files['safety_sheet']
            if f.filename:
                os.makedirs(os.path.join(app.static_folder, 'safety_sheets'), exist_ok=True)
                ss = f'safety_sheets/chem_{item["name"].replace(" ","_")}_{f.filename}'
                f.save(os.path.join(app.static_folder, ss))
        db.update_chemical(
            item_id,
            name=request.form.get('name', '').strip(),
            grade=request.form.get('grade', '').strip(),
            uses=request.form.get('uses', '').strip(),
            nature=request.form.get('nature', 'neutral').strip() or 'neutral',
            quantity=float(request.form.get('quantity', 0) or 0),
            unit=request.form.get('unit', 'ltr').strip() or 'ltr',
            min_stock=float(request.form.get('min_stock', 0) or 0),
            location=request.form.get('location', '').strip(),
            safety_sheet=ss,
        )
        flash('Chemical updated.', 'success')
        return redirect(url_for('chemicals_list'))
    return render_template('chemical_form.html', item=item)

@app.route('/chemicals/delete/<int:item_id>', methods=['POST'])
@admin_required
def chemical_delete(item_id):
    item = db.get_chemical(item_id)
    if item:
        db.delete_chemical(item_id)
        flash(f'"{item["name"]}" deleted.', 'success')
    return redirect(url_for('chemicals_list'))


# ── Greases Routes ──

@app.route('/greases')
@login_required
def greases_list():
    items = db.get_all_greases()
    return render_template('greases_list.html', items=items)

@app.route('/greases/add', methods=['GET', 'POST'])
@admin_required
def grease_add():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Grease name is required.', 'danger')
            return redirect(url_for('grease_add'))
        db.create_grease(
            name=name,
            grade=request.form.get('grade', '').strip(),
            uses=request.form.get('uses', '').strip(),
            quantity=float(request.form.get('quantity', 0) or 0),
            unit=request.form.get('unit', 'kg').strip() or 'kg',
            min_stock=float(request.form.get('min_stock', 0) or 0),
            location=request.form.get('location', '').strip(),
        )
        flash(f'Grease "{name}" added.', 'success')
        return redirect(url_for('greases_list'))
    return render_template('grease_form.html')

@app.route('/greases/edit/<int:item_id>', methods=['GET', 'POST'])
@admin_required
def grease_edit(item_id):
    item = db.get_grease(item_id)
    if not item:
        flash('Item not found.', 'danger')
        return redirect(url_for('greases_list'))
    if request.method == 'POST':
        db.update_grease(
            item_id,
            name=request.form.get('name', '').strip(),
            grade=request.form.get('grade', '').strip(),
            uses=request.form.get('uses', '').strip(),
            quantity=float(request.form.get('quantity', 0) or 0),
            unit=request.form.get('unit', 'kg').strip() or 'kg',
            min_stock=float(request.form.get('min_stock', 0) or 0),
            location=request.form.get('location', '').strip(),
        )
        flash('Grease updated.', 'success')
        return redirect(url_for('greases_list'))
    return render_template('grease_form.html', item=item)

@app.route('/greases/delete/<int:item_id>', methods=['POST'])
@admin_required
def grease_delete(item_id):
    item = db.get_grease(item_id)
    if item:
        db.delete_grease(item_id)
        flash(f'"{item["name"]}" deleted.', 'success')
    return redirect(url_for('greases_list'))


# ── Transaction Routes ──

@app.route('/transaction', methods=['GET', 'POST'])
@login_required
def transaction_add():
    if request.method == 'POST':
        t_type = request.form['transaction_type']
        category = request.form['item_category']
        raw_id = request.form.get('item_id', '')
        quantity = int(request.form.get('quantity', 0) or 0)
        crew_name = request.form.get('crew_name', '').strip()
        remarks = request.form.get('remarks', '').strip()

        # Parse "category:id" format from dropdown value
        if ':' in str(raw_id):
            parts = str(raw_id).split(':', 1)
            category = parts[0]
            item_id = int(parts[1])
        else:
            item_id = int(raw_id)

        if quantity <= 0:
            flash('Quantity must be greater than zero.', 'danger')
            return redirect(url_for('transaction_add'))

        # Check stock for usage
        if t_type == 'usage':
            if category == 'spares':
                part = db.get_spare_part(item_id)
                if part and part['quantity'] < quantity:
                    flash(f'Insufficient stock. Available: {part["quantity"]}', 'danger')
                    return redirect(url_for('transaction_add'))
            elif category == 'stores':
                item = db.get_store_item(item_id)
                if item and item['quantity'] < quantity:
                    flash(f'Insufficient stock. Available: {item["quantity"]}', 'danger')
                    return redirect(url_for('transaction_add'))
            elif category == 'oils':
                item = db.get_oil(item_id)
                if item and item['quantity'] < quantity:
                    flash(f'Insufficient stock. Available: {item["quantity"]}', 'danger')
                    return redirect(url_for('transaction_add'))
            elif category == 'chemicals':
                item = db.get_chemical(item_id)
                if item and item['quantity'] < quantity:
                    flash(f'Insufficient stock. Available: {item["quantity"]}', 'danger')
                    return redirect(url_for('transaction_add'))
            elif category == 'greases':
                item = db.get_grease(item_id)
                if item and item['quantity'] < quantity:
                    flash(f'Insufficient stock. Available: {item["quantity"]}', 'danger')
                    return redirect(url_for('transaction_add'))

        db.record_transaction(t_type, category, item_id, quantity, crew_name, remarks)
        type_label = 'Received' if t_type == 'receipt' else 'Used'
        new_rob = ''
        if category == 'stores':
            it = db.get_store_item(item_id)
            new_rob = f' New ROB: {it["quantity"]} {it["unit"]}.' if it else ''
        flash(f'{type_label} {quantity} item(s) successfully.{new_rob}', 'success')
        return redirect(url_for('transactions'))

    # Pre-populate from query params
    pre_category = request.args.get('category', '')
    pre_type = request.args.get('type', '')
    pre_item = request.args.get('item_id', '')

    crew = db.get_all_crew()
    spares_items = []
    stores_items = []
    oils_items = []
    chemicals_items = []
    greases_items = []
    if pre_category == 'spares' or not pre_category:
        for m in db.get_all_machinery():
            for p in db.get_spare_parts_by_machinery(m['id']):
                p['machinery_name'] = m['name']
                spares_items.append(p)
    # Stores picker is a type-ahead search (14k+ items): only fetch the
    # pre-selected item for deep links; the rest is loaded via /api/stores/lookup.
    if pre_item and pre_category == 'stores':
        try:
            stores_items = [db.get_store_item(int(pre_item))]
        except (TypeError, ValueError):
            stores_items = []
    if pre_category == 'oils' or not pre_category:
        oils_items = db.get_all_oils()
    if pre_category == 'chemicals' or not pre_category:
        chemicals_items = db.get_all_chemicals()
    if pre_category == 'greases' or not pre_category:
        greases_items = db.get_all_greases()

    # Build spares grouped by machinery name
    machinery_spares = {}
    for m in db.get_all_machinery():
        parts = db.get_spare_parts_by_machinery(m['id'])
        if parts:
            machinery_spares[m['name']] = [
                {'id': p['id'], 'part_number': p['part_number'],
                 'description': p['description'], 'quantity': p['quantity']}
                for p in parts
            ]

    return render_template('transaction_form.html',
                           machinery_spares=machinery_spares,
                           spares_items=spares_items, stores_items=stores_items,
                           oils_items=oils_items, chemicals_items=chemicals_items,
                           greases_items=greases_items,
                           crew=crew, pre_category=pre_category,
                           pre_type=pre_type, pre_item=pre_item)


@app.route('/transactions')
@login_required
def transactions():
    category = request.args.get('category', '')
    t_type = request.args.get('type', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    txns = db.get_transactions(
        item_category=category if category else None,
        transaction_type=t_type if t_type else None,
        date_from=date_from if date_from else None,
        date_to=date_to if date_to else None,
        limit=500,
    )
    return render_template('transactions_list.html', transactions=txns,
                           category=category, t_type=t_type,
                           date_from=date_from, date_to=date_to)


# ── PDF Import ──

@app.route('/import-pdf', methods=['GET', 'POST'])
@admin_required
def import_pdf():
    if request.method == 'POST':
        if 'pdf_file' not in request.files:
            flash('No file selected.', 'danger')
            return redirect(url_for('import_pdf'))

        file = request.files['pdf_file']
        if file.filename == '':
            flash('No file selected.', 'danger')
            return redirect(url_for('import_pdf'))

        if not file.filename.lower().endswith('.pdf'):
            flash('Please upload a PDF file.', 'danger')
            return redirect(url_for('import_pdf'))

        machinery_id = request.form.get('machinery_id')

        # Save temp file
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
            file.save(tmp.name)
            tmp_path = tmp.name

        try:
            result = parse_pdf(tmp_path)
            machinery = db.get_all_machinery()
            return render_template('import_preview.html',
                                   result=result, machinery_id=machinery_id,
                                   machinery=machinery,
                                   filename=file.filename)
        except Exception as e:
            flash(f'Error parsing PDF: {str(e)}', 'danger')
            return redirect(url_for('import_pdf'))
        finally:
            os.unlink(tmp_path)

    machinery = db.get_all_machinery()
    return render_template('import_pdf.html', machinery=machinery)


@app.route('/import-confirm', methods=['POST'])
@admin_required
def import_confirm():
    """Confirm and save parsed spare parts from PDF."""
    machinery_id = request.form.get('machinery_id')
    parts_json = request.form.get('parts_json', '[]')
    new_machinery_name = request.form.get('new_machinery_name', '').strip()

    if not machinery_id and not new_machinery_name:
        flash('Please select or create machinery.', 'danger')
        return redirect(url_for('import_pdf'))

    # Create new machinery if needed
    if not machinery_id and new_machinery_name:
        machinery_id = db.create_machinery(name=new_machinery_name)
    else:
        machinery_id = int(machinery_id)

    try:
        parts = json.loads(parts_json)
        # Filter out unchecked parts
        checked_parts = [p for p in parts if p.get('selected', True)]
        if checked_parts:
            db.bulk_create_spare_parts(machinery_id, checked_parts)
            flash(f'Imported {len(checked_parts)} spare parts successfully.', 'success')
        else:
            flash('No parts selected for import.', 'warning')
    except Exception as e:
        flash(f'Error importing parts: {str(e)}', 'danger')

    return redirect(url_for('machinery_view', machinery_id=machinery_id))


# ── IMPA Stores Import ──

@app.route('/import-stores', methods=['GET', 'POST'])
@admin_required
def import_stores():
    if request.method == 'POST':
        if 'pdf_file' not in request.files:
            flash('No file selected.', 'danger')
            return redirect(url_for('import_stores'))

        file = request.files['pdf_file']
        if file.filename == '' or not file.filename.lower().endswith('.pdf'):
            flash('Please upload a PDF file.', 'danger')
            return redirect(url_for('import_stores'))

        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
            file.save(tmp.name)
            tmp_path = tmp.name

        try:
            import impa_parser
            items = impa_parser.parse_impa_pdf(tmp_path)
            return render_template('import_stores_preview.html',
                                   items=items, filename=file.filename)
        except Exception as e:
            flash(f'Error parsing PDF: {str(e)}', 'danger')
            return redirect(url_for('import_stores'))
        finally:
            os.unlink(tmp_path)

    return render_template('import_stores.html')


@app.route('/import-stores-confirm', methods=['POST'])
@admin_required
def import_stores_confirm():
    items_json = request.form.get('items_json', '[]')
    try:
        items = json.loads(items_json)
        checked = [i for i in items if i.get('selected', True)]
        if checked:
            imported = 0
            for item in checked:
                impa_code = item.get('impa_code', '').strip()
                name = item.get('name', '').strip() or item.get('description', '').strip()
                description = item.get('description', '').strip()
                if impa_code and name:
                    existing = db.search_stores(impa_code)
                    if not existing:
                        db.create_store_item(
                            name=name,
                            item_code=impa_code,
                            description=description,
                        )
                        imported += 1
            db.apply_min_stock_defaults()
            flash(f'Imported {imported} store items ({len(checked) - imported} duplicates skipped).', 'success')
        else:
            flash('No items selected for import.', 'warning')
    except Exception as e:
        flash(f'Error importing: {str(e)}', 'danger')

    return redirect(url_for('stores_list'))


# ── CSV Import ──

@app.route('/import-csv-stores', methods=['GET', 'POST'])
@admin_required
def import_csv_stores():
    if request.method == 'POST':
        if 'csv_file' not in request.files:
            flash('No file selected.', 'danger')
            return redirect(url_for('import_csv_stores'))
        file = request.files['csv_file']
        if file.filename == '' or not file.filename.lower().endswith('.csv'):
            flash('Please upload a CSV file.', 'danger')
            return redirect(url_for('import_csv_stores'))

        try:
            import csv, io
            content = file.read().decode('utf-8-sig')  # handle BOM
            reader = csv.DictReader(io.StringIO(content))

            db.ensure_import_batch_column()
            existing_codes = db.get_existing_store_codes()
            batch = datetime.now().strftime('import-%Y%m%d-%H%M%S')

            to_insert = []
            seen_codes = set()
            skipped = 0
            for row in reader:
                impa_code = (row.get('impa_code', '') or row.get('IMPA Code', '') or row.get('item_code', '')).strip()
                name = (row.get('name', '') or row.get('Name', '') or row.get('description', '')).strip()
                description = (row.get('description', '') or row.get('Description', '') or name).strip()
                category = (row.get('category', '') or row.get('Category', '') or 'General').strip()
                quantity = (row.get('quantity', '') or row.get('Quantity', '') or '0').strip()
                unit = (row.get('unit', '') or row.get('Unit', '') or 'pcs').strip()
                min_stock = (row.get('min_stock', '') or row.get('Min Stock', '') or '0').strip()
                location = (row.get('location', '') or row.get('Location', '') or '').strip()

                if not name:
                    skipped += 1
                    continue

                # Fast dedupe: skip codes already in DB or already seen in this file
                if impa_code:
                    if impa_code in existing_codes or impa_code in seen_codes:
                        skipped += 1
                        continue
                    seen_codes.add(impa_code)

                to_insert.append({
                    'item_code': impa_code,
                    'name': name,
                    'description': description,
                    'category': category or 'General',
                    'quantity': int(quantity) if quantity.isdigit() else 0,
                    'unit': unit or 'pcs',
                    'min_stock': int(min_stock) if min_stock.isdigit() else 0,
                    'location': location,
                })

            imported = db.bulk_insert_stores(to_insert, import_batch=batch)
            db.apply_min_stock_defaults()
            flash(f'Imported {imported} store items ({skipped} skipped).', 'success')
        except Exception as e:
            flash(f'Error importing CSV: {str(e)}', 'danger')

        return redirect(url_for('stores_list'))

    return render_template('import_csv_stores.html')


@app.route('/import-csv-spares', methods=['GET', 'POST'])
@admin_required
def import_csv_spares():
    if request.method == 'POST':
        if 'csv_file' not in request.files:
            flash('No file selected.', 'danger')
            return redirect(url_for('import_csv_spares'))
        file = request.files['csv_file']
        if file.filename == '' or not file.filename.lower().endswith('.csv'):
            flash('Please upload a CSV file.', 'danger')
            return redirect(url_for('import_csv_spares'))

        machinery_id = request.form.get('machinery_id')
        new_machinery_name = request.form.get('new_machinery_name', '').strip()

        if not machinery_id and not new_machinery_name:
            flash('Please select or create machinery.', 'danger')
            return redirect(url_for('import_csv_spares'))

        if not machinery_id and new_machinery_name:
            machinery_id = db.create_machinery(name=new_machinery_name)
        else:
            machinery_id = int(machinery_id)

        try:
            import csv, io
            content = file.read().decode('utf-8-sig')
            reader = csv.DictReader(io.StringIO(content))
            imported = 0
            for row in reader:
                part_number = (row.get('part_number', '') or row.get('Part Number', '') or row.get('item_code', '')).strip()
                drawing_number = (row.get('drawing_number', '') or row.get('Drawing Number', '') or row.get('Drawing', '')).strip()
                description = (row.get('description', '') or row.get('Description', '') or row.get('name', '')).strip()
                quantity = row.get('quantity', row.get('Quantity', '0')).strip()
                unit = (row.get('unit', '') or row.get('Unit', '') or 'pcs').strip()
                min_stock = row.get('min_stock', row.get('Min Stock', '0')).strip()
                location = (row.get('location', '') or row.get('Location', '') or '').strip()

                if not description and not part_number:
                    continue

                db.create_spare_part(
                    machinery_id=machinery_id,
                    part_number=part_number,
                    drawing_number=drawing_number,
                    description=description or f'Part {part_number}',
                    quantity=int(quantity) if quantity.isdigit() else 0,
                    unit=unit,
                    min_stock=int(min_stock) if min_stock.isdigit() else 0,
                    location=location,
                )
                imported += 1

            flash(f'Imported {imported} spare parts.', 'success')
        except Exception as e:
            flash(f'Error importing CSV: {str(e)}', 'danger')

        return redirect(url_for('spares_by_machinery', machinery_id=machinery_id))

    machinery = db.get_all_machinery()
    return render_template('import_csv_spares.html', machinery=machinery)


@app.route('/download-sample/<sample_type>')
@login_required
def download_sample_csv(sample_type):
    import csv, io
    output = io.StringIO()
    writer = csv.writer(output)

    if sample_type == 'stores':
        writer.writerow(['impa_code', 'name', 'description', 'category', 'quantity', 'unit', 'min_stock', 'location'])
        writer.writerow(['81-13', 'Araldite Adhesive', 'Epoxy adhesive for metal bonding', 'Adhesives', '10', 'pcs', '2', 'Store Room A'])
        writer.writerow(['63-15', 'Drill Chuck Arbor', 'Morse taper drill chuck arbor', 'Tools', '5', 'pcs', '1', 'Workshop'])
        writer.writerow(['33-91', 'Asbestos Safety Kits', 'Fire-resistant safety kit', 'Safety', '3', 'set', '1', 'Safety Store'])
        filename = 'stores_sample.csv'
    elif sample_type == 'spares':
        writer.writerow(['part_number', 'drawing_number', 'description', 'quantity', 'unit', 'min_stock', 'location'])
        writer.writerow(['P-001', 'DWG-1470-001', 'Hydraulic Jack Complete', '5', 'pcs', '2', 'Spare Store'])
        writer.writerow(['P-002', 'DWG-1470-002', 'Sealing Ring with Back-up', '20', 'pcs', '5', 'Spare Store'])
        writer.writerow(['P-003', '', 'Hex Key Set', '3', 'set', '1', 'Workshop'])
        filename = 'spares_sample.csv'
    elif sample_type == 'count-sheet':
        writer.writerow(['impa_code', 'counted_qty', 'remarks'])
        writer.writerow(['33.0140', '2', 'found in locker 3'])
        writer.writerow(['81-13', '1', 'sealant opened, part used'])
        writer.writerow(['5901234', '6', ''])
        filename = 'count_sheet_sample.csv'
    else:
        flash('Invalid sample type.', 'danger')
        return redirect(url_for('dashboard'))

    output.seek(0)
    from flask import Response
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


# ── Requisition (printable low-ROB order sheet) ──

@app.route('/requisition')
@login_required
def requisition():
    """Printable requisition of low-ROB items grouped by category, with blank
    order-quantity and remarks columns for handwriting."""
    category = request.args.get('category', '').strip()
    search = request.args.get('search', '').strip()
    try:
        limit = int(request.args.get('limit', 500))
    except ValueError:
        limit = 500

    items = db.get_low_stock_stores()  # worst-first
    total_low = len(items)
    if category:
        items = [i for i in items if i['category'] == category]
    if search:
        s = search.lower()
        items = [i for i in items
                 if s in (i['name'] or '').lower()
                 or s in (i['item_code'] or '').lower()]
    filtered_total = len(items)
    truncated = 0 < limit < filtered_total
    if truncated:
        items = items[:limit]

    groups = {}
    for i in items:
        groups.setdefault(i['category'], []).append(i)
    grouped = sorted(groups.items(), key=lambda kv: kv[0])

    return render_template('requisition.html', grouped=grouped,
                           total_low=total_low, filtered_total=filtered_total,
                           truncated=truncated, limit=limit,
                           current_category=category, search=search,
                           categories=db.get_store_categories(),
                           now=datetime.now())


# ── Corrections Audit Log ──

@app.route('/corrections')
@login_required
def corrections_page():
    """Audit log of every ROB correction, filterable and paginated."""
    item = request.args.get('item', '').strip()
    user = request.args.get('user', '').strip()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    try:
        page = max(1, int(request.args.get('page', 1)))
    except ValueError:
        page = 1
    PER_PAGE = 50

    corrections, total = db.get_stock_corrections(
        item=item, corrected_by=user, date_from=date_from, date_to=date_to,
        page=page, per_page=PER_PAGE)
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    users = db.get_correction_users()

    delta_total = sum(c['new_quantity'] - c['old_quantity'] for c in corrections)
    return render_template('corrections.html', corrections=corrections,
                           users=users, total=total, page=page,
                           total_pages=total_pages, per_page=PER_PAGE,
                           f_item=item, f_user=user,
                           f_from=date_from, f_to=date_to,
                           page_delta=delta_total)


@app.route('/corrections/export')
@login_required
def corrections_export():
    """CSV export of the filtered correction log (no pagination)."""
    import csv, io
    from flask import Response

    item = request.args.get('item', '').strip()
    user = request.args.get('user', '').strip()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()

    rows, _total = db.get_stock_corrections(
        item=item, corrected_by=user, date_from=date_from, date_to=date_to,
        page=1, per_page=1000000)  # generous cap; export is login-only
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['timestamp', 'item_code', 'item_name', 'category',
                     'old_rob', 'new_rob', 'delta', 'reason', 'corrected_by'])
    for r in rows:
        writer.writerow([r['created_at'], r['item_code'], r['item_name'],
                         r['category'], r['old_quantity'], r['new_quantity'],
                         r['new_quantity'] - r['old_quantity'], r['reason'],
                         r['corrected_by']])
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition':
                 'attachment; filename=stock_corrections.csv'})


# ── Count-Sheet Import (physical stock take) ──

def _canon_impa(code):
    """'33.0140'/'330140' -> '0330140' (same canonical form as the import prep)."""
    import re as _re
    d = _re.sub(r'\D', '', code or '')
    return d.zfill(7) if 5 <= len(d) <= 7 else ''


@app.route('/import-count-sheet', methods=['GET', 'POST'])
@admin_required
def import_count_sheet():
    if request.method == 'POST':
        if 'csv_file' not in request.files:
            flash('No file selected.', 'danger')
            return redirect(url_for('import_count_sheet'))
        file = request.files['csv_file']
        if file.filename == '' or not file.filename.lower().endswith('.csv'):
            flash('Please upload a CSV file.', 'danger')
            return redirect(url_for('import_count_sheet'))
        try:
            threshold = int(request.form.get('threshold', 10) or 10)
        except ValueError:
            threshold = 10

        try:
            import csv, io
            content = file.read().decode('utf-8-sig')
            reader = csv.DictReader(io.StringIO(content))

            by_raw, by_canon = {}, {}
            for it in db.get_all_stores():
                code = (it.get('item_code') or '').strip()
                if not code:
                    continue
                by_raw[code] = it
                c = _canon_impa(code)
                if c:
                    by_canon.setdefault(c, it)

            matched, unmatched, no_change = [], [], []
            seen_ids = set()
            for row in reader:
                code = (row.get('impa_code') or row.get('IMPA Code')
                        or row.get('code') or '').strip()
                qty_s = (row.get('counted_qty') or row.get('counted')
                         or row.get('quantity') or '').strip()
                remarks = (row.get('remarks') or row.get('note') or '').strip()
                if not code and not qty_s:
                    continue
                item = by_raw.get(code) or by_canon.get(_canon_impa(code))
                if not item:
                    unmatched.append({'code': code, 'counted': qty_s,
                                      'remarks': remarks})
                    continue
                if item['id'] in seen_ids:
                    continue  # duplicate count row for the same item: first wins
                seen_ids.add(item['id'])
                try:
                    counted = int(float(qty_s))
                except (TypeError, ValueError):
                    unmatched.append({'code': code, 'counted': qty_s,
                                      'remarks': remarks,
                                      'error': 'unreadable quantity'})
                    continue
                current = item['quantity']
                delta = counted - current
                pct = (abs(delta) / current * 100.0) if current else \
                    (100.0 if delta else 0.0)
                entry = {
                    'item_id': item['id'], 'code': item['item_code'],
                    'name': item['name'], 'category': item['category'],
                    'unit': item['unit'], 'current': current,
                    'counted': counted, 'delta': delta, 'pct': round(pct),
                    'flagged': bool(delta and pct > threshold),
                    'remarks': remarks, 'selected': True,
                }
                (no_change if delta == 0 else matched).append(entry)

            matched.sort(key=lambda e: (not e['flagged'], -abs(e['delta'])))
            return render_template('import_count_sheet_preview.html',
                                   rows=matched, no_change=no_change,
                                   unmatched=unmatched, threshold=threshold,
                                   filename=file.filename)
        except Exception as e:
            flash(f'Error parsing count sheet: {str(e)}', 'danger')
            return redirect(url_for('import_count_sheet'))

    return render_template('import_count_sheet.html')


@app.route('/import-count-sheet-confirm', methods=['POST'])
@admin_required
def import_count_sheet_confirm():
    try:
        rows = json.loads(request.form.get('rows_json', '[]'))
    except ValueError:
        rows = []
    selected = [r for r in rows if r.get('selected')]
    applied = db.apply_stock_take(selected,
                                  corrected_by=session.get('user_name', ''))
    skipped = len(selected) - applied
    flash(f'Stock take applied: {applied} item(s) updated '
          f'({skipped} already matched the count).', 'success')
    return redirect(url_for('stores_list'))


# ── Stock Settings ──

@app.route('/stock-settings', methods=['GET', 'POST'])
@admin_required
def stock_settings():
    """Per-category min-stock defaults; applying fills min_stock = 0 rows only."""
    if request.method == "POST":
        try:
            default = int(request.form.get('default_min', '0') or 0)
        except ValueError:
            default = 0
        cats = {}
        for key, val in request.form.items():
            if key.startswith('cat_'):
                cat = key[4:]
                if not val.strip():
                    continue  # empty = inherit global default
                try:
                    cats[cat] = int(val or 0)
                except ValueError:
                    cats[cat] = 0
        db.save_stock_settings(default, cats)
        if request.form.get('apply') == '1':
            updated = db.apply_min_stock_defaults()
            flash(f'Saved. Applied defaults to {updated} item(s) that had no min stock.', 'success')
        else:
            flash('Stock settings saved.', 'success')
        return redirect(url_for('stock_settings'))

    settings = db.get_stock_settings()
    counts = {c['category']: c for c in db.get_store_category_counts()}
    return render_template('stock_settings.html', settings=settings, counts=counts)


# ── Backup & Restore ──

@app.route('/backup')
@admin_required
def backup_page():
    backups = db.list_backups()
    stats = db.get_db_stats()
    return render_template('backup.html', backups=backups, stats=stats)


@app.route('/backup/create', methods=['POST'])
@admin_required
def backup_create():
    try:
        db.auto_backup()
        flash('Backup created successfully.', 'success')
    except Exception as e:
        flash(f'Backup failed: {str(e)}', 'danger')
    return redirect(url_for('backup_page'))


@app.route('/backup/download/<filename>')
@admin_required
def backup_download(filename):
    import re
    if not re.match(r'^[\w\-]+\.db$', filename):
        abort(400)
    backup_path = os.path.join(db.BACKUP_DIR, filename)
    if not os.path.exists(backup_path):
        flash('Backup not found.', 'danger')
        return redirect(url_for('backup_page'))
    from flask import send_file
    return send_file(backup_path, as_attachment=True, download_name=filename)


@app.route('/backup/restore/<filename>', methods=['POST'])
@admin_required
def backup_restore(filename):
    import re
    if not re.match(r'^[\w\-]+\.db$', filename):
        abort(400)
    backup_path = os.path.join(db.BACKUP_DIR, filename)
    try:
        db.restore_backup(backup_path)
        flash(f'Restored from {filename}. Restart the app for changes to take effect.', 'success')
    except Exception as e:
        flash(f'Restore failed: {str(e)}', 'danger')
    return redirect(url_for('backup_page'))


@app.route('/backup/upload', methods=['POST'])
@admin_required
def backup_upload():
    if 'backup_file' not in request.files:
        flash('No file selected.', 'danger')
        return redirect(url_for('backup_page'))
    file = request.files['backup_file']
    if file.filename == '' or not file.filename.endswith('.db'):
        flash('Please upload a .db file.', 'danger')
        return redirect(url_for('backup_page'))
    try:
        os.makedirs(db.BACKUP_DIR, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        save_path = os.path.join(db.BACKUP_DIR, f'upload_{timestamp}.db')
        file.save(save_path)
        # Restore from uploaded file
        db.restore_backup(save_path)
        flash('Database restored from uploaded file. Restart the app.', 'success')
    except Exception as e:
        flash(f'Upload failed: {str(e)}', 'danger')
    return redirect(url_for('backup_page'))


@app.route('/export-db')
@admin_required
def export_db():
    from flask import send_file
    return send_file(db.DB_PATH, as_attachment=True,
                     download_name=f'ship_inventory_{datetime.now().strftime("%Y%m%d")}.db')


@app.route('/api/db-stats')
@login_required
def api_db_stats():
    return jsonify(db.get_db_stats())


# ── Reports ──

@app.route('/reports')
@login_required
def reports():
    now = datetime.now()

    # Date range parameters
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    year = request.args.get('year', '')
    month = request.args.get('month', '')

    # Determine report title and params
    report_title = 'Inventory Report'
    report_params = {}

    if date_from or date_to:
        # Custom date range mode
        report_params['date_from'] = date_from
        report_params['date_to'] = date_to
        if date_from and date_to:
            report_title = f'Inventory Report — {date_from} to {date_to}'
        elif date_from:
            report_title = f'Inventory Report — From {date_from}'
        else:
            report_title = f'Inventory Report — Up to {date_to}'
    elif year:
        year_int = int(year)
        report_params['year'] = year_int
        if month:
            month_int = int(month)
            report_params['month'] = month_int
            months_map = {1:'January',2:'February',3:'March',4:'April',5:'May',6:'June',
                         7:'July',8:'August',9:'September',10:'October',11:'November',12:'December'}
            report_title = f'Inventory Report — {months_map.get(month_int,"")} {year_int}'
        else:
            report_title = f'Inventory Report — Full Year {year_int}'
    else:
        # Default: current year
        report_params['year'] = now.year
        report_title = f'Inventory Report — Full Year {now.year}'

    data = db.get_report_data(**report_params)
    years = list(range(now.year - 5, now.year + 1))
    months = [
        (1, 'January'), (2, 'February'), (3, 'March'), (4, 'April'),
        (5, 'May'), (6, 'June'), (7, 'July'), (8, 'August'),
        (9, 'September'), (10, 'October'), (11, 'November'), (12, 'December'),
    ]

    return render_template('reports.html', data=data, years=years, months=months,
                           report_title=report_title, now=now,
                           date_from=date_from, date_to=date_to,
                           year=report_params.get('year', now.year),
                           month=report_params.get('month'))


@app.route('/reports/print')
@login_required
def reports_print():
    """Print-friendly report view."""
    now = datetime.now()

    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    year = request.args.get('year', '')
    month = request.args.get('month', '')

    report_title = 'Inventory Report'
    report_params = {}

    if date_from or date_to:
        report_params['date_from'] = date_from
        report_params['date_to'] = date_to
        if date_from and date_to:
            report_title = f'Inventory Report — {date_from} to {date_to}'
        elif date_from:
            report_title = f'Inventory Report — From {date_from}'
        else:
            report_title = f'Inventory Report — Up to {date_to}'
    elif year:
        year_int = int(year)
        report_params['year'] = year_int
        months_map = {1:'January',2:'February',3:'March',4:'April',5:'May',6:'June',
                     7:'July',8:'August',9:'September',10:'October',11:'November',12:'December'}
        if month:
            month_int = int(month)
            report_params['month'] = month_int
            report_title = f'Inventory Report — {months_map.get(month_int,"")} {year_int}'
        else:
            report_title = f'Inventory Report — Full Year {year_int}'
    else:
        report_params['year'] = now.year
        report_title = f'Inventory Report — Full Year {now.year}'

    data = db.get_report_data(**report_params)

    return render_template('reports_print.html', data=data,
                           report_title=report_title, now=now,
                           date_from=date_from, date_to=date_to,
                           year=report_params.get('year', now.year),
                           month=report_params.get('month'))


# ── Monthly Close-Out (C/E review checklist) ──

def _closeout_data(year, month):
    """Everything the C/E reviews at month end, scoped to one calendar month."""
    last_day = calendar.monthrange(year, month)[1]
    date_from = f'{year}-{month:02d}-01'
    date_to = f'{year}-{month:02d}-{last_day:02d}'
    like = f'{year}-{month:02d}%'

    consumption = db.get_stores_consumption(year=year, month=month)

    # Corrections logged this month (any item_category)
    with db.db_connection() as conn:
        corr_rows = conn.execute(
            "SELECT sc.created_at, sc.old_quantity, sc.new_quantity, "
            "sc.reason, sc.corrected_by, s.item_code, s.name, s.category, s.unit "
            "FROM stock_corrections sc LEFT JOIN stores s ON s.id = sc.item_id "
            "WHERE sc.created_at LIKE ? "
            "ORDER BY sc.created_at DESC", (like,)).fetchall()
    corrections = [dict(r) for r in corr_rows]

    low = db.get_low_stock_stores()  # worst-first

    return {
        'year': year, 'month': month, 'date_from': date_from, 'date_to': date_to,
        'consumption': consumption,
        'corrections': corrections,
        'low_items': low,
        'low_total': len(low),
    }


@app.route('/close-out')
@login_required
def close_out():
    now = datetime.now()
    try:
        year = int(request.args.get('year', now.year))
    except (TypeError, ValueError):
        year = now.year
    try:
        month = int(request.args.get('month', now.month))
    except (TypeError, ValueError):
        month = now.month
    month = min(max(month, 1), 12)

    data = _closeout_data(year, month)
    months_map = {1: 'January', 2: 'February', 3: 'March', 4: 'April',
                  5: 'May', 6: 'June', 7: 'July', 8: 'August',
                  9: 'September', 10: 'October', 11: 'November', 12: 'December'}
    return render_template('close_out.html', data=data,
                           month_name=months_map[month], now=now)


@app.route('/close-out/print')
@login_required
def close_out_print():
    now = datetime.now()
    try:
        year = int(request.args.get('year', now.year))
    except (TypeError, ValueError):
        year = now.year
    try:
        month = int(request.args.get('month', now.month))
    except (TypeError, ValueError):
        month = now.month
    month = min(max(month, 1), 12)

    data = _closeout_data(year, month)
    months_map = {1: 'January', 2: 'February', 3: 'March', 4: 'April',
                  5: 'May', 6: 'June', 7: 'July', 8: 'August',
                  9: 'September', 10: 'October', 11: 'November', 12: 'December'}
    return render_template('close_out_print.html', data=data,
                           month_name=months_map[month], now=now)


# ── Stores Consumption Report ──

def _consumption_params():
    """Shared year/month/date-range parsing for the consumption views."""
    now = datetime.now()
    year = request.args.get('year', str(now.year))
    month = request.args.get('month', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    params = {}
    if date_from or date_to:
        params['date_from'] = date_from or None
        params['date_to'] = date_to or None
    else:
        try:
            params['year'] = int(year)
        except (TypeError, ValueError):
            params['year'] = now.year
        if month:
            try:
                params['month'] = int(month)
            except (TypeError, ValueError):
                pass
    return params


@app.route('/reports/consumption')
@login_required
def reports_consumption():
    """Stores consumption screen report: usage per item + per-category totals."""
    now = datetime.now()
    params = _consumption_params()

    data = db.get_stores_consumption(**params)
    return render_template('report_consumption.html', data=data,
                           year=request.args.get('year', str(now.year)),
                           month=request.args.get('month', ''),
                           date_from=request.args.get('date_from', ''),
                           date_to=request.args.get('date_to', ''), now=now)


@app.route('/reports/consumption/print')
@login_required
def reports_consumption_print():
    """Print view for the stores consumption report."""
    now = datetime.now()
    params = _consumption_params()

    data = db.get_stores_consumption(**params)
    return render_template('report_consumption_print.html', data=data,
                           year=request.args.get('year', str(now.year)),
                           month=request.args.get('month', ''),
                           date_from=request.args.get('date_from', ''),
                           date_to=request.args.get('date_to', ''), now=now)


@app.route('/reports/consumption/export')
@login_required
def reports_consumption_export():
    """CSV export of the consumption report (honors the same filters)."""
    import csv, io
    from flask import Response

    data = db.get_stores_consumption(**_consumption_params())

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['category', 'item_code', 'item_name', 'unit',
                     'times_used', 'total_qty', 'last_used'])
    for r in data['rows']:
        writer.writerow([r['category'], r['item_code'] or '', r['name'],
                         r['unit'] or 'pcs', r['txn_count'], r['total_qty'],
                         (r['last_used'] or '')[:19]])
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition':
                 'attachment; filename=stores_consumption.csv'})


# ── Crew Management ──

@app.route('/crew', methods=['GET', 'POST'])
@admin_required
def crew_manage():
    if request.method == 'POST':
        name = request.form['name'].strip()
        rank = request.form.get('rank', '').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        role = request.form.get('role', 'user').strip()
        if name:
            db.create_crew_member(name, rank, username, password, role)
            flash(f'Crew member "{name}" added.', 'success')
        return redirect(url_for('crew_manage'))
    crew = db.get_all_crew()
    return render_template('crew_list.html', crew=crew)


@app.route('/crew/delete/<int:crew_id>', methods=['POST'])
@admin_required
def crew_delete(crew_id):
    db.delete_crew_member(crew_id)
    flash('Crew member removed.', 'success')
    return redirect(url_for('crew_manage'))


# ── Search API ──

@app.route('/api/search')
@login_required
def api_search():
    query = request.args.get('q', '').strip()
    category = request.args.get('category', 'all')
    results = []

    if len(query) >= 2:
        if category in ('all', 'spares'):
            for p in db.search_spare_parts(query):
                results.append({
                    'type': 'spare',
                    'id': p['id'],
                    'name': p['description'],
                    'code': p['part_number'],
                    'machinery': p.get('machinery_name', ''),
                    'qty': p['quantity'],
                })
        if category in ('all', 'stores'):
            for s in db.search_stores(query):
                results.append({
                    'type': 'store',
                    'id': s['id'],
                    'name': s['name'],
                    'code': s['item_code'],
                    'machinery': s['category'],
                    'qty': s['quantity'],
                })

    return jsonify(results)


@app.route('/api/stores/lookup')
@login_required
def api_stores_lookup():
    """Lightweight type-ahead for the transaction form's stores picker.
    Matches code (prefix), then name (substring); caps results at 25."""
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    limit = 25
    with db.db_connection() as conn:
        like = f"%{q}%"
        rows = conn.execute(
            "SELECT id, item_code, name, category, quantity, unit "
            "FROM stores WHERE item_code LIKE ? OR name LIKE ? "
            "ORDER BY CASE WHEN item_code LIKE ? THEN 0 ELSE 1 END, name "
            "LIMIT ?",
            (like, like, f"{q}%", limit)
        ).fetchall()
    return jsonify([dict(r) for r in rows])


# ── Context Processors ──

@app.context_processor
def inject_globals():
    _cfg = _get_config()
    # Derive active_page from request path for sidebar highlighting
    path = request.path.strip('/')
    active_page = ''
    if path == '' or path == 'index':
        active_page = 'dashboard'
    elif 'import-pdf' in path:
        active_page = 'import-pdf'
    elif 'import-stores' in path:
        active_page = 'import_stores'
    elif 'import-csv-stores' in path:
        active_page = 'import_csv_stores'
    elif 'import-csv-spares' in path:
        active_page = 'import_csv_spares'
    elif 'spares' in path:
        active_page = 'spares'
    elif 'stores' in path:
        active_page = 'stores'
    elif 'oils' in path:
        active_page = 'oils'
    elif 'chemicals' in path:
        active_page = 'chemicals'
    elif 'greases' in path:
        active_page = 'greases'
    elif 'transaction' in path and 'transactions' not in path:
        active_page = 'transaction'
    elif 'transactions' in path:
        active_page = 'transactions'
    elif 'machinery' in path:
        active_page = 'machinery'
    elif 'crew' in path:
        active_page = 'crew'
    elif 'backup' in path:
        active_page = 'backup'
    elif 'reports' in path:
        active_page = 'reports'
    elif 'change-password' in path:
        active_page = 'change-password'

    return {
        'app_name': 'Ship Inventory',
        'ship_name': _cfg.get('ship_name', ''),
        'active_page': active_page,
        'now': datetime.now(),
        'current_user': {
            'id': session.get('user_id'),
            'name': session.get('user_name', ''),
            'rank': session.get('user_rank', ''),
            'role': session.get('user_role', ''),
        } if 'user_id' in session else None,
    }


# ── Run ──

def _get_config():
    """Read config.txt (written by setup.py), returns dict with port and ship_name."""
    config = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.txt")
    cfg = {"port": 8080, "ship_name": ""}
    if os.path.exists(config):
        with open(config, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("port="):
                    try: cfg["port"] = int(line.split("=", 1)[1])
                    except ValueError: pass
                elif line.startswith("ship_name="):
                    cfg["ship_name"] = line.split("=", 1)[1].strip()
    return cfg

if __name__ == '__main__':
    _cfg = _get_config()
    port = _cfg["port"]
    ship = _cfg["ship_name"]
    if ship:
        print(f"\n  ⚓ {ship} — Inventory System")
    print(f"  🌐 Running on http://0.0.0.0:{port}")

    # Print database stats
    stats = db.get_db_stats()
    if 'error' not in stats:
        print(f"  💾 Database: {stats['db_size']//1024}KB")
        for table, count in stats['tables'].items():
            if count and count != 'N/A' and count > 0:
                print(f"     {table}: {count} records")
    backups = db.list_backups()
    if backups:
        print(f"  📁 Backups: {len(backups)} available (latest: {backups[0]['modified']})")
    print()
    app.run(host='0.0.0.0', port=port, debug=False)
