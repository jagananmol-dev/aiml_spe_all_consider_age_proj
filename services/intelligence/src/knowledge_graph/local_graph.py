"""
VEDA AI — Local knowledge graph (no Apache AGE)

Used when VEDA_GRAPH_BACKEND=local, e.g. a Windows dev/demo machine. Nodes
and edges live in the plain PostgreSQL tables `graph_nodes` / `graph_edges`
(infrastructure/docker/postgres/local/003_local_graph.sql).

- Each edge records the document it came from, so re-indexing a document
  replaces exactly that document's edges and deleting it removes them.
- Only entities that take part in an edge become nodes.
- Search walks the graph breadth-first and returns the walked edges
  (parent → child), so every edge shown is one that was actually extracted.
  MEASUREMENT nodes are leaves, and a concept node (failure, action) reached
  from a machine never leads on to another machine: "0.05 mm" or
  "inspection" shared by two machines must not make them look related.

Every query filters on tenant_id explicitly. Functions are synchronous, like
local_store, and are run in a worker thread by callers.
"""

import json
import logging
import threading
import time
from collections import deque

import numpy as np

from ..entity_extraction import semantic
from ..entity_extraction.schema import GraphSchema, get_schema
from ..rag.local_store import _reused_connection
from .relationships import InferredEdge

try:
    import psycopg
except ImportError:  # pragma: no cover - optional dependency
    psycopg = None

logger = logging.getLogger("veda.intelligence.local_graph")

# Leaf types, inverse relationship names and which types are "subjects"
# (assets a concept must not bridge between) come from the graph schema.
# These names are the default schema's, kept for callers that read them.
_DEFAULT = get_schema()
LEAF_TYPES = _DEFAULT.leaf_types
INVERSE_NAMES = dict(_DEFAULT.inverse_names)


def _connect(database_url: str):
    if psycopg is None:
        raise RuntimeError("psycopg is not installed. Install service dependencies first.")
    return psycopg.connect(database_url, connect_timeout=5)


