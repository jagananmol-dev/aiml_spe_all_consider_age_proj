"""
VEDA AI — Local mode tests (no pgvector / AGE / OpenSearch)

- local_store.search_chunks: tenant-filtered query, cosine ranking, top_k
- local_store.replace_document_chunks: refuses other tenants' documents
- RAGPipeline: local vector dispatch, graph/OpenSearch switches, indexing
- IndustrialEntityExtractor: works without any spaCy model
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from src.rag import local_store
from src.rag import pipeline as pipeline_module
from src.rag.pipeline import RAGPipeline

TENANT = "11111111-2222-4333-8444-555555555555"
DOC = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


def _unit(v):
    v = np.asarray(v, dtype=np.float32)
    return (v / np.linalg.norm(v)).tolist()


class FakeConn:
    """Minimal stand-in for a psycopg sync connection."""

    def __init__(self, select_rows=None, owned=True, fingerprint=(1, 1, 1, 1)):
        self.calls = []
        self.fingerprint = fingerprint
        self.select_rows = select_rows or []
        self.owned = owned
        self.executemany_rows = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def commit(self):
        pass

    def close(self):
        pass

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        result = MagicMock()
        if "SELECT (SELECT count(*)" in sql:
            result.fetchone.return_value = self.fingerprint
        elif "FROM document_chunks dc" in sql:
            result.fetchall.return_value = self.select_rows
        elif "FOR UPDATE" in sql:
            result.fetchone.return_value = (DOC,) if self.owned else None
        return result

    def cursor(self):
        conn = self

        class Cur:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def executemany(self, sql, rows):
                conn.executemany_rows = list(rows)

        return Cur()


@pytest.fixture(autouse=True)
def _fresh_search_cache():
    local_store.clear_cache()
    yield
    local_store.clear_cache()


def _select_call(conn):
    return next(call for call in conn.calls if "FROM document_chunks dc" in call[0])


class TestSearchChunks:
    def test_filters_by_tenant_and_ranks_by_cosine(self):
        rows = [
            ("doc-a", "about invoices", {"chunk_index": 0}, _unit([1, 0, 0]), "a.pdf"),
            ("doc-b", "about patients", {}, _unit([0, 1, 0]), "b.csv"),
            ("doc-c", "mostly invoices", {}, _unit([0.9, 0.1, 0]), "c.json"),
        ]
        conn = FakeConn(select_rows=rows)
        with patch.object(local_store, "_connect", return_value=conn):
            results = local_store.search_chunks("db", TENANT, _unit([1, 0, 0]), top_k=2)

        sql, params = _select_call(conn)
        assert "dc.tenant_id = %s::uuid" in sql
        assert "d.status = 'indexed'" in sql
        assert params == [TENANT]
        assert [r["document_id"] for r in results] == ["doc-a", "doc-c"]
        assert results[0]["score"] == pytest.approx(1.0, abs=1e-5)
        assert results[1]["metadata"]["title"] == "c.json"

    def test_skips_embeddings_of_wrong_dimension(self):
        rows = [("doc-a", "x", {}, [1.0, 0.0], "a"), ("doc-b", "y", {}, _unit([1, 0, 0]), "b")]
        with patch.object(local_store, "_connect", return_value=FakeConn(select_rows=rows)):
            results = local_store.search_chunks("db", TENANT, _unit([1, 0, 0]), top_k=5)
        assert [r["document_id"] for r in results] == ["doc-b"]

    def test_reuses_vectors_until_the_tenant_data_changes(self):
        rows = [("doc-a", "x", {}, _unit([1, 0, 0]), "a")]
        conn = FakeConn(select_rows=rows)
        with patch.object(local_store, "_connect", return_value=conn):
            local_store.search_chunks("db", TENANT, _unit([1, 0, 0]), top_k=1)
            local_store.search_chunks("db", TENANT, _unit([1, 0, 0]), top_k=1)
            loads = sum("FROM document_chunks dc" in c[0] for c in conn.calls)
            assert loads == 1  # second search served from memory

            conn.fingerprint = (2, 9, 1, 1)  # a chunk was added
            conn.select_rows = rows + [("doc-b", "y", {}, _unit([0, 1, 0]), "b")]
            results, stats = local_store.search_chunks_with_stats("db", TENANT, _unit([0, 1, 0]), top_k=1)
        assert [r["document_id"] for r in results] == ["doc-b"]
        assert stats == {"chunks_searched": 2, "documents_searched": 2, "low_confidence": False}

    def test_searches_reuse_one_connection(self):
        conn = FakeConn(select_rows=[("doc-a", "x", {}, _unit([1, 0, 0]), "a")])
        with patch.object(local_store, "_connect", return_value=conn) as connect:
            for _ in range(3):
                local_store.search_chunks("db", TENANT, _unit([1, 0, 0]), top_k=1)
        assert connect.call_count == 1

    def test_preload_builds_every_tenant_index_up_front(self):
        conn = FakeConn(select_rows=[("doc-a", "x", {}, _unit([1, 0, 0]), "a")])
        original = conn.execute

        def execute(sql, params=None):
            if "SELECT DISTINCT tenant_id" in sql:
                conn.calls.append((sql, params))
                result = MagicMock()
                result.fetchall.return_value = [(TENANT,)]
                return result
            return original(sql, params)

        conn.execute = execute
        with patch.object(local_store, "_connect", return_value=conn):
            assert local_store.preload_all("db") == 1
            loads_before = sum("FROM document_chunks dc" in c[0] for c in conn.calls)
            local_store.search_chunks("db", TENANT, _unit([1, 0, 0]), top_k=1)
        assert loads_before == 1
        assert sum("FROM document_chunks dc" in c[0] for c in conn.calls) == 1  # search used the preload

    def test_weak_matches_are_returned_and_flagged_when_nothing_clears_the_cutoff(self):
        rows = [
            ("doc-a", "about invoices", {}, _unit([0.2, 1, 0]), "a"),
            ("doc-b", "about patients", {}, _unit([0.1, 0, 1]), "b"),
        ]
        with patch.object(local_store, "_connect", return_value=FakeConn(select_rows=rows)):
            results, stats = local_store.search_chunks_with_stats(
                "db", TENANT, _unit([1, 0, 0]), 5, min_score=0.9, fallback_k=1
            )
        assert stats["low_confidence"] is True
        assert [r["document_id"] for r in results] == ["doc-a"]  # the closest one only

    def test_good_matches_are_not_flagged(self):
        rows = [("doc-a", "x", {}, _unit([1, 0, 0]), "a"), ("doc-b", "y", {}, _unit([0, 1, 0]), "b")]
        with patch.object(local_store, "_connect", return_value=FakeConn(select_rows=rows)):
            results, stats = local_store.search_chunks_with_stats(
                "db", TENANT, _unit([1, 0, 0]), 5, min_score=0.5, fallback_k=3
            )
        assert stats["low_confidence"] is False
        assert [r["document_id"] for r in results] == ["doc-a"]

    def test_empty_store(self):
        with patch.object(local_store, "_connect", return_value=FakeConn()):
            assert local_store.search_chunks("db", TENANT, [1.0, 0.0], top_k=5) == []


class TestReplaceDocumentChunks:
    def test_rejects_document_of_another_tenant(self):
        conn = FakeConn(owned=False)
        with patch.object(local_store, "_connect", return_value=conn):
            with pytest.raises(local_store.DocumentNotFoundError):
                local_store.replace_document_chunks(
                    "db", TENANT, DOC, [local_store.StoredChunk("t", [0.1], {})]
                )
        assert conn.executemany_rows is None
        assert not any("UPDATE documents" in sql for sql, _ in conn.calls)

    def test_replaces_chunks_and_marks_indexed(self):
        conn = FakeConn()
        chunks = [
            local_store.StoredChunk("first", [0.1, 0.2], {"title": "a.pdf"}),
            local_store.StoredChunk("second", [0.3, 0.4], {}),
        ]
        with patch.object(local_store, "_connect", return_value=conn):
            count = local_store.replace_document_chunks("db", TENANT, DOC, chunks)

        assert count == 2
        statements = [sql for sql, _ in conn.calls]
        assert any(s.startswith("DELETE FROM document_chunks") for s in statements)
        update = next(sql for sql in statements if "UPDATE documents" in sql)
        assert "status = 'indexed'" in update
        assert conn.executemany_rows[0][:4] == (TENANT, DOC, 0, "first")
        assert json.loads(conn.executemany_rows[0][5]) == {"title": "a.pdf"}


class TestPipelineLocalMode:
    @pytest.mark.asyncio
    async def test_vector_backend_local_uses_local_store(self):
        pipeline = RAGPipeline()
        hits = [{"document_id": DOC, "chunk_text": "t", "metadata": {"title": "x"}, "score": 0.8}]
        with (
            patch.object(pipeline_module.settings, "vector_backend", "local"),
            patch.object(local_store, "search_chunks_with_stats", return_value=(hits, {})) as search,
        ):
            results = await pipeline.retrieve_vector([0.1, 0.2], TENANT, top_k=3)
        search.assert_called_once()
        assert search.call_args.args[1] == TENANT
        assert results[0].metadata["title"] == "x"
        assert results[0].source == "vector"

    @pytest.mark.asyncio
    async def test_graph_disabled_skips_age(self):
        pipeline = RAGPipeline()
        pipeline._graph_manager = MagicMock()
        with patch.object(pipeline_module.settings, "graph_enabled", False):
            chunks, context = await pipeline.retrieve_graph(["P-1"], ["EQUIPMENT_TAG"], TENANT)
        assert (chunks, context) == ([], [])
        pipeline._graph_manager._get_connection.assert_not_called()

    @pytest.mark.asyncio
    async def test_graph_unavailable_degrades_gracefully(self):
        pipeline = RAGPipeline()
        pipeline._graph_manager = MagicMock()
        pipeline._graph_manager._get_connection = AsyncMock(side_effect=OSError("no AGE"))
        chunks, context = await pipeline.retrieve_graph(["P-1"], ["EQUIPMENT_TAG"], TENANT)
        assert (chunks, context) == ([], [])

    @pytest.mark.asyncio
    async def test_opensearch_disabled_makes_no_request(self):
        pipeline = RAGPipeline()
        with (
            patch.object(pipeline_module.settings, "opensearch_enabled", False),
            patch("src.rag.pipeline.httpx.AsyncClient") as client,
        ):
            assert await pipeline.retrieve_text("q", TENANT) == []
        client.assert_not_called()

    @pytest.mark.asyncio
    async def test_index_document_chunks_embeds_and_stores(self):
        pipeline = RAGPipeline()
        model = MagicMock()
        model.encode = MagicMock(
            side_effect=lambda texts, **kw: np.ones((len(texts), 3), dtype=np.float32)
        )
        pipeline._embedding_model = model
        captured = {}

        def fake_replace(db_url, tenant_id, document_id, chunks):
            captured.update(tenant_id=tenant_id, document_id=document_id, chunks=chunks)
            return len(chunks)

        text = "First paragraph about revenue.\n\nSecond paragraph about costs."
        with (
            patch.object(pipeline_module.settings, "vector_backend", "local"),
            patch.object(local_store, "replace_document_chunks", side_effect=fake_replace),
        ):
            count = await pipeline.index_document(TENANT, DOC, "q3.txt", text)

        assert count == len(captured["chunks"]) >= 1
        assert captured["tenant_id"] == TENANT
        assert all(c.metadata["title"] == "q3.txt" for c in captured["chunks"])
        assert model.encode.call_args.kwargs["normalize_embeddings"] is True

    @pytest.mark.asyncio
    async def test_index_document_requires_local_backend(self):
        with patch.object(pipeline_module.settings, "vector_backend", "pgvector"):
            with pytest.raises(RuntimeError):
                await RAGPipeline().index_document(TENANT, DOC, "t", "text")

    @pytest.mark.asyncio
    async def test_index_document_rejects_empty_text(self):
        with patch.object(pipeline_module.settings, "vector_backend", "local"):
            with pytest.raises(ValueError):
                await RAGPipeline().index_document(TENANT, DOC, "t", "   ")


class TestExtractorWithoutSpacy:
    def test_regex_entities_still_extracted_when_no_model(self):
        from src.entity_extraction.extractor import IndustrialEntityExtractor

        extractor = IndustrialEntityExtractor()
        fake_spacy = MagicMock()
        fake_spacy.load.side_effect = OSError("no model")
        with patch.dict("sys.modules", {"spacy": fake_spacy}):
            entities = extractor.extract_entities("PUMP-101 needs bearing replacement")
            # Second call must not retry loading
            extractor.extract_entities("again")

        assert any(e.entity_type == "EQUIPMENT_TAG" for e in entities)
        # Each model the schema lists (nlp.models) is tried once, never retried
        from src.entity_extraction.schema import get_schema

        assert fake_spacy.load.call_count == len(get_schema().nlp["models"])


class TestMinimumSimilarity:
    def test_low_similarity_chunks_are_dropped(self):
        rows = [
            ("doc-a", "relevant", {}, _unit([1, 0, 0]), "a"),
            ("doc-b", "unrelated", {}, _unit([0.1, 1, 0]), "b"),
        ]
        with patch.object(local_store, "_connect", return_value=FakeConn(select_rows=rows)):
            results = local_store.search_chunks("db", TENANT, _unit([1, 0, 0]), 5, min_score=0.5)
        assert [r["document_id"] for r in results] == ["doc-a"]

    @pytest.mark.asyncio
    async def test_pipeline_passes_threshold(self):
        with (
            patch.object(pipeline_module.settings, "vector_backend", "local"),
            patch.object(pipeline_module.settings, "min_similarity", 0.3),
            patch.object(local_store, "search_chunks_with_stats", return_value=([], {})) as search,
        ):
            await RAGPipeline().retrieve_vector([0.1], TENANT, top_k=3)
        assert search.call_args.args[4] == 0.3
