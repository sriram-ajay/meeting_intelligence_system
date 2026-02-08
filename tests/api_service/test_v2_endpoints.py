"""
Comprehensive tests for V2 API endpoints.

Covers: health, upload_v2, status, meetings, query_v2,
and the _trigger_ecs_worker helper.
"""

import pytest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from api_service.src.main import app
from domain.models import IngestionStatus, MeetingRecord

client = TestClient(app)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_returns_200(self) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_health_includes_environment(self) -> None:
        body = client.get("/health").json()
        assert "environment" in body
        assert "embed_provider" in body


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_meeting(
    meeting_id: str = "abc-123",
    status: IngestionStatus = IngestionStatus.PENDING,
    error: str | None = None,
    participants: list | None = None,
) -> MeetingRecord:
    return MeetingRecord(
        meeting_id=meeting_id,
        title_normalized="standup",
        meeting_date="2026-01-15",
        ingestion_status=status,
        error_message=error,
        participants=participants or [],
    )


def _patch_container():
    """Return a mock DI container with artifact + metadata stores."""
    container = MagicMock()
    artifact = MagicMock()
    metadata = MagicMock()
    artifact.upload_raw.return_value = "s3://bucket/raw/abc/file.txt"
    artifact.get_derived_prefix.return_value = "s3://bucket/derived/abc/"
    container.get_artifact_store.return_value = artifact
    container.get_metadata_store.return_value = metadata
    return container, artifact, metadata


# ---------------------------------------------------------------------------
# POST /api/v2/upload
# ---------------------------------------------------------------------------

class TestUploadV2:
    @patch("api_service.src.main._trigger_ecs_worker")
    @patch("api_service.src.main.get_di_container")
    def test_upload_returns_202(self, mock_get_di, mock_trigger) -> None:
        container, _, metadata = _patch_container()
        mock_get_di.return_value = container

        files = {"file": ("test.txt", b"[00:00:00] Alice: Hello", "text/plain")}
        response = client.post("/api/v2/upload", files=files)

        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "PENDING"
        assert "meeting_id" in body

    @patch("api_service.src.main._trigger_ecs_worker")
    @patch("api_service.src.main.get_di_container")
    def test_upload_stores_raw_and_metadata(self, mock_get_di, mock_trigger) -> None:
        container, artifact, metadata = _patch_container()
        mock_get_di.return_value = container

        files = {"file": ("test.txt", b"[00:00:00] Bob: Hi", "text/plain")}
        client.post("/api/v2/upload", files=files)

        artifact.upload_raw.assert_called_once()
        metadata.put_meeting.assert_called_once()

    @patch("api_service.src.main._trigger_ecs_worker")
    @patch("api_service.src.main.get_di_container")
    def test_upload_triggers_worker(self, mock_get_di, mock_trigger) -> None:
        container, _, _ = _patch_container()
        mock_get_di.return_value = container

        files = {"file": ("test.txt", b"content", "text/plain")}
        client.post("/api/v2/upload", files=files)

        mock_trigger.assert_called_once()

    def test_upload_empty_file(self) -> None:
        files = {"file": ("test.txt", b"", "text/plain")}
        response = client.post("/api/v2/upload", files=files)
        assert response.status_code == 400

    def test_upload_wrong_extension(self) -> None:
        files = {"file": ("test.pdf", b"content", "application/pdf")}
        response = client.post("/api/v2/upload", files=files)
        assert response.status_code == 400

    @patch("api_service.src.main._trigger_ecs_worker")
    @patch("api_service.src.main.get_di_container")
    def test_upload_response_body_shape(self, mock_get_di, mock_trigger) -> None:
        """Response must have meeting_id, status, message."""
        container, _, _ = _patch_container()
        mock_get_di.return_value = container

        files = {"file": ("test.txt", b"content", "text/plain")}
        body = client.post("/api/v2/upload", files=files).json()
        assert set(body.keys()) == {"meeting_id", "status", "message"}

    @patch("api_service.src.main._trigger_ecs_worker")
    @patch("api_service.src.main.get_di_container")
    def test_upload_s3_error_returns_500(self, mock_get_di, mock_trigger) -> None:
        """If artifact store throws, API returns 500."""
        container, artifact, _ = _patch_container()
        artifact.upload_raw.side_effect = RuntimeError("S3 down")
        mock_get_di.return_value = container

        files = {"file": ("test.txt", b"content", "text/plain")}
        response = client.post("/api/v2/upload", files=files)
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# GET /api/status/{meeting_id}
# ---------------------------------------------------------------------------

