"""Query helpers shared by the Streamlit pages."""
import datetime as dt
import pandas as pd
from db import get_conn, D8_STEPS, STATUSES, SEVERITIES


def df(sql, params=()):
    conn = get_conn()
    out = pd.read_sql_query(sql, conn, params=params)
    conn.close()
    return out


def all_facilities():
    return df("SELECT * FROM facilities ORDER BY name")


def all_suppliers():
    return df("SELECT * FROM suppliers ORDER BY name")


def all_users():
    return df("SELECT * FROM users ORDER BY role, display_name")


def get_user(username):
    r = df("SELECT * FROM users WHERE username = ?", (username,))
    return r.iloc[0] if not r.empty else None


def claims_for_scope(role, facility_id=None, supplier_id=None):
    """Return claims visible to a given role/scope."""
    sql = """
        SELECT c.*, f.name AS facility_name, f.business_unit, s.name AS supplier_name, s.commodity
        FROM claims c
        JOIN facilities f ON f.facility_id = c.facility_id
        JOIN suppliers s ON s.supplier_id = c.supplier_id
    """
    params = []
    where = []
    if role == "local_sqm" and facility_id:
        where.append("c.facility_id = ?")
        params.append(facility_id)
    elif role == "supplier" and supplier_id:
        where.append("c.supplier_id = ?")
        params.append(supplier_id)
    # global_sqm sees everything
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY c.created_at DESC"
    return df(sql, tuple(params))


def get_claim(claim_id):
    r = df(
        """SELECT c.*, f.name AS facility_name, f.business_unit, s.name AS supplier_name, s.commodity
           FROM claims c
           JOIN facilities f ON f.facility_id = c.facility_id
           JOIN suppliers s ON s.supplier_id = c.supplier_id
           WHERE c.claim_id = ?""",
        (claim_id,),
    )
    return r.iloc[0] if not r.empty else None


def get_d8_steps(claim_id):
    return df("SELECT * FROM d8_steps WHERE claim_id = ? ORDER BY step_no", (claim_id,))


def get_activity(claim_id):
    return df("SELECT * FROM activity_log WHERE claim_id = ? ORDER BY timestamp DESC", (claim_id,))


def next_claim_id():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT claim_id FROM claims ORDER BY claim_id DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    if not row:
        return "CLM-2026-0001"
    last_n = int(row[0].split("-")[-1])
    return f"CLM-2026-{last_n + 1:04d}"


def create_claim(title, description, facility_id, supplier_id, part_number,
                  severity, created_by):
    conn = get_conn()
    cur = conn.cursor()
    claim_id = next_claim_id()
    now = dt.datetime.now().isoformat()
    due = (dt.datetime.now() + dt.timedelta(days=15 if severity == "Critical" else 30)).isoformat()
    cur.execute(
        """INSERT INTO claims
           (claim_id, title, description, facility_id, supplier_id, part_number,
            severity, status, created_by, created_at, due_date, escalated, defect_cost_eur)
           VALUES (?,?,?,?,?,?,?, 'Open', ?, ?, ?, 0, 0)""",
        (claim_id, title, description, facility_id, supplier_id, part_number,
         severity, created_by, now, due),
    )
    for step_no, code, name in D8_STEPS:
        cur.execute(
            """INSERT INTO d8_steps (claim_id, step_no, step_code, step_name, content, status)
               VALUES (?,?,?,?, '', 'Not Started')""",
            (claim_id, step_no, code, name),
        )
    cur.execute(
        """INSERT INTO activity_log (claim_id, actor, action, note, timestamp)
           VALUES (?,?,?,?,?)""",
        (claim_id, created_by, "Claim created", "Initial claim raised via platform.", now),
    )
    conn.commit()
    conn.close()
    return claim_id


def update_d8_step(claim_id, step_no, content, status, actor):
    conn = get_conn()
    cur = conn.cursor()
    now = dt.datetime.now().isoformat()
    cur.execute(
        """UPDATE d8_steps SET content = ?, status = ?, updated_by = ?, updated_at = ?
           WHERE claim_id = ? AND step_no = ?""",
        (content, status, actor, now, claim_id, step_no),
    )
    cur.execute(
        """INSERT INTO activity_log (claim_id, actor, action, note, timestamp)
           VALUES (?,?,?,?,?)""",
        (claim_id, actor, f"Updated D{step_no}", f"Status set to '{status}'.", now),
    )
    conn.commit()
    conn.close()


def add_comment(claim_id, actor, note):
    conn = get_conn()
    cur = conn.cursor()
    now = dt.datetime.now().isoformat()
    cur.execute(
        """INSERT INTO activity_log (claim_id, actor, action, note, timestamp)
           VALUES (?,?,?,?,?)""",
        (claim_id, actor, "Comment", note, now),
    )
    conn.commit()
    conn.close()


