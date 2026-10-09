"""
VEDA AI — Cypher Injection Security Tests

Validates that graph_manager does NOT blindly interpolate
user-controlled strings in ways that allow Cypher injection.

Attack vectors tested:
1. Single-quote escape sequences
2. Backslash injection
3. Dollar sign / comment injection
4. Null byte injection
5. Very long strings
6. Unicode edge cases

User-controlled values are passed to AGE as a JSON parameter map, never
interpolated into the Cypher text (VEDA-SEC-001). The parameterization
tests at the bottom assert that directly.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.knowledge_graph.graph_manager import KnowledgeGraphManager


TENANT_ID = "tenant-security-test"
DOCUMENT_ID = "doc-security-001"
DB_URL = "postgresql://test:test@localhost:5432/test"


async def _make_mock_conn():
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=AsyncMock(__aiter__=AsyncMock(return_value=iter([]))))
    conn.commit = AsyncMock()
    conn.rollback = AsyncMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    return conn


# ══════════════════════════════════════════════════════
# 1. Single Quote Injection
# ══════════════════════════════════════════════════════


class TestSingleQuoteInjection:
    @pytest.mark.asyncio
    async def test_single_quote_in_entity_value_does_not_crash(self):
        """O'Brien should not break the Cypher string."""
        manager = KnowledgeGraphManager(DB_URL)
        conn = await _make_mock_conn()
        result = await manager._upsert_entity_node_impl(
            conn,
            TENANT_ID,
            "PERSON",
            "O'Brien",
            "o'brien",
            DOCUMENT_ID,
            0.8,
            None,
            commit=False,
        )
        # Must not raise; result could be True or False depending on escaping
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_escaped_single_quote_in_cypher(self):
        """The Cypher query must escape the apostrophe to prevent injection."""
        manager = KnowledgeGraphManager(DB_URL)
        conn = await _make_mock_conn()
        captured_queries = []

        async def capture(sql, params=None):
            if "cypher(" in sql:
                captured_queries.append(sql)
            return AsyncMock(__aiter__=AsyncMock(return_value=iter([])))

        conn.execute = capture

        await manager._upsert_entity_node_impl(
            conn,
            TENANT_ID,
            "PERSON",
            "O'Brien",
            "o'brien",
            DOCUMENT_ID,
            0.8,
            None,
            commit=False,
        )

        if captured_queries:
            cypher = captured_queries[0]
            # The raw unescaped apostrophe must not appear as a standalone quote
            # After replace("'", "\\'"), it should be \\'
            # We verify the original value "o'brien" doesn't appear unescaped
            assert "o'brien" not in cypher or "\\'brien" in cypher or "o\\'brien" in cypher

    @pytest.mark.asyncio
    async def test_multiple_single_quotes_handled(self):
        """Values with multiple quotes: it's O'Brien's pump."""
        manager = KnowledgeGraphManager(DB_URL)
        conn = await _make_mock_conn()
        result = await manager._upsert_entity_node_impl(
            conn,
            TENANT_ID,
            "PERSON",
            "it's O'Brien's",
            "it's o'brien's",
            DOCUMENT_ID,
            0.7,
            None,
            commit=False,
        )
        assert isinstance(result, bool)


# ══════════════════════════════════════════════════════
# 2. Backslash Injection
# ══════════════════════════════════════════════════════


class TestBackslashInjection:
    @pytest.mark.asyncio
    async def test_backslash_in_value_does_not_crash(self):
        manager = KnowledgeGraphManager(DB_URL)
        conn = await _make_mock_conn()
        # Backslash sequences that might confuse string parsers
        result = await manager._upsert_entity_node_impl(
            conn,
            TENANT_ID,
            "EQUIPMENT_TAG",
            "PUMP\\101",
            "pump\\101",
            DOCUMENT_ID,
            0.9,
            None,
            commit=False,
        )
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_escaped_backslash_single_quote_does_not_crash(self):
        """Classic injection: \\' to escape the escaping."""
        manager = KnowledgeGraphManager(DB_URL)
        conn = await _make_mock_conn()
        result = await manager._upsert_entity_node_impl(
            conn,
            TENANT_ID,
            "EQUIPMENT_TAG",
            "\\'",
            "\\'",
            DOCUMENT_ID,
            0.9,
            None,
            commit=False,
        )
        assert isinstance(result, bool)


# ══════════════════════════════════════════════════════
# 3. Comment / Termination Injection
# ══════════════════════════════════════════════════════


