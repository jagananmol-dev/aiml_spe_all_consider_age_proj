"""
Create (or top up) the Nephrova Renal Care demo tenant.

1. Registers the tenant through /api/auth/register (skipped if it exists)
2. Uploads the 60 files through /api/documents/upload in date order,
   skipping files already uploaded
3. Waits until every document is indexed (or failed)
4. Backdates each document, its chunks, and its graph edges to the day in
   demo-data/nephrova-manifest.json, so the history reads as daily uploads
5. Seeds alerts, maintenance orders, and compliance rules that match the
   documents (replaced on every run)

Needs the local stack running (`npm run dev`). Safe to run again.

    services/ingestion/.venv/Scripts/python.exe scripts/demo/seed_tenant.py [--rebuild]

--rebuild first deletes the tenant's documents, chunks, graph, and stored
files (the login is kept), then uploads everything again.
"""

import json
import mimetypes
import sys
import time
from pathlib import Path

import httpx
import psycopg

sys.path.insert(0, str(Path(__file__).parent))
import company as C  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "demo-data" / "nephrova"
MANIFEST = ROOT / "demo-data" / "nephrova-manifest.json"
BASE = "http://localhost:3000"
ACCOUNT = C.ACCOUNT
UPLOAD_TIME = "18:30:00+05:30"  # each day's documents are uploaded at the end of the working day


def database_url() -> str:
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("DATABASE_URL not found in .env")


def login(client: httpx.Client) -> None:
    res = client.post("/api/auth/register", json=ACCOUNT)
    if res.status_code not in (201, 409):
        raise SystemExit(f"Register failed: {res.status_code} {res.text}")
    print("Tenant registered" if res.status_code == 201 else "Tenant already exists — topping up")
    res = client.post("/api/auth/login", json={k: ACCOUNT[k] for k in ("tenantSlug", "email", "password")})
    if res.status_code != 200:
        raise SystemExit(f"Login failed: {res.status_code} {res.text}")


def upload_all(client: httpx.Client, manifest: list[dict]) -> None:
    existing = {d["title"] for d in client.get("/api/documents/upload").json()["documents"]}
    for item in manifest:
        path = DATA / item["file"]
        if path.name in existing:
            continue
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        with path.open("rb") as f:
            res = client.post("/api/documents/upload", data={"format": item["format"]},
                              files={"file": (path.name, f, mime)})
        status = "ok" if res.status_code == 201 else f"FAILED {res.status_code} {res.text}"
        print(f"  {item['date']}  {item['file']}: {status}")


def wait_for_indexing(client: httpx.Client, timeout_s: int = 1800) -> list[dict]:
    deadline = time.time() + timeout_s
    while True:
        docs = client.get("/api/documents/upload").json()["documents"]
        pending = [d for d in docs if d["status"] not in ("indexed", "failed")]
        if not pending or time.time() > deadline:
            return docs
        print(f"  {len(docs) - len(pending)}/{len(docs)} processed")
        time.sleep(10)


def backdate(conn, tenant_id, manifest: list[dict]) -> int:
    changed = 0
    for item in manifest:
        stamp = f"{item['date']} {UPLOAD_TIME}"
        row = conn.execute(
            """UPDATE documents SET created_at = %s::timestamptz, updated_at = %s::timestamptz + interval '4 minutes'
               WHERE tenant_id = %s AND title = %s RETURNING id""",
            [stamp, stamp, tenant_id, Path(item["file"]).name]).fetchone()
        if row:
            conn.execute("UPDATE document_chunks SET created_at = %s::timestamptz + interval '4 minutes' "
                         "WHERE tenant_id = %s AND document_id = %s", [stamp, tenant_id, row[0]])
            conn.execute("UPDATE graph_edges SET created_at = %s::timestamptz + interval '4 minutes' "
                         "WHERE tenant_id = %s AND document_id = %s", [stamp, tenant_id, row[0]])
            changed += 1
    conn.execute("""UPDATE graph_nodes n SET created_at = sub.first FROM (
                        SELECT x.id, min(e.created_at) AS first FROM graph_nodes x
                        JOIN graph_edges e ON e.source_id = x.id OR e.target_id = x.id
                        WHERE x.tenant_id = %s GROUP BY x.id) sub
                    WHERE n.id = sub.id""", [tenant_id])
    return changed


