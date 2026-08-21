"""
engine.py
---------
This is the "brain" of the app. It contains no UI code at all — just
pure calculation functions that the Streamlit pages will call.

Key concepts implemented here:
    1. Current Stock = SUM of quantity_remaining across all of an
       ingredient's batches. Opening stock is itself stored as a batch
       (created on the Ingredients page), so there is only ONE source
       of truth for stock — the batches table. Earlier versions tracked
       opening stock separately from batches, which caused a "phantom
       stock" bug: the formula-based total didn't match what FEFO could
       actually see and deduct from.
    2. Reorder Point = Average Daily Usage x Reorder Period
    3. Waste Cost = sum of (quantity taken x that batch's unit cost)
       across every batch a waste entry actually drew from — computed
       from batch_consumption records, not guessed from a single batch.
    4. FEFO (First-Expiring-First-Out): stock is consumed from the
       batch expiring soonest first. Cooking (Usage) additionally
       EXCLUDES already-expired batches entirely — expired food should
       only ever be removed via Waste, never used in a recipe.
"""

from datetime import datetime, date, timedelta
import pandas as pd
from db import get_connection


# ======================================================================
# SECTION 1: BASIC HELPERS
# ======================================================================

def today_str():
    return date.today().isoformat()


def days_between(date1_str, date2_str):
    d1 = datetime.strptime(date1_str, "%Y-%m-%d").date()
    d2 = datetime.strptime(date2_str, "%Y-%m-%d").date()
    return (d2 - d1).days


# ======================================================================
# SECTION 2: FEFO CONSUMPTION ENGINE
# ======================================================================

def check_stock_available(ingredient_id, quantity_needed, exclude_expired=False, as_of_date=None):
    """
    Checks if enough stock exists WITHOUT deducting anything.

    exclude_expired=True ignores batches whose expiry_date has already
    passed — used by the Usage page so cooking never draws on expired
    stock (a food-safety requirement, not just a data nicety).

    as_of_date lets the caller check expiry against a date other than
    today (defaults to today_str() if not given) — needed when the user
    is logging a Usage entry for a PAST date: a batch that's expired as
    of today may have still been perfectly fresh on that earlier date,
    and should be judged against the date it was actually used, not
    the date it's being logged.
    """
    conn = get_connection()
    cur = conn.cursor()
    # Compare against Python's LOCAL today (or the caller-supplied
    # as_of_date), not SQLite's date('now') (which runs in UTC).
    # Without this, a batch expiring "today" can be classified
    # inconsistently depending on the time of day in timezones ahead
    # of UTC (e.g. IST, UTC+5:30).
    reference_date = as_of_date or today_str()
    if exclude_expired:
        cur.execute("""
            SELECT COALESCE(SUM(quantity_remaining), 0) AS total
            FROM batches
            WHERE ingredient_id = ? AND quantity_remaining > 0 AND expiry_date >= ?
        """, (ingredient_id, reference_date))
    else:
        cur.execute("""
            SELECT COALESCE(SUM(quantity_remaining), 0) AS total
            FROM batches
            WHERE ingredient_id = ? AND quantity_remaining > 0
        """, (ingredient_id,))
    total_available = cur.fetchone()["total"]
    conn.close()
    return total_available >= quantity_needed, round(total_available, 2)


def consume_stock_fefo(ingredient_id, quantity_needed, conn=None, source_type=None, source_id=None, exclude_expired=False, as_of_date=None):
    """
    Deducts `quantity_needed` of an ingredient from its batches,
    ALWAYS starting with the batch that expires soonest (FEFO). Ties
    on expiry_date are broken by batch_id ASC (older batch first),
    so the consumption order is deterministic rather than left to
    SQLite's unspecified ordering for equal keys.

    exclude_expired=True skips already-expired batches entirely — used
    for Usage (cooking). Waste logging leaves this False, since waste
    is exactly where expired stock should go.

    as_of_date lets the caller judge "expired" against a date other
    than today — see check_stock_available's docstring for why (a
    Usage entry logged for a past date should be judged against that
    date, not today).

    If source_type ('usage' or 'waste') and source_id are given, every
    batch deduction is also recorded in batch_consumption. This powers
    two things: accurate reversal (reverse_consumption) and accurate
    multi-batch cost attribution (get_actual_cost_for_source).

    Returns: (success: bool, message: str)
    """
    own_conn = False
    if conn is None:
        conn = get_connection()
        own_conn = True

    cur = conn.cursor()
    reference_date = as_of_date or today_str()

    if exclude_expired:
        cur.execute("""
            SELECT batch_id, quantity_remaining
            FROM batches
            WHERE ingredient_id = ? AND quantity_remaining > 0 AND expiry_date >= ?
            ORDER BY expiry_date ASC, batch_id ASC
        """, (ingredient_id, reference_date))
    else:
        cur.execute("""
            SELECT batch_id, quantity_remaining
            FROM batches
            WHERE ingredient_id = ? AND quantity_remaining > 0
            ORDER BY expiry_date ASC, batch_id ASC
        """, (ingredient_id,))
    batches = cur.fetchall()

    total_available = sum(b["quantity_remaining"] for b in batches)
    if total_available < quantity_needed:
        if own_conn:
            conn.close()
        reason = " (excluding expired batches)" if exclude_expired else ""
        return False, f"Not enough stock{reason}. Available: {round(total_available, 2)}, Needed: {quantity_needed}"

    remaining_to_deduct = quantity_needed
    for b in batches:
        if remaining_to_deduct <= 0:
            break
        take = min(b["quantity_remaining"], remaining_to_deduct)
        # ROUND() in SQL guards against floating-point residue (e.g.
        # 2.3 - 0.1 landing on 2.1999999999999997 instead of 2.2),
        # which would otherwise leave "empty" batches lingering just
        # above zero and never dropping out of FEFO queries.
        cur.execute(
            "UPDATE batches SET quantity_remaining = ROUND(quantity_remaining - ?, 6) WHERE batch_id = ?",
            (take, b["batch_id"])
        )
        if source_type and source_id:
            cur.execute("""
                INSERT INTO batch_consumption (batch_id, source_type, source_id, quantity)
                VALUES (?, ?, ?, ?)
            """, (b["batch_id"], source_type, source_id, take))
        remaining_to_deduct -= take

    if own_conn:
        conn.commit()
        conn.close()

    return True, "Stock deducted successfully (FEFO)"


