"""
seed_data.py
-------------
Generates realistic demo data. Run this ONCE whenever you want a
fresh, populated demo:
    python3 seed_data.py
"""

import random
from datetime import date, timedelta
from db import get_connection, init_db
from engine import consume_stock_fefo, get_actual_cost_for_source

random.seed(42)
TODAY = date.today()


def reset_data():
    init_db()
    conn = get_connection()
    cur = conn.cursor()
    for table in ["batch_consumption", "waste_log", "usage_log", "batches", "ingredients", "categories"]:
        cur.execute(f"DELETE FROM {table}")
    conn.commit()
    conn.close()
    print("Existing data cleared.")


CATEGORIES = [
    ("Vegetables", 3, 1),
    ("Dairy", 4, 2),
    ("Meat", 2, 1),
    ("Grains", 10, 3),
    ("Bakery", 3, 1),
]

INGREDIENTS = [
    ("Tomato", "Vegetables", "kg", 10, 5, 5),
    ("Onion", "Vegetables", "kg", 15, 7, 14),
    ("Potato", "Vegetables", "kg", 20, 7, 20),
    ("Milk", "Dairy", "litre", 8, 3, 4),
    ("Paneer", "Dairy", "kg", 4, 4, 6),
    ("Butter", "Dairy", "kg", 3, 7, 30),
    ("Chicken", "Meat", "kg", 6, 3, 3),
    ("Mutton", "Meat", "kg", 4, 4, 3),
    ("Rice", "Grains", "kg", 30, 14, 180),
    ("Wheat Flour", "Grains", "kg", 20, 14, 90),
    ("Bread", "Bakery", "pcs", 10, 2, 3),
    ("Bun", "Bakery", "pcs", 15, 2, 3),
]

WASTE_REASONS = ["Spoilage", "Expiry", "Damaged", "Prep-Handling"]

UNIT_COSTS = {
    "Tomato": 30, "Onion": 25, "Potato": 20, "Milk": 55, "Paneer": 320,
    "Butter": 480, "Chicken": 220, "Mutton": 650, "Rice": 60,
    "Wheat Flour": 40, "Bread": 35, "Bun": 8,
}


def seed_categories(conn):
    cur = conn.cursor()
    for name, near, crit in CATEGORIES:
        cur.execute(
            "INSERT INTO categories (name, near_expiry_days, critical_expiry_days) VALUES (?, ?, ?)",
            (name, near, crit)
        )
    conn.commit()
    print(f"Inserted {len(CATEGORIES)} categories.")


def seed_ingredients(conn):
    """
    Creates each ingredient AND, if it has opening stock, a matching
    batch for that opening stock (using the ingredient's shelf-life
    figure for a realistic expiry date). This mirrors what the
    Ingredients page itself does — opening stock must be a real batch,
    or FEFO/Usage/Waste can never actually see or consume it.
    """
    cur = conn.cursor()
    cur.execute("SELECT category_id, name FROM categories")
    cat_lookup = {row["name"]: row["category_id"] for row in cur.fetchall()}

    ingredient_ids = {}
    opening_date = (TODAY - timedelta(days=21)).isoformat()

    for name, cat_name, unit, opening_stock, reorder_period, shelf_life in INGREDIENTS:
        cur.execute("""
            INSERT INTO ingredients
                (name, category_id, unit, opening_stock, opening_stock_date, reorder_period_days)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (name, cat_lookup[cat_name], unit, opening_stock, opening_date, reorder_period))
        ingredient_id = cur.lastrowid
        ingredient_ids[name] = ingredient_id

        if opening_stock > 0:
            opening_expiry = (TODAY - timedelta(days=21) + timedelta(days=shelf_life))
            cur.execute("""
                INSERT INTO batches
                    (ingredient_id, purchase_date, expiry_date, quantity_purchased, quantity_remaining, unit_cost, is_opening_stock)
                VALUES (?, ?, ?, ?, ?, ?, 1)
            """, (ingredient_id, opening_date, opening_expiry.isoformat(), opening_stock, opening_stock, UNIT_COSTS[name]))

    conn.commit()
    print(f"Inserted {len(INGREDIENTS)} ingredients (each with an opening-stock batch).")
    return ingredient_ids


def seed_purchases(conn, ingredient_ids):
    cur = conn.cursor()
    purchase_qty_range = {
        "Tomato": (8, 15), "Onion": (10, 20), "Potato": (15, 25), "Milk": (5, 10),
        "Paneer": (2, 5), "Butter": (1, 3), "Chicken": (4, 8), "Mutton": (2, 5),
        "Rice": (10, 25), "Wheat Flour": (8, 15), "Bread": (10, 20), "Bun": (15, 25),
    }

    count = 0
    for name, _, _, _, _, shelf_life in INGREDIENTS:
        ingredient_id = ingredient_ids[name]
        day_offset = 20
        while day_offset >= 0:
            purchase_date = TODAY - timedelta(days=day_offset)
            expiry_date = purchase_date + timedelta(days=shelf_life)
            qty = round(random.uniform(*purchase_qty_range[name]), 1)
            cost = UNIT_COSTS[name] * round(random.uniform(0.9, 1.1), 2)

            cur.execute("""
                INSERT INTO batches
                    (ingredient_id, purchase_date, expiry_date, quantity_purchased, quantity_remaining, unit_cost)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (ingredient_id, purchase_date.isoformat(), expiry_date.isoformat(), qty, qty, round(cost, 2)))
            count += 1
            day_offset -= random.choice([3, 4])

    conn.commit()
    print(f"Inserted {count} purchase batches.")


