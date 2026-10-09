"""
VEDA AI — Local Ingestion Worker (no Docker)

Replaces MinIO + Kafka for single-machine demos and development:

1. The web app saves uploads under LOCAL_STORAGE_DIR and inserts a
   `documents` row with storage_bucket = 'local' and status = 'uploaded'.
2. This worker claims queued rows from PostgreSQL (FOR UPDATE SKIP LOCKED,
   so several workers never take the same file), parses the file with the
   same parsers as the Kafka worker, and
3. sends the text to the intelligence service (POST /documents/index),
   which chunks, embeds, stores it, and marks the document "indexed".

Failures are recorded on the document so the upload page can show them.

Run: python -m src.workers.local_worker
"""

import logging
import os
import time
from pathlib import Path

import httpx

from .ingestion_worker import (
    get_parser,
    psycopg,
    settings,
    update_document_status,
    user_facing_error,
)
from .previews import store_preview_safely

logger = logging.getLogger("veda.ingestion.local")

REPO_ROOT = Path(__file__).resolve().parents[4]
STORAGE_DIR = Path(os.environ.get("LOCAL_STORAGE_DIR") or REPO_ROOT / ".data" / "uploads").resolve()
INTELLIGENCE_URL = os.environ.get("VEDA_INTELLIGENCE_URL", "http://localhost:8002").rstrip("/")
INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY", "")
POLL_SECONDS = float(os.environ.get("LOCAL_WORKER_POLL_SECONDS", "2"))
INDEX_TIMEOUT_SECONDS = float(os.environ.get("LOCAL_WORKER_INDEX_TIMEOUT", "900"))
STALE_MINUTES = 15

CLAIM_SQL = """
    UPDATE documents
    SET status = 'processing', parsing_status = 'processing', updated_at = NOW()
    WHERE id = (
        SELECT id FROM documents
        WHERE status = 'uploaded' AND storage_bucket = 'local'
        ORDER BY created_at
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    RETURNING id::text, tenant_id::text, title, file_name, storage_path
"""

REQUEUE_STALE_SQL = """
    UPDATE documents
    SET status = 'uploaded', parsing_status = 'pending', updated_at = NOW()
    WHERE status = 'processing' AND storage_bucket = 'local'
      AND updated_at < NOW() - make_interval(mins => %s)
"""


def resolve_storage_path(storage_path: str) -> Path:
    """Resolve a stored relative path, refusing anything outside STORAGE_DIR."""
    path = (STORAGE_DIR / storage_path).resolve()
    if not path.is_relative_to(STORAGE_DIR):
        raise ValueError("Stored file path is outside the upload directory")
    if not path.is_file():
        raise FileNotFoundError("Uploaded file is missing from local storage")
    return path


def claim_next_document() -> dict | None:
    """Atomically take the oldest queued local upload, or return None."""
    with psycopg.connect(settings.database_url, connect_timeout=5) as conn:
        row = conn.execute(CLAIM_SQL).fetchone()
    if row is None:
        return None
    document_id, tenant_id, title, file_name, storage_path = row
    return {
        "document_id": document_id,
        "tenant_id": tenant_id,
        "title": title or file_name,
        "file_name": file_name,
        "storage_path": storage_path,
    }


def requeue_stale_documents() -> int:
    """Put back documents left in 'processing' by a worker that crashed."""
    with psycopg.connect(settings.database_url, connect_timeout=5) as conn:
        return conn.execute(REQUEUE_STALE_SQL, [STALE_MINUTES]).rowcount


def index_text(tenant_id: str, document_id: str, title: str, raw_text: str) -> int:
    """Send parsed text to the intelligence service for chunking + embedding."""
    headers = {"X-Tenant-ID": tenant_id}
    if INTERNAL_API_KEY:
        headers["X-Internal-Key"] = INTERNAL_API_KEY
    try:
        response = httpx.post(
            f"{INTELLIGENCE_URL}/documents/index",
            json={"document_id": document_id, "title": title, "raw_text": raw_text},
            headers=headers,
            timeout=INDEX_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as e:
        raise RuntimeError(f"Indexing service unavailable ({e.__class__.__name__})") from e

    if response.status_code != 200:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise RuntimeError(f"Indexing failed ({response.status_code}): {detail}")
    return response.json()["chunks_indexed"]


def process_document(job: dict) -> None:
    """Parse one claimed document and index it. Records failure on the row."""
    tenant_id, document_id = job["tenant_id"], job["document_id"]
    started = time.time()
    try:
        path = resolve_storage_path(job["storage_path"])
        extension = job["file_name"].rsplit(".", 1)[-1].lower() if "." in job["file_name"] else ""
        result = get_parser(extension)(str(path))

        if not result["raw_text"].strip():
            raise ValueError("No readable text found in this file")

        store_preview_safely(settings.database_url, tenant_id, document_id, str(path), extension)

        update_document_status(
            tenant_id,
            document_id,
            status="processing",
            parsing_status="completed",
            page_count=result["page_count"],
            word_count=result["word_count"],
        )

        chunks = index_text(tenant_id, document_id, job["title"], result["raw_text"])
        logger.info(
            f"✅ Indexed {job['file_name']} ({result['word_count']} words, {chunks} chunks) "
            f"in {time.time() - started:.1f}s"
        )
    except Exception as e:
        logger.exception(f"❌ Failed to process {job['file_name']}")
        update_document_status(
            tenant_id,
            document_id,
            status="failed",
            parsing_status="failed",
            error=user_facing_error(e),
        )


def run_local_worker() -> None:
    if psycopg is None:
        logger.error("psycopg is not installed. Install service dependencies first.")
        return

    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"🚀 Local ingestion worker started. Watching uploads in {STORAGE_DIR}")

    try:
        requeued = requeue_stale_documents()
        if requeued:
            logger.info(f"Re-queued {requeued} document(s) left processing by a previous run")
    except Exception as e:
        logger.warning(f"Could not re-queue stale documents: {e}")

    try:
        while True:
            try:
                job = claim_next_document()
            except Exception as e:
                logger.warning(f"Database unavailable, retrying: {e}")
                time.sleep(max(POLL_SECONDS, 5))
                continue

            if job is None:
                time.sleep(POLL_SECONDS)
                continue

            logger.info(f"📄 Processing {job['file_name']} (tenant {job['tenant_id']})")
            process_document(job)
    except KeyboardInterrupt:
        logger.info("🛑 Local ingestion worker shutting down...")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    run_local_worker()
