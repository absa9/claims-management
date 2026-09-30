"""
Data layer for the Claims / 8D / Incident Platform prototype.
SQLite-backed, designed so the schema maps cleanly onto a real backend
(Postgres/SAP-adjacent) later. This module owns: schema creation, seed
data, and small CRUD/query helpers used by the Streamlit app.
"""
import sqlite3
import datetime as dt
from pathlib import Path
import random

DB_PATH = Path(__file__).parent / "data" / "claims8d.db"
DB_PATH.parent.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Reference data (kept small and explicit for a prototype / demo)
# ---------------------------------------------------------------------------

FACILITIES = [
    ("FAC-BER", "Berlin", "TR"),
    ("FAC-MUC", "Munich", "SG"),
    ("FAC-NUR", "Nuremberg", "SG"),
    ("FAC-CHA", "Charlotte (US)", "TR"),
    ("FAC-BAN", "Bangalore", "SG"),
]

SUPPLIERS = [
    ("SUP-001", "Volg Präzisionsteile", "Forgings"),
    ("SUP-002", "NordCast Foundry", "Castings"),
    ("SUP-003", "Elektra Components GmbH", "Electrical"),
    ("SUP-004", "Meridian Machining Inc.", "Machining"),
    ("SUP-005", "Ashoka Insulation Systems", "Insulation Materials"),
    ("SUP-006", "Baltic Steel Works", "Raw Material"),
]

USERS = [
    # (username, display_name, role, facility_id or None, supplier_id or None)
    ("a.shehata", "Abdallah Shehata", "global_sqm", None, None),
    ("l.mueller", "Lena Müller", "local_sqm", "FAC-BER", None),
    ("t.wagner", "Tobias Wagner", "local_sqm", "FAC-MUC", None),
    ("p.singh", "Priya Singh", "local_sqm", "FAC-BAN", None),
    ("j.smith", "Jordan Smith", "local_sqm", "FAC-CHA", None),
    ("supplier.volg", "Markus Volg", "supplier", None, "SUP-001"),
    ("supplier.nordcast", "Erik Nordahl", "supplier", None, "SUP-002"),
]

D8_STEPS = [
    (1, "D1", "Establish the Team"),
    (2, "D2", "Describe the Problem"),
    (3, "D3", "Contain the Problem (Interim Actions)"),
    (4, "D4", "Root Cause Analysis"),
    (5, "D5", "Choose Permanent Corrective Actions"),
    (6, "D6", "Implement Corrective Actions"),
    (7, "D7", "Prevent Recurrence"),
    (8, "D8", "Recognize the Team / Close Out"),
]