def replace_document_graph(
    database_url: str, tenant_id: str, document_id: str, edges: list[InferredEdge]
) -> int:
    """Atomically replace one document's edges. Returns the number of edges stored."""
    with _connect(database_url) as conn:
        conn.execute("SELECT set_config('app.current_tenant_id', %s, true)", [tenant_id])
        conn.execute(
            "DELETE FROM graph_edges WHERE tenant_id = %s::uuid AND document_id = %s::uuid",
            [tenant_id, document_id],
        )

        node_ids: dict[tuple[str, str], str] = {}

        def node_id(entity: dict) -> str:
            key = (entity["entity_type"], entity["normalized_value"])
            if key not in node_ids:
                row = conn.execute(
                    """
                    INSERT INTO graph_nodes (tenant_id, entity_type, normalized_value, value)
                    VALUES (%s::uuid, %s, %s, %s)
                    ON CONFLICT (tenant_id, entity_type, normalized_value)
                    DO UPDATE SET value = graph_nodes.value
                    RETURNING id::text
                    """,
                    [tenant_id, key[0], key[1], entity.get("value") or key[1]],
                ).fetchone()
                node_ids[key] = row[0]
            return node_ids[key]

        for edge in edges:
            conn.execute(
                """
                INSERT INTO graph_edges
                    (tenant_id, document_id, source_id, target_id, relationship, confidence)
                VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                [
                    tenant_id,
                    document_id,
                    node_id(edge.source),
                    node_id(edge.target),
                    edge.relationship_type,
                    float(edge.confidence),
                ],
            )
    return len(edges)


def _load_edges(conn, tenant_id: str) -> list[tuple]:
    return conn.execute(
        """
        SELECT s.id::text, s.entity_type, s.normalized_value,
               t.id::text, t.entity_type, t.normalized_value,
               e.relationship, max(e.confidence), min(e.document_id::text)
        FROM graph_edges e
        JOIN graph_nodes s ON s.id = e.source_id AND s.tenant_id = e.tenant_id
        JOIN graph_nodes t ON t.id = e.target_id AND t.tenant_id = e.tenant_id
        WHERE e.tenant_id = %s::uuid
        GROUP BY s.id, s.entity_type, s.normalized_value,
                 t.id, t.entity_type, t.normalized_value, e.relationship
        """,
        [tenant_id],
    ).fetchall()


def walk(
    rows: list[tuple],
    entity_value: str,
    entity_type: str | None,
    max_hops: int,
    limit: int,
    schema: GraphSchema | None = None,
) -> list[dict]:
    """Breadth-first walk over edge rows from the node matching entity_value."""
    schema = schema or get_schema()
    inverse_names, leaf_types, subjects = (
        schema.inverse_names,
        schema.leaf_types,
        schema.subject_types,
    )
    nodes: dict[str, tuple[str, str]] = {}
    adjacency: dict[str, list[tuple]] = {}
    for sid, stype, sval, tid, ttype, tval, rel, conf, doc in rows:
        nodes[sid], nodes[tid] = (stype, sval), (ttype, tval)
        adjacency.setdefault(sid, []).append((tid, rel, conf, doc))
        adjacency.setdefault(tid, []).append((sid, inverse_names.get(rel, rel), conf, doc))

    wanted = entity_value.strip().lower()
    starts = [
        nid
        for nid, (ntype, nval) in nodes.items()
        if nval.lower() == wanted and (not entity_type or ntype == entity_type)
    ]
    if not starts:
        return []
    # Prefer a subject (asset) node when the same text is several entity types
    start = sorted(starts, key=lambda nid: nodes[nid][0] not in subjects)[0]

    results: list[dict] = []
    seen = {start}
    queue = deque([(start, 0)])
    while queue and len(results) < limit:
        current, depth = queue.popleft()
        if depth >= max_hops or (current != start and nodes[current][0] in leaf_types):
            continue
        bridge_blocked = current != start and nodes[current][0] not in subjects
        for neighbour, rel, conf, doc in sorted(adjacency.get(current, []), key=lambda a: a[1]):
            if neighbour in seen:
                continue
            # A shared concept ("inspection", "bearing failure") must not make
            # two assets look related
            if bridge_blocked and nodes[neighbour][0] in subjects:
                continue
            seen.add(neighbour)
            results.append(
                {
                    "source_type": nodes[current][0],
                    "source_value": nodes[current][1],
                    "target_type": nodes[neighbour][0],
                    "target_value": nodes[neighbour][1],
                    "relationship": rel,
                    "document_id": doc,
                    "confidence": float(conf or 0.0),
                    "distance": depth + 1,
                }
            )
            if len(results) >= limit:
                break
            queue.append((neighbour, depth + 1))
    return results


def search(
    database_url: str,
    tenant_id: str,
    entity_value: str,
    entity_type: str | None = None,
    max_hops: int = 2,
    limit: int = 50,
) -> list[dict]:
    """Return the edges reachable from an entity within max_hops (case-insensitive match)."""
    with _connect(database_url) as conn:
        conn.execute("SELECT set_config('app.current_tenant_id', %s, true)", [tenant_id])
        rows = _load_edges(conn, tenant_id)
    return walk(rows, entity_value, entity_type, max_hops, limit)


def overview(database_url: str, tenant_id: str, limit: int = 2000) -> dict:
    """
    The tenant's whole graph for visualisation: every node that has an edge,
    and every distinct edge with the titles of the documents it came from,
    plus the schema's type labels and colours.
    """
    types = tenant_schema(database_url, tenant_id).public_types()
    with _connect(database_url) as conn:
        conn.execute("SELECT set_config('app.current_tenant_id', %s, true)", [tenant_id])
        rows = conn.execute(
            """
            SELECT s.id::text, s.entity_type, s.normalized_value,
                   t.id::text, t.entity_type, t.normalized_value,
                   e.relationship, max(e.confidence),
                   array_agg(DISTINCT d.title ORDER BY d.title)
            FROM graph_edges e
            JOIN graph_nodes s ON s.id = e.source_id AND s.tenant_id = e.tenant_id
            JOIN graph_nodes t ON t.id = e.target_id AND t.tenant_id = e.tenant_id
            JOIN documents d ON d.id = e.document_id AND d.tenant_id = e.tenant_id
            WHERE e.tenant_id = %s::uuid
            GROUP BY s.id, s.entity_type, s.normalized_value,
                     t.id, t.entity_type, t.normalized_value, e.relationship
            ORDER BY s.normalized_value, e.relationship, t.normalized_value
            LIMIT %s
            """,
            [tenant_id, limit],
        ).fetchall()

    nodes: dict[str, dict] = {}
    edges = []
    for sid, stype, sval, tid, ttype, tval, rel, conf, docs in rows:
        for nid, ntype, nval in ((sid, stype, sval), (tid, ttype, tval)):
            node = nodes.setdefault(nid, {"id": nid, "label": nval, "type": ntype, "degree": 0})
            node["degree"] += 1
        edges.append(
            {
                "source": sid,
                "target": tid,
                "relationship": rel,
                "confidence": float(conf or 0.0),
                "documents": list(docs or []),
            }
        )
    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "types": types,
    }


def stats(database_url: str, tenant_id: str) -> dict:
    """Node/edge counts for the tenant's graph."""
    result = {
        "total_nodes": 0,
        "total_edges": 0,
        "entity_types": {},
        "relationship_types": {},
        "last_updated": None,
    }
    with _connect(database_url) as conn:
        conn.execute("SELECT set_config('app.current_tenant_id', %s, true)", [tenant_id])
        rows = _load_edges(conn, tenant_id)
        last = conn.execute(
            "SELECT max(created_at) FROM graph_edges WHERE tenant_id = %s::uuid", [tenant_id]
        ).fetchone()
    seen: set[str] = set()
    for sid, stype, _, tid, ttype, _, rel, _, _ in rows:
        for nid, ntype in ((sid, stype), (tid, ttype)):
            if nid not in seen:
                seen.add(nid)
                result["entity_types"][ntype] = result["entity_types"].get(ntype, 0) + 1
        result["relationship_types"][rel] = result["relationship_types"].get(rel, 0) + 1
    result["total_nodes"] = len(seen)
    result["total_edges"] = len(rows)
    if last and last[0]:
        result["last_updated"] = last[0].isoformat()
    return result


# ── Tenant schema ─────────────────────────────────────
_SCHEMA_TTL_SECONDS = 60
_schema_cache: dict[str, tuple[float, GraphSchema]] = {}


def tenant_schema(database_url: str, tenant_id: str) -> GraphSchema:
    """
    The base schema extended by the tenant's tenants.settings.graph_schema
    (cached for a minute). Falls back to the base schema if it cannot be read.
    """
    cached = _schema_cache.get(tenant_id)
    if cached and time.monotonic() - cached[0] < _SCHEMA_TTL_SECONDS:
        return cached[1]
    extension = None
    try:
        with _connect(database_url) as conn:
            conn.execute("SELECT set_config('app.current_tenant_id', %s, true)", [tenant_id])
            row = conn.execute(
                "SELECT settings -> 'graph_schema' FROM tenants WHERE id = %s::uuid", [tenant_id]
            ).fetchone()
        if row and row[0]:
            extension = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    except Exception as e:
        logger.warning(f"Could not read the graph schema of tenant {tenant_id}: {e}")
    schema = get_schema(extension)
    _schema_cache[tenant_id] = (time.monotonic(), schema)
    return schema


# ── Node embedding index ──────────────────────────────
# Each tenant's node names, embedded once and kept as a matrix, so a question
# or a new document is linked to existing nodes with one matrix product.
# Reloaded when the tenant's nodes or edges change.
_NODE_FINGERPRINT_SQL = """
    SELECT (SELECT count(*) FROM graph_nodes WHERE tenant_id = %s::uuid),
           (SELECT coalesce(max(xmin::text::bigint), 0) FROM graph_nodes WHERE tenant_id = %s::uuid),
           (SELECT count(*) FROM graph_edges WHERE tenant_id = %s::uuid),
           (SELECT coalesce(max(xmin::text::bigint), 0) FROM graph_edges WHERE tenant_id = %s::uuid)
"""


class _NodeIndex:
    def __init__(self, fingerprint: tuple, nodes: list[tuple[str, str, str]], edges: list[tuple]):
        self.fingerprint = fingerprint
        self.nodes = nodes  # (entity_type, normalized_value, value) of nodes that have an edge
        self.edges = edges  # _load_edges rows, for walks
        self.matrix: np.ndarray | None = None
        self.cache_id: int | None = None


_node_indexes: dict[str, _NodeIndex] = {}
_node_lock = threading.Lock()


def _node_index(database_url: str, tenant_id: str) -> _NodeIndex:
    # Query-time path: reuse the search's per-thread connection (a new
    # connection costs ~100 ms on Windows) and reload only on change
    with _reused_connection(database_url) as conn:
        conn.execute("SELECT set_config('app.current_tenant_id', %s, true)", [tenant_id])
        fingerprint = tuple(conn.execute(_NODE_FINGERPRINT_SQL, [tenant_id] * 4).fetchone())
        with _node_lock:
            cached = _node_indexes.get(tenant_id)
        if cached is not None and cached.fingerprint == fingerprint:
            return cached
        edges = _load_edges(conn, tenant_id)
    nodes = sorted({(r[1], r[2]) for r in edges} | {(r[4], r[5]) for r in edges})
    index = _NodeIndex(fingerprint, [(t, v, v) for t, v in nodes], edges)
    with _node_lock:
        _node_indexes[tenant_id] = index
    return index


def _node_vectors(index: _NodeIndex) -> np.ndarray | None:
    cache = semantic.get_cache()
    if cache is None or not index.nodes:
        return None
    if index.matrix is None or index.cache_id != id(cache):
        index.matrix = cache.encode([v.lower() for _, v, _ in index.nodes])
        index.cache_id = id(cache)
    return index.matrix


def known_node_values(database_url: str, tenant_id: str) -> dict[str, list[str]]:
    """The tenant's node names by type, for merging a new document's entities into them."""
    out: dict[str, list[str]] = {}
    for entity_type, value, _ in _node_index(database_url, tenant_id).nodes:
        out.setdefault(entity_type, []).append(value)
    return out


def link_phrases(
    database_url: str, tenant_id: str, phrases: list[str], threshold: float, limit: int = 5
) -> list[dict]:
    """
    Nodes whose name equals one of the phrases, or is the nearest node to a
    phrase with cosine similarity >= threshold. Best first.
    """
    index = _node_index(database_url, tenant_id)
    if not index.nodes or not phrases:
        return []
    by_value: dict[str, list[int]] = {}
    for i, (_, value, _) in enumerate(index.nodes):
        by_value.setdefault(value.lower(), []).append(i)

    scores: dict[int, float] = {}
    for phrase in phrases:
        for i in by_value.get(phrase.lower(), []):
            scores[i] = 1.0

    matrix = _node_vectors(index)
    cache = semantic.get_cache()
    if matrix is not None and cache is not None:
        sims = cache.encode([p.lower() for p in phrases]) @ matrix.T
        for row in sims:
            j = int(row.argmax())
            if row[j] >= threshold:
                scores[j] = max(scores.get(j, 0.0), float(row[j]))

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:limit]
    return [
        {
            "entity_type": index.nodes[i][0],
            "normalized_value": index.nodes[i][1],
            "score": round(s, 3),
        }
        for i, s in ranked
    ]


