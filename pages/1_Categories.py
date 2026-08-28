"""
pages/1_Categories.py
----------------------
Categories group ingredients (e.g. Vegetables, Dairy, Meat) and
define the expiry-alert thresholds every ingredient in it inherits.
"""

import streamlit as st
import pandas as pd
from db import get_connection
from style import inject_custom_css, show_footer, flash, show_flash

st.set_page_config(page_title="Categories", page_icon="🗂️", layout="wide")
inject_custom_css()
st.title("🗂️ Categories")
st.markdown(
    "Categories group ingredients together and define default "
    "expiry-alert thresholds (Near-Expiry / Critical days)."
)

show_flash()
st.divider()

st.subheader("Add New Category")

with st.form("add_category_form", clear_on_submit=True):
    col1, col2, col3 = st.columns(3)
    with col1:
        name = st.text_input("Category Name", placeholder="e.g. Vegetables")
    with col2:
        near_expiry_days = st.number_input(
            "Near-Expiry Alert (days before expiry)", min_value=1, value=3
        )
    with col3:
        critical_expiry_days = st.number_input(
            "Critical Alert (days before expiry)", min_value=0, value=1
        )

    submitted = st.form_submit_button("Add Category")

    if submitted:
        if not name.strip():
            st.error("Category name cannot be empty.")
        elif critical_expiry_days > near_expiry_days:
            st.error("Critical days should be less than or equal to Near-Expiry days.")
        else:
            conn = get_connection()
            cur = conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO categories (name, near_expiry_days, critical_expiry_days) VALUES (?, ?, ?)",
                    (name.strip(), near_expiry_days, critical_expiry_days)
                )
                conn.commit()
                st.success(f"Category '{name}' added successfully!")
            except Exception as e:
                st.error(f"Could not add category. It may already exist. ({e})")
            finally:
                conn.close()

st.divider()

with st.container(border=True):
    st.subheader("Existing Categories")

    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM categories ORDER BY name", conn)
    conn.close()

    if df.empty:
        st.info("No categories yet. Add your first one above (e.g. 'Vegetables').")
    else:
        st.dataframe(
            df.rename(columns={
                "category_id": "ID",
                "name": "Category",
                "near_expiry_days": "Near-Expiry (days)",
                "critical_expiry_days": "Critical (days)"
            }),
            width="stretch",
            hide_index=True
        )

        with st.expander("Edit a category"):
            edit_options = dict(zip(df["name"], df["category_id"]))
            edit_target = st.selectbox("Select category to edit", edit_options.keys(), key="edit_cat_select")
            target_row = df[df["category_id"] == edit_options[edit_target]].iloc[0]

            with st.form("edit_category_form"):
                target_id = edit_options[edit_target]
                new_name = st.text_input("Category Name", value=target_row["name"], key=f"cat_name_{target_id}")
                new_near = st.number_input("Near-Expiry Alert (days)", min_value=1, value=int(target_row["near_expiry_days"]), key=f"cat_near_{target_id}")
                new_critical = st.number_input("Critical Alert (days)", min_value=0, value=int(target_row["critical_expiry_days"]), key=f"cat_crit_{target_id}")

                update_submitted = st.form_submit_button("Update Category")

                if update_submitted:
                    if not new_name.strip():
                        st.error("Category name cannot be empty.")
                    elif new_critical > new_near:
                        st.error("Critical days should be less than or equal to Near-Expiry days.")
                    else:
                        conn = get_connection()
                        cur = conn.cursor()
                        try:
                            cur.execute("""
                                UPDATE categories
                                SET name = ?, near_expiry_days = ?, critical_expiry_days = ?
                                WHERE category_id = ?
                            """, (new_name.strip(), new_near, new_critical, edit_options[edit_target]))
                            conn.commit()
                            flash(f"Category updated to '{new_name}'.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Could not update. Name may already exist. ({e})")
                        finally:
                            conn.close()

        with st.expander("Delete a category"):
            options = dict(zip(df["name"], df["category_id"]))
            to_delete = st.selectbox("Select category to delete", options.keys())
            if st.button("Delete Selected Category", type="secondary"):
                conn = get_connection()
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) AS cnt FROM ingredients WHERE category_id = ?", (options[to_delete],))
                in_use = cur.fetchone()["cnt"]
                if in_use > 0:
                    st.error(f"Cannot delete '{to_delete}' — {in_use} ingredient(s) still use it.")
                    conn.close()
                else:
                    cur.execute("DELETE FROM categories WHERE category_id = ?", (options[to_delete],))
                    conn.commit()
                    conn.close()
                    flash(f"Deleted '{to_delete}'.")
                    st.rerun()
show_footer()
