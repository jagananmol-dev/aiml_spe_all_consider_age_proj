"""
VEDA AI — Local ingestion worker tests (no Kafka / MinIO)
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.workers import local_worker

TENANT = "11111111-2222-4333-8444-555555555555"
DOC = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(local_worker, "STORAGE_DIR", tmp_path.resolve())
    return tmp_path


def _job(storage_path, file_name="notes.txt"):
    return {
        "document_id": DOC,
        "tenant_id": TENANT,
        "title": file_name,
        "file_name": file_name,
        "storage_path": storage_path,
    }


class TestResolveStoragePath:
    def test_inside_storage_dir(self, storage):
        (storage / TENANT).mkdir()
        f = storage / TENANT / "a.txt"
        f.write_text("x")
        assert local_worker.resolve_storage_path(f"{TENANT}/a.txt") == f.resolve()

    @pytest.mark.parametrize("bad", ["../outside.txt", "../../etc/passwd", "/etc/passwd"])
    def test_rejects_paths_outside_storage(self, storage, bad):
        with pytest.raises(ValueError):
            local_worker.resolve_storage_path(bad)

    def test_missing_file(self, storage):
        with pytest.raises(FileNotFoundError):
            local_worker.resolve_storage_path("nope.txt")


class TestProcessDocument:
    def test_success_parses_then_indexes(self, storage):
        (storage / "notes.txt").write_text("Revenue grew 12% in Q3.", encoding="utf-8")
        with (
            patch.object(local_worker, "update_document_status") as status,
            patch.object(local_worker, "index_text", return_value=1) as index,
        ):
            local_worker.process_document(_job("notes.txt"))

        index.assert_called_once_with(TENANT, DOC, "notes.txt", "Revenue grew 12% in Q3.")
        kwargs = status.call_args.kwargs
        assert kwargs["status"] == "processing"
        assert kwargs["parsing_status"] == "completed"
        assert kwargs["word_count"] == 5

    def test_empty_file_marked_failed(self, storage):
        (storage / "empty.txt").write_text("   ", encoding="utf-8")
        with (
            patch.object(local_worker, "update_document_status") as status,
            patch.object(local_worker, "index_text") as index,
        ):
            local_worker.process_document(_job("empty.txt", "empty.txt"))
        index.assert_not_called()
        assert status.call_args.kwargs["status"] == "failed"
        assert "No readable text" in status.call_args.kwargs["error"]

    def test_indexing_error_marked_failed(self, storage):
        (storage / "notes.txt").write_text("hello", encoding="utf-8")
        with (
            patch.object(local_worker, "update_document_status") as status,
            patch.object(local_worker, "index_text", side_effect=RuntimeError("Indexing failed")),
        ):
            local_worker.process_document(_job("notes.txt"))
        assert status.call_args.kwargs == {
            "status": "failed",
            "parsing_status": "failed",
            "error": "Indexing failed",
        }


class TestIndexText:
    def test_sends_tenant_and_internal_key(self, monkeypatch):
        monkeypatch.setattr(local_worker, "INTERNAL_API_KEY", "k3y")
        response = MagicMock(status_code=200)
        response.json.return_value = {"chunks_indexed": 4}
        with patch.object(local_worker.httpx, "post", return_value=response) as post:
            assert local_worker.index_text(TENANT, DOC, "t", "text") == 4
        headers = post.call_args.kwargs["headers"]
        assert headers == {"X-Tenant-ID": TENANT, "X-Internal-Key": "k3y"}

    def test_service_down_gives_clear_error(self):
        with patch.object(local_worker.httpx, "post", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(RuntimeError, match="Indexing service unavailable"):
                local_worker.index_text(TENANT, DOC, "t", "text")

    def test_http_error_includes_detail(self):
        response = MagicMock(status_code=404)
        response.json.return_value = {"detail": "Document not found"}
        with patch.object(local_worker.httpx, "post", return_value=response):
            with pytest.raises(RuntimeError, match="Document not found"):
                local_worker.index_text(TENANT, DOC, "t", "text")


class TestClaim:
    def test_claim_uses_skip_locked_and_local_bucket(self):
        conn = MagicMock()
        conn.__enter__.return_value = conn
        conn.execute.return_value.fetchone.return_value = (DOC, TENANT, None, "a.csv", "p")
        with patch.object(local_worker.psycopg, "connect", return_value=conn):
            job = local_worker.claim_next_document()
        sql = conn.execute.call_args.args[0]
        assert "FOR UPDATE SKIP LOCKED" in sql
        assert "storage_bucket = 'local'" in sql
        assert job["title"] == "a.csv"  # falls back to file name

    def test_no_work(self):
        conn = MagicMock()
        conn.__enter__.return_value = conn
        conn.execute.return_value.fetchone.return_value = None
        with patch.object(local_worker.psycopg, "connect", return_value=conn):
            assert local_worker.claim_next_document() is None
