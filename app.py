"""
Claims / 8D / Incident Management Platform — Prototype
A module of the broader Supplier Quality Management (SQM) digital backbone.

Run with:  streamlit run app.py
"""
import streamlit as st
import pandas as pd
import plotly.express as px
import datetime as dt

from db import reset_and_seed, DB_PATH, D8_STEPS, SEVERITIES, STATUSES
import queries as q

st.set_page_config(page_title="SQM Claims & 8D Platform", page_icon="🛠️", layout="wide")

if not DB_PATH.exists():
    reset_and_seed()

# ---------------------------------------------------------------------------
# "Login" — role simulation (in production this comes from SSO/Entra ID)
# ---------------------------------------------------------------------------
users_df = q.all_users()

with st.sidebar:
    st.markdown("### 🛠️ SQM Claims & 8D Platform")
    st.caption("Prototype — module of the Supplier Management Platform")
    st.divider()

    st.markdown("**Simulated login**")
    st.caption("In production this would come from company SSO — pick a user to see their view.")
    username = st.selectbox(
        "Log in as",
        options=users_df["username"],
        format_func=lambda u: (
            f"{users_df.set_index('username').loc[u, 'display_name']} "
            f"({users_df.set_index('username').loc[u, 'role'].replace('_', ' ').title()})"
        ),
    )
    user = q.get_user(username)
    role = user["role"]
    facility_id = user["facility_id"]
    supplier_id = user["supplier_id"]

    st.divider()
    role_label = {"global_sqm": "🌍 Global SQM", "local_sqm": "🏭 Local SQM", "supplier": "🤝 Supplier"}[role]
    st.info(f"**{role_label}**\n\n{user['display_name']}")

    if role == "supplier":
        pages = ["Supplier Portal"]
    elif role == "local_sqm":
        pages = ["Dashboard", "Claims", "New Claim", "Supplier Ratings"]
    else:
        pages = ["Dashboard", "Claims", "New Claim", "Supplier Ratings", "Facility Standardization"]

    page = st.radio("Navigate", pages, label_visibility="collapsed")

    st.divider()
    if st.button("🔄 Reset demo data"):
        reset_and_seed()
        st.rerun()


def severity_badge(sev):
    color = {"Critical": "🔴", "Major": "🟠", "Minor": "🟡"}.get(sev, "⚪")
    return f"{color} {sev}"


def status_badge(status):
    color = {
        "Open": "🔵", "Contained": "🟣", "Root Cause In Progress": "🟠",
        "CAPA Implemented": "🟢", "Closed": "✅", "Escalated": "🚨",
    }.get(status, "⚪")
    return f"{color} {status}"


# ---------------------------------------------------------------------------
# DASHBOARD
# ---------------------------------------------------------------------------
def render_dashboard():
    st.title("Dashboard")
    scope_note = "All facilities (Global)" if role == "global_sqm" else f"Facility: {facility_id}"
    st.caption(scope_note)

    claims = q.claims_for_scope(role, facility_id, supplier_id)

    col1, col2, col3, col4, col5 = st.columns(5)
    total = len(claims)
    open_n = (claims["status"] != "Closed").sum() if total else 0
    escalated_n = claims["escalated"].sum() if total else 0
    critical_n = (claims["severity"] == "Critical").sum() if total else 0
    closed = claims[claims["status"] == "Closed"] if total else claims
    if total and not closed.empty:
        avg_days = (pd.to_datetime(closed["closed_at"]) - pd.to_datetime(closed["created_at"])).dt.days.mean()
    else:
        avg_days = None

    col1.metric("Total claims", total)
    col2.metric("Open", int(open_n))
    col3.metric("Escalated to Global", int(escalated_n))
    col4.metric("Critical severity", int(critical_n))
    col5.metric("Avg. resolution (days)", f"{avg_days:.0f}" if avg_days is not None else "—")

    st.divider()

    if total == 0:
        st.info("No claims in scope yet.")
        return

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Claims by status")
        status_counts = claims["status"].value_counts().reset_index()
        status_counts.columns = ["status", "count"]
        fig = px.bar(status_counts, x="status", y="count", color="status")
        fig.update_layout(showlegend=False, height=350)
        st.plotly_chart(fig, width='stretch')
    with c2:
        st.subheader("Claims by severity")
        sev_counts = claims["severity"].value_counts().reindex(SEVERITIES).fillna(0).reset_index()
        sev_counts.columns = ["severity", "count"]
        fig = px.pie(sev_counts, names="severity", values="count", hole=0.4,
                      color="severity", color_discrete_map={"Critical": "#d62728", "Major": "#ff7f0e", "Minor": "#f1c40f"})
        fig.update_layout(height=350)
        st.plotly_chart(fig, width='stretch')

    if role == "global_sqm":
        st.subheader("Claims by facility")
        fac_counts = claims.groupby("facility_name").size().reset_index(name="count")
        fig = px.bar(fac_counts, x="facility_name", y="count")
        fig.update_layout(height=320)
        st.plotly_chart(fig, width='stretch')

    esc = claims[claims["escalated"] == 1]
    if not esc.empty:
        st.subheader("🚨 Escalated claims needing Global SQM attention")
        st.dataframe(
            esc[["claim_id", "title", "facility_name", "supplier_name", "severity", "escalation_reason"]],
            width='stretch', hide_index=True,
        )


