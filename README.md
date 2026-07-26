# ⚓ Ship Inventory Management System

A web-based inventory management system designed for merchant vessels, managing **Stores** and **Spare Parts** with machinery-specific organization.

## Quick Start

```bash
cd ~/ship-inventory
./start.sh
```

Then open **http://localhost:8080** in any browser.

### Access from Ship's LAN

Any device on the ship's network can access the system. The startup script shows the LAN IP address (e.g., `http://192.168.x.x:8080`).

### Default Login

| Field | Value |
|-------|-------|
| Username | `admin` |
| Password | `admin` |

⚠️ **Change the admin password immediately after first login!**

---

## Features

### 📊 Dashboard
- Overview of all inventory stats
- Low stock alerts for both spares and stores
- Recent transaction history
- Monthly usage chart

### ⚙️ Spare Parts (organized by machinery)
- Sub-sections for each machinery onboard
- Part number, description, quantity, min stock, location tracking
- Low-stock highlighting
- **PDF Import**: Upload manufacturer spare parts list PDFs to auto-populate inventory

### 📦 Stores
- General stores organized by category
- Search and filter by category
- Low-stock alerts

### 🔄 Transactions
- Record receipts (incoming stock) and usage (consumption)
- Automatic stock level updates
- Crew member attribution
- Stock validation (prevents negative inventory)
- Full transaction history with filters

### 📈 Reports
- Monthly and yearly reports
- Spare parts and stores activity summaries
- Print-friendly report format
- Receipts vs. usage breakdown

### 👥 Crew Management
- Add crew members with name and rank
- Assign login credentials with roles (Admin / User)
- Admin: Full access (manage machinery, import PDFs, crew)
- User: View inventory, record transactions

---

## Architecture

| Component | Technology |
|-----------|-----------|
| Backend | Python / Flask |
| Database | SQLite (zero-config) |
| Frontend | Custom maritime-themed UI + Bootstrap 5 |
| PDF Parser | pdfplumber |
| Charts | Chart.js |

## Project Structure

```
ship-inventory/
├── app.py              # Flask application (all routes)
├── database.py         # Database schema and operations
├── pdf_parser.py       # PDF spare parts list parser
├── requirements.txt    # Python dependencies
├── start.sh            # Startup script (shows LAN access info)
├── static/
│   └── style.css       # Maritime-themed CSS
├── templates/          # 18 Jinja2 templates
│   ├── base.html           # Master layout with sidebar
│   ├── login.html          # Login page
│   ├── dashboard.html      # Main dashboard
│   ├── spares_overview.html    # All machinery cards
│   ├── spares_list.html        # Parts for one machinery
│   ├── spare_form.html         # Add/edit spare part
│   ├── stores_list.html        # Stores inventory
│   ├── store_form.html         # Add/edit store item
│   ├── transaction_form.html   # Record receipt/usage
│   ├── transactions_list.html  # Transaction history
│   ├── import_pdf.html         # Upload PDF
│   ├── import_preview.html     # Review parsed parts
│   ├── reports.html            # Monthly/yearly reports
│   ├── reports_print.html      # Print-friendly reports
│   ├── machinery_list.html     # All machinery
│   ├── machinery_form.html     # Add/edit machinery
│   ├── machinery_view.html     # Machinery detail + parts
│   ├── crew_list.html          # Crew management
│   └── change_password.html    # Change password
└── venv/               # Python virtual environment
```

## Access Control

| Action | Admin | User |
|--------|-------|------|
| View inventory | ✓ | ✓ |
| Record transactions | ✓ | ✓ |
| View reports | ✓ | ✓ |
| Search items | ✓ | ✓ |
| Add/edit machinery | ✓ | ✗ |
| Import PDF | ✓ | ✗ |
| Add/edit stores | ✓ | ✗ |
| Manage crew | ✓ | ✗ |

## LAN Access Setup

1. Run `./start.sh` on the ship's server computer
2. Note the LAN IP shown (e.g., `192.168.0.105:8080`)
3. Open that URL on any device connected to the ship's network
4. All crew members can access simultaneously

The system uses SQLite which supports concurrent reads. For heavy concurrent write usage, consider the built-in Flask server limitations.
