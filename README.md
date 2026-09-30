# SQM Claims / 8D / Incident Platform — Prototype

A working prototype for a standard, cross-facility claims and 8D workflow
platform — intended to replace email-based claim handling and local Excel
supplier scorecards, and to plug in as a module of the broader Supplier
Management / SQM digital backbone (alongside ASD, PPQ, FAI, SAP QM).

This is a **functional prototype**, not a production system: it runs
locally, uses a simulated login (pick a user from a dropdown instead of
real SSO), and stores data in a local SQLite file. Its purpose is to prove
the workflow and data model, and to give a concrete artifact to bring into
internal conversations — not to be deployed as-is.

## What it demonstrates

- **Single system of record for claims/8D/incidents** instead of email
  threads — one claim record, one activity log, one place both the local
  facility and the supplier can see and update.
- **Role-based access**: Global SQM (sees everything, cross-facility view),
  Local SQM (scoped to their facility, can escalate to Global), and
  Supplier (scoped to only their own claims — this is the "accessible to
  suppliers" requirement).
- **Standard 8D workflow** (D1–D8) built into every claim, with per-step
  status and content, so progress is trackable the same way in every
  facility rather than ad hoc.
- **Escalation path**: a Local SQM user can escalate a stuck claim to
  Global SQM with a reason, and it surfaces on the Global dashboard —
  replacing "the local team gets stuck and emails someone".
- **Supplier performance analytics**: a live rating table (claim volume,
  escalation rate, resolution time, defect cost, composite score) that
  replaces the local Excel scorecards, plus a cross-facility
  standardization view for Global SQM.

## Data model (SQLite, see `db.py`)

- `facilities`, `suppliers`, `users` — reference/master data
- `claims` — one row per claim/incident, with facility, supplier, severity,
  status, escalation flag/reason
- `d8_steps` — 8 rows per claim (D1–D8), each with its own status/content
- `activity_log` — every action and comment, timestamped (this is what
  replaces the email thread)
- `attachments` — table scaffolded for file uploads (not wired into the UI
  yet — flagged as a next step below)

This schema is deliberately simple/relational so it maps cleanly onto a
real backend later (Postgres, or a SharePoint Lists / Dataverse equivalent
if that ends up being the platform choice, or eventually SAP QM
integration).

## Running it

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open the local URL Streamlit prints (usually `http://localhost:8501`).
The database is created and seeded with ~28 realistic demo claims across 5
facilities and 6 suppliers automatically on first run. Use the "Reset demo
data" button in the sidebar to start over.

**Try it as different roles** using the "Log in as" dropdown in the
sidebar — that's the fastest way to see how the same data looks different
to Global SQM, a Local SQM user, and a supplier.

## Known simplifications (by design, for a prototype)

- Login is a dropdown, not real SSO/Entra ID — swap this for your identity
  provider before this goes near real data.
- Attachments table exists but file upload isn't wired into the UI yet.
- The supplier rating formula is illustrative (escalation rate, critical
  share, resolution speed) — it needs to be agreed with Global SQM /
  Quality leadership before it replaces the real Excel scorecards.
- Single SQLite file — fine for a demo and even a small pilot, but a
  multi-facility production rollout should move to a proper server-based
  database.
- No notifications yet (email/Teams alerts on escalation, due-date
  reminders) — natural next feature once the workflow itself is validated.

## Suggested next steps

1. Pilot with one facility + one supplier to validate the 8D workflow and
   escalation logic against how the local team actually works.
2. Decide the real hosting path (internal server for this Streamlit app,
   vs. porting the same data model to SharePoint Lists/Power Automate if
   IT prefers a lower-governance-risk platform).
3. Wire up file attachments and basic notifications.
4. Agree the supplier rating formula with stakeholders, then treat it as
   the system of record instead of the local Excel sheets.
5. Once validated, plan the integration point with ASD/PPQ/FAI/SAP QM as
   the claims module of the shared supplier-and-part record.