def seed_records(conn, tenant_id, user_id, doc_ids: dict[str, str]) -> None:
    for table in ("alerts", "maintenance_orders", "compliance_rules"):
        conn.execute(f"DELETE FROM {table} WHERE tenant_id = %s", [tenant_id])
    R, G, N, K = C.ROH1, C.GENP1, C.NABH, C.HDK04
    t = lambda day: f"{day} 10:00:00+05:30"  # noqa: E731

    alerts = [
        (f"NABH corrective action open: waste colour-coding chart at Kothrud (due {N['closure_due']})",
         "NC-3 from the surveillance assessment of 24 September 2026.", "warning", "compliance", "", "open", "2026-09-25"),
        (f"PM-JAY dues INR {C.RECEIVABLES['Sep'][0]} lakh, {C.RECEIVABLES['Sep'][1]} claims older than 30 days",
         "Resubmit claims rejected for missing session sheets.", "warning", "finance", "", "open", "2026-10-03"),
        ("Catheter lock caps below 14 days of cover",
         "9 days of cover across centres; order placed 9 September 2026.", "warning", "inventory", "", "open", "2026-09-20"),
        (f"Pimpri machine maintenance due {C.PM_DATES_2026_H2['PMP']}",
         "Six-monthly preventive maintenance of the 8 Pimpri dialysis machines.", "info", "maintenance", "", "open", "2026-10-01"),
    ]
    for title, desc, sev, cat, tag, status, day in alerts:
        conn.execute("""INSERT INTO alerts (tenant_id, title, description, severity, category, equipment_tag, status,
                                            created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                     [tenant_id, title, desc, sev, cat, tag, status, t(day), t(day)])

    orders = [
        (K["job"], "Conductivity cell replacement and calibration", "HD-K04", "completed",
         {"conductivity before": f"{K['measured']} mS/cm", "conductivity after": f"{K['reference']} mS/cm"}, "2026-08-14"),
        ("WT-2026-0822", "Chemical and heat disinfection of water plant and loop", "RO-H1", "completed",
         {"endotoxin before": f"{R['endotoxin']} EU/mL", "endotoxin after": f"{R['endotoxin_after']} EU/mL",
          "maximum": f"{C.WATER['endotoxin_max']} EU/mL"}, "2026-08-22"),
        ("PM-2026-KTH-H2", "Six-monthly preventive maintenance, 12 machines", "", "completed", {}, "2026-08-29"),
        ("BME-2026-0347", "Starter battery replacement and load test", "GEN-P1", "completed",
         {"start time after repair": f"{G['test_start_s']} s", "target": f"{G['target_s']} s"}, "2026-09-08"),
        ("PM-2026-HDP-H2", "Six-monthly preventive maintenance, 10 machines", "", "completed", {}, "2026-09-16"),
        ("PM-2026-PMP-H2", "Six-monthly preventive maintenance, 8 machines", "", "open", {}, "2026-10-01"),
    ]
    for number, title, tag, status, tol, day in orders:
        conn.execute("""INSERT INTO maintenance_orders (tenant_id, order_number, title, description, equipment_tag,
                                                        status, tolerances, created_by, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)""",
                     [tenant_id, number, title, f"{title}. Raised {day}.", tag, status, json.dumps(tol), user_id,
                      t(day), t(day)])

    def ev(*names):
        return [doc_ids[n] for n in names if n in doc_ids]

    rules = [
        ("NABH", "5th Edition", "Dialysis water management", "Water plants are disinfected and tested every month with records kept.",
         "compliant", "NC-1 closed: disinfection due dates added to the weekly checklist.",
         ev("SOP-WT-002_Dialysis_Water_Treatment.pdf", "nabh_corrective_action_tracker.csv")),
        ("NABH", "5th Edition", "Infection control audits", "Hand hygiene is audited monthly at every centre.",
         "compliant", f"NC-2 closed. Pimpri re-audit {C.CRBSI['hand_hygiene_after']} percent.",
         ev("Infection_Control_Reaudit_PMP_Sep30.pdf", "Hand_Hygiene_Policy.md")),
        ("NABH", "5th Edition", "Bio-medical waste segregation", "Colour-coding charts are displayed at every collection point.",
         "gaps", f"NC-3 open at Kothrud; due {N['closure_due']}.", ev("NABH_Surveillance_Assessment_Report.pdf")),
        ("Bio-Medical Waste Management Rules", "2016", "Authorisation", "Valid authorisation from the State Pollution Control Board.",
         "compliant", f"Valid until {C.BMW_AUTH_VALID}.", ev("Biomedical_Waste_Management_SOP.md")),
        ("ISO 23500", "", "Dialysis water quality", "Product water within bacteria and endotoxin limits.",
         "compliant", "One August result at Hadapsar above limit; corrected and resampled within limits.",
         ev("Water_Lab_Report_RO-H1_Aug2026.pdf", "Water_Lab_Report_RO-H1_Resample.pdf")),
        ("DPDP Act", "2023", "Patient privacy notice", "Patients are told what data is collected and how to exercise their rights.",
         "compliant", "Privacy notice published 26 September 2026.", ev("Patient_Privacy_Notice.md")),
    ]
    for name, version, section, text, status, notes, evidence in rules:
        conn.execute("""INSERT INTO compliance_rules (tenant_id, regulation_name, regulation_version, section_reference,
                            requirement_text, requirement_type, compliance_status, notes, evidence_document_ids,
                            last_reviewed_at, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, 'mandatory', %s, %s, %s::uuid[], %s, %s, %s)""",
                     [tenant_id, name, version or None, section, text, status, notes, evidence,
                      t("2026-10-07"), t("2026-09-24"), t("2026-10-07")])
    print(f"Seeded {len(alerts)} alerts, {len(orders)} maintenance orders, {len(rules)} compliance rules")


def remove_documents() -> None:
    """--rebuild: delete the tenant's documents, chunks, graph, and stored files (the login stays)."""
    import shutil

    with psycopg.connect(database_url()) as conn:
        row = conn.execute("SELECT id FROM tenants WHERE slug = %s", [ACCOUNT["tenantSlug"]]).fetchone()
        if not row:
            return
        tenant_id = row[0]
        conn.execute("SELECT set_config('app.current_tenant_id', %s, true)", [str(tenant_id)])
        for table in ("graph_edges", "graph_nodes", "document_chunks", "documents"):
            conn.execute(f"DELETE FROM {table} WHERE tenant_id = %s", [tenant_id])
    uploads = (ROOT / ".data" / "uploads" / str(tenant_id)).resolve()
    if uploads.is_dir() and uploads.is_relative_to((ROOT / ".data" / "uploads").resolve()):
        shutil.rmtree(uploads)
    print("Removed existing documents for a clean rebuild")


def main() -> None:
    if "--rebuild" in sys.argv:
        remove_documents()
    manifest = sorted(json.loads(MANIFEST.read_text(encoding="utf-8")), key=lambda m: m["date"])
    with httpx.Client(base_url=BASE, timeout=120) as client:
        login(client)
        upload_all(client, manifest)
        docs = wait_for_indexing(client)
    failed = [d for d in docs if d["status"] == "failed"]
    for d in failed:
        print(f"  FAILED: {d['title']}: {d['error']}")

    with psycopg.connect(database_url()) as conn:
        tenant_id, user_id = conn.execute(
            """SELECT t.id, u.id FROM tenants t JOIN users u ON u.tenant_id = t.id
               WHERE t.slug = %s AND u.email = %s""", [ACCOUNT["tenantSlug"], ACCOUNT["email"]]).fetchone()
        conn.execute("SELECT set_config('app.current_tenant_id', %s, true)", [str(tenant_id)])
        print(f"Backdated {backdate(conn, tenant_id, manifest)} documents to their daily upload dates")
        seed_records(conn, tenant_id, user_id, {d["title"]: d["id"] for d in docs})
    print(f"{len(docs)} documents, {len(docs) - len(failed)} indexed, {len(failed)} failed")


if __name__ == "__main__":
    main()