def seed_usage_and_waste(conn, ingredient_ids):
    usage_count = 0
    waste_count = 0
    cur = conn.cursor()

    daily_usage_range = {
        "Tomato": (1, 3), "Onion": (1.5, 4), "Potato": (2, 5), "Milk": (1, 2.5),
        "Paneer": (0.3, 1), "Butter": (0.1, 0.4), "Chicken": (0.5, 2), "Mutton": (0.3, 1.2),
        "Rice": (1, 3), "Wheat Flour": (0.5, 2), "Bread": (1, 3), "Bun": (1, 4),
    }

    for day_offset in range(20, -1, -1):
        current_date = TODAY - timedelta(days=day_offset)

        for name, _, _, _, _, _ in INGREDIENTS:
            ingredient_id = ingredient_ids[name]
            low, high = daily_usage_range[name]
            qty = round(random.uniform(low, high), 2)

            cur.execute("""
                INSERT INTO usage_log (ingredient_id, usage_date, quantity_used)
                VALUES (?, ?, ?)
            """, (ingredient_id, current_date.isoformat(), qty))
            usage_id = cur.lastrowid
            # exclude_expired=True — cooking should never draw on expired
            # stock, same rule the real Usage page enforces. as_of_date
            # judges expiry against THIS simulated day (current_date),
            # not the real today — otherwise, walking back through 21
            # days of history, a batch that's since expired (relative to
            # today) would be wrongly excluded from a day when it was
            # still perfectly fresh, distorting the simulated usage.
            success, _ = consume_stock_fefo(
                ingredient_id, qty, conn=conn, source_type="usage", source_id=usage_id,
                exclude_expired=True, as_of_date=current_date.isoformat()
            )
            if success:
                usage_count += 1
            else:
                cur.execute("DELETE FROM usage_log WHERE usage_id = ?", (usage_id,))

            if random.random() < 0.08:
                waste_qty = round(random.uniform(0.2, 1.5), 2)
                reason = random.choice(WASTE_REASONS)

                # Insert a placeholder row first, deduct with tracking,
                # THEN compute the true multi-batch cost — same pattern
                # the real Waste page uses, so demo data is just as
                # accurate as live data.
                cur.execute("""
                    INSERT INTO waste_log
                        (ingredient_id, waste_date, quantity_wasted, reason, unit_cost, waste_cost)
                    VALUES (?, ?, ?, ?, 0, 0)
                """, (ingredient_id, current_date.isoformat(), waste_qty, reason))
                waste_id = cur.lastrowid
                ok, _ = consume_stock_fefo(ingredient_id, waste_qty, conn=conn, source_type="waste", source_id=waste_id)
                if ok:
                    total_cost, _, weighted_avg_cost = get_actual_cost_for_source("waste", waste_id, conn=conn)
                    cur.execute(
                        "UPDATE waste_log SET unit_cost = ?, waste_cost = ? WHERE waste_id = ?",
                        (weighted_avg_cost, total_cost, waste_id)
                    )
                    waste_count += 1
                else:
                    cur.execute("DELETE FROM waste_log WHERE waste_id = ?", (waste_id,))

    conn.commit()
    print(f"Inserted {usage_count} usage entries and {waste_count} waste entries.")


def main():
    print("Seeding demo data... this may take a few seconds.")
    reset_data()
    conn = get_connection()
    seed_categories(conn)
    ingredient_ids = seed_ingredients(conn)
    seed_purchases(conn, ingredient_ids)
    seed_usage_and_waste(conn, ingredient_ids)
    conn.close()
    print("\nDone! Run 'streamlit run app.py' and check the Dashboard page.")


if __name__ == "__main__":
    main()