# ---------------------------------------------------------------------------
# CLAIMS LIST + DETAIL
# ---------------------------------------------------------------------------
def render_claims():
    st.title("Claims / 8D Register")
    claims = q.claims_for_scope(role, facility_id, supplier_id)

    if "open_claim" not in st.session_state:
        st.session_state.open_claim = None

    if st.session_state.open_claim:
        render_claim_detail(st.session_state.open_claim)
        return

    fc1, fc2, fc3, fc4 = st.columns(4)
    with fc1:
        f_status = st.multiselect("Status", STATUSES)
    with fc2:
        f_sev = st.multiselect("Severity", SEVERITIES)
    with fc3:
        f_sup = st.multiselect("Supplier", sorted(claims["supplier_name"].unique()) if not claims.empty else [])
    with fc4:
        f_search = st.text_input("Search title/ID")

    filtered = claims.copy()
    if f_status:
        filtered = filtered[filtered["status"].isin(f_status)]
    if f_sev:
        filtered = filtered[filtered["severity"].isin(f_sev)]
    if f_sup:
        filtered = filtered[filtered["supplier_name"].isin(f_sup)]
    if f_search:
        mask = filtered["title"].str.contains(f_search, case=False, na=False) | \
               filtered["claim_id"].str.contains(f_search, case=False, na=False)
        filtered = filtered[mask]

    st.caption(f"{len(filtered)} claim(s)")

    for _, row in filtered.iterrows():
        with st.container(border=True):
            c1, c2, c3, c4, c5 = st.columns([2, 4, 2, 2, 1.5])
            c1.markdown(f"**{row['claim_id']}**")
            c2.markdown(f"{row['title']}  \n:gray[{row['facility_name']} · {row['supplier_name']}]")
            c3.markdown(severity_badge(row["severity"]))
            c4.markdown(status_badge(row["status"]))
            if c5.button("Open", key=f"open_{row['claim_id']}"):
                st.session_state.open_claim = row["claim_id"]
                st.rerun()