class TestStatusEndpoint:
    @patch("api_service.src.main.get_di_container")
    def test_status_pending(self, mock_get_di) -> None:
        container, _, metadata = _patch_container()
        metadata.get_meeting.return_value = _mock_meeting(status=IngestionStatus.PENDING)
        mock_get_di.return_value = container

        response = client.get("/api/status/abc-123")
        assert response.status_code == 200
        assert response.json()["status"] == "PENDING"

    @patch("api_service.src.main.get_di_container")
    def test_status_ready(self, mock_get_di) -> None:
        container, _, metadata = _patch_container()
        metadata.get_meeting.return_value = _mock_meeting(status=IngestionStatus.READY)
        mock_get_di.return_value = container

        response = client.get("/api/status/abc-123")
        assert response.status_code == 200
        assert response.json()["status"] == "READY"

    @patch("api_service.src.main.get_di_container")
    def test_status_failed_includes_error(self, mock_get_di) -> None:
        container, _, metadata = _patch_container()
        metadata.get_meeting.return_value = _mock_meeting(
            status=IngestionStatus.FAILED, error="parse failed"
        )
        mock_get_di.return_value = container

        response = client.get("/api/status/abc-123")
        body = response.json()
        assert body["status"] == "FAILED"
        assert body["error"] == "parse failed"

    @patch("api_service.src.main.get_di_container")
    def test_status_not_found(self, mock_get_di) -> None:
        container, _, metadata = _patch_container()
        metadata.get_meeting.return_value = None
        mock_get_di.return_value = container

        response = client.get("/api/status/nonexistent")
        assert response.status_code == 404

    @patch("api_service.src.main.get_di_container")
    def test_status_response_body_shape(self, mock_get_di) -> None:
        container, _, metadata = _patch_container()
        metadata.get_meeting.return_value = _mock_meeting(status=IngestionStatus.READY)
        mock_get_di.return_value = container

        body = client.get("/api/status/abc-123").json()
        assert "meeting_id" in body
        assert "status" in body
        assert "title" in body


# ---------------------------------------------------------------------------
# GET /api/meetings
# ---------------------------------------------------------------------------

class TestMeetingsEndpoint:
    @patch("api_service.src.main.get_di_container")
    def test_list_meetings_empty(self, mock_get_di) -> None:
        container, _, metadata = _patch_container()
        metadata.query_meetings.return_value = []
        mock_get_di.return_value = container

        response = client.get("/api/meetings")
        assert response.status_code == 200
        assert response.json() == []

    @patch("api_service.src.main.get_di_container")
    def test_list_meetings_returns_records(self, mock_get_di) -> None:
        container, _, metadata = _patch_container()
        metadata.query_meetings.return_value = [
            _mock_meeting("m-1", IngestionStatus.READY),
            _mock_meeting("m-2", IngestionStatus.PENDING),
        ]
        mock_get_di.return_value = container

        response = client.get("/api/meetings")
        body = response.json()
        assert len(body) == 2
        assert body[0]["meeting_id"] == "m-1"
        assert body[1]["status"] == "PENDING"

    @patch("api_service.src.main.get_di_container")
    def test_list_meetings_with_filter(self, mock_get_di) -> None:
        container, _, metadata = _patch_container()
        metadata.query_meetings.return_value = []
        mock_get_di.return_value = container

        client.get("/api/meetings?date=2026-01-15&participant=Alice")
        metadata.query_meetings.assert_called_once_with(
            date="2026-01-15", title=None, participant="Alice"
        )

    @patch("api_service.src.main.get_di_container")
    def test_list_meetings_record_shape(self, mock_get_di) -> None:
        """Each record in the list must have the expected fields."""
        container, _, metadata = _patch_container()
        metadata.query_meetings.return_value = [
            _mock_meeting("m-1", IngestionStatus.READY, participants=["Alice"]),
        ]
        mock_get_di.return_value = container

        body = client.get("/api/meetings").json()
        record = body[0]
        assert set(record.keys()) == {"meeting_id", "title", "date", "status", "participants"}

    @patch("api_service.src.main.get_di_container")
    def test_list_meetings_metadata_error_returns_500(self, mock_get_di) -> None:
        container, _, metadata = _patch_container()
        metadata.query_meetings.side_effect = RuntimeError("DynamoDB down")
        mock_get_di.return_value = container

        response = client.get("/api/meetings")
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# _trigger_ecs_worker
# ---------------------------------------------------------------------------

