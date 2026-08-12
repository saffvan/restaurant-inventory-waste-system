"""
db.py
------
This file is responsible for ONE thing: setting up the SQLite database
and giving the rest of the app a way to connect to it.
"""

import sqlite3
import os

# Absolute path based on this file's own location, not the current
# working directory. Without this, running the app from a different
# folder (e.g. `streamlit run restaurant_inventory/app.py` from one
# level up) silently creates a NEW empty database in the wrong place
# instead of using the real one.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "inventory.db")


def get_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            category_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            near_expiry_days INTEGER NOT NULL DEFAULT 3,
            critical_expiry_days INTEGER NOT NULL DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ingredients (
            ingredient_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category_id INTEGER NOT NULL,
            unit TEXT NOT NULL,
            opening_stock REAL NOT NULL DEFAULT 0,
            opening_stock_date TEXT NOT NULL,
            reorder_period_days INTEGER NOT NULL DEFAULT 7,
            FOREIGN KEY (category_id) REFERENCES categories(category_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS batches (
            batch_id INTEGER PRIMARY KEY AUTOINCREMENT,
            ingredient_id INTEGER NOT NULL,
            purchase_date TEXT NOT NULL,
            expiry_date TEXT NOT NULL,
            quantity_purchased REAL NOT NULL,
            quantity_remaining REAL NOT NULL,
            unit_cost REAL NOT NULL,
            is_opening_stock INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (ingredient_id) REFERENCES ingredients(ingredient_id)
        )
    """)

    # Migration: CREATE TABLE IF NOT EXISTS above does nothing to a
    # batches table that already existed before is_opening_stock was
    # added, so add the column here if it's missing. This lets an
    # existing inventory.db upgrade in place instead of needing to be
    # recreated from scratch.
    cur.execute("PRAGMA table_info(batches)")
    existing_columns = {row["name"] for row in cur.fetchall()}
    if "is_opening_stock" not in existing_columns:
        cur.execute("ALTER TABLE batches ADD COLUMN is_opening_stock INTEGER NOT NULL DEFAULT 0")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS usage_log (
            usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
            ingredient_id INTEGER NOT NULL,
            usage_date TEXT NOT NULL,
            quantity_used REAL NOT NULL,
            FOREIGN KEY (ingredient_id) REFERENCES ingredients(ingredient_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS waste_log (
            waste_id INTEGER PRIMARY KEY AUTOINCREMENT,
            ingredient_id INTEGER NOT NULL,
            waste_date TEXT NOT NULL,
            quantity_wasted REAL NOT NULL,
            reason TEXT NOT NULL,
            unit_cost REAL NOT NULL,
            waste_cost REAL NOT NULL,
            FOREIGN KEY (ingredient_id) REFERENCES ingredients(ingredient_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS batch_consumption (
            consumption_id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL,
            source_type TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            quantity REAL NOT NULL,
            FOREIGN KEY (batch_id) REFERENCES batches(batch_id)
        )
    """)

    conn.commit()
    conn.close()
    # Use the module-level DB_NAME rather than a hardcoded string — tests
    # (see test_engine.py) point this at a throwaway test DB, and a
    # hardcoded message here would misleadingly claim "inventory.db" was
    # initialized even when it wasn't.
    print(f"Database initialized successfully -> {DB_NAME}")


if __name__ == "__main__":
    init_db()
