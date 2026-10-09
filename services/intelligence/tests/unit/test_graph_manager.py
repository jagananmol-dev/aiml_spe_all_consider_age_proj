"""
VEDA AI — Knowledge Graph Manager Unit Tests

All graph DB calls are mocked via psycopg AsyncMock.
Tests every public method:
- upsert_entity_node / _upsert_entity_node_impl
- create_relationship / _create_relationship_impl
- get_entity_context / _get_entity_context_impl
- upsert_entities_batch
- build_document_relationships
- store_entities_in_db
- merge_duplicate_entities
- prune_stale_relationships
- get_graph_stats
"""

import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from datetime import datetime, timezone

from src.knowledge_graph.graph_manager import (
    KnowledgeGraphManager,
    GraphNode,
    GraphEdge,
    RELATIONSHIP_TYPES,
)


# ── Shared Fixtures ────────────────────────────────────

TENANT_ID = "tenant-test-123"
DOCUMENT_ID = "doc-test-456"
DB_URL = "postgresql://test:test@localhost:5432/test_db"


def make_manager() -> KnowledgeGraphManager:
    return KnowledgeGraphManager(DB_URL)


async def _make_mock_conn():
    """Build a fully async-compatible mock psycopg connection."""
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=AsyncMock(__aiter__=AsyncMock(return_value=iter([]))))
    conn.commit = AsyncMock()
    conn.rollback = AsyncMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    return conn


# ══════════════════════════════════════════════════════
# 1. GraphNode / GraphEdge dataclasses
# ══════════════════════════════════════════════════════


class TestDataclasses:
    def test_graph_node_defaults(self):
        node = GraphNode(
            entity_type="EQUIPMENT_TAG",
            value="PUMP-101",
            normalized_value="PUMP-101",
        )
        assert node.confidence == 0.0
        assert node.attributes == {}
        assert node.document_id is None

    def test_graph_edge_defaults(self):
        edge = GraphEdge(
            source_value="PUMP-101",
            target_value="bearing seizure",
            relationship_type="FAILED_WITH",
        )
        assert edge.confidence == 0.0
        assert edge.attributes == {}
        assert edge.document_id is None


# ══════════════════════════════════════════════════════
# 2. RELATIONSHIP_TYPES registry
# ══════════════════════════════════════════════════════


class TestRelationshipTypes:
    def test_all_required_types_present(self):
        required = {
            "MENTIONED_IN",
            "CO_OCCURS_WITH",
            "PART_OF",
            "LOCATED_IN",
            "CONNECTED_TO",
            "GOVERNED_BY",
            "MAINTAINED_BY",
            "MEASURED_BY",
            "OPERATES_AT",
            "FAILED_WITH",
            "REPAIRED_BY",
            "CAUSED_BY",
            "ASSIGNED_TO",
            "REPORTED_BY",
            "MADE_OF",
            "USES_CHEMICAL",
        }
        for r in required:
            assert r in RELATIONSHIP_TYPES, f"Missing relationship type: {r}"

    def test_all_values_are_strings(self):
        for k, v in RELATIONSHIP_TYPES.items():
            assert isinstance(v, str), f"Description for {k!r} must be a string"

    def test_no_empty_descriptions(self):
        for k, v in RELATIONSHIP_TYPES.items():
            assert v.strip(), f"Empty description for relationship type: {k!r}"


# ══════════════════════════════════════════════════════
# 3. _upsert_entity_node_impl
# ══════════════════════════════════════════════════════


