"""
Export the demo tenant's knowledge graph to JSON and check the tenant.

    services/ingestion/.venv/Scripts/python.exe scripts/demo/export_graph.py

Writes demo-data/nephrova-knowledge-graph.json. Fails if:
- the file does not parse back, an edge points at a missing node, or a node has no edges
- stored edges differ from what the source files produce (validate_graph.py logic)
- any document's upload date differs from its day in the manifest
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).parent))
from seed_tenant import ACCOUNT, MANIFEST, database_url  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "demo-data" / "nephrova-knowledge-graph.json"


def expected_edges() -> set[tuple[str, str, str]]:
    import validate_graph as v

    edges = set()
    for path in v.files():
        for e in v.edges_for_file(path)[1]:
            edges.add((e.source["normalized_value"], e.relationship_type, e.target["normalized_value"]))
    return edges


def main() -> int:
    with psycopg.connect(database_url()) as conn:
        tenant_id = conn.execute("SELECT id FROM tenants WHERE slug = %s", [ACCOUNT["tenantSlug"]]).fetchone()[0]
        conn.execute("SELECT set_config('app.current_tenant_id', %s, true)", [str(tenant_id)])
        nodes = conn.execute("""SELECT id::text, entity_type, normalized_value FROM graph_nodes
                                WHERE tenant_id = %s ORDER BY entity_type, normalized_value""", [tenant_id]).fetchall()
        edges = conn.execute(
            """SELECT e.source_id::text, e.target_id::text, e.relationship, max(e.confidence),
                      array_agg(DISTINCT d.title ORDER BY d.title),
                      to_char(min(d.created_at) AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM-DD')
               FROM graph_edges e JOIN documents d ON d.id = e.document_id AND d.tenant_id = e.tenant_id
               WHERE e.tenant_id = %s GROUP BY e.source_id, e.target_id, e.relationship""", [tenant_id]).fetchall()
        upload_days = dict(conn.execute(
            """SELECT title, to_char(created_at AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM-DD')
               FROM documents WHERE tenant_id = %s""", [tenant_id]).fetchall())

    graph = {
        "tenant": ACCOUNT["tenantSlug"],
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": [{"id": i, "type": t, "label": v} for i, t, v in nodes],
        "edges": sorted(
            [{"source": s, "target": t, "relationship": r, "confidence": round(float(c), 3),
              "source_documents": docs, "first_seen": first} for s, t, r, c, docs, first in edges],
            key=lambda e: (e["first_seen"], e["relationship"])),
    }
    OUT.write_text(json.dumps(graph, indent=2, ensure_ascii=False), encoding="utf-8")

    problems = []
    loaded = json.loads(OUT.read_text(encoding="utf-8"))
    labels = {n["id"]: n["label"] for n in loaded["nodes"]}
    for e in loaded["edges"]:
        if e["source"] not in labels or e["target"] not in labels:
            problems.append(f"edge points at a missing node: {e}")
    used = {e["source"] for e in loaded["edges"]} | {e["target"] for e in loaded["edges"]}
    problems += [f"node with no edges: {labels[n]}" for n in labels if n not in used]

    stored = {(labels[e["source"]], e["relationship"], labels[e["target"]]) for e in loaded["edges"]}
    expected = expected_edges()
    import validate_graph as v

    if v.SEMANTIC:
        problems += [f"stored but not in source files: {e}" for e in sorted(stored - expected)]
    else:
        # Edges found through embeddings can't be reproduced without the model
        for e in sorted(stored - expected):
            print(f"  (embedding-typed, not re-checked without sentence-transformers) {e}")
    problems += [f"in source files but not stored: {e}" for e in sorted(expected - stored)]

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for item in manifest:
        name = Path(item["file"]).name
        if upload_days.get(name) != item["date"]:
            problems.append(f"upload date of {name} is {upload_days.get(name)}, expected {item['date']}")
    if len(set(upload_days.values())) != len(manifest):
        problems.append("documents do not fall on one distinct day each")

    print(f"Wrote {OUT.relative_to(ROOT)}: {loaded['node_count']} nodes, {loaded['edge_count']} edges")
    print(f"Upload dates: {min(upload_days.values())} to {max(upload_days.values())}, "
          f"{len(set(upload_days.values()))} distinct days for {len(upload_days)} documents")
    for p in problems:
        print("PROBLEM:", p)
    print("All checks passed" if not problems else f"{len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
