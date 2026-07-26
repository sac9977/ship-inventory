# Ship Inventory Management System — Implementation Plan

> **Developed by Chief Engineer Sachin Kadam**
> Last updated: 25 July 2026

---

## 1. Project Overview

A zero-config, offline-capable inventory management system designed for merchant vessels. Flask (Python) + SQLite backend, maritime-themed responsive UI. Ships on LAN via `0.0.0.0:8080`. All assets bundled locally — no internet required.

**Target users:** Non-technical crew members on merchant vessels.

---

## 2. Architecture

```
ship-inventory/
├── app.py                 # Flask app — all routes, auth, context processor
├── database.py            # SQLite schema, 40+ CRUD/query functions
├── pdf_parser.py          # PDF spare parts parser (pdfplumber + PyMuPDF fallback)
├── impa_parser.py         # IMPA Index PDF parser (PyMuPDF, 628+ entries)
├── requirements.txt       # flask, pdfplumber, PyMuPDF, werkzeug
├── setup.py               # Universal installer (--ship-name, --port, --reset)
├── healthcheck.py         # Diagnostic tool (Python, deps, DB, network)
├── start.sh               # Launch script (reads config.txt, shows LAN IP)
├── install.bat            # Windows double-click installer
├── INSTALL.html           # Visual installation guide (6 steps)
├── README.md              # Full documentation
├── IMPLEMENTATION_PLAN.md # This file
├── config.txt             # Runtime config (ship_name, port) — created by setup.py
├── ship_inventory.db      # SQLite database — auto-created on first run
├── templates/             # 29 Jinja2 templates
│   ├── base.html          # Master layout — sidebar, nav, flash, ship name
│   ├── login.html         # Standalone login page
│   ├── dashboard.html     # Stats cards, recent transactions, low-stock alerts
│   ├── machinery_list.html
│   ├── machinery_form.html
│   ├── spares_list.html   # Parts table with Drawing/Plate No. column
│   ├── spare_form.html    # Add/edit spare part (with drawing_number)
│   ├── stores_list.html
│   ├── store_form.html
│   ├── oils_list.html     # Lubricating oils with safety sheet links
│   ├── oil_form.html      # Add/edit oil (grade, uses, safety sheet upload)
│   ├── chemicals_list.html # Chemicals with nature badges (acidic/alkaline/neutral)
│   ├── chemical_form.html  # Add/edit chemical (grade, uses, nature, safety sheet)
│   ├── greases_list.html  # Greases list
│   ├── grease_form.html   # Add/edit grease (grade, uses)
│   ├── transaction_form.html  # Record receipt/usage (all 5 categories, spares grouped by machinery)
│   ├── transactions_list.html # Filterable transaction history
│   ├── import_preview.html    # PDF import preview with machinery selection
│   ├── import_stores.html     # IMPA Index PDF upload
│   ├── import_stores_preview.html  # IMPA preview with editable descriptions
│   ├── import_csv_stores.html # CSV upload for stores
│   ├── import_csv_spares.html # CSV upload for spares (with machinery selection)
│   ├── reports.html       # Date-range reports with 4 sections
│   ├── reports_print.html # Print-optimized report layout
│   ├── crew_list.html     # User management (admin only)
│   └── change_password.html
├── static/
│   ├── style.css          # Maritime CSS (navy/steel theme)
│   ├── vendor/            # Local assets (zero CDN)
│   │   ├── bootstrap.min.css
│   │   ├── bootstrap.bundle.min.js
│   │   └── chart.min.js
│   └── safety_sheets/     # Uploaded MSDS/SDS files (created on first upload)
```

---

## 3. Database Schema

### Tables