def reverse_consumption(source_type, source_id, conn=None):
    """
    Undoes a specific usage/waste entry's effect on batches, using the
    batch_consumption records created at the time it happened. This
    restores each affected batch's quantity_remaining EXACTLY.
    """
    own_conn = False
    if conn is None:
        conn = get_connection()
        own_conn = True

    cur = conn.cursor()
    cur.execute("""
        SELECT batch_id, quantity FROM batch_consumption
        WHERE source_type = ? AND source_id = ?
    """, (source_type, source_id))
    records = cur.fetchall()

    for r in records:
        cur.execute(
            "UPDATE batches SET quantity_remaining = ROUND(quantity_remaining + ?, 6) WHERE batch_id = ?",
            (r["quantity"], r["batch_id"])
        )

    cur.execute(
        "DELETE FROM batch_consumption WHERE source_type = ? AND source_id = ?",
        (source_type, source_id)
    )

    if own_conn:
        conn.commit()
        conn.close()


def get_actual_cost_for_source(source_type, source_id, conn=None):
    """
    Computes the TRUE cost of a usage/waste entry by looking at exactly
    which batches it drew from (batch_consumption) and each batch's
    real unit_cost — instead of assuming the whole quantity came from
    a single batch's cost.

    Example: 5kg wasted, 2kg from a batch bought at ₹200/kg and 3kg
    from a batch bought at ₹300/kg -> true cost = (2x200)+(3x300) = ₹1300,
    not 5x200 = ₹1000 (what a single-batch-cost assumption would give).

    Returns: (total_cost, total_quantity, weighted_avg_unit_cost)
    """
    own_conn = False
    if conn is None:
        conn = get_connection()
        own_conn = True

    cur = conn.cursor()
    cur.execute("""
        SELECT bc.quantity, b.unit_cost
        FROM batch_consumption bc
        JOIN batches b ON bc.batch_id = b.batch_id
        WHERE bc.source_type = ? AND bc.source_id = ?
    """, (source_type, source_id))
    records = cur.fetchall()

    if own_conn:
        conn.close()

    if not records:
        return 0.0, 0.0, 0.0

    total_cost = sum(r["quantity"] * r["unit_cost"] for r in records)
    total_quantity = sum(r["quantity"] for r in records)
    weighted_avg_unit_cost = total_cost / total_quantity if total_quantity > 0 else 0.0

    return round(total_cost, 2), round(total_quantity, 2), round(weighted_avg_unit_cost, 2)


# ======================================================================
# SECTION 3: CURRENT STOCK CALCULATION
# ======================================================================

def get_current_stock(ingredient_id, conn=None):
    """
    Current Stock = SUM of quantity_remaining across all batches
    belonging to this ingredient.

    Opening stock is created as a batch itself (see Ingredients page),
    so batches are the single source of truth. This keeps "current
    stock" always consistent with what FEFO can actually see and
    deduct from — no separate formula that can drift out of sync.

    Pass an existing `conn` to reuse a connection across many calls
    (e.g. the Dashboard's per-ingredient reorder loop) instead of
    opening/closing a new SQLite connection for every ingredient.
    """
    own_conn = False
    if conn is None:
        conn = get_connection()
        own_conn = True
    cur = conn.cursor()
    cur.execute("""
        SELECT COALESCE(SUM(quantity_remaining), 0) AS total
        FROM batches
        WHERE ingredient_id = ?
    """, (ingredient_id,))
    total = cur.fetchone()["total"]
    if own_conn:
        conn.close()
    return round(total, 2)


