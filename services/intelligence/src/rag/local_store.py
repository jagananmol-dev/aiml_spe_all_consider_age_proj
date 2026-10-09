"""
VEDA AI — Local chunk store (no pgvector)

Used when VEDA_VECTOR_BACKEND=local, e.g. a Windows dev/demo machine whose
PostgreSQL has no pgvector extension. Chunks and their embeddings live in
the `document_chunks` table (REAL[] column) and similarity is computed here
with numpy. That is linear in the number of chunks per tenant, which is fine
for demos and small tenants; production uses pgvector's HNSW index.

All functions are synchronous (psycopg sync API) so callers run them in a
worker thread. This also sidesteps psycopg's async mode, which does not work
with the ProactorEventLoop uvicorn uses on Windows.

Every query filters on tenant_id explicitly.
"""

import json
import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass

import numpy as np

try:
    import psycopg
except ImportError:  # pragma: no cover - optional dependency
    psycopg = None  # type: ignore[assignment]

logger = logging.getLogger("veda.intelligence.local_store")


class DocumentNotFoundError(Exception):
    """The document doesn't exist or belongs to another tenant."""


@dataclass
class StoredChunk:
    text: str
    embedding: list[float]
    metadata: dict


def _connect(database_url: str):
    if psycopg is None:
        raise RuntimeError("psycopg is not installed. Install service dependencies first.")
    return psycopg.connect(database_url, connect_timeout=5)


# Opening a PostgreSQL connection costs ~100 ms (on Windows), far more than a
# search, so searches reuse one connection per worker thread. A connection
# that fails is dropped and the next search opens a new one.
_thread_conns = threading.local()
_generation = 0


@contextmanager
def _reused_connection(database_url: str):
    conns = getattr(_thread_conns, "by_url", None)
    if conns is None:
        conns = _thread_conns.by_url = {}
    generation, conn = conns.get(database_url, (None, None))
    if conn is None or generation != _generation or getattr(conn, "closed", False) is True:
        conn = _connect(database_url)
        conns[database_url] = (_generation, conn)
    try:
        yield conn
        conn.commit()  # end the read transaction (set_config is transaction-local)
    except Exception:
        conns.pop(database_url, None)
        try:
            conn.close()
        except Exception:
            pass
        raise


def replace_document_chunks(
    database_url: str,
    tenant_id: str,
    document_id: str,
    chunks: list[StoredChunk],
) -> int:
    """
    Atomically replace a document's chunks and mark it indexed.

    Raises DocumentNotFoundError if the document isn't this tenant's.
    Returns the number of chunks stored.
    """
    with _connect(database_url) as conn:
        conn.execute("SELECT set_config('app.current_tenant_id', %s, true)", [tenant_id])

        owned = conn.execute(
            "SELECT id FROM documents WHERE id = %s::uuid AND tenant_id = %s::uuid FOR UPDATE",
            [document_id, tenant_id],
        ).fetchone()
        if owned is None:
            raise DocumentNotFoundError(document_id)

        conn.execute(
            "DELETE FROM document_chunks WHERE tenant_id = %s::uuid AND document_id = %s::uuid",
            [tenant_id, document_id],
        )
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO document_chunks
                    (tenant_id, document_id, chunk_index, chunk_text, embedding, metadata)
                VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s::jsonb)
                """,
                [
                    (
                        tenant_id,
                        document_id,
                        index,
                        chunk.text,
                        [float(x) for x in chunk.embedding],
                        json.dumps(chunk.metadata),
                    )
                    for index, chunk in enumerate(chunks)
                ],
            )

        conn.execute(
            """
            UPDATE documents
            SET status = 'indexed',
                extraction_status = 'completed',
                embedding_status = 'completed',
                metadata = COALESCE(metadata, '{}'::jsonb) - 'error',
                updated_at = NOW()
            WHERE id = %s::uuid AND tenant_id = %s::uuid
            """,
            [document_id, tenant_id],
        )

    return len(chunks)


# ── In-memory search index ────────────────────────────
# Decoding every REAL[] embedding from PostgreSQL on each query cost
# 0.3–1.4 s. Each tenant's vectors are kept in memory as a numpy matrix and
# reloaded only when the cheap fingerprint below changes (any insert, update,
# or delete of the tenant's chunks or documents changes a row's xmin or the
# counts).
_FINGERPRINT_SQL = """
    SELECT (SELECT count(*) FROM document_chunks WHERE tenant_id = %s::uuid),
           (SELECT coalesce(max(xmin::text::bigint), 0) FROM document_chunks WHERE tenant_id = %s::uuid),
           (SELECT count(*) FROM documents WHERE tenant_id = %s::uuid AND status = 'indexed'),
           (SELECT coalesce(max(xmin::text::bigint), 0) FROM documents WHERE tenant_id = %s::uuid)