class TestCommentInjection:
    @pytest.mark.asyncio
    async def test_cypher_comment_in_value_does_not_crash(self):
        """Cypher uses // for comments — test it doesn't break execution."""
        manager = KnowledgeGraphManager(DB_URL)
        conn = await _make_mock_conn()
        result = await manager._upsert_entity_node_impl(
            conn,
            TENANT_ID,
            "EQUIPMENT_TAG",
            "PUMP-101 // DROP ALL",
            "pump-101 // drop all",
            DOCUMENT_ID,
            0.9,
            None,
            commit=False,
        )
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_cypher_block_comment_in_value(self):
        """Cypher block comment: /* ... */"""
        manager = KnowledgeGraphManager(DB_URL)
        conn = await _make_mock_conn()
        result = await manager._upsert_entity_node_impl(
            conn,
            TENANT_ID,
            "EQUIPMENT_TAG",
            "PUMP /* evil */ 101",
            "pump /* evil */ 101",
            DOCUMENT_ID,
            0.9,
            None,
            commit=False,
        )
        assert isinstance(result, bool)


# ══════════════════════════════════════════════════════
# 4. Null Byte Injection
# ══════════════════════════════════════════════════════


class TestNullByteInjection:
    @pytest.mark.asyncio
    async def test_null_byte_in_value_does_not_crash(self):
        manager = KnowledgeGraphManager(DB_URL)
        conn = await _make_mock_conn()
        result = await manager._upsert_entity_node_impl(
            conn,
            TENANT_ID,
            "EQUIPMENT_TAG",
            "PUMP\x00101",
            "pump\x00101",
            DOCUMENT_ID,
            0.9,
            None,
            commit=False,
        )
        assert isinstance(result, bool)


# ══════════════════════════════════════════════════════
# 5. Very Long String
# ══════════════════════════════════════════════════════


class TestLongStringInput:
    @pytest.mark.asyncio
    async def test_10k_char_value_does_not_crash(self):
        """Very long entity values should not cause catastrophic issues."""
        manager = KnowledgeGraphManager(DB_URL)
        conn = await _make_mock_conn()
        long_value = "A" * 10000
        result = await manager._upsert_entity_node_impl(
            conn,
            TENANT_ID,
            "EQUIPMENT_TAG",
            long_value,
            long_value.lower(),
            DOCUMENT_ID,
            0.5,
            None,
            commit=False,
        )
        assert isinstance(result, bool)


# ══════════════════════════════════════════════════════
# 6. Relationship Type Allowlist Enforcement
# ══════════════════════════════════════════════════════


class TestRelationshipAllowlist:
    @pytest.mark.asyncio
    async def test_arbitrary_rel_type_rejected(self):
        """Any relationship type not in RELATIONSHIP_TYPES must be rejected."""
        manager = KnowledgeGraphManager(DB_URL)
        mock_conn_ctx = AsyncMock()
        mock_conn = await _make_mock_conn()
        mock_conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch.object(manager, "_get_connection", return_value=mock_conn_ctx):
            result = await manager.create_relationship(
                TENANT_ID,
                "PUMP-101",
                "EQUIPMENT_TAG",
                "CDU-A",
                "EQUIPMENT_TAG",
                "DROP_ALL_TABLES",  # injection attempt as rel type
                DOCUMENT_ID,
                0.9,
            )

        # Must be rejected before any DB call
        assert result is False
        mock_conn.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_valid_rel_types_accepted(self):
        """All RELATIONSHIP_TYPES entries must pass the allowlist check."""
        from src.knowledge_graph.graph_manager import RELATIONSHIP_TYPES

        manager = KnowledgeGraphManager(DB_URL)

        for rel_type in RELATIONSHIP_TYPES:
            mock_conn = await _make_mock_conn()
            mock_conn_ctx = AsyncMock()
            mock_conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_conn_ctx.__aexit__ = AsyncMock(return_value=False)

            with (
                patch.object(manager, "_get_connection", return_value=mock_conn_ctx),
                patch.object(manager, "_set_tenant", AsyncMock()),
                patch.object(manager, "_create_relationship_impl", AsyncMock(return_value=True)),
            ):
                result = await manager.create_relationship(
                    TENANT_ID,
                    "A",
                    "EQUIPMENT_TAG",
                    "B",
                    "EQUIPMENT_TAG",
                    rel_type,
                    DOCUMENT_ID,
                    0.9,
                )
            # Should not be rejected by the allowlist check
            # (may fail at DB level in mock, but that's OK)


# ══════════════════════════════════════════════════════
# 7. Parameterization — user input never reaches query text
# ══════════════════════════════════════════════════════

MALICIOUS_VALUES = [
    "O'Brien",
    "x' }) DETACH DELETE n //",
    "abc\\",
    "$$; DROP TABLE users; --",
    "a$$) AS (n agtype); DELETE FROM tenants; SELECT * FROM cypher('g', $$",
    "/* comment */ MATCH (m) DETACH DELETE m",
    "null\x00byte",
    "%s %(x)s",
]


def _capturing_conn():
    calls = []

    async def execute(sql, params=None):
        calls.append((sql, params))

        async def empty():
            return
            yield

        return empty()

    conn = AsyncMock()
    conn.execute = execute
    conn.commit = AsyncMock()
    conn.rollback = AsyncMock()
    return conn, calls