class TestTriggerECSWorker:
    @patch("api_service.src.main.settings")
    def test_noop_when_no_cluster(self, mock_settings) -> None:
        """When ecs_cluster_name is empty, the function is a no-op."""
        mock_settings.ecs_cluster_name = ""
        from api_service.src.main import _trigger_ecs_worker

        # Should not raise
        _trigger_ecs_worker("m-1", "file.txt")

    @patch("api_service.src.main.boto3.client")
    @patch("api_service.src.main.settings")
    def test_calls_run_task_when_cluster_set(self, mock_settings, mock_boto) -> None:
        mock_settings.ecs_cluster_name = "my-cluster"
        mock_settings.ecs_worker_task_def = "task-def"
        mock_settings.ecs_worker_subnets = "subnet-a,subnet-b"
        mock_settings.ecs_worker_security_group = "sg-123"
        mock_settings.ecs_worker_container_name = "worker"
        mock_settings.aws_region = "eu-west-2"

        ecs_mock = MagicMock()
        mock_boto.return_value = ecs_mock

        from api_service.src.main import _trigger_ecs_worker

        _trigger_ecs_worker("m-1", "standup.txt")

        ecs_mock.run_task.assert_called_once()
        call_kwargs = ecs_mock.run_task.call_args[1]
        assert call_kwargs["cluster"] == "my-cluster"
        assert call_kwargs["launchType"] == "FARGATE"

        # Verify environment overrides include MEETING_ID and FILENAME
        overrides = call_kwargs["overrides"]["containerOverrides"][0]["environment"]
        env_map = {e["name"]: e["value"] for e in overrides}
        assert env_map["MEETING_ID"] == "m-1"
        assert env_map["FILENAME"] == "standup.txt"


# ---------------------------------------------------------------------------
# POST /api/v2/query
# ---------------------------------------------------------------------------

class TestQueryV2:
    """Tests for the v2 query endpoint that returns CitedAnswer."""

    def _patch_query_service(self, cited_answer_dict: dict | None = None):
        """Return (mock_container, mock_query_svc) with a canned CitedAnswer."""
        from domain.models import CitedAnswer

        container = MagicMock()
        query_svc = MagicMock()
        default = CitedAnswer(
            answer="Deploy on Friday.",
            citations=[],
            retrieved_context=["ctx1"],
            meeting_ids=["m-1"],
            latency_ms=42.0,
        )
        query_svc.query.return_value = default
        container.get_query_service.return_value = query_svc
        return container, query_svc

    @patch("api_service.src.main.get_di_container")
    def test_query_returns_200(self, mock_get_di) -> None:
        container, _ = self._patch_query_service()
        mock_get_di.return_value = container

        response = client.post(
            "/api/v2/query", json={"question": "When do we deploy?"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["answer"] == "Deploy on Friday."
        assert body["meeting_ids"] == ["m-1"]

    @patch("api_service.src.main.get_di_container")
    def test_query_forwards_meeting_ids(self, mock_get_di) -> None:
        container, query_svc = self._patch_query_service()
        mock_get_di.return_value = container

        client.post(
            "/api/v2/query",
            json={"question": "test", "meeting_ids": ["m-5", "m-6"]},
        )
        query_svc.query.assert_called_once_with(
            question="test", meeting_ids=["m-5", "m-6"]
        )

    @patch("api_service.src.main.get_di_container")
    def test_query_empty_question_returns_error(self, mock_get_di) -> None:
        container, _ = self._patch_query_service()
        mock_get_di.return_value = container

        response = client.post("/api/v2/query", json={"question": ""})
        assert response.status_code == 400  # ValidationError

    @patch("api_service.src.main.get_di_container")
    def test_query_missing_question_returns_error(self, mock_get_di) -> None:
        container, _ = self._patch_query_service()
        mock_get_di.return_value = container

        response = client.post("/api/v2/query", json={})
        assert response.status_code == 400

    @patch("api_service.src.main.get_di_container")
    def test_query_service_error_returns_500(self, mock_get_di) -> None:
        container = MagicMock()
        query_svc = MagicMock()
        query_svc.query.side_effect = RuntimeError("Boom")
        container.get_query_service.return_value = query_svc
        mock_get_di.return_value = container

        response = client.post(
            "/api/v2/query", json={"question": "test question"}
        )
        assert response.status_code == 500

    @patch("api_service.src.main.get_di_container")
    def test_query_no_meeting_ids_passes_none(self, mock_get_di) -> None:
        container, query_svc = self._patch_query_service()
        mock_get_di.return_value = container

        client.post("/api/v2/query", json={"question": "hello"})
        query_svc.query.assert_called_once_with(
            question="hello", meeting_ids=None
        )

    @patch("api_service.src.main.get_di_container")
    def test_query_response_shape(self, mock_get_di) -> None:
        container, _ = self._patch_query_service()
        mock_get_di.return_value = container

        response = client.post(
            "/api/v2/query", json={"question": "test"}
        )
        body = response.json()
        assert "answer" in body
        assert "citations" in body
        assert "meeting_ids" in body
        assert "latency_ms" in body
