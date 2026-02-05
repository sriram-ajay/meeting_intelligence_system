import pytest
from core_intelligence.parser.cleaner import TranscriptParser

def test_parse_text_with_various_delimiters():
    """Test parsing with colon, dash, and different spacing."""
    text = """
    John Doe: Hello everyone.
    Jane - How are you?
    Bob-I am fine.
    Alice : Let's start.
    """
    transcript = TranscriptParser.parse_text(text, title="Test Meeting")
    
    assert transcript.metadata.title == "Test Meeting"
    assert len(transcript.segments) == 4
    assert transcript.segments[0].speaker == "John Doe"
    assert transcript.segments[0].content == "Hello everyone."
    assert transcript.segments[1].speaker == "Jane"
    assert transcript.segments[1].content == "How are you?"
    assert transcript.segments[2].speaker == "Bob"
    assert transcript.segments[2].content == "I am fine."
    assert transcript.segments[3].speaker == "Alice"
    assert transcript.segments[3].content == "Let's start."

def test_parse_text_skips_empty_lines():
    text = """
    John: Message 1
    
    Jane: Message 2
    """
    transcript = TranscriptParser.parse_text(text)
    assert len(transcript.segments) == 2

def test_parse_text_with_no_valid_segments():
    text = "This is just a random line without a speaker"
    transcript = TranscriptParser.parse_text(text)
    # Should fallback to one segment with Unknown speaker
    assert len(transcript.segments) == 1
    assert transcript.segments[0].speaker == "Unknown"

def test_parse_text_handles_multiple_colons():
    text = "Speaker: Message: with more colons"
    transcript = TranscriptParser.parse_text(text)
    assert transcript.segments[0].speaker == "Speaker"
    assert transcript.segments[0].content == "Message: with more colons"
