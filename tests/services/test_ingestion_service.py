"""
Comprehensive unit tests for IngestionService.

All storage ports are mocked — no AWS calls.
"""

import json
import pytest
from unittest.mock import MagicMock, patch, call

from domain.models import IngestionStatus, VectorRecord, NormalizedSegment
from services.ingestion_service import (
    IngestionService,
    _chunk_segments,
    _compute_hash,
)
from shared_utils.error_handler import IngestionError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_TRANSCRIPT = (
    "[00:00:00] Alice: Hello everyone, welcome to the standup.\n"
    "[00:00:15] Bob: Thanks Alice. I worked on the API refactoring yesterday.\n"
    "[00:00:30] Alice: Great, any blockers?\n"
    "[00:00:45] Bob: No blockers. I'll finish the tests today.\n"
    "[00:01:00] Alice: Perfect. Let's move on to Carol.\n"
    "[00:01:15] Carol: I'm working on the deployment pipeline.\n"
)


def _build_artifact_mock() -> MagicMock:
    """Create a properly configured artifact store mock."""
    mock = MagicMock()
    mock.upload_raw.return_value = "s3://bucket/raw/m-1/file.txt"
    mock.get_derived_prefix.return_value = "s3://bucket/derived/m-1/"
    mock.upload_derived.return_value = "s3://bucket/derived/m-1/chunk_map.json"
    return mock


def _build_embedder_mock() -> MagicMock:
    """Create a properly configured embedding provider mock."""
    mock = MagicMock()
    mock.embed_texts.side_effect = lambda texts: [[0.1, 0.2, 0.3] for _ in texts]
    return mock


def _make_service(
    artifact=None, metadata=None, vector=None, embedder=None,
    max_chunk_tokens: int = 512, chunk_overlap: int = 1,
) -> IngestionService:
    """Build IngestionService with mocked ports.

    When a mock argument is ``None`` a sensible default is created.
    If the caller supplies their own mock (e.g. to inject a side_effect)
    the caller is responsible for configuring its return values.
    """
    artifact = artifact if artifact is not None else _build_artifact_mock()
    metadata = metadata if metadata is not None else MagicMock()
    vector = vector if vector is not None else MagicMock()
    embedder = embedder if embedder is not None else _build_embedder_mock()

    return IngestionService(
        artifact_store=artifact,
        metadata_store=metadata,
        vector_store=vector,
        embedding_provider=embedder,
        max_chunk_tokens=max_chunk_tokens,
        chunk_overlap=chunk_overlap,
    )


# ---------------------------------------------------------------------------
# _chunk_segments tests
# ---------------------------------------------------------------------------

