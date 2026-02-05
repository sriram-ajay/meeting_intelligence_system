"""
Transcript parsing and processing utilities.
Parses raw transcript text into structured segment format.
"""

import re
import uuid
import logging
from typing import List, Optional
from datetime import datetime

from core_intelligence.schemas.models import (
    TranscriptSegment, MeetingTranscript, MeetingMetadata
)
from shared_utils.logging_utils import ContextualLogger
from shared_utils.constants import LogScope
from shared_utils.error_handler import ProcessingError


logger = ContextualLogger(scope=LogScope.PARSER)


class TranscriptParser:
    """Parser for meeting transcript text into structured segments.
    
    Supports standard transcript format with timestamps and speakers:
    [HH:MM:SS] Speaker Name: Content
    
    Also supports flexible speaker separators:
    - [HH:MM:SS] Speaker: Content
    - [HH:MM:SS] Speaker - Content
    - [HH:MM:SS] Speaker- Content
    - [HH:MM:SS] Speaker :: Content
    - [HH:MM:SS] Speaker (multiple spaces) Content
    
    Also handles fallback to raw text if format doesn't match.
    """
    
    # Pattern: Optional [HH:MM:SS] or [MM:SS] followed by Speaker Name and flexible separators
    # Matches: [00:01:02] Speaker: Content OR Speaker: Content
    PATTERN: re.Pattern = re.compile(
        r"(?:\[(\d{1,2}:?\d{1,2}:?\d{2})\]\s+)?([^:\-\s]+(?:\s+[^:\-\s]+)*?)\s*[:|\-]\s*(?:::)?\s*(.*)"
    )

    @staticmethod
    def parse_text(text: str, title: str = "Untitled Meeting") -> MeetingTranscript:
        """Parse transcript text into structured MeetingTranscript.
        
        Args:
            text: Raw transcript text
            title: Meeting title (defaults to "Untitled Meeting")
        
        Returns:
            Structured MeetingTranscript with segments and metadata
        
        Raises:
            ProcessingError: If text is empty or invalid
        """
        if not text or not text.strip():
            raise ProcessingError(
                "Transcript text cannot be empty",
                error_type="parsing",
                context={"title": title}
            )
        
        segments = []
        participants = set()
        lines = text.splitlines()
        
        logger.info(
            "parsing_transcript_text",
            line_count=len(lines),
            title=title
        )
        
        # Try to match structured format: [timestamp] speaker: content
        for line in lines:
            if not line.strip():
                continue
            
            match = TranscriptParser.PATTERN.match(line.strip())
            if match:
                timestamp, speaker, content = match.groups()
                speaker_clean = speaker.strip()
                content_clean = content.strip()
                
                segments.append(TranscriptSegment(
                    timestamp=timestamp or "00:00:00",
                    speaker=speaker_clean,
                    content=content_clean
                ))
                participants.add(speaker_clean)
        
        # Fallback: if no structured segments found, treat entire text as one segment
        if not segments:
            logger.debug(
                "no_structured_segments_found_using_raw_text",
                title=title
            )
            segments.append(TranscriptSegment(
                timestamp="00:00:00",
                speaker="Unknown",
                content=text.strip()
            ))
            participants.add("Unknown")
        
        logger.debug(
            "parsed_segments",
            segment_count=len(segments),
            participant_count=len(participants)
        )
        
        # Create metadata with unique meeting ID
        metadata = MeetingMetadata(
            meeting_id=str(uuid.uuid4()),
            title=title,
            date=datetime.now(),
            participants=sorted(list(participants))
        )
        
        transcript = MeetingTranscript(metadata=metadata, segments=segments)
        
        logger.info(
            "transcript_parsed_successfully",
            meeting_id=metadata.meeting_id,
            segment_count=len(segments),
            participant_count=len(participants)
        )
        
        return transcript

    @staticmethod
    def to_document_text(transcript: MeetingTranscript) -> str:
        """Convert transcript segments back to formatted string.
        
        Args:
            transcript: Structured meeting transcript
        
        Returns:
            Formatted string with timestamps, speakers, and content
        """
        try:
            formatted_segments = [
                f"[{segment.timestamp}] {segment.speaker}: {segment.content}"
                for segment in transcript.segments
            ]
            result = "\n".join(formatted_segments)
            
            logger.debug(
                "converted_to_document_text",
                meeting_id=transcript.metadata.meeting_id,
                text_length=len(result)
            )
            
            return result
        except Exception as e:
            logger.error("document_text_conversion_failed", error=str(e))
            raise ProcessingError(
                f"Failed to convert transcript to document text: {e}",
                error_type="parsing",
                context={"meeting_id": transcript.metadata.meeting_id}
            )
