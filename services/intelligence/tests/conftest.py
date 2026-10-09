"""
VEDA AI — Intelligence Service Test Fixtures & Conftest

Shared fixtures for all intelligence service tests.
Provides mocks for external dependencies (DB, Kafka, embeddings)
so unit tests run offline without any infrastructure.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# ── Sample text fixtures ───────────────────────────────

SAMPLE_INDUSTRIAL_TEXT = """
3.2 Pump Maintenance Procedure

Pump PUMP-101 at location Tank Farm A showed bearing seizure during the Q1 2025 inspection.
The operating temperature was recorded as 350°C and pressure at 15.5 kg/cm².

Work Order WO-2024-1423 was raised. Maintenance action: bearing replacement was completed
by Rajesh Kumar on 23-Mar-2024. Refer to OISD-154 for safety requirements.

The pump is governed by ASME Section VIII. Material used: SS316.
Chemical in service: Crude oil. Connected to CDU-A via 6-inch piping.
"""

SAMPLE_SHORT_TEXT = "PUMP-101 failed with bearing seizure at 15.5 kg/cm²."

SAMPLE_EMPTY_TEXT = ""

SAMPLE_TEXT_NO_ENTITIES = "The quick brown fox jumps over the lazy dog."


# ── Graph context fixtures ─────────────────────────────

SAMPLE_GRAPH_CONTEXT = [
    {
        "source_type": "EQUIPMENT_TAG",
        "source_value": "PUMP-101",
        "target_type": "FAILURE_MODE",
        "target_value": "bearing seizure",
        "relationship": "FAILED_WITH",
        "distance": 1,
        "confidence": 0.95,
    },
    {
        "source_type": "EQUIPMENT_TAG",
        "source_value": "PUMP-101",
        "target_type": "EQUIPMENT_TAG",
        "target_value": "CDU-A",
        "relationship": "PART_OF",
        "distance": 1,
        "confidence": 0.90,
    },
]

SAMPLE_ENTITIES_FOUND = [
    {
        "entity_type": "EQUIPMENT_TAG",
        "value": "PUMP-101",
        "normalized_value": "PUMP-101",
        "confidence": 0.95,
    },
    {
        "entity_type": "FAILURE_MODE",
        "value": "bearing seizure",
        "normalized_value": "bearing seizure",
        "confidence": 0.85,
    },
]


# ── Mock fixtures ──────────────────────────────────────


@pytest.fixture
def mock_psycopg_conn():
    """Async mock for a psycopg connection."""
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.commit = AsyncMock()
    conn.rollback = AsyncMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    return conn


@pytest.fixture
def mock_sentence_transformer():
    """Mock for SentenceTransformer model."""
    model = MagicMock()
    import numpy as np

    # Return a normalized 384-dim embedding
    embedding = np.random.rand(384).astype(np.float32)
    embedding /= np.linalg.norm(embedding)
    model.encode.return_value = embedding
    return model


@pytest.fixture
def mock_spacy_model():
    """Mock for spaCy NLP model."""
    nlp = MagicMock()
    doc = MagicMock()
    doc.ents = []
    nlp.return_value = doc
    return nlp
