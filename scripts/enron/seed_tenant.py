"""
Create (or top up) the Enron Corp. tenant from real public data:

- Enron's SEC filings 1999–2002 (scripts/enron/fetch_sec.py)
- the CMU Enron email corpus, bundled per mailbox and month
  (scripts/enron/build_emails.py)
- Enron's own policies: the July 2000 Code of Ethics and policies announced
  to employees by email (scripts/enron/build_policies.py)

Steps:
1. registers the tenant through /api/auth/register (skipped if it exists)
2. stores the Enron graph-schema extension in tenants.settings.graph_schema
   before anything is indexed
3. uploads every document through /api/documents/upload in date order,
   skipping titles already uploaded (read from the database, since the
   upload list API returns at most 500 rows)
4. waits until the queue is empty, printing throughput
5. backdates each document, its chunks and its graph edges to the date the
   filing was made or the month's last email was sent

Nothing is invented: no alerts, orders or compliance rules are seeded.

    services/ingestion/.venv/Scripts/python.exe scripts/enron/seed_tenant.py [--limit N] [--no-wait]
"""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx
import psycopg

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / ".data" / "enron"
SCHEMA = Path(__file__).with_name("graph_schema_enron.json")
BASE = "http://localhost:3000"
ACCOUNT = {
    "companyName": "Enron Corp.",
    "tenantSlug": "enron",
    "name": "Enron Demo Admin",
    "email": "demo@enron-corp.example",
    "password": "Enron@Demo#2001",
}
UPLOAD_TIME = "18:00:00-06:00"  # Houston


def database_url() -> str:
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("DATABASE_URL not found in .env")


def manifest() -> list[dict]:
    items = [
        {"file": f"sec/{p.name}", "date": p.name.split("_")[3], "kind": "sec"}
        for p in sorted((DATA / "sec").glob("*.txt"))
    ]
    policies = DATA / "policies_manifest.json"
    if policies.exists():
        items += [
            {"file": f"policies/{m['file']}", "date": m["date"], "kind": "policy"}
            for m in json.loads(policies.read_text(encoding="utf-8"))
        ]
    emails = DATA / "emails_manifest.json"
    if emails.exists():
        items += [
            {"file": f"emails/{m['file']}", "date": m["date"], "kind": "email"}
            for m in json.loads(emails.read_text(encoding="utf-8"))
        ]
    return sorted(items, key=lambda m: (m["date"], m["file"]))


def login(client: httpx.Client) -> None:
    res = client.post("/api/auth/register", json=ACCOUNT)
    if res.status_code not in (201, 409):
        raise SystemExit(f"Register failed: {res.status_code} {res.text}")
    print("Tenant registered" if res.status_code == 201 else "Tenant already exists — topping up")
    res = client.post(
        "/api/auth/login", json={k: ACCOUNT[k] for k in ("tenantSlug", "email", "password")}
    )
    if res.status_code != 200:
        raise SystemExit(f"Login failed: {res.status_code} {res.text}")


def tenant_conn():
    conn = psycopg.connect(database_url(), autocommit=True)
    row = conn.execute("SELECT id FROM tenants WHERE slug = %s", [ACCOUNT["tenantSlug"]]).fetchone()
    if not row:
        raise SystemExit("Tenant not found")
    return conn, str(row[0])


def store_schema(conn, tenant_id: str) -> None:
    extension = json.loads(SCHEMA.read_text(encoding="utf-8"))
    conn.execute(
        """UPDATE tenants SET settings = jsonb_set(COALESCE(settings, '{}'::jsonb), '{graph_schema}', %s::jsonb),
                              updated_at = NOW()
           WHERE id = %s""",
        [json.dumps(extension), tenant_id],
    )
    print("Stored the Enron graph-schema extension on the tenant")


def status_counts(conn, tenant_id: str) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status, count(*) FROM documents WHERE tenant_id = %s GROUP BY status", [tenant_id]
    ).fetchall()
    return dict(rows)


def upload_all(client: httpx.Client, conn, tenant_id: str, items: list[dict]) -> int:
    existing = {
        r[0] for r in conn.execute("SELECT title FROM documents WHERE tenant_id = %s", [tenant_id])
    }
    uploaded = 0
    for item in items:
        path = DATA / item["file"]
        if path.name in existing:
            continue
        with path.open("rb") as f:
            res = client.post(
                "/api/documents/upload",
                data={"format": "text"},
                files={"file": (path.name, f, "text/plain")},
            )
        if res.status_code != 201:
            print(f"  FAILED {item['file']}: {res.status_code} {res.text[:200]}")
            continue
        uploaded += 1
        if uploaded % 100 == 0:
            print(f"  uploaded {uploaded}", flush=True)
    return uploaded


def wait_for_indexing(conn, tenant_id: str, timeout_s: int = 24 * 3600) -> None:
    started = time.time()
    first = status_counts(conn, tenant_id).get("indexed", 0)
    while time.time() - started < timeout_s:
        counts = status_counts(conn, tenant_id)
        pending = sum(v for k, v in counts.items() if k not in ("indexed", "failed"))
        done = counts.get("indexed", 0) - first
        rate = done / max(time.time() - started, 1) * 60
        eta = f", ~{pending / rate:.0f} min left" if rate > 0 else ""
        print(f"  {counts} · {rate:.1f} docs/min{eta}", flush=True)
        if pending == 0:
            return
        time.sleep(30)


def backdate(conn, tenant_id: str, items: list[dict]) -> int:
    conn.execute("SELECT set_config('app.current_tenant_id', %s, false)", [tenant_id])
    changed = 0
    for item in items:
        stamp = f"{item['date']} {UPLOAD_TIME}"
        row = conn.execute(
            """UPDATE documents SET created_at = %s::timestamptz,
                                    updated_at = %s::timestamptz + interval '4 minutes'
               WHERE tenant_id = %s AND title = %s RETURNING id""",
            [stamp, stamp, tenant_id, Path(item["file"]).name],
        ).fetchone()
        if row:
            for table in ("document_chunks", "graph_edges"):
                conn.execute(
                    f"UPDATE {table} SET created_at = %s::timestamptz + interval '4 minutes' "
                    "WHERE tenant_id = %s AND document_id = %s",
                    [stamp, tenant_id, row[0]],
                )
            changed += 1
    return changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="upload only the first N documents (by date)")
    parser.add_argument("--no-wait", action="store_true", help="upload and return")
    args = parser.parse_args()

    items = manifest()
    if args.limit:
        items = items[: args.limit]
    print(f"{len(items)} documents in the manifest")

    with httpx.Client(base_url=BASE, timeout=300) as client:
        login(client)
        conn, tenant_id = tenant_conn()
        store_schema(conn, tenant_id)
        print(f"Uploaded {upload_all(client, conn, tenant_id, items)} new documents")
    if args.no_wait:
        return 0
    wait_for_indexing(conn, tenant_id)
    print(f"Backdated {backdate(conn, tenant_id, items)} documents")
    counts = status_counts(conn, tenant_id)
    for title, error in conn.execute(
        "SELECT title, metadata->>'error' FROM documents WHERE tenant_id = %s AND status = 'failed'",
        [tenant_id],
    ):
        print(f"  FAILED {title}: {error}")
    print(f"Done: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