def render_claim_detail(claim_id):
    claim = q.get_claim(claim_id)
    if claim is None:
        st.error("Claim not found.")
        st.session_state.open_claim = None
        return

    if st.button("← Back to register"):
        st.session_state.open_claim = None
        st.rerun()

    st.title(f"{claim['claim_id']} — {claim['title']}")
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(f"**Facility**\n\n{claim['facility_name']} ({claim['business_unit']})")
    c2.markdown(f"**Supplier**\n\n{claim['supplier_name']} ({claim['commodity']})")
    c3.markdown(f"**Severity**\n\n{severity_badge(claim['severity'])}")
    c4.markdown(f"**Status**\n\n{status_badge(claim['status'])}")

    st.markdown(f"**Description:** {claim['description']}")
    due_str = claim["due_date"][:10] if isinstance(claim["due_date"], str) and claim["due_date"] else "—"
    st.caption(f"Part number: {claim['part_number']} · Created {claim['created_at'][:10]} · Due {due_str}")

    if claim["escalated"]:
        st.warning(f"🚨 Escalated to Global SQM: {claim['escalation_reason']}")

    st.divider()
    tab1, tab2, tab3 = st.tabs(["8D Workflow", "Activity Log & Comments", "Actions"])

    with tab1:
        steps = q.get_d8_steps(claim_id)
        for _, s in steps.iterrows():
            icon = {"Complete": "✅", "In Progress": "🟠", "Not Started": "⚪"}.get(s["status"], "⚪")
            with st.expander(f"{icon} {s['step_code']} — {s['step_name']}  ·  {s['status']}"):
                editable = role in ("local_sqm", "global_sqm") or (role == "supplier" and s["step_no"] in (3, 4, 5, 6, 7))
                content = st.text_area("Content", value=s["content"] or "", key=f"content_{claim_id}_{s['step_no']}",
                                        disabled=not editable, height=100)
                new_status = st.selectbox(
                    "Step status", ["Not Started", "In Progress", "Complete"],
                    index=["Not Started", "In Progress", "Complete"].index(s["status"]),
                    key=f"status_{claim_id}_{s['step_no']}", disabled=not editable,
                )
                if editable and st.button("Save", key=f"save_{claim_id}_{s['step_no']}"):
                    q.update_d8_step(claim_id, s["step_no"], content, new_status, username)
                    st.success("Saved.")
                    st.rerun()
                if isinstance(s["updated_at"], str) and s["updated_at"]:
                    st.caption(f"Last updated by {s['updated_by']} on {s['updated_at'][:16]}")

    with tab2:
        note = st.text_area("Add a comment (replaces the email thread)", key=f"comment_{claim_id}")
        if st.button("Post comment"):
            if note.strip():
                q.add_comment(claim_id, username, note.strip())
                st.rerun()
        st.divider()
        activity = q.get_activity(claim_id)
        for _, a in activity.iterrows():
            st.markdown(f"**{a['action']}** — :gray[{a['actor']} · {a['timestamp'][:16]}]")
            if a["note"]:
                st.markdown(f"> {a['note']}")

    with tab3:
        if role in ("local_sqm",) and not claim["escalated"] and claim["status"] != "Closed":
            st.markdown("**Escalate to Global SQM**")
            reason = st.text_input("Reason for escalation", key=f"esc_reason_{claim_id}")
            if st.button("🚨 Escalate", type="primary"):
                if reason.strip():
                    q.escalate_claim(claim_id, username, reason.strip())
                    st.success("Escalated to Global SQM.")
                    st.rerun()
                else:
                    st.error("Provide a reason before escalating.")

        if role in ("local_sqm", "global_sqm") and claim["status"] != "Closed":
            st.markdown("**Update status**")
            new_status = st.selectbox("New status", STATUSES, key=f"new_status_{claim_id}")
            if st.button("Update status"):
                q.set_claim_status(claim_id, new_status, username)
                st.success("Status updated.")
                st.rerun()

        if claim["status"] == "Closed":
            st.success(f"Closed on {claim['closed_at'][:10]}")


# ---------------------------------------------------------------------------
# NEW CLAIM
# ---------------------------------------------------------------------------
def render_new_claim():
    st.title("New Claim / Incident")
    st.caption("Standard intake form — replaces free-text email reporting across all locations.")

    facilities = q.all_facilities()
    suppliers = q.all_suppliers()

    with st.form("new_claim_form"):
        title = st.text_input("Short title *")
        description = st.text_area("Description *", height=120)
        c1, c2 = st.columns(2)
        with c1:
            fac_choice = st.selectbox(
                "Facility *", facilities["facility_id"],
                format_func=lambda x: facilities.set_index("facility_id").loc[x, "name"],
                index=int(facilities[facilities["facility_id"] == facility_id].index[0]) if role == "local_sqm" and facility_id in list(facilities["facility_id"]) else 0,
                disabled=(role == "local_sqm"),
            )
            part_number = st.text_input("Part number")
        with c2:
            sup_choice = st.selectbox(
                "Supplier *", suppliers["supplier_id"],
                format_func=lambda x: suppliers.set_index("supplier_id").loc[x, "name"],
            )
            severity = st.selectbox("Severity *", SEVERITIES)

        submitted = st.form_submit_button("Submit claim", type="primary")
        if submitted:
            if not title.strip() or not description.strip():
                st.error("Title and description are required.")
            else:
                fac_final = facility_id if role == "local_sqm" else fac_choice
                claim_id = q.create_claim(title.strip(), description.strip(), fac_final, sup_choice,
                                           part_number.strip(), severity, username)
                st.success(f"Claim {claim_id} created. The supplier and relevant SQM team now have visibility — no email required.")