SEVERITIES = ["Critical", "Major", "Minor"]
STATUSES = ["Open", "Contained", "Root Cause In Progress", "CAPA Implemented", "Closed", "Escalated"]


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(reset: bool = False):
    if reset and DB_PATH.exists():
        DB_PATH.unlink()
    conn = get_conn()
    cur = conn.cursor()

    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS facilities (
            facility_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            business_unit TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS suppliers (
            supplier_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            commodity TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('global_sqm','local_sqm','supplier')),
            facility_id TEXT REFERENCES facilities(facility_id),
            supplier_id TEXT REFERENCES suppliers(supplier_id)
        );

        CREATE TABLE IF NOT EXISTS claims (
            claim_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            facility_id TEXT NOT NULL REFERENCES facilities(facility_id),
            supplier_id TEXT NOT NULL REFERENCES suppliers(supplier_id),
            part_number TEXT,
            severity TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Open',
            created_by TEXT REFERENCES users(username),
            created_at TEXT NOT NULL,
            due_date TEXT,
            closed_at TEXT,
            escalated INTEGER NOT NULL DEFAULT 0,
            escalated_at TEXT,
            escalation_reason TEXT,
            defect_cost_eur REAL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS d8_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id TEXT NOT NULL REFERENCES claims(claim_id),
            step_no INTEGER NOT NULL,
            step_code TEXT NOT NULL,
            step_name TEXT NOT NULL,
            content TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Not Started',
            updated_by TEXT,
            updated_at TEXT,
            UNIQUE(claim_id, step_no)
        );

        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id TEXT NOT NULL REFERENCES claims(claim_id),
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            note TEXT,
            timestamp TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id TEXT NOT NULL REFERENCES claims(claim_id),
            filename TEXT NOT NULL,
            uploaded_by TEXT,
            uploaded_at TEXT
        );
        """
    )
    conn.commit()
    conn.close()


def _seed_reference_data(conn):
    cur = conn.cursor()
    cur.executemany(
        "INSERT OR IGNORE INTO facilities (facility_id, name, business_unit) VALUES (?,?,?)",
        FACILITIES,
    )
    cur.executemany(
        "INSERT OR IGNORE INTO suppliers (supplier_id, name, commodity) VALUES (?,?,?)",
        SUPPLIERS,
    )
    cur.executemany(
        "INSERT OR IGNORE INTO users (username, display_name, role, facility_id, supplier_id) VALUES (?,?,?,?,?)",
        USERS,
    )
    conn.commit()


def _make_claim_id(i):
    return f"CLM-{2026}-{i:04d}"


def seed_demo_claims(n=28, seed=42):
    """Populate a realistic spread of claims/8D records for demo purposes."""
    random.seed(seed)
    conn = get_conn()
    _seed_reference_data(conn)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM claims")
    if cur.fetchone()[0] > 0:
        conn.close()
        return  # already seeded

    local_users = [u for u in USERS if u[2] == "local_sqm"]
    now = dt.datetime(2026, 9, 27)

    for i in range(1, n + 1):
        claim_id = _make_claim_id(i)
        fac = random.choice(FACILITIES)
        sup = random.choice(SUPPLIERS)
        severity = random.choices(SEVERITIES, weights=[0.2, 0.45, 0.35])[0]
        created_days_ago = random.randint(1, 120)
        created_at = now - dt.timedelta(days=created_days_ago)
        creator = next((u for u in local_users if u[3] == fac[0]), local_users[0])

        # progress the claim through the 8D lifecycle probabilistically
        age = created_days_ago
        if age > 60:
            status_roll = random.random()
            status = "Closed" if status_roll < 0.75 else ("Escalated" if status_roll < 0.85 else "CAPA Implemented")
        elif age > 30:
            status = random.choice(["Root Cause In Progress", "CAPA Implemented", "Closed", "Escalated"])
        elif age > 10:
            status = random.choice(["Contained", "Root Cause In Progress"])
        else:
            status = random.choice(["Open", "Contained"])

        due_date = created_at + dt.timedelta(days=30 if severity != "Critical" else 15)
        closed_at = None
        if status == "Closed":
            closed_delay = random.randint(10, 45)
            closed_at = (created_at + dt.timedelta(days=closed_delay)).isoformat()

        escalated = 1 if status == "Escalated" else 0
        escalated_at = (created_at + dt.timedelta(days=random.randint(5, 20))).isoformat() if escalated else None
        escalation_reason = (
            random.choice([
                "Local team unable to reach root cause within SLA",
                "Supplier non-responsive after two follow-ups",
                "Recurrence of a previously closed issue",
                "Cross-facility impact identified",
            ])
            if escalated else None
        )

        defect_cost = round(random.uniform(500, 45000) * (2.5 if severity == "Critical" else 1), 2)

        cur.execute(
            """INSERT INTO claims
               (claim_id, title, description, facility_id, supplier_id, part_number,
                severity, status, created_by, created_at, due_date, closed_at,
                escalated, escalated_at, escalation_reason, defect_cost_eur)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                claim_id,
                f"{severity} nonconformance – {sup[2]} part from {sup[1]}",
                f"Deviation detected during incoming inspection / field return at {fac[1]}. "
                f"Part number affected, linked to {sup[1]} ({sup[2]}).",
                fac[0], sup[0], f"PN-{random.randint(10000,99999)}",
                severity, status, creator[0], created_at.isoformat(),
                due_date.isoformat(), closed_at,
                escalated, escalated_at, escalation_reason, defect_cost,
            ),
        )

        # 8D step progress consistent with status
        step_progress_map = {
            "Open": 1, "Contained": 3, "Root Cause In Progress": 4,
            "CAPA Implemented": 6, "Closed": 8, "Escalated": 4,
        }
        completed_through = step_progress_map.get(status, 1)
        for step_no, code, name in D8_STEPS:
            if step_no < completed_through:
                s_status = "Complete"
            elif step_no == completed_through:
                s_status = "In Progress"
            else:
                s_status = "Not Started"
            content = ""
            if s_status != "Not Started":
                content = f"({code}) recorded by {creator[1]} — placeholder demo content."
            cur.execute(
                """INSERT INTO d8_steps (claim_id, step_no, step_code, step_name, content, status, updated_by, updated_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (claim_id, step_no, code, name, content, s_status,
                 creator[0] if s_status != "Not Started" else None,
                 created_at.isoformat() if s_status != "Not Started" else None),
            )

        # activity log
        cur.execute(
            """INSERT INTO activity_log (claim_id, actor, action, note, timestamp)
               VALUES (?,?,?,?,?)""",
            (claim_id, creator[0], "Claim created", "Initial claim raised.", created_at.isoformat()),
        )
        if escalated:
            cur.execute(
                """INSERT INTO activity_log (claim_id, actor, action, note, timestamp)
                   VALUES (?,?,?,?,?)""",
                (claim_id, creator[0], "Escalated to Global SQM", escalation_reason, escalated_at),
            )
        if status == "Closed":
            cur.execute(
                """INSERT INTO activity_log (claim_id, actor, action, note, timestamp)
                   VALUES (?,?,?,?,?)""",
                (claim_id, creator[0], "Claim closed", "8D closed out, CAPA verified effective.", closed_at),
            )

    conn.commit()
    conn.close()


def reset_and_seed():
    init_db(reset=True)
    seed_demo_claims()


if __name__ == "__main__":
    reset_and_seed()
    print(f"Database ready at {DB_PATH}")
