"""
VEDA AI — Knowledge Graph Manager

Encapsulates all Apache AGE (graph database) operations for the VEDA
knowledge graph. Handles:
- Upserting entity nodes (MERGE semantics to avoid duplicates)
- Creating typed relationships between entities
- Graph traversal for context retrieval
- Periodic consolidation (merge duplicates, prune stale edges)
- Graph statistics and health monitoring

Tenant isolation:
    All tenants share one AGE graph, and PostgreSQL RLS does not apply to
    AGE's internal tables. Isolation is therefore enforced here: `tenant_id`
    is part of every node's identity (the MERGE key) and every query filters
    on it, so one tenant can never read, modify, or prune another's graph.

Injection safety:
    User-controlled values are never interpolated into Cypher. They are
    passed as an AGE parameter map (third argument of `cypher()`). Only
    values that cannot be parameterized — relationship labels and path
    lengths — are interpolated, and those are allow-listed or clamped ints.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

try:
    import psycopg
except ImportError:  # pragma: no cover - optional dependency
    psycopg = None

from .relationships import infer_relationships

logger = logging.getLogger("veda.intelligence.knowledge_graph")

GRAPH_NAME = "veda_knowledge_graph"

# Bounds for values that must be interpolated into Cypher
MAX_HOPS_LIMIT = 5
MAX_RESULTS_LIMIT = 500


@dataclass
class GraphNode:
    """A node in the knowledge graph."""

    entity_type: str
    value: str
    normalized_value: str
    document_id: Optional[str] = None
    tenant_id: Optional[str] = None
    confidence: float = 0.0
    attributes: dict = field(default_factory=dict)
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None


@dataclass
class GraphEdge:
    """An edge (relationship) in the knowledge graph."""

    source_value: str
    target_value: str
    relationship_type: str
    document_id: Optional[str] = None
    confidence: float = 0.0
    attributes: dict = field(default_factory=dict)


# ── Relationship type definitions ─────────────────────
# These define how entities connect in the industrial domain
RELATIONSHIP_TYPES = {
    # Co-occurrence relationships (entities found in same document/section)
    "MENTIONED_IN": "Entity is mentioned in a document",
    "CO_OCCURS_WITH": "Entities appear in the same document section",
    # Structural relationships
    "PART_OF": "Equipment is part of a larger system (PUMP-101 PART_OF CDU-A)",
    "LOCATED_IN": "Equipment/entity is located in a place",
    "CONNECTED_TO": "Equipment is physically connected (piping, electrical)",
    # Operational relationships
    "GOVERNED_BY": "Equipment/process is governed by a regulation",
    "MAINTAINED_BY": "Equipment maintenance action",
    "MEASURED_BY": "Parameter is measured by an instrument",
    "OPERATES_AT": "Equipment operates at a measurement value",
    "HAS_MEASUREMENT": "A value (rating, limit, or reading) stated for the equipment",
    # Failure/maintenance relationships
    "FAILED_WITH": "Equipment failed with a specific failure mode",
    "REPAIRED_BY": "Failure was repaired by a maintenance action",
    "DETECTED_BY": "Failure was found by an inspection or test",
    "TREATED_WITH": "Clinical condition was treated with a medicine",
    "CAUSED_BY": "Failure was caused by another condition",
    # Personnel relationships
    "ASSIGNED_TO": "Equipment/task is assigned to a person",
    "REPORTED_BY": "Incident/failure was reported by a person",
    # Material relationships
    "MADE_OF": "Equipment is made of a specific material",
    "USES_CHEMICAL": "Process uses a specific chemical",
}


# ── Cypher helpers ────────────────────────────────────


def cypher_sql(query: str, columns: str) -> str:
    """
    Wrap a static Cypher query in the AGE `cypher()` SQL call.

    The query receives its values through the `$name` parameters of the
    agtype map bound to `%s`. `query` must be a static string — never
    build it from user input.
    """
    if "$$" in query or "%" in query:
        raise ValueError("Cypher query text must not contain '$$' or '%'")
    return f"SELECT * FROM cypher('{GRAPH_NAME}', $$ {query} $$, %s::agtype) AS ({columns});"


async def run_cypher(conn, query: str, columns: str, params: dict[str, Any]):
    """Execute a parameterized Cypher query and return the cursor."""
    return await conn.execute(cypher_sql(query, columns), [json.dumps(params)])


def _clamp_int(value: Any, low: int, high: int, default: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def _agtype_str(value: Any) -> str:
    return str(value).strip('"')


class KnowledgeGraphManager:
    """
    Manages the Apache AGE knowledge graph for VEDA AI.

    Key design decisions:
    - Uses MERGE (not CREATE) keyed on (tenant_id, normalized_value, entity_type)
    - Maintains timestamps (first_seen, last_seen) for temporal awareness
    - Supports multi-hop traversal for deep context retrieval
    - Every query is filtered by tenant_id (see module docstring)
    """

    def __init__(self, database_url: str):
        self.database_url = database_url

    async def _get_connection(self):
        """Create a new async connection with AGE loaded."""
        if psycopg is None:
            raise RuntimeError("psycopg is not installed. Install service dependencies first.")
        conn = await psycopg.AsyncConnection.connect(self.database_url)
        await conn.execute("LOAD 'age'")
        await conn.execute("SET search_path = ag_catalog, '$user', public")
        return conn

    async def _set_tenant(self, conn, tenant_id: str):
        """Set the tenant context for RLS on relational tables."""
        await conn.execute("SELECT set_config('app.current_tenant_id', %s, true)", [tenant_id])

    async def _run_write(self, conn, query: str, columns: str, params: dict, commit: bool) -> bool:
        """
        Run a write query.

        With commit=True the statement owns the transaction (commit/rollback).
        With commit=False it runs inside a savepoint, so one failed statement
        does not abort the caller's surrounding batch transaction.
        """
        if not commit:
            await conn.execute("SAVEPOINT graph_write")
        try:
            await run_cypher(conn, query, columns, params)
        except Exception:
            if commit:
                await conn.rollback()
            else:
                await conn.execute("ROLLBACK TO SAVEPOINT graph_write")
            raise
        if commit:
            await conn.commit()
        else:
            await conn.execute("RELEASE SAVEPOINT graph_write")
        return True

    # ── Node Operations ───────────────────────────────

    async def upsert_entity_node(
        self,
        tenant_id: str,
        entity_type: str,
        value: str,
        normalized_value: str,
        document_id: str,
        confidence: float = 0.0,
        attributes: dict | None = None,
        conn=None,
    ) -> bool:
        """
        Upsert an entity node in the knowledge graph.

        If the node exists for this tenant, updates last_seen and the
        mention count; otherwise creates it with first_seen = now.

        Returns True if the operation succeeded.
        """
        if conn is None:
            async with await self._get_connection() as local_conn:
                await self._set_tenant(local_conn, tenant_id)
                return await self._upsert_entity_node_impl(
                    local_conn,
                    tenant_id,
                    entity_type,
                    value,
                    normalized_value,
                    document_id,
                    confidence,
                    attributes,
                    commit=True,
                )
        return await self._upsert_entity_node_impl(
            conn,
            tenant_id,
            entity_type,
            value,
            normalized_value,
            document_id,
            confidence,
            attributes,
            commit=False,
        )

    async def _upsert_entity_node_impl(
        self,
        conn,
        tenant_id: str,
        entity_type: str,
        value: str,
        normalized_value: str,
        document_id: str,
        confidence: float,
        attributes: dict | None,
        commit: bool,
    ) -> bool:
        query = """
            MERGE (n:Entity {tenant_id: $tenant_id, normalized_value: $normalized_value,
                             entity_type: $entity_type})
            ON CREATE SET
                n.value = $value,
                n.document_id = $document_id,
                n.confidence = $confidence,
                n.first_seen = $now,
                n.last_seen = $now,
                n.mention_count = 1
            ON MATCH SET
                n.last_seen = $now,
                n.mention_count = coalesce(n.mention_count, 0) + 1,
                n.confidence = CASE
                    WHEN $confidence > n.confidence THEN $confidence
                    ELSE n.confidence
                END
            RETURN n
        """
        params = {
            "tenant_id": tenant_id,
            "normalized_value": normalized_value,
            "entity_type": entity_type,
            "value": value,
            "document_id": document_id,
            "confidence": float(confidence),
            "now": datetime.now(timezone.utc).isoformat(),
        }
        try:
            return await self._run_write(conn, query, "node agtype", params, commit)
        except Exception as e:
            logger.error(f"Failed to upsert node '{normalized_value}': {e}")
            return False

    async def create_relationship(
        self,
        tenant_id: str,
        source_value: str,
        source_type: str,
        target_value: str,
        target_type: str,
        relationship_type: str,
        document_id: str,
        confidence: float = 0.0,
        attributes: dict | None = None,
        conn=None,
    ) -> bool:
        """
        Create a relationship (edge) between two entity nodes of the same tenant.

        Uses MERGE to avoid duplicate edges between the same nodes.
        Updates the edge's last_seen timestamp on re-encounter.
        """
        if relationship_type not in RELATIONSHIP_TYPES:
            logger.warning(
                f"Unknown relationship type '{relationship_type}', "
                f"valid types: {list(RELATIONSHIP_TYPES.keys())}"
            )
            return False

        if conn is None:
            async with await self._get_connection() as local_conn:
                await self._set_tenant(local_conn, tenant_id)
                return await self._create_relationship_impl(
                    local_conn,
                    tenant_id,
                    source_value,
                    source_type,
                    target_value,
                    target_type,
                    relationship_type,
                    document_id,
                    confidence,
                    attributes,
                    commit=True,
                )
        return await self._create_relationship_impl(
            conn,
            tenant_id,
            source_value,
            source_type,
            target_value,
            target_type,
            relationship_type,
            document_id,
            confidence,
            attributes,
            commit=False,
        )

    async def _create_relationship_impl(
        self,
        conn,
        tenant_id: str,
        source_value: str,
        source_type: str,
        target_value: str,
        target_type: str,
        relationship_type: str,
        document_id: str,
        confidence: float,
        attributes: dict | None,
        commit: bool,
    ) -> bool:
        # Labels cannot be parameterized; re-check the allow-list here too
        if relationship_type not in RELATIONSHIP_TYPES:
            logger.warning(f"Rejected unknown relationship type '{relationship_type}'")
            return False

        query = f"""
            MATCH (a:Entity {{tenant_id: $tenant_id, normalized_value: $source_value,
                              entity_type: $source_type}})
            MATCH (b:Entity {{tenant_id: $tenant_id, normalized_value: $target_value,
                              entity_type: $target_type}})
            MERGE (a)-[r:{relationship_type}]->(b)
            ON CREATE SET
                r.tenant_id = $tenant_id,
                r.document_id = $document_id,
                r.confidence = $confidence,
                r.first_seen = $now,
                r.last_seen = $now,
                r.mention_count = 1
            ON MATCH SET
                r.last_seen = $now,
                r.mention_count = coalesce(r.mention_count, 0) + 1
            RETURN r
        """
        params = {
            "tenant_id": tenant_id,
            "source_value": source_value,
            "source_type": source_type,
            "target_value": target_value,
            "target_type": target_type,
            "document_id": document_id,
            "confidence": float(confidence),
            "now": datetime.now(timezone.utc).isoformat(),
        }
        try:
            return await self._run_write(conn, query, "rel agtype", params, commit)
        except Exception as e:
            logger.error(
                f"Failed to create relationship "
                f"'{source_value}' -[{relationship_type}]-> '{target_value}': {e}"
            )
            return False

    async def get_entity_context(
        self,
        tenant_id: str,
        entity_value: str,
        entity_type: str | None = None,
        max_hops: int = 3,
        limit: int = 50,
        conn=None,
    ) -> list[dict]:
        """
        Traverse the tenant's knowledge graph starting from an entity node.

        Returns connected entities sorted by distance (closer = more relevant):
        [
            {
                "source_type": "EQUIPMENT_TAG",
                "source_value": "PUMP-101",
                "target_type": "EQUIPMENT_TAG",
                "target_value": "CDU-A",
                "document_id": "...",
                "distance": 1,
                "confidence": 0.95,
            },
            ...
        ]
        """
        if conn is None:
            async with await self._get_connection() as local_conn:
                await self._set_tenant(local_conn, tenant_id)
                return await self._get_entity_context_impl(
                    local_conn, tenant_id, entity_value, entity_type, max_hops, limit
                )
        return await self._get_entity_context_impl(
            conn, tenant_id, entity_value, entity_type, max_hops, limit
        )

    async def _get_entity_context_impl(
        self,
        conn,
        tenant_id: str,
        entity_value: str,
        entity_type: str | None,
        max_hops: int,
        limit: int,
    ) -> list[dict]:
        hops = _clamp_int(max_hops, 1, MAX_HOPS_LIMIT, 3)
        row_limit = _clamp_int(limit, 1, MAX_RESULTS_LIMIT, 50)
        params: dict[str, Any] = {"tenant_id": tenant_id, "entity_value": entity_value}

        type_filter = ""
        if entity_type:
            type_filter = " AND n.entity_type = $entity_type"
            params["entity_type"] = entity_type

        query = f"""
            MATCH path = (n:Entity)-[*1..{hops}]-(related:Entity)
            WHERE n.tenant_id = $tenant_id
              AND n.normalized_value = $entity_value{type_filter}
              AND related.tenant_id = $tenant_id
            RETURN
                n.entity_type AS source_type,
                n.normalized_value AS source_value,
                related.entity_type AS related_type,
                related.normalized_value AS related_value,
                related.document_id AS doc_id,
                related.confidence AS confidence,
                length(path) AS distance
            ORDER BY length(path) ASC
            LIMIT {row_limit}
        """
        columns = (
            "source_type agtype, source_value agtype, related_type agtype, "
            "related_value agtype, doc_id agtype, confidence agtype, distance agtype"
        )

        results = []
        try:
            rows = await run_cypher(conn, query, columns, params)
            async for row in rows:
                results.append(
                    {
                        "source_type": _agtype_str(row[0]),
                        "source_value": _agtype_str(row[1]),
                        "target_type": _agtype_str(row[2]),
                        "target_value": _agtype_str(row[3]),
                        "document_id": _agtype_str(row[4]) if row[4] else None,
                        "confidence": float(str(row[5])) if row[5] else 0.0,
                        "distance": int(str(row[6])),
                    }
                )
        except Exception as e:
            logger.warning(f"Graph traversal failed for '{entity_value}': {e}")

        return results

    # ── Consolidation & Maintenance ───────────────────

    async def merge_duplicate_entities(self, tenant_id: str) -> int:
        """
        Merge duplicate entity nodes of this tenant that share the same
        (normalized_value, entity_type) — possible when concurrent workers
        race on MERGE.

        Keeps the node with the most mentions, re-points every edge of each
        duplicate to the keeper, then deletes the duplicate.

        Returns the number of duplicate nodes removed.
        """
        merged_count = 0

        async with await self._get_connection() as conn:
            await self._set_tenant(conn, tenant_id)

            try:
                groups_query = """
                    MATCH (n:Entity)
                    WHERE n.tenant_id = $tenant_id
                    WITH n.normalized_value AS nv, n.entity_type AS et,
                         collect(id(n)) AS ids, count(n) AS cnt
                    WHERE cnt > 1
                    RETURN nv, et, ids
                """
                rows = await run_cypher(
                    conn,
                    groups_query,
                    "nv agtype, et agtype, ids agtype",
                    {"tenant_id": tenant_id},
                )
                groups = [(_agtype_str(r[0]), _agtype_str(r[1])) async for r in rows]

                for nv, et in groups:
                    merged_count += await self._merge_group(conn, tenant_id, nv, et)

                await conn.commit()

            except Exception as e:
                logger.error(f"Duplicate merge failed: {e}")
                await conn.rollback()
                return 0

        logger.info(f"Merged {merged_count} duplicate entities for tenant {tenant_id}")
        return merged_count

    async def _merge_group(self, conn, tenant_id: str, nv: str, et: str) -> int:
        """Merge one group of duplicate nodes into its most-mentioned node."""
        base = {"tenant_id": tenant_id, "nv": nv, "et": et}
        ids_query = """
            MATCH (n:Entity {tenant_id: $tenant_id, normalized_value: $nv, entity_type: $et})
            RETURN id(n)
            ORDER BY coalesce(n.mention_count, 0) DESC
        """
        rows = await run_cypher(conn, ids_query, "id agtype", base)
        node_ids = [int(str(r[0])) async for r in rows]
        if len(node_ids) < 2:
            return 0

        keeper_id, duplicate_ids = node_ids[0], node_ids[1:]
        for dup_id in duplicate_ids:
            params = {**base, "keep_id": keeper_id, "dup_id": dup_id}
            for rel_type in RELATIONSHIP_TYPES:
                for pattern in (
                    f"(dup)-[r:{rel_type}]->(other)",
                    f"(dup)<-[r:{rel_type}]-(other)",
                ):
                    target = (
                        f"(keep)-[nr:{rel_type}]->(other)"
                        if "->" in pattern
                        else f"(keep)<-[nr:{rel_type}]-(other)"
                    )
                    repoint_query = f"""
                        MATCH (keep:Entity), (dup:Entity)
                        WHERE id(keep) = $keep_id AND id(dup) = $dup_id
                          AND keep.tenant_id = $tenant_id AND dup.tenant_id = $tenant_id
                        MATCH {pattern}
                        WHERE id(other) <> $keep_id
                        MERGE {target}
                        SET nr.tenant_id = $tenant_id,
                            nr.document_id = r.document_id,
                            nr.confidence = r.confidence,
                            nr.last_seen = r.last_seen
                        RETURN count(nr)
                    """
                    await run_cypher(conn, repoint_query, "cnt agtype", params)

            delete_query = """
                MATCH (dup:Entity)
                WHERE id(dup) = $dup_id AND dup.tenant_id = $tenant_id
                DETACH DELETE dup
            """
            await run_cypher(conn, delete_query, "result agtype", params)

        return len(duplicate_ids)

    async def prune_stale_relationships(self, tenant_id: str, max_age_days: int = 365) -> int:
        """
        Remove this tenant's relationships not seen in max_age_days.

        Returns the number of pruned edges.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()

        async with await self._get_connection() as conn:
            await self._set_tenant(conn, tenant_id)

            try:
                query = """
                    MATCH (a:Entity)-[r]->(b:Entity)
                    WHERE a.tenant_id = $tenant_id AND b.tenant_id = $tenant_id
                      AND r.last_seen < $cutoff
                    DELETE r
                    RETURN count(r) AS pruned
                """
                result = await run_cypher(
                    conn, query, "pruned agtype", {"tenant_id": tenant_id, "cutoff": cutoff}
                )
                row = await result.fetchone()
                pruned = int(str(row[0])) if row else 0
                await conn.commit()

                logger.info(
                    f"Pruned {pruned} stale relationships (older than {max_age_days} days) "
                    f"for tenant {tenant_id}"
                )
                return pruned

            except Exception as e:
                logger.error(f"Stale relationship pruning failed: {e}")
                await conn.rollback()
                return 0

    # ── Statistics & Monitoring ───────────────────────

    async def get_graph_stats(self, tenant_id: str) -> dict:
        """
        Get this tenant's knowledge graph statistics.

        Returns node count, edge count, entity type distribution,
        and last update timestamp.
        """
        stats = {
            "total_nodes": 0,
            "total_edges": 0,
            "entity_types": {},
            "relationship_types": {},
            "last_updated": None,
        }
        params = {"tenant_id": tenant_id}

        async with await self._get_connection() as conn:
            await self._set_tenant(conn, tenant_id)

            try:
                node_query = """
                    MATCH (n:Entity)
                    WHERE n.tenant_id = $tenant_id
                    RETURN n.entity_type AS entity_type, count(n) AS cnt
                """
                rows = await run_cypher(conn, node_query, "entity_type agtype, cnt agtype", params)
                async for row in rows:
                    count = int(str(row[1]))
                    stats["entity_types"][_agtype_str(row[0])] = count
                    stats["total_nodes"] += count

                edge_query = """
                    MATCH (a:Entity)-[r]->(b:Entity)
                    WHERE a.tenant_id = $tenant_id AND b.tenant_id = $tenant_id
                    RETURN type(r) AS rel_type, count(r) AS cnt
                """
                rows = await run_cypher(conn, edge_query, "rel_type agtype, cnt agtype", params)
                async for row in rows:
                    count = int(str(row[1]))
                    stats["relationship_types"][_agtype_str(row[0])] = count
                    stats["total_edges"] += count

                last_query = """
                    MATCH (n:Entity)
                    WHERE n.tenant_id = $tenant_id
                    RETURN max(n.last_seen) AS last_seen
                """
                result = await run_cypher(conn, last_query, "last_seen agtype", params)
                row = await result.fetchone()
                if row and row[0]:
                    stats["last_updated"] = _agtype_str(row[0])

            except Exception as e:
                logger.error(f"Failed to get graph stats: {e}")

        return stats

    async def upsert_entities_batch(
        self,
        tenant_id: str,
        document_id: str,
        entities: list[dict],
    ) -> int:
        """
        Batch upsert multiple entity nodes from a single document.

        This is the primary method called by the graph worker during
        document processing. Each upsert runs in its own savepoint, so a
        single bad entity doesn't discard the rest of the batch.

        Returns the number of successfully upserted nodes.
        """
        success_count = 0

        async with await self._get_connection() as conn:
            await self._set_tenant(conn, tenant_id)
            for entity in entities:
                result = await self.upsert_entity_node(
                    tenant_id=tenant_id,
                    entity_type=entity["entity_type"],
                    value=entity["value"],
                    normalized_value=entity["normalized_value"],
                    document_id=document_id,
                    confidence=entity.get("confidence", 0.0),
                    attributes=entity.get("attributes"),
                    conn=conn,
                )
                if result:
                    success_count += 1
            await conn.commit()

        logger.info(
            f"Batch upserted {success_count}/{len(entities)} entities for document {document_id}"
        )
        return success_count

    async def build_document_relationships(
        self,
        tenant_id: str,
        document_id: str,
        entities: list[dict],
        text: str | None = None,
    ) -> int:
        """
        Build relationships between entities extracted from the same document.

        With `text`, only entities in the same sentence or record are linked
        (see relationships.py); without it the whole document is one segment.
        Relationship types come from relationships.INFERENCE_RULES.

        Returns the number of relationships created.
        """
        edge_count = 0

        async with await self._get_connection() as conn:
            await self._set_tenant(conn, tenant_id)
            for edge in infer_relationships(entities, text):
                result = await self.create_relationship(
                    tenant_id=tenant_id,
                    source_value=edge.source["normalized_value"],
                    source_type=edge.source["entity_type"],
                    target_value=edge.target["normalized_value"],
                    target_type=edge.target["entity_type"],
                    relationship_type=edge.relationship_type,
                    document_id=document_id,
                    confidence=edge.confidence,
                    conn=conn,
                )
                if result:
                    edge_count += 1
            await conn.commit()

        logger.info(
            f"Built {edge_count} relationships from {len(entities)} entities "
            f"for document {document_id}"
        )
        return edge_count

    async def store_entities_in_db(
        self,
        tenant_id: str,
        document_id: str,
        entities: list[dict],
    ) -> int:
        """
        Persist extracted entities to the relational entities table
        (in addition to the graph). This provides fast SQL queries
        for entity lookups and analytics.
        """
        stored = 0

        async with await psycopg.AsyncConnection.connect(self.database_url) as conn:
            await self._set_tenant(conn, tenant_id)

            for entity in entities:
                try:
                    await conn.execute("SAVEPOINT entity_insert")
                    await conn.execute(
                        """
                        INSERT INTO entities (
                            tenant_id, document_id, entity_type, entity_value,
                            normalized_value, page_number, start_offset, end_offset,
                            confidence, attributes
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                        ON CONFLICT DO NOTHING
                        """,
                        [
                            tenant_id,
                            document_id,
                            entity["entity_type"],
                            entity["value"],
                            entity["normalized_value"],
                            entity.get("page_number"),
                            entity.get("start_offset"),
                            entity.get("end_offset"),
                            entity.get("confidence", 0.0),
                            json.dumps(entity.get("attributes") or {}),
                        ],
                    )
                    await conn.execute("RELEASE SAVEPOINT entity_insert")
                    stored += 1
                except Exception as e:
                    await conn.execute("ROLLBACK TO SAVEPOINT entity_insert")
                    logger.warning(f"Failed to store entity '{entity['value']}': {e}")

            await conn.commit()

        return stored