| Table | Purpose | Key Fields |
|-------|---------|------------|
| `machinery` | Ship machinery/engines | name, type, manufacturer, model, description |
| `spare_parts` | Spare parts per machinery | machinery_id, part_number, **drawing_number**, description, quantity, unit, min_stock, location |
| `stores` | General stores/consumables | item_code (IMPA), name, description, category, quantity, unit, min_stock, location |
| `lubricating_oils` | Lube oils inventory | name, grade, uses, quantity, unit, min_stock, location, **safety_sheet** |
| `chemicals` | Chemicals inventory | name, grade, uses, **nature** (neutral/acidic/alkaline), quantity, unit, min_stock, location, **safety_sheet** |
| `greases` | Grease inventory | name, grade, uses, quantity, unit, min_stock, location |
| `transactions` | Receipt/usage log | **transaction_type** (receipt/usage), **item_category** (spares/stores/oils/chemicals/greases), item_id, quantity, crew_name, remarks |
| `crew` | User accounts | name, rank, username (unique), password_hash, role (admin/user), active |

### Relationships
- `spare_parts.machinery_id` → `machinery.id` (CASCADE DELETE)
- `transactions` uses polymorphic references: `item_category` + `item_id` maps to any of the 5 inventory tables

---

## 4. Feature Inventory

### 4.1 Authentication & Access Control ✅
- [x] Session-based login with 7-day "remember me"
- [x] Default admin account (admin/admin) created on first run
- [x] `@login_required` on all routes
- [x] `@admin_required` on create/edit/delete routes
- [x] User role management (admin/user) — admin-only can add users
- [x] Password change for logged-in users
- [x] Admin-only sidebar sections (hidden for regular users)

### 4.2 Spare Parts Module ✅
- [x] Machinery grouping (list → view → add/edit parts)
- [x] Fields: part_number, **drawing_number**, description, quantity, unit, min_stock, location
- [x] CRUD with error handling (try/except on all routes)
- [x] Drawing/Plate Number field — added per maritime requirement
- [x] Low-stock highlighting in list view

### 4.3 Stores Module ✅
- [x] IMPA number field (`item_code`)
- [x] Category field for organization
- [x] Full CRUD

### 4.4 Lubricating Oils Module ✅
- [x] Fields: name, grade, uses, quantity, unit, min_stock, location
- [x] **Safety sheet upload** (PDF stored in `static/safety_sheets/`)
- [x] Safety sheet download link in list view
- [x] Full CRUD

### 4.5 Chemicals Module ✅
- [x] Fields: name, grade, uses, **nature** (neutral/acidic/alkaline), quantity, unit, min_stock, location
- [x] **Safety sheet upload** (PDF stored in `static/safety_sheets/`)
- [x] Color-coded nature badges (🔴 Acidic, 🔵 Alkaline, 🟢 Neutral)
- [x] Full CRUD

### 4.6 Greases Module ✅
- [x] Fields: name, grade, uses, quantity, unit, min_stock, location
- [x] Full CRUD

### 4.7 Transaction System ✅
- [x] Record receipt (stock in) or usage (stock out)
- [x] All 5 categories: spares, stores, oils, chemicals, greases
- [x] Auto-updates stock quantity on transaction
- [x] Stock validation — prevents usage exceeding available quantity
- [x] Crew name and remarks fields
- [x] Category radio buttons that dynamically update item dropdown (JS)
- [x] Parses `"category:id"` format from dropdown values
- [x] **Spare parts grouped by machinery** in dropdown (`<optgroup>`) for easier navigation

### 4.8 PDF Import (Spare Parts) ✅ (partial)
- [x] Multi-table extraction with header detection
- [x] Pattern matching for part numbers, descriptions, quantities
- [x] Maritime-specific skip patterns (headers, footers, page numbers)
- [x] Preview page with machinery assignment before confirm
- [x] **PyMuPDF installed and working** — extracts item numbers from CID-encoded fonts
- [x] Noise filtering (dates, doc numbers, page refs, CID-garbled headers)
- [ ] Full CID font decoding — proprietary MAN font mapping cannot be decoded without embedded CMap
- [ ] Description text from CID-encoded pages is partially garbled

### 4.9 IMPA Index Import ✅
- [x] `impa_parser.py` — PyMuPDF-based parser for IMPA Index PDF (29 pages)
- [x] Extracts **628+ unique IMPA codes** with descriptions
- [x] Dual extraction: normal text for readable pages, reversed text for garbled pages
- [x] Preview page with editable descriptions and select/deselect checkboxes
- [x] Duplicate IMPA codes skipped on import
- [x] Route: `/import-stores` (upload) → `/import-stores-confirm` (bulk insert)
- [x] Sidebar link under Stores section

