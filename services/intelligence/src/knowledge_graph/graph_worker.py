"""
VEDA AI — Knowledge Graph Worker

Kafka consumer that continuously maintains the knowledge graph.
This is the "always-active brain" — every document that enters the system
triggers entity extraction, graph node upserts, and relationship building.

Pipeline per document:
1. Consume `veda.documents.parsed` event from Kafka
2. Extract entities using IndustrialEntityExtractor
3. Upsert entity nodes into Apache AGE (MERGE semantics)
4. Build relationships between co-occurring entities
5. Store entities in the relational DB for fast lookups
6. Generate and store embeddings in pgvector
7. Publish `veda.entities.extracted` and `veda.graph.updated` events
8. Periodically run graph consolidation (merge duplicates, prune stale)

The worker is designed to be horizontally scalable — multiple instances
can run in parallel with Kafka consumer group load balancing.
"""

import json
import logging
import time
from datetime import datetime, timezone

try:
    from confluent_kafka import Consumer, Producer, KafkaError
except ImportError:  # pragma: no cover - optional dependency
    Consumer = Producer = None

    class KafkaError(Exception):
        _PARTITION_EOF = 0


try:
    from pydantic_settings import BaseSettings
except ImportError:  # pragma: no cover - optional dependency

    class BaseSettings:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)


try:
    from sentence_transformers import SentenceTransformer
except ImportError:  # pragma: no cover - optional dependency
    SentenceTransformer = None

from ..entity_extraction import semantic
from ..entity_extraction.extractor import IndustrialEntityExtractor
from .graph_manager import KnowledgeGraphManager

logger = logging.getLogger("veda.intelligence.graph_worker")


# ── Configuration ─────────────────────────────────────


class GraphWorkerSettings(BaseSettings):
    """Configuration for the knowledge graph worker."""

    # Kafka
    kafka_brokers: str = "localhost:9092"
    kafka_group_id: str = "veda-graph-workers"
    kafka_auto_offset_reset: str = "earliest"

    # Database
    database_url: str = "postgresql://veda:changeme@localhost:5432/veda_db"

    # Embeddings
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dimension: int = 384

    # Chunking
    max_chunk_size: int = 1500
    chunk_overlap: int = 200

    # Graph maintenance
    consolidation_interval_docs: int = 100  # Run consolidation every N documents
    max_stale_days: int = 365  # Prune relationships older than this

    class Config:
        env_prefix = "VEDA_"


settings = GraphWorkerSettings()


# ── Kafka Topics ──────────────────────────────────────

TOPICS = {
    "DOCUMENT_PARSED": "veda.documents.parsed",
    "ENTITIES_EXTRACTED": "veda.entities.extracted",
    "ENTITIES_EXTRACTION_FAILED": "veda.entities.extraction-failed",
    "GRAPH_UPDATED": "veda.graph.updated",
    "EMBEDDINGS_GENERATED": "veda.embeddings.generated",
    "EMBEDDINGS_FAILED": "veda.embeddings.failed",
}


# ── Worker Class ──────────────────────────────────────


