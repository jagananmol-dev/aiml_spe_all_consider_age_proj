"""
VEDA AI — Intelligence Service API Integration Tests

Uses FastAPI TestClient — no real DB/Kafka/embeddings needed.
All service dependencies are mocked at the import level.

Tests every endpoint:
- GET  /health
- GET  /metrics
- POST /query/prepare
- POST /query  (alias)
- POST /entities/extract
- POST /graph/search
- GET  /graph/stats
"""

import sys

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


# ── App import with mocks pre-loaded ──────────────────


@pytest.fixture(scope="module")
def client():
    """TestClient with all heavy deps mocked before app import."""
    with patch.dict(
        "sys.modules",
        {
            "psycopg": MagicMock(),
            "sentence_transformers": MagicMock(),
            "spacy": MagicMock(),
            "prometheus_client": MagicMock(
                Counter=MagicMock(
                    return_value=MagicMock(
                        labels=MagicMock(return_value=MagicMock(inc=MagicMock()))
                    )
                ),
                Histogram=MagicMock(return_value=MagicMock(observe=MagicMock())),
                generate_latest=MagicMock(return_value=b"# metrics"),
            ),
        },
    ):
        from src.api import app

        # patch.dict restores sys.modules on exit, which would drop src.api and
        # make later patch("src.api.X") calls target a fresh copy of the module
        # rather than the one the app uses. Keep the loaded src modules.
        loaded = {
            name: mod
            for name, mod in sys.modules.items()
            if name == "src" or name.startswith("src.")
        }

    sys.modules.update(loaded)
    return TestClient(app)


TENANT_HEADER = {"X-Tenant-ID": "11111111-2222-4333-8444-555555555555"}


# ══════════════════════════════════════════════════════
# 1. Health Check
# ══════════════════════════════════════════════════════


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_has_status_healthy(self, client):
        resp = client.get("/health")
        data = resp.json()
        assert data["status"] == "healthy"

    def test_health_has_service_name(self, client):
        resp = client.get("/health")
        assert "service" in resp.json()
        assert resp.json()["service"] == "veda-intelligence"

    def test_health_has_version(self, client):
        assert "version" in client.get("/health").json()


# ══════════════════════════════════════════════════════
# 2. Metrics Endpoint
# ══════════════════════════════════════════════════════


class TestMetricsEndpoint:
    def test_metrics_returns_200(self, client):
        with patch("src.api.generate_latest", return_value=b"# prometheus"):
            resp = client.get("/metrics")
        assert resp.status_code == 200


# ══════════════════════════════════════════════════════
# 3. /query/prepare
# ══════════════════════════════════════════════════════


class TestQueryPrepareEndpoint:
    def _mock_prepared_context(self):
        from src.knowledge_graph.chunk_builder import PreparedContext, PreparedChunk

        chunk = PreparedChunk(
            text="PUMP-101 failed with bearing seizure.",
            source_type="vector",
            relevance_score=0.88,
            document_id="doc-uuid-1",
            token_estimate=10,
        )
        return PreparedContext(
            query="What failed?",
            chunks=[chunk],
            graph_context=[],
            system_prompt="You are VEDA AI...",
            formatted_prompt="Context:\n...\nQuestion: What failed?",
            total_token_estimate=500,
            entities_found=[],
            retrieval_metadata={"confidence_score": 88.0},
        )

    def test_missing_tenant_header_returns_422(self, client):
        resp = client.post("/query/prepare", json={"query": "test"})
        assert resp.status_code == 422  # FastAPI validation

    def test_empty_query_body_returns_422(self, client):
        resp = client.post("/query/prepare", json={}, headers=TENANT_HEADER)
        assert resp.status_code == 422

    def test_success_returns_200(self, client):
        ctx = self._mock_prepared_context()
        with patch("src.api.rag_pipeline") as mock_pipeline:
            mock_pipeline.prepare = AsyncMock(return_value=ctx)
            resp = client.post(
                "/query/prepare",
                json={"query": "What failed?"},
                headers=TENANT_HEADER,
            )
        assert resp.status_code == 200

    def test_success_response_has_chunks(self, client):
        ctx = self._mock_prepared_context()
        with patch("src.api.rag_pipeline") as mock_pipeline:
            mock_pipeline.prepare = AsyncMock(return_value=ctx)
            resp = client.post(
                "/query/prepare",
                json={"query": "What failed?"},
                headers=TENANT_HEADER,
            )
        data = resp.json()
        assert "chunks" in data
        assert len(data["chunks"]) == 1

    def test_success_response_has_formatted_prompt(self, client):
        ctx = self._mock_prepared_context()
        with patch("src.api.rag_pipeline") as mock_pipeline:
            mock_pipeline.prepare = AsyncMock(return_value=ctx)
            resp = client.post(
                "/query/prepare",
                json={"query": "What failed?"},
                headers=TENANT_HEADER,
            )
        data = resp.json()
        assert "formatted_prompt" in data
        assert "What failed?" in data["formatted_prompt"]

    def test_pipeline_failure_returns_500(self, client):
        with patch("src.api.rag_pipeline") as mock_pipeline:
            mock_pipeline.prepare = AsyncMock(side_effect=Exception("Vector DB down"))
            resp = client.post(
                "/query/prepare",
                json={"query": "What failed?"},
                headers=TENANT_HEADER,
            )
        assert resp.status_code == 500

    def test_filters_passed_to_pipeline(self, client):
        ctx = self._mock_prepared_context()
        with patch("src.api.rag_pipeline") as mock_pipeline:
            mock_pipeline.prepare = AsyncMock(return_value=ctx)
            client.post(
                "/query/prepare",
                json={"query": "Pump failure", "filters": {"document_type": "SOP"}},
                headers=TENANT_HEADER,
            )
        # Verify prepare was called with the tenant ID
        mock_pipeline.prepare.assert_called_once()
        call_kwargs = mock_pipeline.prepare.call_args[1]
        assert call_kwargs["tenant_id"] == TENANT_HEADER["X-Tenant-ID"]


