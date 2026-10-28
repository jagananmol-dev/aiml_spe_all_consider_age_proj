"""
VEDA AI — Local Ingestion Worker (no Docker)

Replaces MinIO + Kafka for single-machine demos and development:

1. The web app saves uploads under LOCAL_STORAGE_DIR and inserts a
   `documents` row with storage_bucket = 'local' and status = 'uploaded'.
   In hosted mode (STORAGE_BACKEND=db) the bytes are in document_files
   instead and storage_bucket = 'db'; this worker then runs on the owner's
   PC and reads them from the database.
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
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
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

# A document that crashes or hangs the worker is retried at most this often
MAX_ATTEMPTS = 3

CLAIM_SQL = """
    UPDATE documents
    SET status = 'processing', parsing_status = 'processing', updated_at = NOW(),
        metadata = COALESCE(metadata, '{}'::jsonb)
            || jsonb_build_object('attempts', COALESCE((metadata->>'attempts')::int, 0) + 1)
    WHERE id = (
        SELECT id FROM documents
        WHERE status = 'uploaded' AND storage_bucket IN ('local', 'db')
        ORDER BY created_at
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    RETURNING id::text, tenant_id::text, title, file_name, storage_path, storage_bucket
"""

FILE_SQL = "SELECT data FROM document_files WHERE document_id = %s AND tenant_id = %s"

# Documents left in 'processing' by a crashed worker go back to the queue,
# unless they have already had MAX_ATTEMPTS tries: then they are marked
# failed, so one bad file cannot crash the worker over and over
REQUEUE_STALE_SQL = """
    UPDATE documents
    SET status = CASE WHEN COALESCE((metadata->>'attempts')::int, 0) >= %(max)s
                      THEN 'failed' ELSE 'uploaded' END,
        parsing_status = CASE WHEN COALESCE((metadata->>'attempts')::int, 0) >= %(max)s
                              THEN 'failed' ELSE 'pending' END,
        metadata = CASE WHEN COALESCE((metadata->>'attempts')::int, 0) >= %(max)s
                        THEN COALESCE(metadata, '{}'::jsonb) || jsonb_build_object(
                            'error', 'Processing stopped this file several times; it was skipped.')
                        ELSE metadata END,
        updated_at = NOW()
    WHERE status = 'processing' AND storage_bucket IN ('local', 'db')
      AND updated_at < NOW() - make_interval(mins => %(mins)s)
"""


def resolve_storage_path(storage_path: str) -> Path:
    """Resolve a stored relative path, refusing anything outside STORAGE_DIR."""
    path = (STORAGE_DIR / storage_path).resolve()
    if not path.is_relative_to(STORAGE_DIR):
        raise ValueError("Stored file path is outside the upload directory")
    if not path.is_file():
        raise FileNotFoundError("Uploaded file is missing from local storage")
    return path


@contextmanager
def stored_file(job: dict) -> Iterator[Path]:
    """
    The claimed upload as a file on disk. Files kept in the database are
    written to a temporary file (the parsers read paths), removed afterwards.
    """
    if job.get("storage_bucket", "local") != "db":
        yield resolve_storage_path(job["storage_path"])
        return

    with psycopg.connect(settings.database_url, connect_timeout=5) as conn:
        row = conn.execute(FILE_SQL, (job["document_id"], job["tenant_id"])).fetchone()
    if row is None:
        raise FileNotFoundError("Uploaded file is missing from the database")
    suffix = Path(job["file_name"]).suffix
    handle, name = tempfile.mkstemp(prefix="veda-", suffix=suffix)
    try:
        with os.fdopen(handle, "wb") as f:
            f.write(bytes(row[0]))
        yield Path(name)
    finally:
        Path(name).unlink(missing_ok=True)


def claim_next_document() -> dict | None:
    """Atomically take the oldest queued local upload, or return None."""
    with psycopg.connect(settings.database_url, connect_timeout=5) as conn:
        row = conn.execute(CLAIM_SQL).fetchone()
    if row is None:
        return None
    document_id, tenant_id, title, file_name, storage_path, storage_bucket = row
    return {
        "document_id": document_id,
        "tenant_id": tenant_id,
        "title": title or file_name,
        "file_name": file_name,
        "storage_path": storage_path,
        "storage_bucket": storage_bucket,
    }


def requeue_stale_documents() -> int:
    """Put back documents left in 'processing' by a worker that crashed."""
    with psycopg.connect(settings.database_url, connect_timeout=5) as conn:
        return conn.execute(
            REQUEUE_STALE_SQL, {"max": MAX_ATTEMPTS, "mins": STALE_MINUTES}
        ).rowcount


class IndexingUnavailableError(RuntimeError):
    """The intelligence service could not be reached; the file itself is fine."""


def wait_for_intelligence(max_wait_seconds: float = 300) -> bool:
    """Wait until the intelligence service answers, so files are not failed during start-up."""
    deadline = time.time() + max_wait_seconds
    while time.time() < deadline:
        try:
            if httpx.get(f"{INTELLIGENCE_URL}/health", timeout=5).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(2)
    return False


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
        raise IndexingUnavailableError(
            f"Indexing service unavailable ({e.__class__.__name__})"
        ) from e

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
        extension = job["file_name"].rsplit(".", 1)[-1].lower() if "." in job["file_name"] else ""
        with stored_file(job) as path:
            result = get_parser(extension)(str(path))

            if not result["raw_text"].strip():
                raise ValueError("No readable text found in this file")

            store_preview_safely(
                settings.database_url, tenant_id, document_id, str(path), extension
            )

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
    except IndexingUnavailableError:
        # Not the file's fault: back to the queue, and wait for the service
        logger.warning(f"Intelligence service unreachable; re-queued {job['file_name']}")
        update_document_status(
            tenant_id, document_id, status="uploaded", parsing_status="pending"
        )
        wait_for_intelligence()
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

    if not wait_for_intelligence():
        logger.warning(f"Intelligence service at {INTELLIGENCE_URL} is not answering yet")

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
