"""
pages/4_Usage.py
-------------------
Log ingredients consumed in cooking/prep. Uses FEFO to deduct stock.
"""

import streamlit as st
import pandas as pd
from datetime import date
from db import get_connection
from engine import consume_stock_fefo, get_current_stock, check_stock_available, reverse_consumption
from style import inject_custom_css, show_footer, flash, show_flash

st.set_page_config(page_title="Usage", page_icon="🍳", layout="wide")
inject_custom_css()
st.title("🍳 Usage")
st.markdown("Log ingredients used in cooking/prep. Stock is deducted automatically using FEFO.")

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

st.subheader("Log Usage")

# Ingredient selector lives OUTSIDE the form: widgets inside st.form only
# trigger a rerun when the form is submitted, so if this selectbox were
# inside the form, picking a different ingredient wouldn't refresh the
# "Current available stock" caption below — it'd stay frozen on whichever
# ingredient was selected first, which could show stock that isn't
# actually there for the ingredient the user is now looking at.
ingredient_label = st.selectbox("Ingredient", ingredient_options.keys())
ingredient_id = ingredient_options[ingredient_label]

# Show USABLE stock only (excluding expired batches) — this must
# match exactly what the form validates against below, or the
# caption can promise stock that a submission then rejects.
_, usable_stock = check_stock_available(ingredient_id, 0, exclude_expired=True)
st.caption(f"Current available stock (excluding expired): **{usable_stock}**")

with st.form("add_usage_form", clear_on_submit=True):
    usage_date = st.date_input("Usage Date", value=date.today(), max_value=date.today())
    quantity_used = st.number_input("Quantity Used", min_value=0.01, value=1.0, step=0.5)

    submitted = st.form_submit_button("Log Usage")

    if submitted:
        # Judge expiry as of the usage date itself, not today — a batch
        # that's expired by today may have still been perfectly fresh
        # on an earlier date the user is logging cooking for.
        as_of = usage_date.isoformat()
        available, total = check_stock_available(ingredient_id, quantity_used, exclude_expired=True, as_of_date=as_of)

        if not available:
            st.error(f"Not enough stock. Available: {total}, Needed: {quantity_used}")
        else:
            conn = get_connection()
            try:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO usage_log (ingredient_id, usage_date, quantity_used)
                    VALUES (?, ?, ?)
                """, (ingredient_id, usage_date.isoformat(), quantity_used))
                usage_id = cur.lastrowid

                success, message = consume_stock_fefo(
                    ingredient_id, quantity_used, conn=conn,
                    source_type="usage", source_id=usage_id,
                    exclude_expired=True, as_of_date=as_of
                )

                if not success:
                    # Roll back the usage_log row we just inserted — without
                    # this, a failed deduction would leave an orphaned log
                    # entry with no matching batch_consumption records,
                    # corrupting future audit history and reversal.
                    cur.execute("DELETE FROM usage_log WHERE usage_id = ?", (usage_id,))
                    conn.commit()
                    st.error(message)
                else:
                    conn.commit()
                    flash(f"Usage logged: {quantity_used} deducted via FEFO. {message}")
                    st.rerun()
            except Exception as e:
                conn.rollback()
                st.error(f"Could not log usage due to a database error: {e}")
            finally:
                conn.close()

st.divider()

with st.container(border=True):
    st.subheader("Usage History")

    conn = get_connection()
    usage_df = pd.read_sql_query("""
        SELECT u.usage_id, i.name AS ingredient, c.name AS category,
               u.usage_date, u.quantity_used, i.unit
        FROM usage_log u
        JOIN ingredients i ON u.ingredient_id = i.ingredient_id
        JOIN categories c ON i.category_id = c.category_id
        ORDER BY u.usage_date DESC, u.usage_id DESC
    """, conn)
    conn.close()

    if usage_df.empty:
        st.info("No usage logged yet.")
    else:
        display_usage_df = usage_df.rename(columns={
            "usage_id": "ID",
            "ingredient": "Ingredient",
            "category": "Category",
            "usage_date": "Date",
            "quantity_used": "Quantity Used",
            "unit": "Unit"
        })
        st.dataframe(display_usage_df, width="stretch", hide_index=True)

        st.download_button(
            label="📥 Download Usage History (CSV)",
            data=display_usage_df.to_csv(index=False).encode("utf-8"),
            file_name="usage_history.csv",
            mime="text/csv"
        )

        with st.expander("Delete a usage entry"):
            usage_df["label"] = (
                "ID " + usage_df["usage_id"].astype(str) + " — " + usage_df["ingredient"] +
                ", " + usage_df["quantity_used"].astype(str) + " on " + usage_df["usage_date"].astype(str)
            )
            id_options = dict(zip(usage_df["label"], usage_df["usage_id"]))
            to_delete_label = st.selectbox("Select usage entry to delete", id_options.keys())
            to_delete_id = id_options[to_delete_label]

            st.caption("This restores the exact batch(es) it was deducted from, then removes the log entry.")
            if st.button("Delete Selected Usage Entry", type="secondary"):
                conn = get_connection()
                try:
                    cur = conn.cursor()
                    reverse_consumption("usage", to_delete_id, conn=conn)
                    cur.execute("DELETE FROM usage_log WHERE usage_id = ?", (to_delete_id,))
                    conn.commit()
                    flash(f"Deleted {to_delete_label} and restored stock to its original batch(es).")
                    st.rerun()
                except Exception as e:
                    conn.rollback()
                    st.error(f"Could not delete this entry due to a database error: {e}")
                finally:
                    conn.close()
show_footer()
