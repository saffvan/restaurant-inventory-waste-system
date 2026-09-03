"""
pages/3_Purchases.py
----------------------
Log a purchase = create a new BATCH for an ingredient.
"""

import streamlit as st
import pandas as pd
from datetime import date, timedelta
from db import get_connection
from style import inject_custom_css, show_footer, flash, show_flash

st.set_page_config(page_title="Purchases", page_icon="🛒", layout="wide")
inject_custom_css()
st.title("🛒 Purchases")
st.markdown("Log a new purchase. Each purchase creates a new batch with its own expiry date and cost.")

show_flash()
st.divider()

conn = get_connection()
ingredients_df = pd.read_sql_query("""
    SELECT i.ingredient_id, i.name, c.name AS category, i.unit
    FROM ingredients i
    JOIN categories c ON i.category_id = c.category_id
    ORDER BY c.name, i.name
""", conn)
conn.close()

if ingredients_df.empty:
    st.warning("No ingredients found. Please add ingredients first on the **Ingredients** page.")
    st.stop()

ingredients_df["label"] = ingredients_df["name"] + " (ID " + ingredients_df["ingredient_id"].astype(str) + ", " + ingredients_df["category"] + ", " + ingredients_df["unit"] + ")"
ingredient_options = dict(zip(ingredients_df["label"], ingredients_df["ingredient_id"]))

st.subheader("Log New Purchase")

with st.form("add_purchase_form", clear_on_submit=True):
    col1, col2 = st.columns(2)
    with col1:
        ingredient_label = st.selectbox("Ingredient", ingredient_options.keys())
        purchase_date = st.date_input("Purchase Date", value=date.today(), max_value=date.today())
        expiry_date = st.date_input("Expiry Date", value=date.today() + timedelta(days=7))
    with col2:
        quantity = st.number_input("Quantity Purchased", min_value=0.01, value=1.0, step=0.5)
        unit_cost = st.number_input("Unit Cost (₹ per unit)", min_value=0.0, value=0.0, step=1.0)

    submitted = st.form_submit_button("Log Purchase")

    if submitted:
        if expiry_date <= purchase_date:
            st.error("Expiry date must be after the purchase date.")
        else:
            total_cost = quantity * unit_cost
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO batches
                    (ingredient_id, purchase_date, expiry_date, quantity_purchased, quantity_remaining, unit_cost)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                ingredient_options[ingredient_label],
                purchase_date.isoformat(),
                expiry_date.isoformat(),
                quantity,
                quantity,
                unit_cost
            ))
            conn.commit()
            conn.close()
            st.success(f"Purchase logged! New batch of {quantity} added (Total Cost: ₹{total_cost:.2f}), expiring {expiry_date.isoformat()}.")

st.divider()

with st.container(border=True):
    st.subheader("Purchase History (Batches)")

    conn = get_connection()
    batches_df = pd.read_sql_query("""
        SELECT b.batch_id, i.name AS ingredient, c.name AS category,
               b.purchase_date, b.expiry_date, b.quantity_purchased,
               b.quantity_remaining, b.unit_cost, b.is_opening_stock
        FROM batches b
        JOIN ingredients i ON b.ingredient_id = i.ingredient_id
        JOIN categories c ON i.category_id = c.category_id
        ORDER BY b.purchase_date DESC, b.batch_id DESC
    """, conn)
    conn.close()

    if batches_df.empty:
        st.info("No purchases logged yet.")
    else:
        # Opening-stock batches (created on the Ingredients page, not
        # here) are shown with a distinct label — they're often the
        # ONLY record of an ingredient's starting stock, so deleting
        # one has different consequences than deleting a regular
        # purchase and deserves to be visually distinguishable.
        display_source = batches_df.copy()
        display_source["ingredient"] = display_source.apply(
            lambda r: f"{r['ingredient']} (Opening Stock)" if r["is_opening_stock"] else r["ingredient"],
            axis=1
        )
        display_batches_df = display_source.drop(columns=["is_opening_stock"]).rename(columns={
            "batch_id": "Batch ID",
            "ingredient": "Ingredient",
            "category": "Category",
            "purchase_date": "Purchase Date",
            "expiry_date": "Expiry Date",
            "quantity_purchased": "Qty Purchased",
            "quantity_remaining": "Qty Remaining",
            "unit_cost": "Unit Cost (₹)"
        })
        st.dataframe(display_batches_df, width="stretch", hide_index=True)

        st.download_button(
            label="📥 Download Purchase History (CSV)",
            data=display_batches_df.to_csv(index=False).encode("utf-8"),
            file_name="purchase_history.csv",
            mime="text/csv"
        )

        with st.expander("Delete a purchase"):
            batches_df["label"] = (
                "Batch " + batches_df["batch_id"].astype(str) + " — " + batches_df["ingredient"] +
                (batches_df["is_opening_stock"] == 1).map({True: " (Opening Stock)", False: ""}) +
                ", " + batches_df["quantity_purchased"].astype(str) + " on " + batches_df["purchase_date"]
            )
            id_options = dict(zip(batches_df["label"], batches_df["batch_id"]))
            to_delete_label = st.selectbox("Select purchase to delete", id_options.keys())
            to_delete_id = id_options[to_delete_label]
            to_delete_is_opening = bool(
                batches_df.loc[batches_df["batch_id"] == to_delete_id, "is_opening_stock"].iloc[0]
            )

            conn = get_connection()
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) AS cnt FROM batch_consumption WHERE batch_id = ?", (to_delete_id,))
            consumption_count = cur.fetchone()["cnt"]
            conn.close()

            if consumption_count > 0:
                st.error(
                    f"Cannot delete this batch — {consumption_count} usage/waste record(s) already "
                    f"drew from it. Deleting it would break their ability to be accurately reversed "
                    f"later. Delete those usage/waste entries first if you really need to remove this batch."
                )
            else:
                if to_delete_is_opening:
                    st.warning(
                        "This is the ingredient's **opening stock** batch, not a regular purchase. "
                        "Deleting it removes that starting quantity from Current Stock, but the "
                        "'Opening Stock' figure shown on the Ingredients page (a historical record of "
                        "what was originally entered) will NOT update to match — the two will then "
                        "disagree. If you're correcting a mistake, consider deleting the whole "
                        "ingredient and re-adding it instead."
                    )
                else:
                    st.caption("Deleting a purchase removes this batch entirely, including any remaining quantity.")
                if st.button("Delete Selected Purchase", type="secondary"):
                    conn = get_connection()
                    cur = conn.cursor()
                    cur.execute("DELETE FROM batches WHERE batch_id = ?", (to_delete_id,))
                    conn.commit()
                    conn.close()
                    flash(f"Deleted {to_delete_label}.")
                    st.rerun()
show_footer()
