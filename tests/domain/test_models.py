"""
Unit tests for domain models.

Validates pure domain types with no AWS dependencies.
"""

import pytest
from datetime import datetime

from domain.models import (
    ChunkMapEntry,
    Citation,
    CitedAnswer,
    IngestionReport,
    IngestionStatus,
    MeetingRecord,
    NormalizedSegment,
    NormalizedTranscript,
    VectorRecord,
)


class TestIngestionStatus:
    def test_values(self) -> None:
        assert IngestionStatus.PENDING == "PENDING"
        assert IngestionStatus.READY == "READY"
        assert IngestionStatus.FAILED == "FAILED"

    def test_from_string(self) -> None:
        assert IngestionStatus("PENDING") is IngestionStatus.PENDING


class TestMeetingRecord:
    def test_defaults(self) -> None:
        record = MeetingRecord(
            meeting_id="abc-123",
            title_normalized="standup",
            meeting_date="2026-01-15",
        )
        assert record.ingestion_status == IngestionStatus.PENDING
        assert record.version == 1
        assert record.participants == []
        assert record.error_message is None
        assert record.ingested_at is None

    def test_full_record(self) -> None:
        record = MeetingRecord(
            meeting_id="abc-123",
            title_normalized="quarterly review",
            meeting_date="2026-01-15",
            participants=["Alice", "Bob"],
            s3_uri_raw="s3://bucket/raw/abc-123/file.txt",
            s3_uri_derived_prefix="s3://bucket/derived/abc-123/",
            doc_hash="sha256abc",
            version=1,
            ingestion_status=IngestionStatus.READY,
            ingested_at="2026-01-15T10:00:00Z",
        )
        assert record.ingestion_status == IngestionStatus.READY
        assert "Alice" in record.participants

    def test_serialization_roundtrip(self) -> None:
        record = MeetingRecord(
            meeting_id="id-1",
            title_normalized="test",
            meeting_date="2026-02-01",
            ingestion_status=IngestionStatus.FAILED,
            error_message="parsing failed",
        )
        data = record.model_dump()
        restored = MeetingRecord(**data)
        assert restored.error_message == "parsing failed"
        assert restored.ingestion_status == IngestionStatus.FAILED


class TestChunkMapEntry:
    def test_creation(self) -> None:
        entry = ChunkMapEntry(
            chunk_id="chunk-001",
            meeting_id="m-1",
            timestamp_start="00:05:30",
            timestamp_end="00:06:15",
            speaker="Alice",
            snippet="We need to finalize the budget",
            raw_s3_uri="s3://bucket/raw/m-1/file.txt",
        )
        assert entry.chunk_id == "chunk-001"
        assert entry.speaker == "Alice"


class TestVectorRecord:
    def test_creation(self) -> None:
        vr = VectorRecord(
            chunk_id="c-1",
            meeting_id="m-1",
            embedding=[0.1, 0.2, 0.3],
            text="Hello world",
        )
        assert len(vr.embedding) == 3
        assert vr.metadata == {}

    def test_with_metadata(self) -> None:
        vr = VectorRecord(
            chunk_id="c-2",
            meeting_id="m-1",
            embedding=[0.0],
            text="test",
            metadata={"speaker": "Bob"},
        )
        assert vr.metadata["speaker"] == "Bob"


class TestCitation:
    def test_creation(self) -> None:
        citation = Citation(
            chunk_id="c-1",
            meeting_id="m-1",
            speaker="Alice",
            timestamp_start="00:01:00",
            timestamp_end="00:01:30",
            snippet="Action item: review budget",
        )
        assert citation.snippet.startswith("Action item")


class TestCitedAnswer:
    def test_empty_citations(self) -> None:
        answer = CitedAnswer(answer="No info found.")
        assert answer.citations == []
        assert answer.meeting_ids == []

    def test_with_citations(self) -> None:
        c = Citation(
            chunk_id="c-1",
            meeting_id="m-1",
            speaker="Alice",
            timestamp_start="00:01:00",
            timestamp_end="00:02:00",
            snippet="We agreed on the timeline.",
        )
        answer = CitedAnswer(
            answer="The team agreed on the timeline.",
            citations=[c],
            meeting_ids=["m-1"],
        )
        assert len(answer.citations) == 1


class TestIngestionReport:
    def test_defaults(self) -> None:
        report = IngestionReport(
            meeting_id="m-1",
            status=IngestionStatus.READY,
            chunks_created=10,
            embeddings_stored=10,
        )
        assert report.error_message is None
        assert report.duration_ms == 0.0

    def test_failed_report(self) -> None:
        report = IngestionReport(
            meeting_id="m-1",
            status=IngestionStatus.FAILED,
            error_message="Parsing impossible",
        )
        assert report.status == IngestionStatus.FAILED


class TestNormalizedTranscript:
    def test_creation(self) -> None:
        segments = [
            NormalizedSegment(timestamp="00:00:00", speaker="Alice", text="Hello"),
            NormalizedSegment(timestamp="00:00:05", speaker="Bob", text="Hi there"),
        ]
        transcript = NormalizedTranscript(
            meeting_id="m-1",
            title="Standup",
            date="2026-01-15",
            participants=["Alice", "Bob"],
            segments=segments,
            raw_text_hash="abc123",
        )
        assert len(transcript.segments) == 2
        assert transcript.segments[0].speaker == "Alice"
