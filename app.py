"""
app.py
------
This is the ENTRY POINT of the Streamlit app — the Home page.
"""

import streamlit as st
from db import init_db
from engine import get_dashboard_summary, get_all_batches_with_status
from style import inject_custom_css, show_footer

st.set_page_config(
    page_title="Restaurant Inventory & Waste Analytics",
    page_icon="🍽️",
    layout="wide"
)
inject_custom_css()

init_db()

st.markdown("""
    <div style="
        background: linear-gradient(135deg, #0C447C 0%, #185FA5 100%);
        border-radius: 16px;
        padding: 32px 36px;
        margin-bottom: 24px;
    ">
        <div style="font-size: 28px; font-weight: 600; color: #FFFFFF; margin-bottom: 6px;">
            🍽️ Restaurant Inventory & Food Waste Analytics
        </div>
        <div style="font-size: 15px; color: #D6E8F7; max-width: 640px;">
            Track ingredient stock, purchases, usage, and waste — with FEFO-based
            batch consumption, expiry alerts, and live cost analytics.
        </div>
    </div>
""", unsafe_allow_html=True)

summary = get_dashboard_summary()

# ----------------------------------------------------------------------
# NOTIFICATION BELL
# Instead of always-visible banners taking up space, alerts live
# inside a bell icon with a badge count — click it to see details.
# st.popover() renders a button that opens a small floating panel,
# similar to notification bells on real websites/apps.
# ----------------------------------------------------------------------
batches_df = get_all_batches_with_status()
expired_count = 0
critical_count = 0
near_expiry_count = 0
if not batches_df.empty:
    expired_count = (batches_df["status"] == "Expired").sum()
    critical_count = (batches_df["status"] == "Critical").sum()
    near_expiry_count = (batches_df["status"] == "Near-Expiry").sum()

reorder_count = summary["reorder_needed_count"]
total_alerts = reorder_count + expired_count + critical_count + near_expiry_count

_, bell_col = st.columns([6, 1])
with bell_col:
    bell_label = f"🔔 {total_alerts}" if total_alerts > 0 else "🔔"
    with st.popover(bell_label, width="stretch"):
        st.markdown("**Notifications**")
        if total_alerts == 0:
            st.success("✅ No urgent alerts right now.")
        else:
            # Expired stock is the single most urgent thing a manager
            # needs to see and discard, so it's shown first.
            if expired_count > 0:
                st.error(f"🚨 **{expired_count} batch(es)** are EXPIRED and should be discarded now.")
            if reorder_count > 0:
                st.error(f"🔔 **{reorder_count} ingredient(s)** need reordering.")
            if critical_count > 0:
                st.error(f"⏳ **{critical_count} batch(es)** critically close to expiry.")
            if near_expiry_count > 0:
                st.warning(f"⚠️ **{near_expiry_count} batch(es)** nearing expiry soon.")
            st.caption("See the Dashboard page for full details.")

col1, col2, col3 = st.columns(3)
col1.metric("Total Ingredients Tracked", summary["total_ingredients"])
col2.metric("Total Waste Cost (all-time)", f"₹{summary['total_waste_cost']:,.2f}")
col3.metric("Items Needing Reorder", summary["reorder_needed_count"])

st.write("")
st.subheader("Get started")
st.caption("Set these up in order — each page builds on the one before it.")

nav_col1, nav_col2, nav_col3 = st.columns(3)

with nav_col1:
    with st.container(border=True):
        st.markdown('<div style="width:32px;height:32px;border-radius:8px;background:#E6F1FB;display:flex;align-items:center;justify-content:center;font-size:16px;margin-bottom:6px;">🗂️</div>', unsafe_allow_html=True)
        st.page_link("pages/1_Categories.py", label="**1. Categories**")
        st.caption("Group ingredients and set expiry alert thresholds.")

with nav_col2:
    with st.container(border=True):
        st.markdown('<div style="width:32px;height:32px;border-radius:8px;background:#EAF3DE;display:flex;align-items:center;justify-content:center;font-size:16px;margin-bottom:6px;">🧂</div>', unsafe_allow_html=True)
        st.page_link("pages/2_Ingredients.py", label="**2. Ingredients**")
        st.caption("Add ingredients with opening stock and reorder settings.")

with nav_col3:
    with st.container(border=True):
        st.markdown('<div style="width:32px;height:32px;border-radius:8px;background:#FAEEDA;display:flex;align-items:center;justify-content:center;font-size:16px;margin-bottom:6px;">🛒</div>', unsafe_allow_html=True)
        st.page_link("pages/3_Purchases.py", label="**3. Purchases**")
        st.caption("Log purchases — each one creates a new expiry-dated batch.")

nav_col4, nav_col5, nav_col6 = st.columns(3)

with nav_col4:
    with st.container(border=True):
        st.markdown('<div style="width:32px;height:32px;border-radius:8px;background:#FAECE7;display:flex;align-items:center;justify-content:center;font-size:16px;margin-bottom:6px;">🍳</div>', unsafe_allow_html=True)
        st.page_link("pages/4_Usage.py", label="**4. Usage**")
        st.caption("Log cooking consumption — stock deducted automatically via FEFO.")

with nav_col5:
    with st.container(border=True):
        st.markdown('<div style="width:32px;height:32px;border-radius:8px;background:#FCEBEB;display:flex;align-items:center;justify-content:center;font-size:16px;margin-bottom:6px;">🗑️</div>', unsafe_allow_html=True)
        st.page_link("pages/5_Waste.py", label="**5. Waste**")
        st.caption("Log discarded ingredients with automatic cost calculation.")

with nav_col6:
    with st.container(border=True):
        st.markdown('<div style="width:32px;height:32px;border-radius:8px;background:#EEEDFE;display:flex;align-items:center;justify-content:center;font-size:16px;margin-bottom:6px;">📊</div>', unsafe_allow_html=True)
        st.page_link("pages/6_Dashboard.py", label="**6. Dashboard**")
        st.caption("View stock health, expiry risk, and waste analytics.")

show_footer()