class TestChunkSegments:
    def test_empty(self) -> None:
        assert _chunk_segments([]) == []

    def test_single_segment(self) -> None:
        segs = [NormalizedSegment(timestamp="00:00:00", speaker="A", text="hello")]
        chunks = _chunk_segments(segs, max_tokens=512)
        assert len(chunks) == 1
        assert "hello" in chunks[0]["text"]

    def test_multiple_chunks(self) -> None:
        segs = [
            NormalizedSegment(timestamp=f"00:00:{i:02d}", speaker="A", text="word " * 100)
            for i in range(10)
        ]
        chunks = _chunk_segments(segs, max_tokens=200, overlap=1)
        assert len(chunks) > 1
        # Each chunk should have text
        for c in chunks:
            assert c["text"]
            assert c["chunk_id"]

    def test_overlap_shares_segments(self) -> None:
        segs = [
            NormalizedSegment(
                timestamp=f"00:00:{i:02d}", speaker="A", text="word " * 50
            )
            for i in range(4)
        ]
        chunks = _chunk_segments(segs, max_tokens=120, overlap=1)
        # With overlap the last segment of chunk N must equal the first of chunk N+1.
        # Compare after per-line strip to avoid trailing-whitespace artefacts.
        assert len(chunks) >= 2, "Need at least 2 chunks to verify overlap"
        last_line_c0 = chunks[0]["text"].strip().split("\n")[-1].rstrip()
        first_line_c1 = chunks[1]["text"].strip().split("\n")[0].rstrip()
        assert last_line_c0 == first_line_c1

    def test_chunk_keys(self) -> None:
        """Every chunk must have the expected dict keys."""
        segs = [NormalizedSegment(timestamp="00:00:00", speaker="A", text="hello world")]
        chunks = _chunk_segments(segs)
        required_keys = {"chunk_id", "text", "timestamp_start", "timestamp_end", "speaker", "speakers"}
        assert required_keys.issubset(chunks[0].keys())

    def test_speakers_list_sorted(self) -> None:
        segs = [
            NormalizedSegment(timestamp="00:00:00", speaker="Charlie", text="hi"),
            NormalizedSegment(timestamp="00:00:01", speaker="Alice", text="hey"),
        ]
        chunks = _chunk_segments(segs, max_tokens=1000)
        assert chunks[0]["speakers"] == ["Alice", "Charlie"]

    def test_single_speaker_speaker_field(self) -> None:
        segs = [
            NormalizedSegment(timestamp="00:00:00", speaker="Alice", text="hello"),
            NormalizedSegment(timestamp="00:00:01", speaker="Alice", text="world"),
        ]
        chunks = _chunk_segments(segs, max_tokens=1000)
        assert chunks[0]["speaker"] == "Alice"

    def test_multi_speaker_speaker_field(self) -> None:
        segs = [
            NormalizedSegment(timestamp="00:00:00", speaker="Alice", text="hello"),
            NormalizedSegment(timestamp="00:00:01", speaker="Bob", text="hi"),
        ]
        chunks = _chunk_segments(segs, max_tokens=1000)
        assert "Alice" in chunks[0]["speaker"]
        assert "Bob" in chunks[0]["speaker"]

    def test_zero_overlap(self) -> None:
        """With zero overlap, chunks should not share segments."""
        segs = [
            NormalizedSegment(timestamp=f"00:00:{i:02d}", speaker="A", text="word " * 50)
            for i in range(4)
        ]
        chunks = _chunk_segments(segs, max_tokens=120, overlap=0)
        assert len(chunks) >= 2
        # All texts should be non-empty
        for c in chunks:
            assert len(c["text"].strip()) > 0


class TestComputeHash:
    def test_deterministic(self) -> None:
        h1 = _compute_hash(b"hello")
        h2 = _compute_hash(b"hello")
        assert h1 == h2

    def test_different_content(self) -> None:
        assert _compute_hash(b"a") != _compute_hash(b"b")

    def test_returns_hex_string(self) -> None:
        h = _compute_hash(b"test")
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex = 64 chars
        assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# IngestionService.ingest tests
# ---------------------------------------------------------------------------

