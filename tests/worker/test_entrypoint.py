"""
Comprehensive tests for worker.entrypoint.main().

Covers:
  - Happy path (env vars set, ingest succeeds, exit 0)
  - Missing env vars (exit 1)
  - Ingest failure (exception, exit 1)
  - Correct S3 URI construction for download_raw
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from worker.entrypoint import main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_settings(**overrides):
    """Return a MagicMock that looks like Settings with sensible v2 defaults."""
    defaults = {
        "s3_raw_bucket": "test-raw-bucket",
        "s3_raw_prefix": "raw",
        "s3_derived_bucket": "test-derived-bucket",
        "s3_derived_prefix": "derived",
        "aws_region": "eu-west-2",
        "dynamodb_table_name": "TestTable",
        "s3_vectors_bucket": "vec-bucket",
        "s3_vectors_index_name": "vec-idx",
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


def _mock_report():
    """Return a MagicMock that looks like IngestionReport."""
    from domain.models import IngestionStatus

    report = MagicMock()
    report.status = IngestionStatus.READY
    report.chunks_created = 5
    report.duration_ms = 123.4
    return report


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWorkerMain:
    @patch.dict(os.environ, {"MEETING_ID": "m-1", "FILENAME": "standup.txt"}, clear=False)
    @patch("worker.entrypoint.get_settings")
    @patch("worker.entrypoint.get_di_container")
    def test_happy_path_returns_zero(self, mock_get_di, mock_get_settings) -> None:
        settings = _mock_settings()
        mock_get_settings.return_value = settings

        container = MagicMock()
        artifact = MagicMock()
        artifact.download_raw.return_value = b"[00:00:00] A: Hi"
        container.get_artifact_store.return_value = artifact

        svc = MagicMock()
        svc.ingest.return_value = _mock_report()
        container.get_ingestion_service.return_value = svc

        mock_get_di.return_value = container

        assert main() == 0

        # Verify download_raw was called with correct URI
        expected_uri = "s3://test-raw-bucket/raw/m-1/standup.txt"
        artifact.download_raw.assert_called_once_with(expected_uri)

        # Verify ingest was called
        svc.ingest.assert_called_once_with(
            meeting_id="m-1",
            filename="standup.txt",
            raw_content=b"[00:00:00] A: Hi",
        )

    @patch.dict(os.environ, {}, clear=False)
    def test_missing_meeting_id_returns_one(self) -> None:
        # Remove MEETING_ID if present
        os.environ.pop("MEETING_ID", None)
        os.environ.pop("FILENAME", None)
        assert main() == 1

    @patch.dict(os.environ, {"MEETING_ID": "m-2", "FILENAME": ""}, clear=False)
    def test_empty_filename_returns_one(self) -> None:
        assert main() == 1

    @patch.dict(os.environ, {"MEETING_ID": "", "FILENAME": "f.txt"}, clear=False)
    def test_empty_meeting_id_returns_one(self) -> None:
        assert main() == 1

    @patch.dict(os.environ, {"MEETING_ID": "m-3", "FILENAME": "fail.txt"}, clear=False)
    @patch("worker.entrypoint.get_settings")
    @patch("worker.entrypoint.get_di_container")
    def test_ingest_failure_returns_one(self, mock_get_di, mock_get_settings) -> None:
        mock_get_settings.return_value = _mock_settings()

        container = MagicMock()
        artifact = MagicMock()
        artifact.download_raw.return_value = b"data"
        container.get_artifact_store.return_value = artifact

        svc = MagicMock()
        svc.ingest.side_effect = RuntimeError("Bedrock timeout")
        container.get_ingestion_service.return_value = svc

        mock_get_di.return_value = container

        assert main() == 1

    @patch.dict(os.environ, {"MEETING_ID": "m-4", "FILENAME": "a.txt"}, clear=False)
    @patch("worker.entrypoint.get_settings")
    @patch("worker.entrypoint.get_di_container")
    def test_download_failure_returns_one(self, mock_get_di, mock_get_settings) -> None:
        mock_get_settings.return_value = _mock_settings()

        container = MagicMock()
        artifact = MagicMock()
        artifact.download_raw.side_effect = Exception("S3 down")
        container.get_artifact_store.return_value = artifact
        container.get_ingestion_service.return_value = MagicMock()

        mock_get_di.return_value = container

        assert main() == 1

    @patch.dict(os.environ, {"MEETING_ID": "m-5", "FILENAME": "test.txt"}, clear=False)
    @patch("worker.entrypoint.get_settings")
    @patch("worker.entrypoint.get_di_container")
    def test_s3_uri_uses_settings_prefix(self, mock_get_di, mock_get_settings) -> None:
        settings = _mock_settings(s3_raw_bucket="custom-bkt", s3_raw_prefix="uploads")
        mock_get_settings.return_value = settings

        container = MagicMock()
        artifact = MagicMock()
        artifact.download_raw.return_value = b"content"
        container.get_artifact_store.return_value = artifact

        svc = MagicMock()
        svc.ingest.return_value = _mock_report()
        container.get_ingestion_service.return_value = svc

        mock_get_di.return_value = container

        main()

        expected_uri = "s3://custom-bkt/uploads/m-5/test.txt"
        artifact.download_raw.assert_called_once_with(expected_uri)
