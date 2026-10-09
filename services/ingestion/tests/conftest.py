"""
VEDA AI — Ingestion Service Test Fixtures

Shared fixtures for ingestion worker tests.
"""

import os
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_kafka_consumer():
    consumer = MagicMock()
    consumer.subscribe = MagicMock()
    consumer.poll = MagicMock(return_value=None)
    consumer.commit = MagicMock()
    consumer.close = MagicMock()
    return consumer


@pytest.fixture
def mock_kafka_producer():
    producer = MagicMock()
    producer.produce = MagicMock()
    producer.flush = MagicMock()
    return producer


@pytest.fixture
def mock_minio():
    minio = MagicMock()
    minio.fget_object = MagicMock()
    return minio


@pytest.fixture
def sample_upload_event():
    return {
        "tenant_id": "tenant-test-123",
        "document_id": "doc-test-456",
        "file_name": "inspection_report.pdf",
        "file_type": "pdf",
        "storage_path": "documents/2026-01-01_doc-test-456_inspection_report.pdf",
        "storage_bucket": "veda-tenant-test",
        "uploaded_by": "user-admin-001",
        "timestamp": "2026-07-09T10:00:00+00:00",
    }