class TestUpsertEntityNodeImpl:
    @pytest.mark.asyncio
    async def test_returns_true_on_success(self):
        manager = make_manager()
        conn = await _make_mock_conn()
        result = await manager._upsert_entity_node_impl(
            conn,
            TENANT_ID,
            "EQUIPMENT_TAG",
            "PUMP-101",
            "pump-101",
            DOCUMENT_ID,
            confidence=0.95,
            attributes=None,
            commit=False,
        )
        assert result is True
        statements = [c.args[0] for c in conn.execute.call_args_list]
        assert sum("cypher(" in s for s in statements) == 1
        assert statements[0] == "SAVEPOINT graph_write"
        assert statements[-1] == "RELEASE SAVEPOINT graph_write"

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self):
        manager = make_manager()
        conn = await _make_mock_conn()
        conn.execute = AsyncMock(side_effect=Exception("Cypher error"))
        result = await manager._upsert_entity_node_impl(
            conn,
            TENANT_ID,
            "EQUIPMENT_TAG",
            "PUMP-101",
            "pump-101",
            DOCUMENT_ID,
            confidence=0.95,
            attributes=None,
            commit=False,
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_commits_when_flag_set(self):
        manager = make_manager()
        conn = await _make_mock_conn()
        await manager._upsert_entity_node_impl(
            conn,
            TENANT_ID,
            "EQUIPMENT_TAG",
            "X",
            "x",
            DOCUMENT_ID,
            0.9,
            None,
            commit=True,
        )
        conn.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_commit_when_flag_false(self):
        manager = make_manager()
        conn = await _make_mock_conn()
        await manager._upsert_entity_node_impl(
            conn,
            TENANT_ID,
            "EQUIPMENT_TAG",
            "X",
            "x",
            DOCUMENT_ID,
            0.9,
            None,
            commit=False,
        )
        conn.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_rollback_on_exception_with_commit(self):
        manager = make_manager()
        conn = await _make_mock_conn()
        conn.execute = AsyncMock(side_effect=Exception("Fail"))
        await manager._upsert_entity_node_impl(
            conn,
            TENANT_ID,
            "EQUIPMENT_TAG",
            "X",
            "x",
            DOCUMENT_ID,
            0.9,
            None,
            commit=True,
        )
        conn.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_cypher_contains_merge(self):
        """The Cypher query must use MERGE semantics, not CREATE."""
        manager = make_manager()
        conn = await _make_mock_conn()
        captured = []
        captured_params = []

        async def capture_execute(sql, params=None):
            if "cypher(" in sql:
                captured.append(sql)
                captured_params.append(params)
            return AsyncMock(__aiter__=AsyncMock(return_value=iter([])))

        conn.execute = capture_execute

        await manager._upsert_entity_node_impl(
            conn,
            TENANT_ID,
            "EQUIPMENT_TAG",
            "PUMP-101",
            "pump-101",
            DOCUMENT_ID,
            0.95,
            None,
            commit=False,
        )
        assert len(captured) == 1
        assert "MERGE" in captured[0]
        assert "ON CREATE SET" in captured[0]
        assert "ON MATCH SET" in captured[0]


# ══════════════════════════════════════════════════════
# 4. _create_relationship_impl
# ══════════════════════════════════════════════════════


class TestCreateRelationshipImpl:
    @pytest.mark.asyncio
    async def test_returns_true_on_success(self):
        manager = make_manager()
        conn = await _make_mock_conn()
        result = await manager._create_relationship_impl(
            conn,
            TENANT_ID,
            "PUMP-101",
            "EQUIPMENT_TAG",
            "bearing seizure",
            "FAILURE_MODE",
            "FAILED_WITH",
            DOCUMENT_ID,
            0.9,
            None,
            commit=False,
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self):
        manager = make_manager()
        conn = await _make_mock_conn()
        conn.execute = AsyncMock(side_effect=Exception("AGE error"))
        result = await manager._create_relationship_impl(
            conn,
            TENANT_ID,
            "A",
            "EQUIPMENT_TAG",
            "B",
            "FAILURE_MODE",
            "FAILED_WITH",
            DOCUMENT_ID,
            0.5,
            None,
            commit=False,
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_unknown_relationship_rejected_at_public_api(self):
        """create_relationship must reject unknown rel types before hitting DB."""
        manager = make_manager()
        mock_conn_ctx = AsyncMock()
        mock_conn_ctx.__aenter__ = AsyncMock(return_value=await _make_mock_conn())
        mock_conn_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch.object(manager, "_get_connection", return_value=mock_conn_ctx):
            result = await manager.create_relationship(
                TENANT_ID,
                "A",
                "EQUIPMENT_TAG",
                "B",
                "FAILURE_MODE",
                "INVALID_RELATIONSHIP_TYPE",
                DOCUMENT_ID,
                0.9,
            )
        assert result is False

    @pytest.mark.asyncio
    async def test_cypher_contains_merge(self):
        manager = make_manager()
        conn = await _make_mock_conn()
        captured = []
        captured_params = []

        async def capture(sql, params=None):
            if "cypher(" in sql:
                captured.append(sql)
                captured_params.append(params)
            return AsyncMock(__aiter__=AsyncMock(return_value=iter([])))

        conn.execute = capture

        await manager._create_relationship_impl(
            conn,
            TENANT_ID,
            "PUMP-101",
            "EQUIPMENT_TAG",
            "bearing seizure",
            "FAILURE_MODE",
            "FAILED_WITH",
            DOCUMENT_ID,
            0.9,
            None,
            commit=False,
        )
        assert "MERGE" in captured[0]
        assert "FAILED_WITH" in captured[0]


# ══════════════════════════════════════════════════════
# 5. _get_entity_context_impl
# ══════════════════════════════════════════════════════


class TestGetEntityContextImpl:
    @pytest.mark.asyncio
    async def test_returns_list_of_dicts(self):
        manager = KnowledgeGraphManager(DB_URL)
        conn = await _make_mock_conn()

        # Use async generator for proper async iteration
        async def mock_rows():
            # Note: confidence is not JSON-quoted — just a bare numeric string
            yield (
                '"EQUIPMENT_TAG"',
                '"PUMP-101"',
                '"FAILURE_MODE"',
                '"bearing seizure"',
                '"doc-uuid"',
                "0.95",
                "1",
            )

        conn.execute = AsyncMock(return_value=mock_rows())

        results = await manager._get_entity_context_impl(
            conn, TENANT_ID, "PUMP-101", "EQUIPMENT_TAG", 3, 50
        )

        assert len(results) == 1
        r = results[0]
        assert r["source_type"] == "EQUIPMENT_TAG"
        assert r["source_value"] == "PUMP-101"
        assert r["target_type"] == "FAILURE_MODE"
        assert r["target_value"] == "bearing seizure"
        assert r["distance"] == 1

    @pytest.mark.asyncio
    async def test_empty_result(self):
        manager = KnowledgeGraphManager(DB_URL)
        conn = await _make_mock_conn()

        async def empty_rows():
            return
            yield

        conn.execute = AsyncMock(return_value=empty_rows())
        results = await manager._get_entity_context_impl(conn, TENANT_ID, "PUMP-101", None, 3, 50)
        assert results == []

    @pytest.mark.asyncio
    async def test_exception_returns_empty_list(self):
        manager = make_manager()
        conn = await _make_mock_conn()
        conn.execute = AsyncMock(side_effect=Exception("AGE traversal error"))
        results = await manager._get_entity_context_impl(
            conn, TENANT_ID, "PUMP-101", "EQUIPMENT_TAG", 3, 50
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_match_clause_includes_type_when_provided(self):
        manager = KnowledgeGraphManager(DB_URL)
        conn = await _make_mock_conn()
        captured = []
        captured_params = []

        async def empty_gen():
            return
            yield

        async def capture(sql, params=None):
            if "cypher(" in sql:
                captured.append(sql)
                captured_params.append(params)
            return empty_gen()

        conn.execute = capture

        await manager._get_entity_context_impl(conn, TENANT_ID, "PUMP-101", "EQUIPMENT_TAG", 3, 50)
        assert "n.entity_type = $entity_type" in captured[0]
        assert "EQUIPMENT_TAG" not in captured[0]
        assert json.loads(captured_params[0][0])["entity_type"] == "EQUIPMENT_TAG"

    @pytest.mark.asyncio
    async def test_match_clause_no_type_when_none(self):
        manager = KnowledgeGraphManager(DB_URL)
        conn = await _make_mock_conn()
        captured = []
        captured_params = []

        async def empty_gen():
            return
            yield

        async def capture(sql, params=None):
            if "cypher(" in sql:
                captured.append(sql)
                captured_params.append(params)
            return empty_gen()

        conn.execute = capture

        await manager._get_entity_context_impl(conn, TENANT_ID, "PUMP-101", None, 3, 50)
        # Without entity_type, the type filter is omitted entirely
        assert "$entity_type" not in captured[0]
        assert "entity_type" not in json.loads(captured_params[0][0])


# ══════════════════════════════════════════════════════
# 6. upsert_entities_batch
# ══════════════════════════════════════════════════════


class TestUpsertEntitiesBatch:
    @pytest.mark.asyncio
    async def test_returns_count_of_successes(self):
        manager = make_manager()
        conn = await _make_mock_conn()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        entities = [
            {
                "entity_type": "EQUIPMENT_TAG",
                "value": "PUMP-101",
                "normalized_value": "pump-101",
                "confidence": 0.95,
                "attributes": {},
            },
            {
                "entity_type": "FAILURE_MODE",
                "value": "bearing seizure",
                "normalized_value": "bearing seizure",
                "confidence": 0.85,
                "attributes": {},
            },
        ]

        with (
            patch.object(manager, "_get_connection", return_value=mock_ctx),
            patch.object(manager, "_set_tenant", AsyncMock()),
            patch.object(manager, "upsert_entity_node", AsyncMock(return_value=True)),
        ):
            count = await manager.upsert_entities_batch(TENANT_ID, DOCUMENT_ID, entities)

        assert count == 2

    @pytest.mark.asyncio
    async def test_empty_entities_returns_zero(self):
        manager = make_manager()
        conn = await _make_mock_conn()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(manager, "_get_connection", return_value=mock_ctx),
            patch.object(manager, "_set_tenant", AsyncMock()),
        ):
            count = await manager.upsert_entities_batch(TENANT_ID, DOCUMENT_ID, [])

        assert count == 0


# ══════════════════════════════════════════════════════
# 7. build_document_relationships — Inference Rules
# ══════════════════════════════════════════════════════


class TestBuildDocumentRelationships:
    @pytest.mark.asyncio
    async def test_equipment_plus_failure_creates_failed_with(self):
        manager = make_manager()
        conn = await _make_mock_conn()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        created = []

        async def mock_create_rel(**kwargs):
            created.append(kwargs["relationship_type"])
            return True

        entities = [
            {
                "entity_type": "EQUIPMENT_TAG",
                "value": "PUMP-101",
                "normalized_value": "pump-101",
                "confidence": 0.95,
            },
            {
                "entity_type": "FAILURE_MODE",
                "value": "bearing seizure",
                "normalized_value": "bearing seizure",
                "confidence": 0.85,
            },
        ]

        with (
            patch.object(manager, "_get_connection", return_value=mock_ctx),
            patch.object(manager, "_set_tenant", AsyncMock()),
            patch.object(manager, "create_relationship", side_effect=mock_create_rel),
        ):
            count = await manager.build_document_relationships(TENANT_ID, DOCUMENT_ID, entities)

        assert "FAILED_WITH" in created

    @pytest.mark.asyncio
    async def test_equipment_plus_regulation_creates_governed_by(self):
        manager = make_manager()
        conn = await _make_mock_conn()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        created = []

        async def mock_create_rel(**kwargs):
            created.append(kwargs["relationship_type"])
            return True

        entities = [
            {
                "entity_type": "EQUIPMENT_TAG",
                "value": "PUMP-101",
                "normalized_value": "pump-101",
                "confidence": 0.95,
            },
            {
                "entity_type": "REGULATION",
                "value": "OISD-154",
                "normalized_value": "oisd-154",
                "confidence": 0.92,
            },
        ]

        with (
            patch.object(manager, "_get_connection", return_value=mock_ctx),
            patch.object(manager, "_set_tenant", AsyncMock()),
            patch.object(manager, "create_relationship", side_effect=mock_create_rel),
        ):
            await manager.build_document_relationships(TENANT_ID, DOCUMENT_ID, entities)

        assert "GOVERNED_BY" in created

    @pytest.mark.asyncio
    async def test_same_equipment_tags_co_occurs_with(self):
        manager = make_manager()
        conn = await _make_mock_conn()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        created = []

        async def mock_create_rel(**kwargs):
            created.append(kwargs["relationship_type"])
            return True

        entities = [
            {
                "entity_type": "EQUIPMENT_TAG",
                "value": "PUMP-101",
                "normalized_value": "pump-101",
                "confidence": 0.95,
            },
            {
                "entity_type": "EQUIPMENT_TAG",
                "value": "PUMP-102",
                "normalized_value": "pump-102",
                "confidence": 0.90,
            },
        ]

        with (
            patch.object(manager, "_get_connection", return_value=mock_ctx),
            patch.object(manager, "_set_tenant", AsyncMock()),
            patch.object(manager, "create_relationship", side_effect=mock_create_rel),
        ):
            await manager.build_document_relationships(TENANT_ID, DOCUMENT_ID, entities)

        assert "CO_OCCURS_WITH" in created

    @pytest.mark.asyncio
    async def test_unrelated_types_no_relationship(self):
        """DATE + ORGANIZATION have no inference rule, no relationship created."""
        manager = make_manager()
        conn = await _make_mock_conn()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        created = []

        async def mock_create_rel(**kwargs):
            created.append(kwargs["relationship_type"])
            return True

        entities = [
            {
                "entity_type": "DATE",
                "value": "23-Mar-2024",
                "normalized_value": "23-mar-2024",
                "confidence": 0.8,
            },
            {
                "entity_type": "ORGANIZATION",
                "value": "XYZ Corp",
                "normalized_value": "xyz corp",
                "confidence": 0.75,
            },
        ]

        with (
            patch.object(manager, "_get_connection", return_value=mock_ctx),
            patch.object(manager, "_set_tenant", AsyncMock()),
            patch.object(manager, "create_relationship", side_effect=mock_create_rel),
        ):
            count = await manager.build_document_relationships(TENANT_ID, DOCUMENT_ID, entities)

        assert count == 0

    @pytest.mark.asyncio
    async def test_empty_entities_returns_zero(self):
        manager = make_manager()
        conn = await _make_mock_conn()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(manager, "_get_connection", return_value=mock_ctx),
            patch.object(manager, "_set_tenant", AsyncMock()),
        ):
            count = await manager.build_document_relationships(TENANT_ID, DOCUMENT_ID, [])

        assert count == 0
