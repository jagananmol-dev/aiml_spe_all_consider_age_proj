"""
VEDA AI — Document Ingestion Workers

Kafka consumers that process uploaded documents through the ingestion pipeline:
1. Parse documents (PDF, images, spreadsheets, emails)
2. Extract text content with layout preservation
3. Handle OCR for scanned documents
4. Extract tables and structured data
5. Publish parsed results for downstream processing
"""

import json
import logging
import os
import re
import tempfile
from datetime import UTC, datetime

try:
    from confluent_kafka import Consumer, KafkaError, Producer
except ImportError:  # pragma: no cover - optional dependency
    Consumer = Producer = None  # type: ignore[assignment,misc]

    class KafkaError(Exception):  # type: ignore[no-redef]
        _PARTITION_EOF = 0


try:
    from minio import Minio
except ImportError:  # pragma: no cover - optional dependency
    Minio = None  # type: ignore[assignment,misc]

try:
    import psycopg
except ImportError:  # pragma: no cover - optional dependency
    psycopg = None  # type: ignore[assignment]

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

# Text extraction and OCR are step 1 of the NLP pipeline (nlp_sts/)
from nlp_sts.step01_text_extraction import get_parser

try:
    from pydantic_settings import BaseSettings
except ImportError:  # pragma: no cover - optional dependency

    class BaseSettings:  # type: ignore[no-redef]
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)


# ── Configuration ─────────────────────────────────────
class Settings(BaseSettings):
    """Service configuration from environment variables."""

    # Kafka
    kafka_brokers: str = "localhost:9092"
    kafka_group_id: str = "veda-ingestion-workers"
    kafka_auto_offset_reset: str = "earliest"

    # MinIO
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_secure: bool = False

    # PostgreSQL
    database_url: str = "postgresql://veda:changeme@localhost:5432/veda_db"

    # Processing
    max_file_size_mb: int = 100
    # OCR languages are read from VEDA_OCR_LANGUAGES by nlp_sts/step01_text_extraction.py

    class Config:
        env_prefix = "VEDA_"


settings = Settings()
logger = logging.getLogger("veda.ingestion")


