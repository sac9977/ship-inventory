# Ship Inventory Management System — Implementation Plan

> **Developed by Chief Engineer Sachin Kadam**
> Last updated: 28 July 2026

---

## 1. Project Overview

A zero-config, offline-capable inventory management system designed for merchant vessels.
The system handles spares, stores, machinery, and transactions with a focus on maritime 
logistics (IMPA/ISM standards) and data resilience in remote environments.

---

## 2. Technical Stack

- **Frontend:** Flask (Jinja2), Bootstrap 5, Custom CSS (Maritime Theme)
- **Backend:** Python 3.9+, Flask 3.1.1
- **Database:** SQLite (with Write-Ahead Logging (WAL) enabled for power-loss resilience)
- **Deployment:** Single-folder standalone (Zero-config)

---

## 3. Core Features

### 3.1 Inventory Modules
- **Spare Parts:** Machinery-grouped spares with part number tracking.
- **Stores:** General consumables and supplies.
- **Machinery:** Tracking of critical shipboard components.
- **Transactions:** Full audit trail of stock movements (Receipt/Usage).

### 3.2 Intelligent Data Management
- **IMPA Integration:** Dual-strategy PDF parser for IMPA Index imports.
- **CSV Import:** Flexible bulk loading for stores and spares.
- **Data Protection:** Automatic database backup and restoration module.

### 3.3 Maritime UX
- **Diorama Splash Screen:** Immersive "Scroll-World" cinematic intro.
- **Dashboard:** High-level overview of stock levels, alerts, and transaction logs.
- **Adaptive UI:** Optimized for tablets and mobile devices on shipboard networks.

---

## 4. Implementation Roadmap

### Phase 1: Core CRUD & Logistics (COMPLETED)
- [x] Database schema (Machinery, Spares, Stores, Transactions)
- [x] Manual CRUD for all inventory types
- [x] Machinery-grouped spare lists
- [x] Transaction history and logic

### Phase 2: Intelligent Imports & Data Protection (COMPLETED)
- [x] IMPA PDF parsing (`impa_parser.py`)
- [x] CSV import for Stores/Spares
- [x] SQLite WAL mode & Auto-backup system
- [x] Backup/Restore Admin interface

### Phase 3: Visual Experience & UX (IN PROGRESS)
- [x] Maritime UI Theme (Bootstrap + Custom CSS)
- [ ] Cinematic Splash Screen (`scroll-world` architecture)
- [ ] Automated Video Intro (Macro-cinematic)
- [ ] Dashboard "Hero" Visualization

### Phase 4: Distribution & Deployment (COMPLETED)
- [x] Git repository setup (GitHub)
- [x] Standardized installation scripts (`setup.py`, `install.bat`)
- [x] Maintenance & Troubleshooting guides

---

## 5. Data Integrity & Safety

- **Database:** Always use `database.py` for queries. Never modify `.db` directly.
- **Backups:** Check `backups/` directory for historical recovery points.
- **Shutdowns:** App uses `wal` mode to ensure data integrity during sudden power loss.

---

## 6. Log of Changes

- **2026-07-28:** Implemented cinematic splash screen architecture and backup/restore.
- **2026-07-28:** Added IMPA/CSV import modules and machine-grouped transactions.
- **2026-07-28:** Established GitHub repository and deployment package.
