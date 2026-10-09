"""
Build previews for already-processed Word, Excel and PowerPoint uploads in
local storage that do not have one yet (documents processed before previews
existed). Safe to run more than once.

Run: python -m src.workers.backfill_previews
"""

import logging

from .ingestion_worker import psycopg, settings
from .local_worker import resolve_storage_path
from .previews import OFFICE_EXTENSIONS, build_preview, save_preview

logger = logging.getLogger("veda.ingestion.backfill")


def backfill() -> tuple[int, int]:
    with psycopg.connect(settings.database_url, connect_timeout=5) as conn:
        rows = conn.execute(
            """
            SELECT d.id::text, d.tenant_id::text, d.file_name, d.storage_path
            FROM documents d
            LEFT JOIN document_previews p ON p.document_id = d.id
            WHERE p.document_id IS NULL AND d.storage_bucket = 'local'
              AND lower(d.file_type) = ANY(%s)
            """,
            [sorted(OFFICE_EXTENSIONS)],
        ).fetchall()

    done = failed = 0
    for document_id, tenant_id, file_name, storage_path in rows:
        try:
            path = resolve_storage_path(storage_path)
            preview = build_preview(str(path), file_name.rsplit(".", 1)[-1])
            if preview is None:  # a format without a preview
                continue
            save_preview(settings.database_url, tenant_id, document_id, preview)
            done += 1
        except Exception as e:
            logger.warning(f"Preview failed for {file_name}: {e}")
            failed += 1
    return done, failed


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    created, errors = backfill()
    print(f"Previews created: {created}, failed: {errors}")
