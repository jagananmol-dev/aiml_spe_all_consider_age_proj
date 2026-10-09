"""
VEDA AI — Rebuild the local knowledge graph

The graph is derived data: entities and edges are extracted with the graph
schema in force when a document is indexed. After changing
graph_schema.json or a tenant's tenants.settings.graph_schema, rebuild the
graph so existing documents follow the new schema. Text comes from the
stored chunks (overlaps removed), so nothing is re-parsed or re-embedded.

Run (intelligence venv, from services/intelligence):
    python -m src.knowledge_graph.rebuild --tenant <slug or id>
    python -m src.knowledge_graph.rebuild --all
"""

import argparse
import logging
import sys
import time

from ..rag.pipeline import rag_pipeline, settings
from . import local_graph

logger = logging.getLogger("veda.intelligence.rebuild")


def join_chunks(chunks: list[str], max_overlap: int = 600) -> str:
    """Rejoin consecutive chunks, dropping the text a chunk repeats from the previous one."""
    text = ""
    for chunk in chunks:
        if not text:
            text = chunk
            continue
        overlap = 0
        for size in range(min(max_overlap, len(chunk), len(text)), 20, -1):
            if text.endswith(chunk[:size]):
                overlap = size
                break
        text += ("" if overlap else "\n\n") + chunk[overlap:]
    return text


def _tenants(conn, selector: str | None) -> list[tuple[str, str]]:
    if selector is None:
        return conn.execute(
            "SELECT DISTINCT t.id::text, t.slug FROM tenants t JOIN documents d ON d.tenant_id = t.id "
            "WHERE d.status = 'indexed'"
        ).fetchall()
    return conn.execute(
        "SELECT id::text, slug FROM tenants WHERE slug = %s OR id::text = %s", [selector, selector]
    ).fetchall()


def rebuild_tenant(tenant_id: str) -> tuple[int, int]:
    """Re-extract every indexed document's graph. Returns (documents, edges)."""
    with local_graph._connect(settings.database_url) as conn:
        conn.execute("SELECT set_config('app.current_tenant_id', %s, true)", [tenant_id])
        rows = conn.execute(
            """
            SELECT d.id::text, array_agg(c.chunk_text ORDER BY c.chunk_index)
            FROM documents d JOIN document_chunks c ON c.document_id = d.id AND c.tenant_id = d.tenant_id
            WHERE d.tenant_id = %s::uuid AND d.status = 'indexed'
            GROUP BY d.id, d.created_at ORDER BY d.created_at
            """,
            [tenant_id],
        ).fetchall()
    edges = 0
    for document_id, chunks in rows:
        edges += rag_pipeline.build_local_graph(tenant_id, document_id, join_chunks(list(chunks)))
    # Nodes no document uses any more
    with local_graph._connect(settings.database_url) as conn:
        conn.execute("SELECT set_config('app.current_tenant_id', %s, true)", [tenant_id])
        conn.execute(
            """
            DELETE FROM graph_nodes n WHERE n.tenant_id = %s::uuid AND NOT EXISTS (
                SELECT 1 FROM graph_edges e WHERE e.tenant_id = n.tenant_id
                AND (e.source_id = n.id OR e.target_id = n.id))
            """,
            [tenant_id],
        )
    return len(rows), edges


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild the local knowledge graph from stored chunks"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tenant", help="tenant slug or id")
    group.add_argument("--all", action="store_true", help="every tenant with indexed documents")
    args = parser.parse_args(argv)

    with local_graph._connect(settings.database_url) as conn:
        tenants = _tenants(conn, None if args.all else args.tenant)
    if not tenants:
        print("No matching tenant", file=sys.stderr)
        return 1
    for tenant_id, slug in tenants:
        started = time.time()
        documents, edges = rebuild_tenant(tenant_id)
        print(
            f"{slug}: {documents} documents, {edges} edges (per document) in {time.time() - started:.1f}s"
        )
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    sys.exit(main())
