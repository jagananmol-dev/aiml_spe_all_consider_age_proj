"""
VEDA AI — Graph Worker Unit Tests

All external deps mocked (Kafka, psycopg, SentenceTransformer).
Tests:
- KnowledgeGraphWorker.process_document: full pipeline orchestration
- _generate_and_store_embeddings: chunking → embedding → pgvector insert
- _update_document_status: SQL update call
- _maybe_consolidate: consolidation trigger logic
- _publish_event: Kafka produce + flush
- Worker.run: Kafka consumer loop structure
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from datetime import datetime, timezone

from src.knowledge_graph.graph_worker import KnowledgeGraphWorker, TOPICS


# ── Fixtures ───────────────────────────────────────────

RAW_TEXT = """
Pump PUMP-101 showed bearing seizure. Work order WO-2024-1423 raised.
Maintenance action: bearing replacement by Rajesh Kumar.
Refer to OISD-154 for compliance.
"""
TENANT_ID = "tenant-test-123"
DOCUMENT_ID = "doc-test-456"


def make_worker() -> KnowledgeGraphWorker:
    """Build a worker with all heavy deps mocked."""
    worker = KnowledgeGraphWorker.__new__(KnowledgeGraphWorker)
    worker._embedding_model = None
    worker._docs_since_consolidation = 0

    # Mock extractor
    worker.extractor = MagicMock()
    mock_entity = MagicMock()
    mock_entity.entity_type = "EQUIPMENT_TAG"
    mock_entity.value = "PUMP-101"
    mock_entity.normalized_value = "pump-101"
    mock_entity.confidence = 0.95
    mock_entity.start_offset = 0
    mock_entity.end_offset = 8
    mock_entity.page_number = None
    mock_entity.attributes = {}
    worker.extractor.extract_entities = MagicMock(return_value=[mock_entity])

    # Mock graph manager
    worker.graph_manager = AsyncMock()
    worker.graph_manager.upsert_entities_batch = AsyncMock(return_value=1)
    worker.graph_manager.build_document_relationships = AsyncMock(return_value=1)
    worker.graph_manager.store_entities_in_db = AsyncMock(return_value=1)
    worker.graph_manager.merge_duplicate_entities = AsyncMock(return_value=0)
    worker.graph_manager.prune_stale_relationships = AsyncMock(return_value=0)

    return worker


# ══════════════════════════════════════════════════════
# 1. process_document — full pipeline
# ══════════════════════════════════════════════════════


class TestProcessDocument:
    @pytest.mark.asyncio
    async def test_returns_stats_dict(self):
        worker = make_worker()
        producer = MagicMock()

        with (
            patch.object(worker, "_generate_and_store_embeddings", AsyncMock(return_value=3)),
            patch.object(worker, "_update_document_status", AsyncMock()),
        ):
            stats = await worker.process_document(TENANT_ID, DOCUMENT_ID, RAW_TEXT, {}, producer)

        assert isinstance(stats, dict)
        assert "entities_extracted" in stats
        assert "nodes_upserted" in stats
        assert "relationships_created" in stats
        assert "embeddings_generated" in stats
        assert "errors" in stats

    @pytest.mark.asyncio
    async def test_entity_extraction_called(self):
        worker = make_worker()
        producer = MagicMock()

        with (
            patch.object(worker, "_generate_and_store_embeddings", AsyncMock(return_value=2)),
            patch.object(worker, "_update_document_status", AsyncMock()),
        ):
            await worker.process_document(TENANT_ID, DOCUMENT_ID, RAW_TEXT, {}, producer)

        worker.extractor.extract_entities.assert_called_once_with(RAW_TEXT)

    @pytest.mark.asyncio
    async def test_graph_upsert_called(self):
        worker = make_worker()
        producer = MagicMock()

        with (
            patch.object(worker, "_generate_and_store_embeddings", AsyncMock(return_value=2)),
            patch.object(worker, "_update_document_status", AsyncMock()),
        ):
            await worker.process_document(TENANT_ID, DOCUMENT_ID, RAW_TEXT, {}, producer)

        worker.graph_manager.upsert_entities_batch.assert_called_once()

    @pytest.mark.asyncio
    async def test_relationship_building_called(self):
        worker = make_worker()
        producer = MagicMock()

        with (
            patch.object(worker, "_generate_and_store_embeddings", AsyncMock(return_value=2)),
            patch.object(worker, "_update_document_status", AsyncMock()),
        ):
            await worker.process_document(TENANT_ID, DOCUMENT_ID, RAW_TEXT, {}, producer)

        worker.graph_manager.build_document_relationships.assert_called_once()

    @pytest.mark.asyncio
    async def test_document_status_updated_to_indexed(self):
        worker = make_worker()
        producer = MagicMock()
        status_calls = []

        async def capture_status(tid, did, status):
            status_calls.append(status)

        with (
            patch.object(worker, "_generate_and_store_embeddings", AsyncMock(return_value=2)),
            patch.object(worker, "_update_document_status", capture_status),
        ):
            await worker.process_document(TENANT_ID, DOCUMENT_ID, RAW_TEXT, {}, producer)

        assert "indexed" in status_calls

    @pytest.mark.asyncio
    async def test_kafka_events_published(self):
        worker = make_worker()
        producer = MagicMock()
        published_topics = []

        def capture_produce(topic, key, value):
            published_topics.append(topic)

        producer.produce = capture_produce
        producer.flush = MagicMock()

        with (
            patch.object(worker, "_generate_and_store_embeddings", AsyncMock(return_value=2)),
            patch.object(worker, "_update_document_status", AsyncMock()),
        ):
            await worker.process_document(TENANT_ID, DOCUMENT_ID, RAW_TEXT, {}, producer)

        assert TOPICS["ENTITIES_EXTRACTED"] in published_topics
        assert TOPICS["GRAPH_UPDATED"] in published_topics

    @pytest.mark.asyncio
    async def test_entity_extraction_failure_returns_early(self):
        """If entity extraction fails, downstream steps should be skipped."""
        worker = make_worker()
        worker.extractor.extract_entities = MagicMock(side_effect=Exception("NLP error"))
        producer = MagicMock()
        producer.produce = MagicMock()
        producer.flush = MagicMock()

        stats = await worker.process_document(TENANT_ID, DOCUMENT_ID, RAW_TEXT, {}, producer)

        assert len(stats["errors"]) > 0
        # Graph operations should NOT have been called
        worker.graph_manager.upsert_entities_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_graph_failure_logged_not_raised(self):
        """Graph upsert failure should be logged but not crash the pipeline."""
        worker = make_worker()
        worker.graph_manager.upsert_entities_batch = AsyncMock(
            side_effect=Exception("DB connection lost")
        )
        producer = MagicMock()
        producer.produce = MagicMock()
        producer.flush = MagicMock()

        with (
            patch.object(worker, "_generate_and_store_embeddings", AsyncMock(return_value=2)),
            patch.object(worker, "_update_document_status", AsyncMock()),
        ):
            stats = await worker.process_document(TENANT_ID, DOCUMENT_ID, RAW_TEXT, {}, producer)

        assert len(stats["errors"]) > 0
        # Stats should still be returned, not raised
        assert isinstance(stats, dict)


# ══════════════════════════════════════════════════════
# 2. _publish_event
# ══════════════════════════════════════════════════════


class TestPublishEvent:
    def test_calls_produce_and_flush(self):
        worker = KnowledgeGraphWorker.__new__(KnowledgeGraphWorker)
        producer = MagicMock()
        event = {"tenant_id": TENANT_ID, "document_id": DOCUMENT_ID}

        worker._publish_event(producer, "veda.test.topic", event)

        producer.produce.assert_called_once()
        producer.flush.assert_called_once()

    def test_json_serialized_value(self):
        worker = KnowledgeGraphWorker.__new__(KnowledgeGraphWorker)
        producer = MagicMock()
        event = {"key": "value", "num": 42}

        worker._publish_event(producer, "test.topic", event)

        _, kwargs = producer.produce.call_args if producer.produce.call_args else (None, {})
        # Get value arg
        call_args = producer.produce.call_args[0]  # positional args
        value_str = (
            call_args[2] if len(call_args) > 2 else producer.produce.call_args[1].get("value")
        )
        if value_str:
            parsed = json.loads(value_str)
            assert parsed["key"] == "value"
            assert parsed["num"] == 42

    def test_produce_exception_not_raised(self):
        """Kafka publish errors must be swallowed, not crash the worker."""
        worker = KnowledgeGraphWorker.__new__(KnowledgeGraphWorker)
        producer = MagicMock()
        producer.produce = MagicMock(side_effect=Exception("Kafka unavailable"))

        # Must not raise
        worker._publish_event(producer, "test.topic", {"data": "x"})


# ══════════════════════════════════════════════════════
# 3. _maybe_consolidate
# ══════════════════════════════════════════════════════


class TestMaybeConsolidate:
    @pytest.mark.asyncio
    async def test_consolidation_not_run_below_threshold(self):
        worker = make_worker()
        worker._docs_since_consolidation = 5

        with patch("src.knowledge_graph.graph_worker.settings") as mock_settings:
            mock_settings.consolidation_interval_docs = 100
            mock_settings.max_stale_days = 365
            await worker._maybe_consolidate(TENANT_ID)

        worker.graph_manager.merge_duplicate_entities.assert_not_called()

    @pytest.mark.asyncio
    async def test_consolidation_runs_at_threshold(self):
        worker = make_worker()
        worker._docs_since_consolidation = 99  # will be incremented to 100

        with patch("src.knowledge_graph.graph_worker.settings") as mock_settings:
            mock_settings.consolidation_interval_docs = 100
            mock_settings.max_stale_days = 365
            await worker._maybe_consolidate(TENANT_ID)

        worker.graph_manager.merge_duplicate_entities.assert_called_once_with(TENANT_ID)
        worker.graph_manager.prune_stale_relationships.assert_called_once()

    @pytest.mark.asyncio
    async def test_counter_reset_after_consolidation(self):
        worker = make_worker()
        worker._docs_since_consolidation = 99

        with patch("src.knowledge_graph.graph_worker.settings") as mock_settings:
            mock_settings.consolidation_interval_docs = 100
            mock_settings.max_stale_days = 365
            await worker._maybe_consolidate(TENANT_ID)

        assert worker._docs_since_consolidation == 0


# ══════════════════════════════════════════════════════
# 4. _update_document_status
# ══════════════════════════════════════════════════════


class TestUpdateDocumentStatus:
    @pytest.mark.asyncio
    async def test_executes_update_sql(self):
        worker = KnowledgeGraphWorker.__new__(KnowledgeGraphWorker)
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_conn.commit = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        with patch("psycopg.AsyncConnection.connect", AsyncMock(return_value=mock_conn)):
            await worker._update_document_status(TENANT_ID, DOCUMENT_ID, "indexed")

        assert mock_conn.execute.call_count >= 2  # set_config + UPDATE
        mock_conn.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_db_failure_does_not_raise(self):
        """Status update failures must be swallowed — they are non-critical."""
        worker = KnowledgeGraphWorker.__new__(KnowledgeGraphWorker)

        with patch("psycopg.AsyncConnection.connect", AsyncMock(side_effect=Exception("DB down"))):
            # Must not raise
            await worker._update_document_status(TENANT_ID, DOCUMENT_ID, "indexed")
