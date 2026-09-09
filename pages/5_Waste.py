"""
pages/5_Waste.py
-------------------
Log discarded/spoiled ingredients. Uses FEFO to deduct, and
calculates waste cost automatically.
"""

import streamlit as st
import pandas as pd
from datetime import date
from db import get_connection
from engine import consume_stock_fefo, get_current_stock, check_stock_available, reverse_consumption, get_actual_cost_for_source
from style import inject_custom_css, show_footer, flash, show_flash

st.set_page_config(page_title="Waste", page_icon="🗑️", layout="wide")
inject_custom_css()
st.title("🗑️ Waste Logging")
st.markdown("Log discarded or spoiled ingredients. Cost is calculated automatically.")

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

WASTE_REASONS = ["Spoilage", "Expiry", "Damaged", "Prep-Handling"]

st.subheader("Log Waste")

# Ingredient selector lives OUTSIDE the form for the same reason as on
# the Usage page: widgets inside st.form only rerun on submit, so a
# selectbox inside the form would leave this stock caption frozen on
# whichever ingredient was picked first.
ingredient_label = st.selectbox("Ingredient", ingredient_options.keys())
ingredient_id = ingredient_options[ingredient_label]

current_stock = get_current_stock(ingredient_id)
st.caption(f"Current available stock: **{current_stock}**")

with st.form("add_waste_form", clear_on_submit=True):
    col1, col2 = st.columns(2)
    with col1:
        waste_date = st.date_input("Waste Date", value=date.today(), max_value=date.today())
        quantity_wasted = st.number_input("Quantity Wasted", min_value=0.01, value=1.0, step=0.5)
    with col2:
        reason = st.selectbox("Reason", WASTE_REASONS)

    submitted = st.form_submit_button("Log Waste")

    if submitted:
        available, total = check_stock_available(ingredient_id, quantity_wasted)

        if not available:
            st.error(f"Not enough stock. Available: {total}, Needed: {quantity_wasted}")
        else:
            conn = get_connection()
            try:
                cur = conn.cursor()

                # Insert a placeholder row first (cost filled in accurately
                # below, AFTER we know exactly which batches were drawn from).
                cur.execute("""
                    INSERT INTO waste_log
                        (ingredient_id, waste_date, quantity_wasted, reason, unit_cost, waste_cost)
                    VALUES (?, ?, ?, ?, 0, 0)
                """, (ingredient_id, waste_date.isoformat(), quantity_wasted, reason))
                waste_id = cur.lastrowid

                success, message = consume_stock_fefo(
                    ingredient_id, quantity_wasted, conn=conn,
                    source_type="waste", source_id=waste_id
                )

                if not success:
                    # Shouldn't normally happen since we just checked
                    # availability, but stay safe: undo the placeholder row.
                    cur.execute("DELETE FROM waste_log WHERE waste_id = ?", (waste_id,))
                    conn.commit()
                    st.error(message)
                else:
                    # Now that batch_consumption records exist, compute the
                    # TRUE cost: sum of (quantity taken x that batch's own
                    # unit_cost), which correctly handles waste that spans
                    # multiple batches bought at different prices — instead
                    # of assuming the whole quantity came from one batch.
                    total_cost, total_qty, weighted_avg_cost = get_actual_cost_for_source("waste", waste_id, conn=conn)
                    cur.execute(
                        "UPDATE waste_log SET unit_cost = ?, waste_cost = ? WHERE waste_id = ?",
                        (weighted_avg_cost, total_cost, waste_id)
                    )
                    conn.commit()
                    flash(f"Waste logged: {quantity_wasted} ({reason}). Cost: ₹{total_cost:.2f}")
                    st.rerun()
            except Exception as e:
                conn.rollback()
                st.error(f"Could not log waste due to a database error: {e}")
            finally:
                conn.close()

st.divider()

with st.container(border=True):
    st.subheader("Waste History")

    conn = get_connection()
    waste_df = pd.read_sql_query("""
        SELECT w.waste_id, i.name AS ingredient, c.name AS category,
               w.waste_date, w.quantity_wasted, i.unit, w.reason,
               w.unit_cost, w.waste_cost
        FROM waste_log w
        JOIN ingredients i ON w.ingredient_id = i.ingredient_id
        JOIN categories c ON i.category_id = c.category_id
        ORDER BY w.waste_date DESC, w.waste_id DESC
    """, conn)
    conn.close()

    if waste_df.empty:
        st.info("No waste logged yet.")
    else:
        total_cost = waste_df["waste_cost"].sum()
        st.metric("Total Waste Cost (all-time)", f"₹{total_cost:.2f}")

        display_waste_df = waste_df.rename(columns={
            "waste_id": "ID",
            "ingredient": "Ingredient",
            "category": "Category",
            "waste_date": "Date",
            "quantity_wasted": "Quantity",
            "unit": "Unit",
            "reason": "Reason",
            "unit_cost": "Unit Cost (₹)",
            "waste_cost": "Waste Cost (₹)"
        })
        st.dataframe(display_waste_df, width="stretch", hide_index=True)

        st.download_button(
            label="📥 Download Waste History (CSV)",
            data=display_waste_df.to_csv(index=False).encode("utf-8"),
            file_name="waste_history.csv",
            mime="text/csv"
        )

        with st.expander("Delete a waste entry"):
            waste_df["label"] = (
                "ID " + waste_df["waste_id"].astype(str) + " — " + waste_df["ingredient"] +
                ", " + waste_df["quantity_wasted"].astype(str) + " (" + waste_df["reason"] + ") on " + waste_df["waste_date"].astype(str)
            )
            id_options = dict(zip(waste_df["label"], waste_df["waste_id"]))
            to_delete_label = st.selectbox("Select waste entry to delete", id_options.keys())
            to_delete_id = id_options[to_delete_label]

            st.caption("This restores the exact batch(es) it was deducted from, then removes the log entry.")
            if st.button("Delete Selected Waste Entry", type="secondary"):
                conn = get_connection()
                try:
                    cur = conn.cursor()
                    reverse_consumption("waste", to_delete_id, conn=conn)
                    cur.execute("DELETE FROM waste_log WHERE waste_id = ?", (to_delete_id,))
                    conn.commit()
                    flash(f"Deleted {to_delete_label} and restored stock to its original batch(es).")
                    st.rerun()
                except Exception as e:
                    conn.rollback()
                    st.error(f"Could not delete this entry due to a database error: {e}")
                finally:
                    conn.close()
show_footer()
