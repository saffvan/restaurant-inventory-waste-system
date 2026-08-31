"""
pages/2_Ingredients.py
------------------------
Add individual ingredients under a category, with unit, opening
stock, and reorder period.

IMPORTANT DESIGN NOTE: Opening stock is created as a real BATCH
(in the batches table), not just a number stored on the ingredient.
Earlier versions stored opening_stock separately from batches, which
meant FEFO (which only looks at batches) could never actually see or
consume it — leading to a "phantom stock" bug where the displayed
Current Stock was higher than what Usage/Waste could actually deduct.
Treating opening stock as a batch (with its own expiry date) fixes
this: there is now only ONE source of truth for stock.
"""

import streamlit as st
import pandas as pd
from datetime import date, timedelta
from db import get_connection
from engine import get_current_stock
from style import inject_custom_css, show_footer, flash, show_flash

st.set_page_config(page_title="Ingredients", page_icon="🧂", layout="wide")
inject_custom_css()
st.title("🧂 Ingredients")
st.markdown("Add ingredients under a category, with opening stock and reorder settings.")

show_flash()
st.divider()

conn = get_connection()
categories_df = pd.read_sql_query("SELECT * FROM categories ORDER BY name", conn)
conn.close()

if categories_df.empty:
    st.warning("No categories found. Please add a category first on the **Categories** page.")
    st.stop()

category_options = dict(zip(categories_df["name"], categories_df["category_id"]))

st.subheader("Add New Ingredient")

with st.form("add_ingredient_form", clear_on_submit=True):
    col1, col2 = st.columns(2)
    with col1:
        name = st.text_input("Ingredient Name", placeholder="e.g. Tomato")
        category_name = st.selectbox("Category", category_options.keys())
        unit = st.selectbox("Unit", ["kg", "g", "litre", "ml", "pcs"])
        reorder_period_days = st.number_input("Reorder Period (days)", min_value=1, value=7)
    with col2:
        opening_stock = st.number_input("Opening Stock", min_value=0.0, value=0.0, step=0.5)
        opening_stock_date = st.date_input("Opening Stock Date", value=date.today())
        opening_stock_expiry = st.date_input(
            "Opening Stock Expiry Date",
            value=date.today() + timedelta(days=7),
            help="Since opening stock becomes a real batch (so FEFO/Usage/Waste can actually use it), it needs its own expiry date, just like a purchase."
        )
        opening_stock_cost = st.number_input(
            "Opening Stock Unit Cost (₹, optional)", min_value=0.0, value=0.0, step=1.0,
            help="Used if this opening stock is later wasted, for accurate cost tracking. Leave 0 if unknown."
        )

    submitted = st.form_submit_button("Add Ingredient")

    if submitted:
        if not name.strip():
            st.error("Ingredient name cannot be empty.")
        elif opening_stock > 0 and opening_stock_expiry <= opening_stock_date:
            st.error("Opening Stock Expiry Date must be after the Opening Stock Date.")
        else:
            dup_conn = get_connection()
            dup_cur = dup_conn.cursor()
            # Case-insensitive check: ingredients.name has no UNIQUE
            # constraint (unlike categories.name), and duplicates would
            # get silently conflated together in reports that group by
            # ingredient_name (e.g. Top Wasted Ingredients), mixing two
            # distinct ingredients' stock and cost into one row.
            dup_cur.execute(
                "SELECT COUNT(*) AS cnt FROM ingredients WHERE LOWER(name) = LOWER(?)",
                (name.strip(),)
            )
            name_exists = dup_cur.fetchone()["cnt"] > 0
            dup_conn.close()

            if name_exists:
                st.error(f"An ingredient named '{name.strip()}' already exists. Use a different name (e.g. 'Tomato - Cherry') to tell them apart.")
            else:
                conn = get_connection()
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO ingredients
                        (name, category_id, unit, opening_stock, opening_stock_date, reorder_period_days)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    name.strip(),
                    category_options[category_name],
                    unit,
                    opening_stock,
                    opening_stock_date.isoformat(),
                    reorder_period_days
                ))
                ingredient_id = cur.lastrowid

                # Opening stock becomes a real batch, so it's actually
                # visible to FEFO/Usage/Waste — not just a display number.
                if opening_stock > 0:
                    cur.execute("""
                        INSERT INTO batches
                            (ingredient_id, purchase_date, expiry_date, quantity_purchased, quantity_remaining, unit_cost, is_opening_stock)
                        VALUES (?, ?, ?, ?, ?, ?, 1)
                    """, (
                        ingredient_id,
                        opening_stock_date.isoformat(),
                        opening_stock_expiry.isoformat(),
                        opening_stock,
                        opening_stock,
                        opening_stock_cost
                    ))

                conn.commit()
                conn.close()
                st.success(f"Ingredient '{name}' added successfully!")

