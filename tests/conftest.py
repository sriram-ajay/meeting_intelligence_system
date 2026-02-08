"""
Root conftest.py — shared fixtures for the entire test suite.

Guidelines:
    • No __init__.py in test sub-directories (avoids shadowing root packages).
    • pytest.ini_options lives in pyproject.toml with pythonpath=["."].
    • Markers: integration, rag_eval.
"""

import sys
from typing import Dict
from unittest.mock import MagicMock

import pytest

from domain.models import (
    IngestionStatus,
    MeetingRecord,
    NormalizedSegment,
    NormalizedTranscript,
)


# ---------------------------------------------------------------------------
# Marker registration
# ---------------------------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line("markers", "integration: mark test as integration test")
    config.addinivalue_line("markers", "rag_eval: mark test as RAG evaluation test")


# ---------------------------------------------------------------------------
# Minimal required settings kwargs for Settings(**BASE_SETTINGS_KWARGS)
# ---------------------------------------------------------------------------

BASE_SETTINGS_KWARGS: Dict[str, str] = {
    "llm_provider": "bedrock",
    "embed_provider": "bedrock",
    "bedrock_region": "eu-west-2",
    "bedrock_llm_model_id": "anthropic.claude-3-haiku-20240307-v1:0",
    "environment": "development",
}


@pytest.fixture()
def base_settings_kwargs() -> Dict[str, str]:
    """Provide the minimal kwargs needed to instantiate ``Settings``."""
    return {**BASE_SETTINGS_KWARGS}


# ---------------------------------------------------------------------------
# Sample transcript fixtures
# ---------------------------------------------------------------------------

SAMPLE_TRANSCRIPT_TEXT = (
    "[00:00:00] Alice: Hello everyone, welcome to the standup.\n"
    "[00:00:15] Bob: Thanks Alice. I worked on the API refactoring yesterday.\n"
    "[00:00:30] Alice: Great, any blockers?\n"
    "[00:00:45] Bob: No blockers. I'll finish the tests today.\n"
    "[00:01:00] Alice: Perfect. Let's move on to Carol.\n"
    "[00:01:15] Carol: I'm working on the deployment pipeline.\n"
)


@pytest.fixture()
def sample_transcript_bytes() -> bytes:
    """Raw transcript bytes suitable for IngestionService.ingest()."""
    return SAMPLE_TRANSCRIPT_TEXT.encode()


@pytest.fixture()
def sample_normalized_segments() -> list[NormalizedSegment]:
    """Ready-made normalized segments for chunking / embedding tests."""
    return [
        NormalizedSegment(timestamp="00:00:00", speaker="Alice", text="Hello everyone"),
        NormalizedSegment(timestamp="00:00:15", speaker="Bob", text="Thanks Alice"),
        NormalizedSegment(timestamp="00:00:30", speaker="Alice", text="Any blockers?"),
    ]


# ---------------------------------------------------------------------------
# Mock adapter factories
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_artifact_store() -> MagicMock:
    """Pre-configured artifact store mock."""
    mock = MagicMock()
    mock.upload_raw.return_value = "s3://bucket/raw/m-1/file.txt"
    mock.get_derived_prefix.return_value = "s3://bucket/derived/m-1/"
    mock.upload_derived.return_value = "s3://bucket/derived/m-1/chunk_map.json"
    mock.download_raw.return_value = SAMPLE_TRANSCRIPT_TEXT.encode()
    return mock


@pytest.fixture()
def mock_metadata_store() -> MagicMock:
    """Pre-configured metadata store mock."""
    return MagicMock()


@pytest.fixture()
def mock_vector_store() -> MagicMock:
    """Pre-configured vector store mock."""
    return MagicMock()


@pytest.fixture()
def mock_embedding_provider() -> MagicMock:
    """Pre-configured embedding provider mock."""
    mock = MagicMock()
    mock.embed_texts.side_effect = lambda texts: [[0.1, 0.2, 0.3] for _ in texts]
    return mock


# ---------------------------------------------------------------------------
# Domain object factories
# ---------------------------------------------------------------------------

@pytest.fixture()
def sample_meeting_record() -> MeetingRecord:
    """A standard MeetingRecord useful for metadata-store or API tests."""
    return MeetingRecord(
        meeting_id="m-test-1",
        title_normalized="standup",
        meeting_date="2026-01-15",
        ingestion_status=IngestionStatus.READY,
    )