### 4.10 CSV Import ✅
- [x] **Stores CSV import** — `/import-csv-stores`
  - Columns: `impa_code`, `name`, `description`, `category`, `quantity`, `unit`, `min_stock`, `location`
  - Only `name` required. Duplicate IMPA codes skipped.
  - Flexible column names (case-insensitive, handles aliases)
- [x] **Spare parts CSV import** — `/import-csv-spares`
  - Columns: `part_number`, `drawing_number`, `description`, `quantity`, `unit`, `min_stock`, `location`
  - Assign to existing machinery or create new during import
- [x] **Sample CSV downloads** — `/download-sample/stores` and `/download-sample/spares`
  - Pre-filled with 3 example rows showing exact format
- [x] Sidebar links for both (admin-only)
- [x] UTF-8 BOM handling for Excel-exported CSVs

### 4.11 Reports ✅
- [x] Custom date range (From/To picker)
- [x] Quick-select shortcuts (This Month, Last Month, Year to Date, Last 30 Days)
- [x] 4-section layout: Spares Received | Spares Used | Stores Received | Stores Used
- [x] Print-optimized layout (`/reports/print`)
- [x] Developer credit on print header

### 4.12 Global Search ✅
- [x] API endpoint `/api/search?q=<query>`
- [x] Searches across spares (description + part_number) and stores (name + description + item_code)
- [x] Live search from sidebar

### 4.13 Dashboard ✅
- [x] Stats cards: machinery count, spare parts, stores, oils, chemicals, greases
- [x] Low-stock alerts (spares and stores)
- [x] Recent transactions (last 10)
- [x] Monthly usage chart (Chart.js)

### 4.14 Packaging & Distribution ✅
- [x] `setup.py` — universal installer with `--ship-name`, `--port`, `--reset`
- [x] `install.bat` — Windows double-click installer
- [x] `start.sh` — launch script with LAN IP display
- [x] `healthcheck.py` — diagnostic tool
- [x] `INSTALL.html` — visual installation guide
- [x] `README.md` — full documentation
- [x] All CDN assets bundled in `static/vendor/` (Bootstrap, Chart.js)
- [x] Windows encoding fix (`encoding="utf-8"` on all `open()` calls)
- [x] Ship name customization (stored in `config.txt`)
- [x] Developer credit on login, footer, and print reports

### 4.15 Sidebar Navigation ✅
- [x] Auto-highlighting of current page (path-based `active_page` in context processor)
- [x] Organized sections: Overview, Spare Parts, Stores, Consumables, Operations, Reports, Admin
- [x] Admin-only sections hidden from regular users
- [x] All import options accessible from sidebar

---

## 5. Known Issues & Limitations

### 5.1 PDF CID Font Encoding ⚠️
- **Problem:** Some manufacturer PDFs use CID-encoded fonts (e.g., MAN HelveticaNeue) with proprietary character maps not embedded in the PDF.
- **Impact:** Pages using these fonts produce partially garbled descriptions. Item numbers decode correctly (control chars 0x12–0x1B map to digits 0–9).
- **Workaround:** PyMuPDF extracts readable item numbers. Users can edit descriptions after import.
- **Alternative:** Use CSV import for 100% reliable data entry.

### 5.2 IMPA Index PDF ⚠️
- **Problem:** The IMPA Index PDF uses CID-encoded fonts on odd-numbered pages, producing garbled descriptions.
- **Impact:** ~70% of descriptions are readable, ~30% are partially garbled.
- **Workaround:** Preview page allows editing all descriptions before import. CSV import available as alternative.

### 5.3 SQLite Limitations
- No concurrent write support (fine for single-ship LAN use)
- WAL mode could improve read performance under load
- No built-in full-text search (could add FTS5 for better search)

### 5.4 Safety Sheets
- Files stored on disk (`static/safety_sheets/`) — not in database
- No file size limit enforcement (should add)
- No cleanup of orphaned files on record deletion