class KnowledgeGraphWorker:
    """
    Kafka consumer that maintains the knowledge graph continuously.

    Processes parsed documents through:
    entity extraction → graph upsert → relationship building → embedding generation

    This ensures the "brain" is always up-to-date with the latest documents.
    """

    def __init__(self):
        self.extractor = IndustrialEntityExtractor()
        self.graph_manager = KnowledgeGraphManager(settings.database_url)
        self._embedding_model = None
        self._docs_since_consolidation = 0

    @property
    def embedding_model(self):
        """Lazy-load the embedding model."""
        if SentenceTransformer is None:
            raise RuntimeError(
                "sentence-transformers is not installed. Install service dependencies first."
            )
        if self._embedding_model is None:
            logger.info(f"Loading embedding model: {settings.embedding_model}")
            model = SentenceTransformer(settings.embedding_model)
            # Entity typing uses the same model (see entity_extraction/semantic.py)
            semantic.set_encoder(
                lambda texts: model.encode(
                    texts, normalize_embeddings=True, batch_size=64, show_progress_bar=False
                )
            )
            self._embedding_model = model
        return self._embedding_model

    def create_consumer(self):
        """Create a Kafka consumer for the graph worker group."""
        if Consumer is None:
            raise RuntimeError(
                "confluent-kafka is not installed. Install service dependencies first."
            )
        return Consumer(
            {
                "bootstrap.servers": settings.kafka_brokers,
                "group.id": settings.kafka_group_id,
                "auto.offset.reset": settings.kafka_auto_offset_reset,
                "enable.auto.commit": False,
                "max.poll.interval.ms": 600000,  # 10 min for heavy processing
            }
        )

    def create_producer(self):
        """Create a Kafka producer for publishing events."""
        if Producer is None:
            raise RuntimeError(
                "confluent-kafka is not installed. Install service dependencies first."
            )
        return Producer(
            {
                "bootstrap.servers": settings.kafka_brokers,
                "acks": "all",
                "retries": 3,
                "linger.ms": 10,
            }
        )

    async def process_document(
        self,
        tenant_id: str,
        document_id: str,
        raw_text: str,
        parsed_content: dict,
        producer: Producer,
    ) -> dict:
        """
        Process a single parsed document through the full intelligence pipeline.

        Steps:
        1. Extract entities from the document text
        2. Upsert entity nodes into the knowledge graph
        3. Build relationships between entities
        4. Store entities in relational DB
        5. Generate and store embeddings for vector search
        6. Publish downstream events

        Returns a summary dict with processing statistics.
        """
        start_time = time.time()
        stats = {
            "document_id": document_id,
            "entities_extracted": 0,
            "nodes_upserted": 0,
            "relationships_created": 0,
            "embeddings_generated": 0,
            "errors": [],
        }

        # ─── Step 1: Extract entities ─────────────────
        logger.info(f"📝 Extracting entities from document {document_id}...")

        try:
            extracted_entities = self.extractor.extract_entities(raw_text)
            entity_dicts = [
                {
                    "entity_type": e.entity_type,
                    "value": e.value,
                    "normalized_value": e.normalized_value,
                    "confidence": e.confidence,
                    "start_offset": e.start_offset,
                    "end_offset": e.end_offset,
                    "page_number": e.page_number,
                    "attributes": e.attributes,
                }
                for e in extracted_entities
            ]
            stats["entities_extracted"] = len(entity_dicts)

            logger.info(f"  → Extracted {len(entity_dicts)} entities from {len(raw_text)} chars")

        except Exception as e:
            error_msg = f"Entity extraction failed: {e}"
            logger.error(error_msg, exc_info=True)
            stats["errors"].append(error_msg)

            # Publish failure event
            self._publish_event(
                producer,
                TOPICS["ENTITIES_EXTRACTION_FAILED"],
                {
                    "tenant_id": tenant_id,
                    "document_id": document_id,
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
            return stats

        # ─── Step 2: Upsert entity nodes ──────────────
        logger.info(f"🧠 Upserting {len(entity_dicts)} nodes into knowledge graph...")

        try:
            nodes_upserted = await self.graph_manager.upsert_entities_batch(
                tenant_id=tenant_id,
                document_id=document_id,
                entities=entity_dicts,
            )
            stats["nodes_upserted"] = nodes_upserted

        except Exception as e:
            error_msg = f"Graph node upsert failed: {e}"
            logger.error(error_msg, exc_info=True)
            stats["errors"].append(error_msg)

        # ─── Step 3: Build relationships ──────────────
        logger.info(f"🔗 Building relationships between entities...")

        try:
            relationships_created = await self.graph_manager.build_document_relationships(
                tenant_id=tenant_id,
                document_id=document_id,
                entities=entity_dicts,
                text=raw_text,
            )
            stats["relationships_created"] = relationships_created

        except Exception as e:
            error_msg = f"Relationship building failed: {e}"
            logger.error(error_msg, exc_info=True)
            stats["errors"].append(error_msg)

        # ─── Step 4: Store entities in relational DB ──
        try:
            await self.graph_manager.store_entities_in_db(
                tenant_id=tenant_id,
                document_id=document_id,
                entities=entity_dicts,
            )
        except Exception as e:
            logger.warning(f"Entity DB storage failed (non-critical): {e}")

        # ─── Step 5: Generate embeddings ──────────────
        logger.info(f"📐 Generating embeddings for document chunks...")

        try:
            embeddings_count = await self._generate_and_store_embeddings(
                tenant_id=tenant_id,
                document_id=document_id,
                raw_text=raw_text,
            )
            stats["embeddings_generated"] = embeddings_count

            # Publish embeddings event
            self._publish_event(
                producer,
                TOPICS["EMBEDDINGS_GENERATED"],
                {
                    "tenant_id": tenant_id,
                    "document_id": document_id,
                    "chunks_embedded": embeddings_count,
                    "model": settings.embedding_model,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )

        except Exception as e:
            error_msg = f"Embedding generation failed: {e}"
            logger.error(error_msg, exc_info=True)
            stats["errors"].append(error_msg)

            self._publish_event(
                producer,
                TOPICS["EMBEDDINGS_FAILED"],
                {
                    "tenant_id": tenant_id,
                    "document_id": document_id,
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )

        # ─── Step 6: Publish success events ───────────
        self._publish_event(
            producer,
            TOPICS["ENTITIES_EXTRACTED"],
            {
                "tenant_id": tenant_id,
                "document_id": document_id,
                "entities": [
                    {
                        "type": e["entity_type"],
                        "value": e["value"],
                        "normalizedValue": e["normalized_value"],
                        "confidence": e["confidence"],
                        "pageNumber": e.get("page_number"),
                    }
                    for e in entity_dicts
                ],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

        self._publish_event(
            producer,
            TOPICS["GRAPH_UPDATED"],
            {
                "tenant_id": tenant_id,
                "document_id": document_id,
                "nodesCreated": stats["nodes_upserted"],
                "edgesCreated": stats["relationships_created"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

        # ─── Step 7: Update document status ───────────
        await self._update_document_status(tenant_id, document_id, "indexed")

        elapsed = time.time() - start_time
        logger.info(
            f"✅ Document {document_id} processed in {elapsed:.1f}s: "
            f"{stats['entities_extracted']} entities, "
            f"{stats['nodes_upserted']} nodes, "
            f"{stats['relationships_created']} relationships, "
            f"{stats['embeddings_generated']} embeddings"
        )

        return stats

    async def _generate_and_store_embeddings(
        self,
        tenant_id: str,
        document_id: str,
        raw_text: str,
    ) -> int:
        """
        Generate embeddings for document chunks and store in pgvector.

        Uses the ChunkBuilder for semantic splitting, then generates
        embeddings with sentence-transformers.
        """
        import psycopg
        from .chunk_builder import ChunkBuilder

        builder = ChunkBuilder(
            max_chunk_size=settings.max_chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )

        # Split text into chunks
        chunks = builder.merge_small_chunks(builder.split_into_chunks(raw_text, document_id))

        if not chunks:
            return 0

        # Generate embeddings in batch
        chunk_texts = [c.text for c in chunks]
        embeddings = self.embedding_model.encode(
            chunk_texts, normalize_embeddings=True, show_progress_bar=False
        )

        # Store in pgvector
        stored = 0
        async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
            await conn.execute("SELECT set_config('app.current_tenant_id', %s, true)", [tenant_id])

            for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                try:
                    embedding_str = f"[{','.join(str(x) for x in embedding.tolist())}]"

                    await conn.execute(
                        """
                        INSERT INTO document_embeddings (
                            tenant_id, document_id, chunk_index,
                            chunk_text, chunk_metadata, embedding
                        ) VALUES (%s, %s, %s, %s, %s::jsonb, %s::vector)
                        """,
                        [
                            tenant_id,
                            document_id,
                            idx,
                            chunk.text,
                            json.dumps(chunk.metadata),
                            embedding_str,
                        ],
                    )
                    stored += 1
                except Exception as e:
                    logger.warning(f"Failed to store embedding for chunk {idx}: {e}")

            await conn.commit()

        return stored

    async def _update_document_status(self, tenant_id: str, document_id: str, status: str):
        """Update the document's processing status in the database."""
        import psycopg

        try:
            async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
                await conn.execute(
                    "SELECT set_config('app.current_tenant_id', %s, true)", [tenant_id]
                )

                await conn.execute(
                    """
                    UPDATE documents
                    SET status = %s,
                        extraction_status = 'completed',
                        embedding_status = 'completed',
                        updated_at = NOW()
                    WHERE id = %s::uuid
                    """,
                    [status, document_id],
                )
                await conn.commit()

        except Exception as e:
            logger.warning(f"Failed to update document status: {e}")

    async def _maybe_consolidate(self, tenant_id: str):
        """
        Run graph consolidation periodically.

        Every N documents processed, merge duplicates and prune stale
        relationships to keep the graph clean and efficient.
        """
        self._docs_since_consolidation += 1

        if self._docs_since_consolidation >= settings.consolidation_interval_docs:
            logger.info(
                f"🔧 Running graph consolidation "
                f"(every {settings.consolidation_interval_docs} docs)..."
            )

            merged = await self.graph_manager.merge_duplicate_entities(tenant_id)
            pruned = await self.graph_manager.prune_stale_relationships(
                tenant_id, settings.max_stale_days
            )

            logger.info(
                f"  → Consolidation complete: "
                f"{merged} duplicates merged, {pruned} stale edges pruned"
            )

            self._docs_since_consolidation = 0

    def _publish_event(self, producer: Producer, topic: str, event: dict):
        """Publish an event to Kafka."""
        try:
            producer.produce(
                topic,
                key=event.get("document_id", ""),
                value=json.dumps(event),
            )
            producer.flush()
        except Exception as e:
            logger.error(f"Failed to publish event to {topic}: {e}")

    # ── Main Worker Loop ──────────────────────────────

    def run(self):
        """
        Main Kafka consumer loop.

        Listens for `veda.documents.parsed` events and processes each
        document through the full intelligence pipeline.

        This loop runs forever — it's the heartbeat of the knowledge graph.
        """
        import asyncio

        # Load the embedding model up front: entity extraction types phrases
        # with it, and it runs before the embedding step of the first document
        try:
            self.embedding_model
        except Exception as e:
            logger.warning(f"Embedding model unavailable, typing entities with patterns only: {e}")

        try:
            consumer = self.create_consumer()
            producer = self.create_producer()
        except RuntimeError as exc:
            logger.error(str(exc))
            return

        consumer.subscribe([TOPICS["DOCUMENT_PARSED"]])

        logger.info("🧠 VEDA Knowledge Graph Worker started. The brain is alive and listening...")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            while True:
                msg = consumer.poll(timeout=1.0)

                if msg is None:
                    continue

                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    logger.error(f"Kafka error: {msg.error()}")
                    continue

                try:
                    # Parse the document parsed event
                    event_data = json.loads(msg.value().decode("utf-8"))

                    tenant_id = event_data["tenant_id"]
                    document_id = event_data["document_id"]
                    raw_text = event_data.get("raw_text", "")

                    logger.info(
                        f"📥 Received parsed document: {document_id} "
                        f"(tenant: {tenant_id}, {len(raw_text)} chars)"
                    )

                    if not raw_text.strip():
                        logger.warning(f"Empty document text, skipping: {document_id}")
                        consumer.commit(asynchronous=False)
                        continue

                    # Process the document
                    stats = loop.run_until_complete(
                        self.process_document(
                            tenant_id=tenant_id,
                            document_id=document_id,
                            raw_text=raw_text,
                            parsed_content=event_data.get("parsed_content", {}),
                            producer=producer,
                        )
                    )

                    # Maybe run consolidation
                    loop.run_until_complete(self._maybe_consolidate(tenant_id))

                    # Commit offset after successful processing
                    consumer.commit(asynchronous=False)

                except Exception as e:
                    logger.error(f"❌ Failed to process document: {e}", exc_info=True)
                    # Still commit to avoid reprocessing poison pills forever
                    consumer.commit(asynchronous=False)

        except KeyboardInterrupt:
            logger.info("🛑 Knowledge Graph Worker shutting down...")
        finally:
            consumer.close()
            loop.close()


# ── Entry Point ───────────────────────────────────────


def run_graph_worker():
    """Start the knowledge graph maintenance worker."""
    worker = KnowledgeGraphWorker()
    worker.run()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    run_graph_worker()