def search_many(
    database_url: str,
    tenant_id: str,
    starts: list[dict],
    max_hops: int = 2,
    limit: int = 30,
    schema: GraphSchema | None = None,
) -> list[dict]:
    """Walk from several linked nodes, loading the tenant's edges once."""
    if not starts:
        return []
    rows = _node_index(database_url, tenant_id).edges
    seen: set[tuple] = set()
    results: list[dict] = []
    for start in starts:
        for edge in walk(
            rows, start["normalized_value"], start["entity_type"], max_hops, limit, schema
        ):
            key = (edge["source_value"], edge["relationship"], edge["target_value"])
            if key not in seen:
                seen.add(key)
                results.append(edge)
    return results[:limit]


# ── Findings: what the documents say about each asset ─
def findings(
    database_url: str, tenant_id: str, schema: GraphSchema | None = None, limit: int = 200
) -> list[dict]:
    """
    For every subject node (an asset, by the schema's roles), the issues,
    actions and other facts linked to it, with the documents they come from
    and when the latest was uploaded. Built from the graph, so it covers
    whatever the tenant uploaded; nothing here is seeded.
    """
    schema = schema or tenant_schema(database_url, tenant_id)
    subjects = schema.subject_types
    if not subjects:
        return []
    with _connect(database_url) as conn:
        conn.execute("SELECT set_config('app.current_tenant_id', %s, true)", [tenant_id])
        rows = conn.execute(
            """
            SELECT s.entity_type, s.value, s.normalized_value,
                   t.entity_type, t.value, t.normalized_value,
                   e.relationship, max(e.confidence),
                   array_agg(DISTINCT d.title ORDER BY d.title),
                   max(d.created_at)
            FROM graph_edges e
            JOIN graph_nodes s ON s.id = e.source_id AND s.tenant_id = e.tenant_id
            JOIN graph_nodes t ON t.id = e.target_id AND t.tenant_id = e.tenant_id
            JOIN documents d ON d.id = e.document_id AND d.tenant_id = e.tenant_id
            WHERE e.tenant_id = %s::uuid AND (s.entity_type = ANY(%s) OR t.entity_type = ANY(%s))
            GROUP BY s.entity_type, s.value, s.normalized_value,
                     t.entity_type, t.value, t.normalized_value, e.relationship
            """,
            [tenant_id, list(subjects), list(subjects)],
        ).fetchall()

    roles = {name: t.role or "other" for name, t in schema.types.items()}
    labels = {name: t.label for name, t in schema.types.items()}
    by_subject: dict[tuple[str, str], dict] = {}
    for stype, sval, snorm, ttype, tval, tnorm, rel, conf, docs, last in rows:
        # Read every edge from the subject's side
        if stype in subjects:
            subject_type, subject_norm, subject_name = stype, snorm, sval
            other_type, other_value, relationship = ttype, tval, rel
        else:
            subject_type, subject_norm, subject_name = ttype, tnorm, tval
            other_type, other_value = stype, sval
            relationship = schema.inverse_names.get(rel, rel)
        entry = by_subject.setdefault(
            (subject_type, subject_norm),
            {
                "type": subject_type,
                "typeLabel": labels.get(subject_type, subject_type),
                "name": subject_name,
                "facts": [],
                "documents": set(),
                "lastSeen": None,
            },
        )
        entry["facts"].append(
            {
                "role": roles.get(other_type, "other"),
                "type": other_type,
                "typeLabel": labels.get(other_type, other_type),
                "value": other_value,
                "relationship": relationship,
                "confidence": round(float(conf or 0.0), 3),
                "documents": list(docs or []),
            }
        )
        entry["documents"].update(docs or [])
        if last and (entry["lastSeen"] is None or last > entry["lastSeen"]):
            entry["lastSeen"] = last

    order = {"issue": 0, "action": 1, "value": 2}
    out = []
    for entry in by_subject.values():
        entry["facts"].sort(key=lambda f: (order.get(f["role"], 3), f["value"].lower()))
        entry["issueCount"] = sum(1 for f in entry["facts"] if f["role"] == "issue")
        entry["actionCount"] = sum(1 for f in entry["facts"] if f["role"] == "action")
        entry["documents"] = sorted(entry["documents"])
        entry["lastSeen"] = entry["lastSeen"].isoformat() if entry["lastSeen"] else None
        out.append(entry)
    out.sort(key=lambda e: (-e["issueCount"], -len(e["facts"]), e["name"]))
    return out[:limit]
