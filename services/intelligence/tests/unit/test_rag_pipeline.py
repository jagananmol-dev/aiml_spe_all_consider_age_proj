"""
VEDA AI — RAG Pipeline Unit Tests

Tests the multi-retrieval pipeline components in isolation.
All external dependencies (psycopg, httpx, sentence-transformers,
KnowledgeGraphManager) are mocked.

Tests:
- embed_query: output shape and type
- reciprocal_rank_fusion: score calculation, deduplication, top-k
- retrieve_vector: parameterized query, RLS set_config
- retrieve_text: OpenSearch integration, error tolerance
- retrieve_graph: entity filtering, empty entities path
- prepare: full pipeline orchestration
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import numpy as np

from src.rag.pipeline import RAGPipeline, RetrievedChunk, tenant_index_suffix


# ── Helpers ────────────────────────────────────────────


def make_chunk(doc_id: str, text: str, score: float, source: str = "vector") -> RetrievedChunk:
    return RetrievedChunk(document_id=doc_id, chunk_text=text, score=score, source=source)


# ══════════════════════════════════════════════════════
# 1. embed_query
# ══════════════════════════════════════════════════════


class TestEmbedQuery:
    def test_returns_list_of_floats(self, mock_sentence_transformer):
        pipeline = RAGPipeline()
        pipeline._embedding_model = mock_sentence_transformer
        result = pipeline.embed_query("What failed?")
        assert isinstance(result, list)
        assert all(isinstance(x, float) for x in result)

    def test_embedding_length_384(self, mock_sentence_transformer):
        pipeline = RAGPipeline()
        pipeline._embedding_model = mock_sentence_transformer
        result = pipeline.embed_query("Test query")
        assert len(result) == 384

    def test_embedding_normalized(self, mock_sentence_transformer):
        """Embeddings should have unit L2 norm (normalized_embeddings=True)."""
        pipeline = RAGPipeline()
        pipeline._embedding_model = mock_sentence_transformer
        result = pipeline.embed_query("Query")
        norm = sum(x**2 for x in result) ** 0.5
        assert abs(norm - 1.0) < 0.01

    def test_calls_encode(self, mock_sentence_transformer):
        pipeline = RAGPipeline()
        pipeline._embedding_model = mock_sentence_transformer
        pipeline.embed_query("My query")
        mock_sentence_transformer.encode.assert_called_once_with(
            "My query", normalize_embeddings=True
        )


# ══════════════════════════════════════════════════════
# 2. Reciprocal Rank Fusion
# ══════════════════════════════════════════════════════


class TestReciprocalRankFusion:
    def test_empty_lists_returns_empty(self):
        pipeline = RAGPipeline()
        result = pipeline.reciprocal_rank_fusion([])
        assert result == []

    def test_single_list_returns_sorted(self):
        pipeline = RAGPipeline()
        chunks = [
            make_chunk("doc-1", "Text A", 0.9),
            make_chunk("doc-2", "Text B", 0.5),
            make_chunk("doc-3", "Text C", 0.1),
        ]
        result = pipeline.reciprocal_rank_fusion([chunks])
        assert len(result) >= 1
        # First result should have highest RRF score
        assert result[0].document_id == "doc-1"

    def test_document_in_multiple_lists_scores_higher(self):
        """A doc appearing in both vector and text results should rank higher via RRF."""
        pipeline = RAGPipeline()
        shared_text = "Shared content about PUMP-101 failure mode details here."
        vector_chunks = [
            make_chunk("doc-shared", shared_text, 0.8, "vector"),
            make_chunk("doc-v-only", "Vector only text.", 0.7, "vector"),
        ]
        text_chunks = [
            make_chunk("doc-shared", shared_text, 0.9, "text"),
            make_chunk("doc-t-only", "Text only result.", 0.6, "text"),
        ]
        result = pipeline.reciprocal_rank_fusion([vector_chunks, text_chunks])
        # The shared document should appear first
        assert result[0].document_id == "doc-shared"

    def test_respects_final_top_k(self):
        """Output must not exceed settings.final_top_k."""
        pipeline = RAGPipeline()
        chunks = [
            make_chunk(f"doc-{i}", f"Text {i} with enough content.", float(i) / 20)
            for i in range(30)
        ]
        result = pipeline.reciprocal_rank_fusion([chunks])
        from src.rag.pipeline import settings

        assert len(result) <= settings.final_top_k

    def test_rrf_score_positive(self):
        pipeline = RAGPipeline()
        chunks = [make_chunk("doc-1", "Some text content here.", 0.5)]
        result = pipeline.reciprocal_rank_fusion([chunks])
        for chunk in result:
            assert chunk.score > 0

    def test_all_empty_lists(self):
        pipeline = RAGPipeline()
        result = pipeline.reciprocal_rank_fusion([[], [], []])
        assert result == []

    def test_deduplication_keeps_longer_text(self):
        """When same doc:text key appears twice, keep the chunk with more text."""
        pipeline = RAGPipeline()
        short = make_chunk("doc-1", "Short text.", 0.9, "vector")
        # Same key prefix (first 100 chars match)
        long_text = "Short text. Extended with more content about the pump failure analysis."
        long = make_chunk("doc-1", long_text, 0.9, "text")
        result = pipeline.reciprocal_rank_fusion([[short], [long]])
        # The longer text should have survived
        kept_texts = [c.chunk_text for c in result]
        assert any(len(t) > len("Short text.") for t in kept_texts)


# ══════════════════════════════════════════════════════
# 3. retrieve_vector (async, DB mocked)
# ══════════════════════════════════════════════════════


class TestRetrieveVector:
    @pytest.mark.asyncio
    async def test_returns_retrieved_chunks(self):
        pipeline = RAGPipeline()
        pipeline._embedding_model = MagicMock()

        # Use an async generator for proper async iteration
        async def async_rows():
            yield ("doc-uuid-1", "Chunk text here", {"title": "Test"}, 0.88)

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=async_rows())
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        with patch("src.rag.pipeline.psycopg") as mock_psycopg:
            mock_psycopg.AsyncConnection.connect = AsyncMock(return_value=mock_conn)
            result = await pipeline.retrieve_vector(
                [0.1] * 384, "11111111-2222-4333-8444-555555555555", top_k=5
            )

        # Should call execute for set_config + for the query
        assert mock_conn.execute.call_count >= 1

    @pytest.mark.asyncio
    async def test_sets_rls_config_first(self):
        """Must call set_config before any data query."""
        pipeline = RAGPipeline()
        call_order = []

        async def async_empty():
            return
            yield  # make it a generator

        async def mock_execute(sql, params=None):
            call_order.append(str(sql)[:50])
            return async_empty()

        mock_conn = AsyncMock()
        mock_conn.execute = mock_execute
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        with patch("src.rag.pipeline.psycopg") as mock_psycopg:
            mock_psycopg.AsyncConnection.connect = AsyncMock(return_value=mock_conn)
            await pipeline.retrieve_vector([0.1] * 384, "11111111-2222-4333-8444-555555555555")

        # First call should be set_config for RLS
        assert "set_config" in call_order[0].lower()

    @pytest.mark.asyncio
    async def test_vector_query_filters_by_tenant(self):
        """Vector search must filter on tenant_id explicitly, not rely on RLS alone."""
        pipeline = RAGPipeline()
        tenant = "11111111-2222-4333-8444-555555555555"
        captured = []

        async def async_empty():
            return
            yield

        async def mock_execute(sql, params=None):
            captured.append((str(sql), params))
            return async_empty()

        mock_conn = AsyncMock()
        mock_conn.execute = mock_execute
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        with patch("src.rag.pipeline.psycopg") as mock_psycopg:
            mock_psycopg.AsyncConnection.connect = AsyncMock(return_value=mock_conn)
            await pipeline.retrieve_vector([0.1] * 384, tenant)

        sql, params = captured[1]
        assert "de.tenant_id = %s" in sql
        assert "d.tenant_id = de.tenant_id" in sql
        assert tenant in params


class TestTenantIndexSuffix:
    def test_accepts_uuid(self):
        tenant = "11111111-2222-4333-8444-555555555555"
        assert tenant_index_suffix(tenant) == tenant

    @pytest.mark.parametrize("bad", ["../other-index", "tenant-123", "x/_search?q=*", ""])
    def test_rejects_non_uuid(self, bad):
        with pytest.raises(ValueError):
            tenant_index_suffix(bad)


# ══════════════════════════════════════════════════════
# 4. retrieve_text (async, httpx mocked)
# ══════════════════════════════════════════════════════


class TestRetrieveText:
    @pytest.mark.asyncio
    async def test_returns_chunks_on_success(self):
        pipeline = RAGPipeline()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "hits": {
                "hits": [
                    {
                        "_id": "doc-1",
                        "_score": 15.5,
                        "_source": {
                            "document_id": "doc-uuid-1",
                            "chunk_text": "PUMP-101 inspection report content.",
                            "title": "Inspection Report",
                        },
                    }
                ]
            }
        }

        with patch("src.rag.pipeline.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await pipeline.retrieve_text(
                "PUMP-101 failure", "11111111-2222-4333-8444-555555555555"
            )

        assert len(result) == 1
        assert result[0].source == "text"
        assert result[0].document_id == "doc-uuid-1"

    @pytest.mark.asyncio
    async def test_returns_empty_on_opensearch_error(self):
        """If OpenSearch is unavailable, return [] — never crash."""
        pipeline = RAGPipeline()

        with patch("src.rag.pipeline.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))
            mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await pipeline.retrieve_text("Query", "11111111-2222-4333-8444-555555555555")

        assert result == []

    @pytest.mark.asyncio
    async def test_non_200_response_returns_empty(self):
        pipeline = RAGPipeline()
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("src.rag.pipeline.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await pipeline.retrieve_text("Query", "11111111-2222-4333-8444-555555555555")

        assert result == []


# ══════════════════════════════════════════════════════
# 5. retrieve_graph (async)
# ══════════════════════════════════════════════════════


class TestRetrieveGraph:
    @pytest.mark.asyncio
    async def test_empty_entities_returns_empty(self):
        pipeline = RAGPipeline()
        # No entities → no graph traversal needed
        mock_gm = AsyncMock()
        pipeline._graph_manager = mock_gm
        chunks, context = await pipeline.retrieve_graph(
            [], [], "11111111-2222-4333-8444-555555555555"
        )
        assert chunks == []
        assert context == []

    @pytest.mark.asyncio
    async def test_graph_results_converted_to_chunks(self):
        pipeline = RAGPipeline()

        graph_result = {
            "source_type": "EQUIPMENT_TAG",
            "source_value": "PUMP-101",
            "target_type": "FAILURE_MODE",
            "target_value": "bearing seizure",
            "relationship": "FAILED_WITH",
            "distance": 1,
            "document_id": "doc-uuid-1",
            "confidence": 0.95,
        }

        mock_conn = AsyncMock()
        mock_async_cm = AsyncMock()
        mock_async_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_async_cm.__aexit__ = AsyncMock(return_value=False)

        mock_gm = MagicMock()
        # _get_connection() is awaited: 'async with await gm._get_connection()'
        mock_gm._get_connection = AsyncMock(return_value=mock_async_cm)
        mock_gm._set_tenant = AsyncMock()
        mock_gm.get_entity_context = AsyncMock(return_value=[graph_result])
        pipeline._graph_manager = mock_gm

        chunks, context = await pipeline.retrieve_graph(
            ["PUMP-101"], ["EQUIPMENT_TAG"], "11111111-2222-4333-8444-555555555555"
        )

        assert len(chunks) == 1
        assert chunks[0].source == "graph"
        assert "PUMP-101" in chunks[0].chunk_text
        assert len(context) == 1

    @pytest.mark.asyncio
    async def test_graph_traversal_failure_does_not_crash(self):
        """Graph traversal errors should be logged and silently skipped."""
        pipeline = RAGPipeline()

        mock_conn = AsyncMock()
        mock_async_cm = AsyncMock()
        mock_async_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_async_cm.__aexit__ = AsyncMock(return_value=False)

        mock_gm = MagicMock()
        # _get_connection() is awaited in the source
        mock_gm._get_connection = AsyncMock(return_value=mock_async_cm)
        mock_gm._set_tenant = AsyncMock()
        mock_gm.get_entity_context = AsyncMock(side_effect=Exception("DB error"))
        pipeline._graph_manager = mock_gm

        # Should not raise
        chunks, context = await pipeline.retrieve_graph(
            ["PUMP-101"], ["EQUIPMENT_TAG"], "11111111-2222-4333-8444-555555555555"
        )
        assert chunks == []


# ══════════════════════════════════════════════════════
# 6. RetrievedChunk dataclass
# ══════════════════════════════════════════════════════


class TestRetrievedChunk:
    def test_default_metadata_is_empty_dict(self):
        chunk = RetrievedChunk("doc-1", "Text", 0.5, "vector")
        assert chunk.metadata == {}

    def test_explicit_metadata(self):
        chunk = RetrievedChunk("doc-1", "Text", 0.5, "vector", {"key": "val"})
        assert chunk.metadata == {"key": "val"}

    def test_fields_accessible(self):
        chunk = RetrievedChunk("doc-id", "Some text", 0.75, "text")
        assert chunk.document_id == "doc-id"
        assert chunk.chunk_text == "Some text"
        assert chunk.score == 0.75
        assert chunk.source == "text"