---

## 6. Configuration

### config.txt (created by setup.py)
```
ship_name=MV Example Vessel
port=8080
```

### Default Credentials
- **Admin:** username `admin`, password `admin`
- Users should change admin password after first login

### Environment
- Python 3.9+ (ships with macOS; Windows typically has 3.10+)
- Flask 3.1.1
- pdfplumber (for standard PDF parsing)
- PyMuPDF (for CID-encoded PDF fallback + IMPA Index parsing)

---

## 7. Deployment per Ship

### Quick Install
```bash
# 1. Copy ship-inventory.zip to the ship's computer
# 2. Extract to any folder
# 3. Run setup:
python setup.py --ship-name "MV Example Vessel"

# 4. Start:
bash start.sh
# → App runs at http://192.168.x.x:8080
```

### First-Time Setup
1. Login as `admin`/`admin`
2. Change admin password (Admin → Change Password)
3. Create crew accounts (Admin → Crew Management)
4. Add machinery (Spare Parts → Add Machinery)
5. Import spare parts:
   - **PDF Import** — upload manufacturer PDF (best for official catalogs)
   - **CSV Import** — upload prepared CSV file (most reliable)
   - **Manual Entry** — add parts one by one
6. Import stores:
   - **IMPA Index PDF** — upload IMPA Index (auto-extracts 628+ codes)
   - **CSV Import** — upload prepared CSV file
   - **Manual Entry** — add items one by one
7. Add oils, chemicals, greases as needed

### Data Import Options Summary

| Data Type | PDF Import | CSV Import | Manual Entry |
|-----------|-----------|------------|--------------|
| Spare Parts | ✅ `import-pdf` | ✅ `import-csv-spares` | ✅ Add form |
| Stores (IMPA) | ✅ `import-stores` | ✅ `import-csv-stores` | ✅ Add form |
| Lubricating Oils | — | — | ✅ Add form |
| Chemicals | — | — | ✅ Add form |
| Greases | — | — | ✅ Add form |

### Access from Other Computers
Open browser on any ship computer: `http://<server-ip>:8080`
The launch script (`start.sh`) displays the LAN IP automatically.

---

## 8. Implementation Status

| Module | Status | Notes |
|--------|--------|-------|
| Auth & Users | ✅ Complete | |
| Machinery | ✅ Complete | |
| Spare Parts (with drawing_number) | ✅ Complete | |
| Stores (with IMPA) | ✅ Complete | |
| Lubricating Oils | ✅ Complete | Safety sheet upload working |
| Chemicals (with nature) | ✅ Complete | Safety sheet upload working |
| Greases | ✅ Complete | |
| Transactions (all 5 categories) | ✅ Complete | Spares grouped by machinery |
| Dashboard | ✅ Complete | Stats for all modules |
| Reports | ✅ Complete | 4-section layout |
| Global Search | ✅ Complete | |
| PDF Import (Spare Parts) | ⚠️ Partial | CID-encoded fonts produce garbled text |
| IMPA Index Import | ✅ Complete | 628+ entries, editable preview |
| CSV Import (Stores + Spares) | ✅ Complete | With sample downloads |
| Sidebar Navigation | ✅ Complete | Auto-highlighting, all sections |
| Packaging & Distribution | ✅ Complete | zip on Desktop |
| Offline Operation | ✅ Complete | All assets local |
| Ship Customization | ✅ Complete | Name in config.txt |

---

## 9. Future Enhancements (Backlog)

### Priority 1 — High Value
- [ ] **OCR-based PDF parsing** — Tesseract integration for scanned/encoded PDFs
- [ ] **Export to Excel** — Reports and inventory lists exportable as .xlsx
- [ ] **Stock alerts / notifications** — On-screen alerts when stock drops below minimum
- [ ] **Backup/restore** — One-click database backup and restore from UI
- [ ] **CSV export** — Export current inventory to CSV for backup/sharing