st.divider()

st.subheader("Existing Ingredients")

conn = get_connection()
ingredients_df = pd.read_sql_query("""
    SELECT i.ingredient_id, i.name, c.name AS category, i.unit,
           i.opening_stock, i.opening_stock_date, i.reorder_period_days
    FROM ingredients i
    JOIN categories c ON i.category_id = c.category_id
    ORDER BY c.name, i.name
""", conn)
conn.close()

if ingredients_df.empty:
    st.info("No ingredients yet. Add your first one above.")
else:
    ingredients_df["current_stock"] = ingredients_df["ingredient_id"].apply(get_current_stock)

    display_df = ingredients_df.rename(columns={
        "ingredient_id": "ID",
        "name": "Ingredient",
        "category": "Category",
        "unit": "Unit",
        "opening_stock": "Opening Stock",
        "opening_stock_date": "Opening Date",
        "reorder_period_days": "Reorder Period (days)",
        "current_stock": "Current Stock (live)"
    })
    st.dataframe(display_df, width="stretch", hide_index=True)

    # ------------------------------------------------------------------
    # EDIT: Only master-data fields (name/category/unit/reorder period).
    # Opening stock is NOT editable here anymore — once created, it's a
    # real batch (a transaction), and per our own data-integrity rule,
    # transactions aren't edited, only deleted-and-recreated.
    # ------------------------------------------------------------------
    with st.expander("Edit an ingredient"):
        edit_id_options = dict(zip(
            ingredients_df["name"] + " (ID " + ingredients_df["ingredient_id"].astype(str) + ", " + ingredients_df["category"] + ")",
            ingredients_df["ingredient_id"]
        ))
        edit_target_label = st.selectbox("Select ingredient to edit", edit_id_options.keys(), key="edit_ing_select")
        edit_target_id = edit_id_options[edit_target_label]
        target_row = ingredients_df[ingredients_df["ingredient_id"] == edit_target_id].iloc[0]

        # If this ingredient already has batches, changing its unit here
        # would silently corrupt every existing batch and historical
        # record — a "10 kg" batch would instantly read as "10 g" with
        # no conversion applied. Lock the Unit field in that case rather
        # than let it happen quietly.
        unit_lock_conn = get_connection()
        unit_lock_cur = unit_lock_conn.cursor()
        unit_lock_cur.execute("SELECT COUNT(*) AS cnt FROM batches WHERE ingredient_id = ?", (edit_target_id,))
        has_batches = unit_lock_cur.fetchone()["cnt"] > 0
        unit_lock_conn.close()

        with st.form("edit_ingredient_form"):
            new_name = st.text_input("Ingredient Name", value=target_row["name"], key=f"ing_name_{edit_target_id}")
            new_category_name = st.selectbox(
                "Category", category_options.keys(),
                index=list(category_options.keys()).index(target_row["category"]),
                key=f"ing_cat_{edit_target_id}"
            )
            unit_list = ["kg", "g", "litre", "ml", "pcs"]
            # Fall back to index 0 instead of crashing the whole page if a
            # row somehow has a unit outside this list (e.g. imported data,
            # or a future edit adds a unit that's since been removed here).
            unit_index = unit_list.index(target_row["unit"]) if target_row["unit"] in unit_list else 0
            if has_batches:
                st.caption("⚠️ Unit is locked — this ingredient already has batches recorded in its current unit. Changing it now would silently corrupt their quantities (e.g. a 10 kg batch would read as 10 g).")
            new_unit = st.selectbox(
                "Unit", unit_list,
                index=unit_index,
                key=f"ing_unit_{edit_target_id}",
                disabled=has_batches
            )
            new_reorder_period = st.number_input("Reorder Period (days)", min_value=1, value=int(target_row["reorder_period_days"]), key=f"ing_reorder_{edit_target_id}")
            st.caption("Opening stock can't be edited here — it's a batch now. Delete and re-add the ingredient if it was entered wrong.")

            update_submitted = st.form_submit_button("Update Ingredient")

            if update_submitted:
                if not new_name.strip():
                    st.error("Ingredient name cannot be empty.")
                else:
                    conn = get_connection()
                    cur = conn.cursor()
                    cur.execute("""
                        UPDATE ingredients
                        SET name = ?, category_id = ?, unit = ?, reorder_period_days = ?
                        WHERE ingredient_id = ?
                    """, (
                        new_name.strip(),
                        category_options[new_category_name],
                        new_unit,
                        new_reorder_period,
                        edit_target_id
                    ))
                    conn.commit()
                    conn.close()
                    flash(f"Ingredient updated to '{new_name}'.")
                    st.rerun()

    # ------------------------------------------------------------------
    # DELETE: Cascades through ALL related tables in the correct order,
    # including batch_consumption (a table earlier versions forgot,
    # which caused an unhandled FOREIGN KEY constraint crash).
    # ------------------------------------------------------------------
    with st.expander("Delete an ingredient"):
        id_options = dict(zip(
            ingredients_df["name"] + " (ID " + ingredients_df["ingredient_id"].astype(str) + ", " + ingredients_df["category"] + ")",
            ingredients_df["ingredient_id"]
        ))
        to_delete_label = st.selectbox("Select ingredient to delete", id_options.keys())
        to_delete_id = id_options[to_delete_label]

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS cnt FROM batches WHERE ingredient_id = ?", (to_delete_id,))
        batch_count = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) AS cnt FROM usage_log WHERE ingredient_id = ?", (to_delete_id,))
        usage_count = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) AS cnt FROM waste_log WHERE ingredient_id = ?", (to_delete_id,))
        waste_count = cur.fetchone()["cnt"]
        conn.close()

        total_related = batch_count + usage_count + waste_count

        if total_related > 0:
            st.warning(
                f"This ingredient has {batch_count} batch(es), {usage_count} usage entr(y/ies), "
                f"and {waste_count} waste entr(y/ies) linked to it. Deleting it will also delete "
                f"ALL of these related records. This cannot be undone."
            )
            confirm = st.checkbox(
                "Yes, I understand — delete this ingredient and all its related records.",
                key=f"del_confirm_{to_delete_id}"
            )
        else:
            st.info("No related records found — safe to delete.")
            confirm = True

        if st.button("Delete Selected Ingredient", type="secondary"):
            if not confirm:
                st.error("Please tick the confirmation checkbox first.")
            else:
                conn = get_connection()
                cur = conn.cursor()
                # Order matters: batch_consumption references batches,
                # so it must be deleted BEFORE the batches themselves,
                # or SQLite's foreign key constraint blocks the delete.
                cur.execute("""
                    DELETE FROM batch_consumption
                    WHERE batch_id IN (SELECT batch_id FROM batches WHERE ingredient_id = ?)
                """, (to_delete_id,))
                cur.execute("DELETE FROM waste_log WHERE ingredient_id = ?", (to_delete_id,))
                cur.execute("DELETE FROM usage_log WHERE ingredient_id = ?", (to_delete_id,))
                cur.execute("DELETE FROM batches WHERE ingredient_id = ?", (to_delete_id,))
                cur.execute("DELETE FROM ingredients WHERE ingredient_id = ?", (to_delete_id,))
                conn.commit()
                conn.close()
                flash(f"Deleted '{to_delete_label}' and all related records.")
                st.rerun()
show_footer()