"""


@dataclass
class _TenantIndex:
    fingerprint: tuple
    rows: list[tuple]  # (document_id, chunk_text, metadata, title)
    matrices: dict[int, tuple[np.ndarray, np.ndarray]]  # dimension → (row indices, vectors)
    documents: int


_INDEX: dict[str, _TenantIndex] = {}


def clear_cache() -> None:
    """Forget cached vectors and reused connections (tests, or after a schema change)."""
    global _generation
    _INDEX.clear()
    _generation += 1


def _tenant_index(conn, tenant_id: str) -> _TenantIndex:
    fingerprint = tuple(conn.execute(_FINGERPRINT_SQL, [tenant_id] * 4).fetchone())
    cached = _INDEX.get(tenant_id)
    if cached is not None and cached.fingerprint == fingerprint:
        return cached

    raw = conn.execute(
        """
        SELECT dc.document_id::text, dc.chunk_text, dc.metadata, dc.embedding, d.title
        FROM document_chunks dc
        JOIN documents d ON d.id = dc.document_id AND d.tenant_id = dc.tenant_id
        WHERE dc.tenant_id = %s::uuid AND d.status = 'indexed'
        """,
        [tenant_id],
    ).fetchall()

    by_dim: dict[int, list[int]] = {}
    for i, row in enumerate(raw):
        by_dim.setdefault(len(row[3]), []).append(i)
    matrices = {
        dim: (np.asarray(idx), np.asarray([raw[i][3] for i in idx], dtype=np.float32))
        for dim, idx in by_dim.items()
    }
    index = _TenantIndex(
        fingerprint=fingerprint,
        rows=[(r[0], r[1], r[2], r[4]) for r in raw],
        matrices=matrices,
        documents=len({r[0] for r in raw}),
    )
    _INDEX[tenant_id] = index
    return index


def preload_all(database_url: str) -> int:
    """
    Build the in-memory index of every tenant that has passages, so the
    first question after start-up does not wait for it. Returns the number
    of tenants loaded.
    """
    with _reused_connection(database_url) as conn:
        tenants = [
            r[0]
            for r in conn.execute("SELECT DISTINCT tenant_id::text FROM document_chunks").fetchall()
        ]
        for tenant_id in tenants:
            conn.execute("SELECT set_config('app.current_tenant_id', %s, true)", [tenant_id])
            _tenant_index(conn, tenant_id)
    return len(tenants)


def search_chunks_with_stats(
    database_url: str,
    tenant_id: str,
    query_embedding: list[float],
    top_k: int,
    min_score: float = 0.0,
    fallback_k: int = 0,
    boost: dict[str, set[str]] | None = None,
    boost_amount: float = 0.0,
) -> tuple[list[dict], dict]:
    """
    Return this tenant's top_k most similar chunks from indexed documents,
    ignoring chunks whose similarity is below min_score, plus search stats
    ({"chunks_searched", "documents_searched"}).

    Embeddings are stored L2-normalised, so the dot product is the cosine
    similarity. Each result: document_id, chunk_text, metadata (with title),
    and score.

    `boost` ({document_id: entity names}, from the knowledge graph) raises
    by boost_amount the chunks of those documents that name one of the
    entities, so passages about the entities in the question rank higher.
    """
    with _reused_connection(database_url) as conn:
        conn.execute("SELECT set_config('app.current_tenant_id', %s, true)", [tenant_id])
        index = _tenant_index(conn, tenant_id)

    query = np.asarray(query_embedding, dtype=np.float32)
    row_ids, matrix = index.matrices.get(len(query), (np.asarray([]), None))
    stats = {"chunks_searched": len(row_ids), "documents_searched": index.documents}
    if matrix is None or len(row_ids) == 0:
        return [], stats

    scores = matrix @ query
    if boost and boost_amount:
        boosted = 0
        for j, row_id in enumerate(row_ids):
            document_id, text = index.rows[row_id][0], index.rows[row_id][1]
            terms = boost.get(document_id)
            if terms:
                lowered = text.lower()
                if any(term in lowered for term in terms):
                    scores[j] += boost_amount
                    boosted += 1
        stats["graph_boosted_chunks"] = boosted
    k = min(top_k, len(row_ids))
    best = np.argpartition(-scores, k - 1)[:k]
    best = best[np.argsort(-scores[best])]

    # Nothing clears the cut-off: still return the closest few (when asked),
    # flagged as a weak match, so the answer can use or rule them out
    low_confidence = fallback_k > 0 and not (scores[best] >= min_score).any()
    stats["low_confidence"] = bool(low_confidence)
    if low_confidence:
        best = best[:fallback_k]

    results = []
    for i in best:
        if scores[i] < min_score and not low_confidence:
            continue
        document_id, text, metadata, title = index.rows[row_ids[i]]
        metadata = dict(metadata or {})
        metadata.setdefault("title", title)
        results.append(
            {
                "document_id": document_id,
                "chunk_text": text,
                "metadata": metadata,
                "score": float(scores[i]),
            }
        )
    return results, stats


def search_chunks(
    database_url: str,
    tenant_id: str,
    query_embedding: list[float],
    top_k: int,
    min_score: float = 0.0,
) -> list[dict]:
    """search_chunks_with_stats without the stats."""
    return search_chunks_with_stats(database_url, tenant_id, query_embedding, top_k, min_score)[0]