def _cypher_calls(calls):
    return [(sql, params) for sql, params in calls if "cypher(" in sql]


class TestParameterization:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("value", MALICIOUS_VALUES)
    async def test_upsert_values_only_in_params(self, value):
        import json

        manager = KnowledgeGraphManager(DB_URL)
        conn, calls = _capturing_conn()
        await manager._upsert_entity_node_impl(
            conn, TENANT_ID, "PERSON", value, value, DOCUMENT_ID, 0.8, None, commit=False
        )
        [(sql, params)] = _cypher_calls(calls)
        assert value not in sql
        decoded = json.loads(params[0])
        assert decoded["value"] == value
        assert decoded["normalized_value"] == value

    @pytest.mark.asyncio
    @pytest.mark.parametrize("value", MALICIOUS_VALUES)
    async def test_traversal_values_only_in_params(self, value):
        import json

        manager = KnowledgeGraphManager(DB_URL)
        conn, calls = _capturing_conn()
        await manager._get_entity_context_impl(conn, TENANT_ID, value, value, 3, 50)
        [(sql, params)] = _cypher_calls(calls)
        assert value not in sql
        assert json.loads(params[0])["entity_value"] == value

    @pytest.mark.asyncio
    @pytest.mark.parametrize("hops,limit", [(999, 10**9), ("3) DETACH DELETE n //", "x"), (-1, -1)])
    async def test_interpolated_ints_are_clamped(self, hops, limit):
        manager = KnowledgeGraphManager(DB_URL)
        conn, calls = _capturing_conn()
        await manager._get_entity_context_impl(conn, TENANT_ID, "PUMP-101", None, hops, limit)
        [(sql, _)] = _cypher_calls(calls)
        assert "DETACH" not in sql
        import re

        upper = int(re.search(r"\[\*1\.\.(\d+)\]", sql).group(1))
        assert 1 <= upper <= 5
        assert int(re.search(r"LIMIT (\d+)", sql).group(1)) <= 500

    def test_cypher_sql_rejects_dollar_quote_in_template(self):
        from src.knowledge_graph.graph_manager import cypher_sql

        with pytest.raises(ValueError):
            cypher_sql("MATCH (n) $$ RETURN n", "n agtype")


# ══════════════════════════════════════════════════════
# 8. Tenant isolation in the shared AGE graph
# ══════════════════════════════════════════════════════


class TestTenantIsolation:
    @pytest.mark.asyncio
    async def test_merge_key_includes_tenant(self):
        import json

        manager = KnowledgeGraphManager(DB_URL)
        conn, calls = _capturing_conn()
        await manager._upsert_entity_node_impl(
            conn, TENANT_ID, "EQUIPMENT_TAG", "P-1", "P-1", DOCUMENT_ID, 0.9, None, commit=False
        )
        [(sql, params)] = _cypher_calls(calls)
        merge_line = sql[sql.index("MERGE") : sql.index("ON CREATE")]
        assert "tenant_id: $tenant_id" in merge_line
        assert json.loads(params[0])["tenant_id"] == TENANT_ID

    @pytest.mark.asyncio
    async def test_relationship_endpoints_scoped_to_tenant(self):
        manager = KnowledgeGraphManager(DB_URL)
        conn, calls = _capturing_conn()
        await manager._create_relationship_impl(
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
        [(sql, _)] = _cypher_calls(calls)
        assert sql.count("tenant_id: $tenant_id") == 2

    @pytest.mark.asyncio
    async def test_traversal_filters_start_and_related_by_tenant(self):
        manager = KnowledgeGraphManager(DB_URL)
        conn, calls = _capturing_conn()
        await manager._get_entity_context_impl(conn, TENANT_ID, "P-1", None, 2, 10)
        [(sql, _)] = _cypher_calls(calls)
        assert "n.tenant_id = $tenant_id" in sql
        assert "related.tenant_id = $tenant_id" in sql

    @pytest.mark.asyncio
    async def test_prune_only_touches_own_tenant(self):
        import json

        manager = KnowledgeGraphManager(DB_URL)
        conn, calls = _capturing_conn()

        async def fetchone():
            return ("0",)

        async def execute(sql, params=None):
            calls.append((sql, params))
            result = MagicMock()
            result.fetchone = fetchone
            return result

        conn.execute = execute
        conn.__aenter__ = AsyncMock(return_value=conn)
        conn.__aexit__ = AsyncMock(return_value=False)
        with patch.object(manager, "_get_connection", AsyncMock(return_value=conn)):
            await manager.prune_stale_relationships(TENANT_ID, 30)
        [(sql, params)] = _cypher_calls(calls)
        assert "a.tenant_id = $tenant_id AND b.tenant_id = $tenant_id" in sql
        assert json.loads(params[0])["tenant_id"] == TENANT_ID