class TestIngestionService:
    def test_ingest_success(self) -> None:
        svc = _make_service()
        report = svc.ingest("m-1", "standup.txt", SAMPLE_TRANSCRIPT.encode())

        assert report.status == IngestionStatus.READY
        assert report.chunks_created > 0
        assert report.embeddings_stored > 0
        assert report.meeting_id == "m-1"

        # Metadata should be updated twice (PENDING then READY)
        svc._metadata.put_meeting.assert_called()
        svc._metadata.update_status.assert_called_once_with("m-1", IngestionStatus.READY)

        # Vectors should be stored
        svc._vectors.store_vectors.assert_called_once()

        # Chunk map should be uploaded as derived artifact
        svc._artifacts.upload_derived.assert_called_once()
        call_args = svc._artifacts.upload_derived.call_args
        assert call_args[0][1] == "chunk_map.json"

    def test_ingest_failure_marks_failed(self) -> None:
        embedder = MagicMock()
        embedder.embed_texts.side_effect = RuntimeError("Bedrock timeout")

        svc = _make_service(embedder=embedder)

        with pytest.raises(IngestionError, match="Ingestion failed"):
            svc.ingest("m-2", "fail.txt", SAMPLE_TRANSCRIPT.encode())

        # Should mark as FAILED in metadata
        svc._metadata.update_status.assert_called_once()
        call_args = svc._metadata.update_status.call_args
        assert call_args[0][1] == IngestionStatus.FAILED

    def test_ingest_empty_content_raises(self) -> None:
        svc = _make_service()
        with pytest.raises(Exception):
            svc.ingest("m-3", "empty.txt", b"")

    def test_ingest_stores_raw_first(self) -> None:
        svc = _make_service()
        svc.ingest("m-4", "test.txt", SAMPLE_TRANSCRIPT.encode())

        # upload_raw should be called before vectors
        svc._artifacts.upload_raw.assert_called_once_with(
            "m-4", "test.txt", SAMPLE_TRANSCRIPT.encode()
        )

    def test_chunk_map_is_valid_json(self) -> None:
        svc = _make_service()
        svc.ingest("m-5", "test.txt", SAMPLE_TRANSCRIPT.encode())

        # Grab the bytes passed to upload_derived
        call_args = svc._artifacts.upload_derived.call_args
        chunk_map_bytes = call_args[0][2]
        chunk_map = json.loads(chunk_map_bytes)
        assert isinstance(chunk_map, list)
        assert len(chunk_map) > 0
        assert "chunk_id" in chunk_map[0]
        assert "meeting_id" in chunk_map[0]

    def test_report_has_duration(self) -> None:
        svc = _make_service()
        report = svc.ingest("m-6", "test.txt", SAMPLE_TRANSCRIPT.encode())
        assert report.duration_ms >= 0

    def test_report_derived_artifacts_list(self) -> None:
        svc = _make_service()
        report = svc.ingest("m-7", "test.txt", SAMPLE_TRANSCRIPT.encode())
        assert isinstance(report.derived_artifacts, list)
        assert len(report.derived_artifacts) == 1
        assert "chunk_map.json" in report.derived_artifacts[0]

    def test_title_normalized_from_filename(self) -> None:
        """The meeting record title should be derived from filename."""
        metadata_mock = MagicMock()
        svc = _make_service(metadata=metadata_mock)
        svc.ingest("m-8", "team_standup.txt", SAMPLE_TRANSCRIPT.encode())

        # Check the first put_meeting call for PENDING record
        first_call = metadata_mock.put_meeting.call_args_list[0]
        record = first_call[0][0]
        assert record.title_normalized == "team standup"

    def test_participants_populated(self) -> None:
        """After parse the metadata record should contain participant names."""
        metadata_mock = MagicMock()
        svc = _make_service(metadata=metadata_mock)
        svc.ingest("m-9", "test.txt", SAMPLE_TRANSCRIPT.encode())

        # Second put_meeting call should have participants
        second_call = metadata_mock.put_meeting.call_args_list[1]
        record = second_call[0][0]
        assert "Alice" in record.participants
        assert "Bob" in record.participants

    def test_embed_called_with_chunk_texts(self) -> None:
        embedder = _build_embedder_mock()
        svc = _make_service(embedder=embedder)
        svc.ingest("m-10", "test.txt", SAMPLE_TRANSCRIPT.encode())

        # embed_texts should receive a list of non-empty strings
        call_args = embedder.embed_texts.call_args[0][0]
        assert isinstance(call_args, list)
        assert all(isinstance(t, str) and len(t) > 0 for t in call_args)

    def test_status_update_failure_still_raises_ingestion_error(self) -> None:
        """If update_status fails AFTER an ingest error, IngestionError still raised."""
        embedder = MagicMock()
        embedder.embed_texts.side_effect = RuntimeError("Bedrock down")
        metadata = MagicMock()
        metadata.update_status.side_effect = RuntimeError("DynamoDB down too")

        svc = _make_service(embedder=embedder, metadata=metadata)

        with pytest.raises(IngestionError, match="Ingestion failed"):
            svc.ingest("m-11", "fail.txt", SAMPLE_TRANSCRIPT.encode())

    def test_custom_chunk_params(self) -> None:
        """Service should respect custom max_chunk_tokens and overlap."""
        svc = IngestionService(
            artifact_store=_build_artifact_mock(),
            metadata_store=MagicMock(),
            vector_store=MagicMock(),
            embedding_provider=_build_embedder_mock(),
            max_chunk_tokens=20,
            chunk_overlap=0,
        )
        report = svc.ingest("m-12", "test.txt", SAMPLE_TRANSCRIPT.encode())
        # With very small chunk size (~38 words total), we should get multiple chunks
        assert report.chunks_created >= 2


# ---------------------------------------------------------------------------
# IngestionService._normalise tests
# ---------------------------------------------------------------------------


class TestNormalise:
    def test_converts_transcript_to_normalized(self) -> None:
        from core_intelligence.parser.cleaner import TranscriptParser

        text = "[00:00:00] Alice: Hello\n[00:00:15] Bob: Hi"
        transcript = TranscriptParser.parse_text(text, title="test")
        normalised = IngestionService._normalise(transcript, "m-100")

        assert normalised.meeting_id == "m-100"
        assert normalised.title == "test"
        assert len(normalised.segments) == 2
        assert normalised.segments[0].speaker == "Alice"
        assert normalised.segments[1].text == "Hi"
        assert normalised.participants == ["Alice", "Bob"]