# ── Event Schemas ─────────────────────────────────────
class DocumentUploadedEvent(BaseModel):
    """
    Published by the web app (apps/web/src/lib/kafka.ts) in camelCase,
    e.g. {"tenantId": ..., "documentId": ...}. Snake_case is accepted too.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    tenant_id: str
    document_id: str
    file_name: str
    file_type: str
    storage_path: str
    storage_bucket: str
    uploaded_by: str
    timestamp: str


class DocumentParsedEvent(BaseModel):
    tenant_id: str
    document_id: str
    raw_text: str
    page_count: int
    word_count: int
    tables: list[dict] = []
    parsed_content: dict = {}
    timestamp: str


class DocumentParseFailedEvent(BaseModel):
    tenant_id: str
    document_id: str
    error: str
    timestamp: str


# ── Kafka Setup ───────────────────────────────────────
TOPICS = {
    "DOCUMENT_UPLOADED": "veda.documents.uploaded",
    "DOCUMENT_PARSED": "veda.documents.parsed",
    "DOCUMENT_PARSE_FAILED": "veda.documents.parse-failed",
}


def create_consumer():
    """Create a Kafka consumer configured for the ingestion group."""
    if Consumer is None:
        raise RuntimeError("confluent-kafka is not installed. Install service dependencies first.")
    return Consumer(
        {
            "bootstrap.servers": settings.kafka_brokers,
            "group.id": settings.kafka_group_id,
            "auto.offset.reset": settings.kafka_auto_offset_reset,
            "enable.auto.commit": False,
            "max.poll.interval.ms": 300000,  # 5 min for large doc processing
        }
    )


def create_producer():
    """Create a Kafka producer for publishing parsed results."""
    if Producer is None:
        raise RuntimeError("confluent-kafka is not installed. Install service dependencies first.")
    return Producer(
        {
            "bootstrap.servers": settings.kafka_brokers,
            "acks": "all",
            "retries": 3,
            "linger.ms": 10,
        }
    )


# ── MinIO Client ──────────────────────────────────────
def get_minio_client():
    """Create a MinIO client for document storage access."""
    if Minio is None:
        raise RuntimeError("minio is not installed. Install service dependencies first.")
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


# ── Temp file handling ────────────────────────────────
def safe_temp_path(document_id: str, file_name: str) -> str:
    """
    Build a temp path for a downloaded document that cannot escape the
    temp directory, whatever the (client-supplied) file name contains.
    """
    base = os.path.basename(file_name.replace("\\", "/"))
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base).lstrip(".") or "file"
    safe_id = re.sub(r"[^A-Za-z0-9-]", "_", document_id)
    path = os.path.join(tempfile.gettempdir(), f"veda_{safe_id}_{cleaned[:200]}")
    if os.path.dirname(os.path.abspath(path)) != os.path.abspath(tempfile.gettempdir()):
        raise ValueError(f"Unsafe temp path for document {document_id}")
    return path


# ── Document status in PostgreSQL ─────────────────────
def update_document_status(
    tenant_id: str,
    document_id: str,
    *,
    status: str,
    parsing_status: str | None = None,
    page_count: int | None = None,
    word_count: int | None = None,
    error: str | None = None,
) -> None:
    """
    Record processing progress on the document row so the upload page can
    show it. Uses statuses valid in both schemas (uploaded / processing /
    indexed / failed). Never raises: status reporting must not break parsing.
    """
    if psycopg is None:
        logger.warning("psycopg not installed; cannot update document status")
        return
    try:
        with psycopg.connect(settings.database_url, connect_timeout=5) as conn:
            conn.execute("SELECT set_config('app.current_tenant_id', %s, true)", [tenant_id])
            conn.execute(
                """
                UPDATE documents
                SET status = %s,
                    parsing_status = COALESCE(%s, parsing_status),
                    page_count = COALESCE(%s, page_count),
                    word_count = COALESCE(%s, word_count),
                    metadata = CASE
                        WHEN %s::text IS NULL THEN COALESCE(metadata, '{}'::jsonb) - 'error'
                        ELSE COALESCE(metadata, '{}'::jsonb) || jsonb_build_object('error', %s::text)
                    END,
                    updated_at = NOW()
                WHERE id = %s::uuid AND tenant_id = %s::uuid
                """,
                [
                    status,
                    parsing_status,
                    page_count,
                    word_count,
                    error,
                    error,
                    document_id,
                    tenant_id,
                ],
            )
    except Exception as e:
        logger.warning(f"Could not update status for document {document_id}: {e}")


def user_facing_error(exc: Exception) -> str:
    """Short, safe error text to show on the upload page."""
    message = str(exc).strip() or exc.__class__.__name__
    return message[:300]


# ── Main Worker Loop ──────────────────────────────────
def run_ingestion_worker():
    """
    Main Kafka consumer loop for the ingestion service.

    Listens for document upload events, downloads files from MinIO,
    parses them, and publishes results.
    """
    try:
        consumer = create_consumer()
        producer = create_producer()
        minio_client = get_minio_client()
    except RuntimeError as exc:
        logger.error(str(exc))
        return

    consumer.subscribe([TOPICS["DOCUMENT_UPLOADED"]])

    logger.info("🚀 VEDA Ingestion Worker started. Listening for documents...")

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

            event_data: dict = {}
            try:
                # Parse the upload event
                event_data = json.loads(msg.value().decode("utf-8"))
                event = DocumentUploadedEvent(**event_data)

                logger.info(
                    f"📄 Processing document: {event.file_name} "
                    f"(tenant: {event.tenant_id}, doc: {event.document_id})"
                )
                update_document_status(
                    event.tenant_id,
                    event.document_id,
                    status="processing",
                    parsing_status="processing",
                )

                # Download file from MinIO
                temp_path = safe_temp_path(event.document_id, event.file_name)
                minio_client.fget_object(
                    event.storage_bucket,
                    event.storage_path,
                    temp_path,
                )

                # Get parser and process (temp file is removed even if parsing fails)
                file_ext = event.file_name.rsplit(".", 1)[-1].lower()
                try:
                    parser = get_parser(file_ext)
                    result = parser(temp_path)
                    from .previews import store_preview_safely

                    store_preview_safely(
                        settings.database_url,
                        event.tenant_id,
                        event.document_id,
                        temp_path,
                        file_ext,
                    )
                finally:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)

                if not result["raw_text"].strip():
                    raise ValueError("No readable text found in this file")

                # Publish parsed result
                parsed_event = DocumentParsedEvent(
                    tenant_id=event.tenant_id,
                    document_id=event.document_id,
                    raw_text=result["raw_text"],
                    page_count=result["page_count"],
                    word_count=result["word_count"],
                    tables=result.get("tables", []),
                    # Everything except the text fields already sent above, to
                    # keep the Kafka message small
                    parsed_content={
                        k: v for k, v in result.items() if k not in ("raw_text", "pages", "tables")
                    },
                    timestamp=datetime.now(UTC).isoformat(),
                )

                producer.produce(
                    TOPICS["DOCUMENT_PARSED"],
                    key=event.document_id,
                    value=parsed_event.model_dump_json(),
                )
                producer.flush()

                # Parsed; the graph worker marks it "indexed" once embedded
                update_document_status(
                    event.tenant_id,
                    event.document_id,
                    status="processing",
                    parsing_status="completed",
                    page_count=result["page_count"],
                    word_count=result["word_count"],
                )

                # Commit offset after successful processing
                consumer.commit(asynchronous=False)

                logger.info(
                    f"✅ Document parsed: {event.file_name} "
                    f"({result['page_count']} pages, {result['word_count']} words, "
                    f"{len(result.get('tables', []))} tables)"
                )

            except Exception as e:
                logger.exception("❌ Failed to process document")

                tenant_id = event_data.get("tenantId") or event_data.get("tenant_id")
                document_id = event_data.get("documentId") or event_data.get("document_id")
                if tenant_id and document_id:
                    update_document_status(
                        tenant_id,
                        document_id,
                        status="failed",
                        parsing_status="failed",
                        error=user_facing_error(e),
                    )

                # Publish failure event
                try:
                    fail_event = DocumentParseFailedEvent(
                        tenant_id=tenant_id or "unknown",
                        document_id=document_id or "unknown",
                        error=str(e),
                        timestamp=datetime.now(UTC).isoformat(),
                    )
                    producer.produce(
                        TOPICS["DOCUMENT_PARSE_FAILED"],
                        value=fail_event.model_dump_json(),
                    )
                    producer.flush()
                except Exception:
                    pass

                consumer.commit(asynchronous=False)

    except KeyboardInterrupt:
        logger.info("🛑 Ingestion worker shutting down...")
    finally:
        consumer.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    run_ingestion_worker()
