"""
Comprehensive tests for core_intelligence.parser.cleaner.TranscriptParser.

Covers parse_text() (various formats, edge cases, empty input) and
to_document_text() (round-trip, error propagation).
"""

import pytest

from core_intelligence.parser.cleaner import TranscriptParser
from domain.models import TranscriptSegment, MeetingTranscript, MeetingMetadata
from shared_utils.error_handler import ProcessingError


# ---------------------------------------------------------------------------
# parse_text — basic format handling
# ---------------------------------------------------------------------------


class TestParseTextFormats:
    def test_colon_delimiter(self) -> None:
        text = "John Doe: Hello everyone."
        t = TranscriptParser.parse_text(text, title="Test")
        assert t.segments[0].speaker == "John Doe"
        assert t.segments[0].content == "Hello everyone."

    def test_dash_delimiter(self) -> None:
        text = "Jane - How are you?"
        t = TranscriptParser.parse_text(text)
        assert t.segments[0].speaker == "Jane"
        assert t.segments[0].content == "How are you?"

    def test_no_space_dash(self) -> None:
        text = "Bob-I am fine."
        t = TranscriptParser.parse_text(text)
        assert t.segments[0].speaker == "Bob"
        assert t.segments[0].content == "I am fine."

    def test_colon_with_spaces(self) -> None:
        text = "Alice : Let's start."
        t = TranscriptParser.parse_text(text)
        assert t.segments[0].speaker == "Alice"
        assert t.segments[0].content == "Let's start."

    def test_with_timestamp(self) -> None:
        text = "[00:01:30] Alice: Welcome to the meeting."
        t = TranscriptParser.parse_text(text)
        assert t.segments[0].timestamp == "00:01:30"
        assert t.segments[0].speaker == "Alice"

    def test_multiple_delimiters_in_one_transcript(self) -> None:
        text = (
            "John Doe: Hello everyone.\n"
            "Jane - How are you?\n"
            "Bob-I am fine.\n"
            "Alice : Let's start.\n"
        )
        t = TranscriptParser.parse_text(text, title="Test Meeting")
        assert t.metadata.title == "Test Meeting"
        assert len(t.segments) == 4


class TestParseTextEdgeCases:
    def test_skips_empty_lines(self) -> None:
        text = "John: Message 1\n\nJane: Message 2\n"
        t = TranscriptParser.parse_text(text)
        assert len(t.segments) == 2

    def test_no_valid_segments_fallback(self) -> None:
        text = "This is just a random line without a speaker"
        t = TranscriptParser.parse_text(text)
        assert len(t.segments) == 1
        assert t.segments[0].speaker == "Unknown"
        assert "random line" in t.segments[0].content

    def test_multiple_colons_in_content(self) -> None:
        text = "Speaker: Message: with more colons"
        t = TranscriptParser.parse_text(text)
        assert t.segments[0].speaker == "Speaker"
        assert t.segments[0].content == "Message: with more colons"

    def test_empty_text_raises_processing_error(self) -> None:
        with pytest.raises(ProcessingError, match="cannot be empty"):
            TranscriptParser.parse_text("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(ProcessingError, match="cannot be empty"):
            TranscriptParser.parse_text("   \n  \n  ")

    def test_participants_are_sorted(self) -> None:
        text = "Charlie: Hi\nAlice: Hello\nBob: Hey"
        t = TranscriptParser.parse_text(text)
        assert t.metadata.participants == ["Alice", "Bob", "Charlie"]

    def test_meeting_id_is_uuid(self) -> None:
        import re
        text = "Alice: Hello"
        t = TranscriptParser.parse_text(text)
        uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        assert re.match(uuid_pattern, t.metadata.meeting_id, re.IGNORECASE)

    def test_default_title(self) -> None:
        text = "Alice: Hello"
        t = TranscriptParser.parse_text(text)
        assert t.metadata.title == "Untitled Meeting"

    def test_default_timestamp_when_missing(self) -> None:
        text = "Alice: Hello"
        t = TranscriptParser.parse_text(text)
        assert t.segments[0].timestamp == "00:00:00"


# ---------------------------------------------------------------------------
# to_document_text
# ---------------------------------------------------------------------------


class TestToDocumentText:
    def test_round_trip(self) -> None:
        text = "[00:00:00] Alice: Hello\n[00:00:15] Bob: Hi"
        transcript = TranscriptParser.parse_text(text)
        result = TranscriptParser.to_document_text(transcript)
        assert "[00:00:00] Alice: Hello" in result
        assert "[00:00:15] Bob: Hi" in result

    def test_single_segment(self) -> None:
        text = "[00:01:00] Carol: Just me here."
        transcript = TranscriptParser.parse_text(text)
        result = TranscriptParser.to_document_text(transcript)
        assert result == "[00:01:00] Carol: Just me here."

    def test_preserves_segment_order(self) -> None:
        text = "[00:00:00] A: first\n[00:00:01] B: second\n[00:00:02] C: third"
        transcript = TranscriptParser.parse_text(text)
        result = TranscriptParser.to_document_text(transcript)
        lines = result.strip().split("\n")
        assert "first" in lines[0]
        assert "second" in lines[1]
        assert "third" in lines[2]

    def test_empty_segments_produces_empty_string(self) -> None:
        """Edge case: a transcript with no segments."""
        import datetime
        transcript = MeetingTranscript(
            metadata=MeetingMetadata(
                meeting_id="test",
                title="Empty",
                date=datetime.datetime.now(),
                participants=[],
            ),
            segments=[],
        )
        result = TranscriptParser.to_document_text(transcript)
        assert result == ""
