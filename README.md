# Restaurant Inventory & Food Waste Analytics System

MCA Mini Project (20MCA245) — MES College of Engineering, Kuttippuram.

A Streamlit-based inventory management system for restaurants, focused on
FEFO (First-Expiring-First-Out) batch tracking and food waste cost analytics.

## How to run

```bash
pip install -r requirements.txt
python seed_data.py      # optional: populates realistic demo data
streamlit run app.py
```

## Architecture

- **`db.py`** — SQLite schema and connection handling. 6 tables:
  `categories`, `ingredients`, `batches`, `usage_log`, `waste_log`,
  `batch_consumption`.
- **`engine.py`** — all business logic (FEFO consumption, stock
  calculation, expiry classification, reorder alerts, accurate waste
  costing). No UI code — every function is independently testable.
- **`style.py`** — shared CSS/theme tweaks applied on every page.
- **`app.py`** — Home page.
- **`pages/`** — one file per feature (Categories, Ingredients,
  Purchases, Usage, Waste, Dashboard). Streamlit auto-generates the
  sidebar navigation from this folder.
- **`seed_data.py`** — generates 3 weeks of realistic demo data.

## Key design decisions

- **Opening stock is stored as a real batch**, not a separate number.
  This keeps `batches` as the single source of truth for stock, so
  FEFO/Usage/Waste can always see and consume it correctly.
- **`batch_consumption`** records exactly which batch(es) a usage/waste
  entry drew from and how much. This enables (a) exact reversal on
  delete, and (b) accurate cost attribution when a single transaction
  spans multiple batches bought at different prices.
- **Master data (Categories, Ingredients) can be edited.** Transactional
  records (Purchases, Usage, Waste) can only be deleted, never edited —
  matching standard accounting/inventory audit-trail practice.
- **Cooking (Usage) excludes expired batches** from FEFO selection —
  expired stock should only ever be removed via Waste, never used in
  a recipe.

## Core formulas

- `Current Stock = SUM(batches.quantity_remaining)` for that ingredient
- `Reorder Point = Average Daily Usage (14-day) x Reorder Period (days)`
- `Waste Cost = sum of (quantity taken from each batch x that batch's own unit cost)`

## Known limitations

- No multi-user login/auth (single-user local app, appropriate for
  mini-project scope).
- SQLite is file-based; not designed for concurrent multi-writer use.