def escalate_claim(claim_id, actor, reason):
    conn = get_conn()
    cur = conn.cursor()
    now = dt.datetime.now().isoformat()
    cur.execute(
        """UPDATE claims SET escalated = 1, escalated_at = ?, escalation_reason = ?, status = 'Escalated'
           WHERE claim_id = ?""",
        (now, reason, claim_id),
    )
    cur.execute(
        """INSERT INTO activity_log (claim_id, actor, action, note, timestamp)
           VALUES (?,?,?,?,?)""",
        (claim_id, actor, "Escalated to Global SQM", reason, now),
    )
    conn.commit()
    conn.close()


def set_claim_status(claim_id, status, actor):
    conn = get_conn()
    cur = conn.cursor()
    now = dt.datetime.now().isoformat()
    closed_at = now if status == "Closed" else None
    if closed_at:
        cur.execute("UPDATE claims SET status = ?, closed_at = ? WHERE claim_id = ?", (status, closed_at, claim_id))
    else:
        cur.execute("UPDATE claims SET status = ? WHERE claim_id = ?", (status, claim_id))
    cur.execute(
        """INSERT INTO activity_log (claim_id, actor, action, note, timestamp)
           VALUES (?,?,?,?,?)""",
        (claim_id, actor, "Status changed", f"Status set to '{status}'.", now),
    )
    conn.commit()
    conn.close()


def supplier_rating_table():
    """Composite supplier performance/rating, replacing the local Excel sheets."""
    claims = df(
        """SELECT c.*, s.name AS supplier_name, s.commodity
           FROM claims c JOIN suppliers s ON s.supplier_id = c.supplier_id"""
    )
    if claims.empty:
        return pd.DataFrame()

    claims["created_at"] = pd.to_datetime(claims["created_at"])
    claims["closed_at"] = pd.to_datetime(claims["closed_at"])
    claims["resolution_days"] = (claims["closed_at"] - claims["created_at"]).dt.days

    rows = []
    for sup_id, g in claims.groupby("supplier_id"):
        name = g["supplier_name"].iloc[0]
        commodity = g["commodity"].iloc[0]
        total = len(g)
        closed = g[g["status"] == "Closed"]
        avg_resolution = closed["resolution_days"].mean() if not closed.empty else None
        escalation_rate = g["escalated"].mean() * 100
        critical_share = (g["severity"] == "Critical").mean() * 100
        total_cost = g["defect_cost_eur"].sum()
        open_count = (g["status"] != "Closed").sum()

        # simple composite score, 0-100, higher is better — illustrative only
        score = 100
        score -= min(escalation_rate, 40)
        score -= min(critical_share * 0.5, 20)
        if avg_resolution is not None:
            score -= min(max(avg_resolution - 20, 0) * 0.5, 20)
        score = max(0, round(score, 1))

        rows.append({
            "supplier_id": sup_id, "supplier_name": name, "commodity": commodity,
            "total_claims": total, "open_claims": int(open_count),
            "avg_resolution_days": round(avg_resolution, 1) if avg_resolution is not None else None,
            "escalation_rate_pct": round(escalation_rate, 1),
            "critical_share_pct": round(critical_share, 1),
            "total_defect_cost_eur": round(total_cost, 0),
            "rating_score": score,
        })
    out = pd.DataFrame(rows).sort_values("rating_score", ascending=False).reset_index(drop=True)
    return out


def facility_kpis():
    claims = df(
        """SELECT c.*, f.name AS facility_name, f.business_unit
           FROM claims c JOIN facilities f ON f.facility_id = c.facility_id"""
    )
    if claims.empty:
        return pd.DataFrame()
    claims["created_at"] = pd.to_datetime(claims["created_at"])
    claims["closed_at"] = pd.to_datetime(claims["closed_at"])
    claims["resolution_days"] = (claims["closed_at"] - claims["created_at"]).dt.days

    rows = []
    for fac_id, g in claims.groupby("facility_id"):
        rows.append({
            "facility_id": fac_id,
            "facility_name": g["facility_name"].iloc[0],
            "business_unit": g["business_unit"].iloc[0],
            "total_claims": len(g),
            "open_claims": int((g["status"] != "Closed").sum()),
            "escalated_claims": int(g["escalated"].sum()),
            "avg_resolution_days": round(g.loc[g["status"] == "Closed", "resolution_days"].mean(), 1)
            if (g["status"] == "Closed").any() else None,
        })
    return pd.DataFrame(rows).sort_values("total_claims", ascending=False).reset_index(drop=True)