# ======================================================================
# SECTION 4: REORDER POINT & STATUS
# ======================================================================

def get_average_daily_usage(ingredient_id, lookback_days=14, conn=None):
    own_conn = False
    if conn is None:
        conn = get_connection()
        own_conn = True
    cur = conn.cursor()
    # Compute the cutoff in Python (local time) rather than SQLite's
    # date('now', ...) (UTC), for the same timezone-consistency reason
    # as check_stock_available / consume_stock_fefo above.
    cutoff_date = (date.today() - timedelta(days=lookback_days)).isoformat()
    cur.execute("""
        SELECT COALESCE(SUM(quantity_used), 0) AS total
        FROM usage_log
        WHERE ingredient_id = ?
          AND usage_date >= ?
    """, (ingredient_id, cutoff_date))
    total = cur.fetchone()["total"]
    if own_conn:
        conn.close()
    return round(total / lookback_days, 2) if lookback_days > 0 else 0


def get_reorder_status(ingredient_id, conn=None):
    own_conn = False
    if conn is None:
        conn = get_connection()
        own_conn = True
    cur = conn.cursor()
    cur.execute("SELECT reorder_period_days FROM ingredients WHERE ingredient_id = ?", (ingredient_id,))
    row = cur.fetchone()
    reorder_period = row["reorder_period_days"] if row else 7

    avg_daily_usage = get_average_daily_usage(ingredient_id, conn=conn)
    reorder_point = round(avg_daily_usage * reorder_period, 2)
    current_stock = get_current_stock(ingredient_id, conn=conn)

    if own_conn:
        conn.close()

    return {
        "current_stock": current_stock,
        "avg_daily_usage": avg_daily_usage,
        "reorder_point": reorder_point,
        "needs_reorder": current_stock <= reorder_point
    }


# ======================================================================
# SECTION 5: EXPIRY CLASSIFICATION
# ======================================================================

def classify_batch_expiry(expiry_date_str, near_expiry_days, critical_expiry_days):
    days_left = days_between(today_str(), expiry_date_str)

    if days_left < 0:
        return "Expired"
    elif days_left <= critical_expiry_days:
        return "Critical"
    elif days_left <= near_expiry_days:
        return "Near-Expiry"
    else:
        return "OK"


def get_all_batches_with_status():
    conn = get_connection()
    query = """
        SELECT
            b.batch_id,
            i.name AS ingredient_name,
            c.name AS category_name,
            i.unit,
            b.purchase_date,
            b.expiry_date,
            b.quantity_remaining,
            b.unit_cost,
            c.near_expiry_days,
            c.critical_expiry_days
        FROM batches b
        JOIN ingredients i ON b.ingredient_id = i.ingredient_id
        JOIN categories c ON i.category_id = c.category_id
        WHERE b.quantity_remaining > 0
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    if df.empty:
        return df

    df["status"] = df.apply(
        lambda row: classify_batch_expiry(
            row["expiry_date"], row["near_expiry_days"], row["critical_expiry_days"]
        ),
        axis=1
    )
    return df


# ======================================================================
# SECTION 6: WASTE COST SUMMARY (for Dashboard)
# ======================================================================

def get_waste_summary():
    conn = get_connection()
    query = """
        SELECT
            w.waste_id,
            i.name AS ingredient_name,
            c.name AS category_name,
            w.waste_date,
            w.quantity_wasted,
            w.reason,
            w.unit_cost,
            w.waste_cost
        FROM waste_log w
        JOIN ingredients i ON w.ingredient_id = i.ingredient_id
        JOIN categories c ON i.category_id = c.category_id
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df


def get_top_wasted_ingredients(limit=5):
    waste_df = get_waste_summary()
    if waste_df.empty:
        return waste_df

    ranked = (
        waste_df.groupby("ingredient_name")
        .agg(total_quantity_wasted=("quantity_wasted", "sum"), total_waste_cost=("waste_cost", "sum"))
        .reset_index()
        .sort_values("total_waste_cost", ascending=False)
        .head(limit)
    )
    return ranked


def get_dashboard_summary():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT ingredient_id FROM ingredients")
    ingredient_ids = [row["ingredient_id"] for row in cur.fetchall()]

    total_waste_df = get_waste_summary()
    total_waste_cost = round(total_waste_df["waste_cost"].sum(), 2) if not total_waste_df.empty else 0

    # Reuse this one connection for every ingredient's reorder check
    # instead of get_reorder_status opening (and closing) its own
    # connection per ingredient — avoids N separate SQLite connections
    # for what's otherwise a handful of small queries.
    reorder_needed_count = 0
    for iid in ingredient_ids:
        status = get_reorder_status(iid, conn=conn)
        if status["needs_reorder"]:
            reorder_needed_count += 1

    conn.close()

    return {
        "total_ingredients": len(ingredient_ids),
        "total_waste_cost": total_waste_cost,
        "reorder_needed_count": reorder_needed_count
    }