### Priority 2 — Useful Additions
- [ ] **Multi-language support** — Crew may include non-English speakers
- [ ] **Photo upload** — Attach photos to spare parts (helpful for identification)
- [ ] **Barcode/QR scanning** — Quick item lookup via phone camera
- [ ] **Consumption forecasting** — Historical usage patterns to predict reorder dates
- [ ] **Order requisition** — Generate purchase requisition forms for shore-side procurement
- [ ] **Minimum stock alerts** — Dashboard widget highlighting items below minimum

### Priority 3 — Nice to Have
- [ ] **Fleet sync** — Central office sees inventory across all vessels (when internet available)
- [ ] **Audit trail** — Who changed what and when (beyond transaction log)
- [ ] **GMDSS inventory** — Safety equipment tracking per SOLAS requirements
- [ ] **PO (Purchase Order) tracking** — Track orders from requisition to delivery
- [ ] **Barcode label printing** — Print labels for warehouse racking
- [ ] **Oils/Chemicals/Greases CSV import** — Bulk import for consumables

---

## 10. Testing Checklist

### Core Operations (all passing)
- [x] Add spare part (with drawing_number)
- [x] View spare parts list
- [x] Add store item
- [x] Add lubricating oil
- [x] Add chemical
- [x] Add grease
- [x] Record transaction (all 5 categories)
- [x] View transactions list
- [x] View dashboard
- [x] Delete operations
- [x] PDF import (spare parts) — 45 parts from MAIN ENGINE.pdf
- [x] IMPA Index import — 628 entries extracted
- [x] CSV import (stores) — 2 items imported
- [x] CSV import (spares) — 2 items imported
- [x] Sample CSV download (both types)
- [x] New user creation and login
- [x] Transaction form — spares grouped by machinery

### Edge Cases (to verify on ship)
- [ ] Multiple users accessing simultaneously
- [ ] PDF import with large files (100+ parts)
- [ ] IMPA Index import with full 29-page PDF
- [ ] CSV import with 1000+ rows
- [ ] Safety sheet upload (large PDF files)
- [ ] Windows deployment (encoding, path separators)
- [ ] Tablet/phone responsive layout
- [ ] Print reports from different browsers

---

## 11. File Change Log

| Date | Change | Files |
|------|--------|-------|
| 24 Jul 2026 | Initial build — all modules, templates, auth | All files |
| 24 Jul 2026 | Ship name customization, developer credit | app.py, base.html, login.html, setup.py |
| 24 Jul 2026 | Offline assets bundled (Bootstrap, Chart.js) | static/vendor/ |
| 24 Jul 2026 | Windows encoding fix | setup.py, app.py, healthcheck.py |
| 25 Jul 2026 | Added drawing_number to spare_parts | database.py, app.py, spare_form.html, spares_list.html |
| 25 Jul 2026 | Added lubricating oils, chemicals, greases modules | database.py, app.py, 6 new templates, base.html |
| 25 Jul 2026 | Fixed strftime errors on SQLite string fields | spares_list.html, transactions_list.html, dashboard.html |
| 25 Jul 2026 | Fixed transaction form (hidden→functional radios, dynamic dropdown) | transaction_form.html, app.py |
| 25 Jul 2026 | Fixed item_category CHECK constraint for new categories | database.py |
| 25 Jul 2026 | Installed PyMuPDF, added to requirements.txt | venv, requirements.txt |
| 25 Jul 2026 | PDF parser noise filtering (dates, doc numbers, page refs) | pdf_parser.py |
| 25 Jul 2026 | Transaction form: spares grouped by machinery (`<optgroup>`) | transaction_form.html, app.py |
| 25 Jul 2026 | IMPA Index parser (628+ entries, dual extraction) | impa_parser.py (new) |
| 25 Jul 2026 | IMPA Index import routes and templates | app.py, import_stores.html, import_stores_preview.html |
| 25 Jul 2026 | CSV import for stores and spares | app.py, import_csv_stores.html, import_csv_spares.html |
| 25 Jul 2026 | Sample CSV download routes | app.py (download-sample endpoint) |
| 25 Jul 2026 | Sidebar: CSV import links, IMPA import link, auto-highlighting | base.html, app.py (context processor) |