class TestCallerAuthentication:
    @pytest.mark.parametrize("bad", ["tenant-test-123", "../../etc", "1 OR 1=1"])
    def test_non_uuid_tenant_rejected(self, client, bad):
        resp = client.post("/query/prepare", json={"query": "q"}, headers={"X-Tenant-ID": bad})
        assert resp.status_code == 400

    def test_missing_tenant_rejected(self, client):
        assert client.post("/query/prepare", json={"query": "q"}).status_code == 422

    def test_internal_key_required_when_configured(self, client):
        import os

        with patch.dict(os.environ, {"INTERNAL_API_KEY": "s3cret-key"}):
            no_key = client.post("/entities/extract", json={"text": "x"}, headers=TENANT_HEADER)
            wrong = client.post(
                "/entities/extract",
                json={"text": "x"},
                headers={**TENANT_HEADER, "X-Internal-Key": "nope"},
            )
            with patch("src.api.extractor") as mock_ext:
                mock_ext.extract_entities = MagicMock(return_value=[])
                ok = client.post(
                    "/entities/extract",
                    json={"text": "x"},
                    headers={**TENANT_HEADER, "X-Internal-Key": "s3cret-key"},
                )
        assert no_key.status_code == 401
        assert wrong.status_code == 401
        assert ok.status_code == 200

    def test_max_hops_bounded(self, client):
        resp = client.post(
            "/graph/search",
            json={"entity_value": "P-1", "max_hops": 50},
            headers=TENANT_HEADER,
        )
        assert resp.status_code == 422

    def test_internal_errors_not_leaked(self, client):
        with patch("src.api.rag_pipeline") as mock_pipeline:
            mock_pipeline.prepare = AsyncMock(side_effect=Exception("password=hunter2 at db"))
            resp = client.post("/query/prepare", json={"query": "q"}, headers=TENANT_HEADER)
        assert resp.status_code == 500
        assert "hunter2" not in resp.text


# ══════════════════════════════════════════════════════
# 4. /query (alias)
# ══════════════════════════════════════════════════════


class TestQueryAliasEndpoint:
    def test_alias_returns_same_as_prepare(self, client):
        from src.knowledge_graph.chunk_builder import PreparedContext, PreparedChunk

        chunk = PreparedChunk("Text.", "vector", 0.5, "doc-1", token_estimate=5)
        ctx = PreparedContext(
            query="Q",
            chunks=[chunk],
            graph_context=[],
            system_prompt="sys",
            formatted_prompt="fmt",
            total_token_estimate=100,
            entities_found=[],
        )
        with patch("src.api.rag_pipeline") as mock_pipeline:
            mock_pipeline.prepare = AsyncMock(return_value=ctx)
            resp = client.post("/query", json={"query": "Q"}, headers=TENANT_HEADER)
        assert resp.status_code == 200


# ══════════════════════════════════════════════════════
# 5. /entities/extract
# ══════════════════════════════════════════════════════


