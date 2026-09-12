"""
pages/6_Dashboard.py
-----------------------
The analytics dashboard.
"""

import streamlit as st
import pandas as pd
import plotly.express as px
from db import get_connection
from engine import (
    get_dashboard_summary,
    get_reorder_status,
    get_all_batches_with_status,
    get_waste_summary,
    get_top_wasted_ingredients,
)
from style import inject_custom_css, show_footer

st.set_page_config(page_title="Dashboard", page_icon="📊", layout="wide")
inject_custom_css()
st.title("📊 Analytics Dashboard")
st.markdown("Live overview of stock health, expiry risk, and waste costs.")

st.divider()

summary = get_dashboard_summary()
col1, col2, col3 = st.columns(3)
col1.metric("Total Ingredients", summary["total_ingredients"])
col2.metric("Total Waste Cost (all-time)", f"₹{summary['total_waste_cost']:,.2f}")
col3.metric("Items Needing Reorder", summary["reorder_needed_count"])

st.divider()

st.subheader("🔔 Reorder Alerts")

conn = get_connection()
ingredients_df = pd.read_sql_query("""
    SELECT ingredient_id, name, unit FROM ingredients ORDER BY name
""", conn)
conn.close()

reorder_rows = []
# Reuse one connection across the loop instead of get_reorder_status
# opening a fresh one per ingredient.
loop_conn = get_connection()
for _, row in ingredients_df.iterrows():
    status = get_reorder_status(row["ingredient_id"], conn=loop_conn)
    if status["needs_reorder"]:
        reorder_rows.append({
            "Ingredient": row["name"],
            "Unit": row["unit"],
            "Current Stock": status["current_stock"],
            "Reorder Point": status["reorder_point"],
            "Avg Daily Usage": status["avg_daily_usage"],
        })
loop_conn.close()

if reorder_rows:
    st.dataframe(pd.DataFrame(reorder_rows), width="stretch", hide_index=True)
else:
    st.success("No ingredients currently need reordering.")

st.divider()

st.subheader("⏳ Expiry Risk Breakdown")

batches_df = get_all_batches_with_status()

if batches_df.empty:
    st.info("No active batches to analyze yet.")
else:
    col1, col2 = st.columns(2)

    with col1:
        status_counts = batches_df["status"].value_counts().reset_index()
        status_counts.columns = ["Status", "Count"]
        fig1 = px.pie(
            status_counts, names="Status", values="Count",
            title="Batches by Expiry Status",
            color="Status",
            color_discrete_map={
                "OK": "#2ecc71", "Near-Expiry": "#f39c12",
                "Critical": "#e74c3c", "Expired": "#7f8c8d"
            }
        )
        st.plotly_chart(fig1, width="stretch")

    with col2:
        at_risk = batches_df[batches_df["status"].isin(["Near-Expiry", "Critical", "Expired"])].sort_values("expiry_date")
        if at_risk.empty:
            st.success("No batches are near expiry right now.")
        else:
            st.dataframe(
                at_risk[["ingredient_name", "category_name", "expiry_date", "quantity_remaining", "status"]].rename(
                    columns={
                        "ingredient_name": "Ingredient",
                        "category_name": "Category",
                        "expiry_date": "Expiry Date",
                        "quantity_remaining": "Qty Remaining",
                        "status": "Status"
                    }
                ),
                width="stretch",
                hide_index=True
            )

st.divider()

st.subheader("🏆 Top Wasted Ingredients (by cost)")

top_wasted_df = get_top_wasted_ingredients(limit=5)

if top_wasted_df.empty:
    st.info("No waste logged yet — this ranking will appear once you log some.")
else:
    display_top = top_wasted_df.rename(columns={
        "ingredient_name": "Ingredient",
        "total_quantity_wasted": "Total Quantity Wasted",
        "total_waste_cost": "Total Waste Cost (₹)"
    })

    col1, col2 = st.columns([1, 1])
    with col1:
        fig_top = px.bar(
            top_wasted_df, x="ingredient_name", y="total_waste_cost",
            title="Top 5 Ingredients by Waste Cost",
            labels={"ingredient_name": "Ingredient", "total_waste_cost": "Waste Cost (₹)"},
            color="total_waste_cost", color_continuous_scale="Reds"
        )
        st.plotly_chart(fig_top, width="stretch")
    with col2:
        st.dataframe(display_top, width="stretch", hide_index=True)

    # Only surface the "biggest source of waste cost" insight when there's
    # an actual cost behind it — otherwise (e.g. all logged waste has ₹0
    # cost, such as opening-stock batches entered with no unit cost) the
    # caption would misleadingly call a ₹0.00 item the "biggest" problem.
    if top_wasted_df.iloc[0]["total_waste_cost"] > 0:
        st.caption(
            f"💡 **{top_wasted_df.iloc[0]['ingredient_name']}** is your single biggest source of "
            f"waste cost (₹{top_wasted_df.iloc[0]['total_waste_cost']:.2f}) — worth investigating "
            f"whether purchase quantities or storage practices need adjusting."
        )

st.divider()

st.subheader("💸 Waste Cost Analytics")

waste_df = get_waste_summary()

if waste_df.empty:
    st.info("No waste logged yet — analytics will appear here once you log some.")
else:
    col1, col2 = st.columns(2)

    with col1:
        by_category = waste_df.groupby("category_name")["waste_cost"].sum().reset_index()
        fig2 = px.bar(
            by_category, x="category_name", y="waste_cost",
            title="Waste Cost by Category",
            labels={"category_name": "Category", "waste_cost": "Waste Cost (₹)"},
            color="category_name"
        )
        st.plotly_chart(fig2, width="stretch")

    with col2:
        by_reason = waste_df.groupby("reason")["waste_cost"].sum().reset_index()
        fig3 = px.pie(
            by_reason, names="reason", values="waste_cost",
            title="Waste Cost by Reason"
        )
        st.plotly_chart(fig3, width="stretch")

    waste_df["waste_date"] = pd.to_datetime(waste_df["waste_date"])
    by_date = waste_df.groupby("waste_date")["waste_cost"].sum().reset_index()
    fig4 = px.line(
        by_date, x="waste_date", y="waste_cost",
        title="Waste Cost Over Time",
        labels={"waste_date": "Date", "waste_cost": "Waste Cost (₹)"},
        markers=True
    )
    st.plotly_chart(fig4, width="stretch")

    st.download_button(
        label="📥 Download Full Waste Data (CSV)",
        data=waste_df.to_csv(index=False).encode("utf-8"),
        file_name="waste_analytics_full.csv",
        mime="text/csv"
    )
show_footer()