# ---------------------------------------------------------------------------
# SUPPLIER RATINGS (analytics)
# ---------------------------------------------------------------------------
def render_supplier_ratings():
    st.title("Supplier Performance & Rating")
    st.caption("Replaces locally-maintained Excel supplier scorecards with a live, shared view.")

    ratings = q.supplier_rating_table()
    if ratings.empty:
        st.info("No data yet.")
        return

    st.dataframe(
        ratings.rename(columns={
            "supplier_name": "Supplier", "commodity": "Commodity", "total_claims": "Total claims",
            "open_claims": "Open", "avg_resolution_days": "Avg. resolution (days)",
            "escalation_rate_pct": "Escalation rate (%)", "critical_share_pct": "Critical share (%)",
            "total_defect_cost_eur": "Total defect cost (€)", "rating_score": "Rating score (0-100)",
        }).drop(columns=["supplier_id"]),
        width='stretch', hide_index=True,
    )

    c1, c2 = st.columns(2)
    with c1:
        fig = px.bar(ratings.sort_values("rating_score"), x="rating_score", y="supplier_name",
                      orientation="h", color="rating_score", color_continuous_scale="RdYlGn",
                      title="Supplier rating score (illustrative composite)")
        fig.update_layout(height=400)
        st.plotly_chart(fig, width='stretch')
    with c2:
        fig = px.scatter(ratings, x="escalation_rate_pct", y="avg_resolution_days",
                          size="total_claims", color="commodity", hover_name="supplier_name",
                          title="Escalation rate vs. resolution speed")
        fig.update_layout(height=400)
        st.plotly_chart(fig, width='stretch')

    st.caption(
        "Rating score is an illustrative composite (escalation rate, critical-defect share, resolution speed). "
        "The real formula should be agreed with Global SQM/Quality leadership before this replaces the Excel scorecards."
    )


# ---------------------------------------------------------------------------
# FACILITY STANDARDIZATION (global-only)
# ---------------------------------------------------------------------------
def render_facility_view():
    st.title("Cross-Facility Standardization View")
    st.caption("Global SQM view — process consistency and workload across all locations.")

    kpis = q.facility_kpis()
    if kpis.empty:
        st.info("No data yet.")
        return

    st.dataframe(
        kpis.rename(columns={
            "facility_name": "Facility", "business_unit": "Business Unit",
            "total_claims": "Total claims", "open_claims": "Open",
            "escalated_claims": "Escalated", "avg_resolution_days": "Avg. resolution (days)",
        }).drop(columns=["facility_id"]),
        width='stretch', hide_index=True,
    )

    fig = px.bar(kpis, x="facility_name", y="avg_resolution_days", color="business_unit",
                  title="Average resolution time by facility — standardization gaps show up here")
    fig.update_layout(height=380)
    st.plotly_chart(fig, width='stretch')


# ---------------------------------------------------------------------------
# SUPPLIER PORTAL
# ---------------------------------------------------------------------------
def render_supplier_portal():
    st.title(f"Supplier Portal — {q.all_suppliers().set_index('supplier_id').loc[supplier_id, 'name']}")
    st.caption("Restricted view: this supplier can only see and act on their own claims.")

    claims = q.claims_for_scope(role, facility_id, supplier_id)
    col1, col2, col3 = st.columns(3)
    col1.metric("Total claims", len(claims))
    col2.metric("Open", int((claims["status"] != "Closed").sum()) if len(claims) else 0)
    col3.metric("Closed", int((claims["status"] == "Closed").sum()) if len(claims) else 0)

    if "open_claim" not in st.session_state:
        st.session_state.open_claim = None

    if st.session_state.open_claim:
        render_claim_detail(st.session_state.open_claim)
        return

    st.divider()
    for _, row in claims.iterrows():
        with st.container(border=True):
            c1, c2, c3, c4, c5 = st.columns([2, 4, 2, 2, 1.5])
            c1.markdown(f"**{row['claim_id']}**")
            c2.markdown(f"{row['title']}  \n:gray[{row['facility_name']}]")
            c3.markdown(severity_badge(row["severity"]))
            c4.markdown(status_badge(row["status"]))
            if c5.button("Open", key=f"sup_open_{row['claim_id']}"):
                st.session_state.open_claim = row["claim_id"]
                st.rerun()


# ---------------------------------------------------------------------------
# ROUTER
# ---------------------------------------------------------------------------
if page == "Dashboard":
    render_dashboard()
elif page == "Claims":
    render_claims()
elif page == "New Claim":
    render_new_claim()
elif page == "Supplier Ratings":
    render_supplier_ratings()
elif page == "Facility Standardization":
    render_facility_view()
elif page == "Supplier Portal":
    render_supplier_portal()