class TestEntitiesExtractEndpoint:
    def test_missing_tenant_returns_422(self, client):
        resp = client.post("/entities/extract", json={"text": "PUMP-101"})
        assert resp.status_code == 422

    def test_missing_text_returns_422(self, client):
        resp = client.post("/entities/extract", json={}, headers=TENANT_HEADER)
        assert resp.status_code == 422

    def test_success_returns_entities(self, client):
        mock_entity = MagicMock()
        mock_entity.entity_type = "EQUIPMENT_TAG"
        mock_entity.value = "PUMP-101"
        mock_entity.normalized_value = "PUMP-101"
        mock_entity.confidence = 0.95
        mock_entity.start_offset = 0
        mock_entity.end_offset = 8
        mock_entity.page_number = None
        mock_entity.attributes = {}

        with patch("src.api.extractor") as mock_ext:
            mock_ext.extract_entities = MagicMock(return_value=[mock_entity])
            resp = client.post(
                "/entities/extract",
                json={"text": "PUMP-101 was inspected."},
                headers=TENANT_HEADER,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "entities" in data
        assert data["count"] == 1
        assert data["entities"][0]["type"] == "EQUIPMENT_TAG"

    def test_processing_time_returned(self, client):
        with patch("src.api.extractor") as mock_ext:
            mock_ext.extract_entities = MagicMock(return_value=[])
            resp = client.post(
                "/entities/extract",
                json={"text": "No entities here."},
                headers=TENANT_HEADER,
            )
        assert "processing_time_ms" in resp.json()
        assert resp.json()["processing_time_ms"] >= 0


# ══════════════════════════════════════════════════════
# 6. /graph/search
# ══════════════════════════════════════════════════════


class TestGraphSearchEndpoint:
    def test_missing_tenant_returns_422(self, client):
        resp = client.post("/graph/search", json={"entity_value": "PUMP-101"})
        assert resp.status_code == 422

    def test_success_returns_nodes_and_edges(self, client):
        graph_result = {
            "source_type": "EQUIPMENT_TAG",
            "source_value": "PUMP-101",
            "target_type": "FAILURE_MODE",
            "target_value": "bearing seizure",
            "relationship": "FAILED_WITH",
            "distance": 1,
            "confidence": 0.95,
        }
        import os

        with (
            patch.dict(os.environ, {"VEDA_DATABASE_URL": "postgresql://test:test@localhost/test"}),
            patch("src.api.KnowledgeGraphManager") as MockGM,
        ):
            mock_gm_instance = AsyncMock()
            mock_gm_instance.get_entity_context = AsyncMock(return_value=[graph_result])
            MockGM.return_value = mock_gm_instance

            resp = client.post(
                "/graph/search",
                json={"entity_value": "PUMP-101", "entity_type": "EQUIPMENT_TAG"},
                headers=TENANT_HEADER,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "nodes" in data
        assert "edges" in data

    def test_graph_error_returns_500(self, client):
        import os

        with (
            patch.dict(os.environ, {"VEDA_DATABASE_URL": "postgresql://test:test@localhost/test"}),
            patch("src.api.KnowledgeGraphManager") as MockGM,
        ):
            mock_gm_instance = AsyncMock()
            mock_gm_instance.get_entity_context = AsyncMock(side_effect=Exception("Graph DB down"))
            MockGM.return_value = mock_gm_instance

            resp = client.post(
                "/graph/search",
                json={"entity_value": "PUMP-101"},
                headers=TENANT_HEADER,
            )

        assert resp.status_code == 500


# ══════════════════════════════════════════════════════
# 7. /graph/stats
# ══════════════════════════════════════════════════════


class TestGraphStatsEndpoint:
    def test_missing_tenant_returns_422(self, client):
        resp = client.get("/graph/stats")
        assert resp.status_code == 422

    def test_success_returns_stats(self, client):
        stats = {
            "total_nodes": 150,
            "total_edges": 300,
            "entity_types": {"EQUIPMENT_TAG": 80, "FAILURE_MODE": 70},
            "relationship_types": {"FAILED_WITH": 200, "GOVERNED_BY": 100},
            "last_updated": "2026-07-09T10:00:00+00:00",
        }
        import os

        with (
            patch.dict(os.environ, {"VEDA_DATABASE_URL": "postgresql://test:test@localhost/test"}),
            patch("src.api.KnowledgeGraphManager") as MockGM,
        ):
            mock_gm_instance = AsyncMock()
            mock_gm_instance.get_graph_stats = AsyncMock(return_value=stats)
            MockGM.return_value = mock_gm_instance

            resp = client.get("/graph/stats", headers=TENANT_HEADER)

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_nodes"] == 150
        assert data["total_edges"] == 300


class TestIndexDocumentEndpoint:
    DOC = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"

    def test_indexes_for_calling_tenant(self, client):
        with patch("src.api.rag_pipeline") as mock_pipeline:
            mock_pipeline.index_document = AsyncMock(return_value=7)
            resp = client.post(
                "/documents/index",
                json={"document_id": self.DOC, "title": "a.pdf", "raw_text": "hello"},
                headers=TENANT_HEADER,
            )
        assert resp.status_code == 200
        assert resp.json()["chunks_indexed"] == 7
        kwargs = mock_pipeline.index_document.call_args.kwargs
        assert kwargs["tenant_id"] == TENANT_HEADER["X-Tenant-ID"]
        assert kwargs["document_id"] == self.DOC

    def test_other_tenants_document_is_404(self, client):
        from src.rag.local_store import DocumentNotFoundError

        with patch("src.api.rag_pipeline") as mock_pipeline:
            mock_pipeline.index_document = AsyncMock(side_effect=DocumentNotFoundError(self.DOC))
            resp = client.post(
                "/documents/index",
                json={"document_id": self.DOC, "raw_text": "hello"},
                headers=TENANT_HEADER,
            )
        assert resp.status_code == 404

    def test_rejects_bad_document_id_and_empty_text(self, client):
        bad_id = client.post(
            "/documents/index",
            json={"document_id": "not-a-uuid", "raw_text": "x"},
            headers=TENANT_HEADER,
        )
        empty = client.post(
            "/documents/index",
            json={"document_id": self.DOC, "raw_text": ""},
            headers=TENANT_HEADER,
        )
        assert bad_id.status_code == 422
        assert empty.status_code == 422
