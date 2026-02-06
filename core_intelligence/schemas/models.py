"""
Data models for Meeting Intelligence System.

Data flow:
  Raw transcript → TranscriptSegment (individual lines)
                → MeetingTranscript (complete meeting)
                → Database (indexed)
                → QueryRequest (user search)
                → QueryResponse (results with sources)
"""

from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class TranscriptSegment(BaseModel):
    """Single statement from a meeting transcript."""
    speaker: str
    timestamp: str
    content: str


class MeetingMetadata(BaseModel):
    """Metadata for a meeting session."""
    meeting_id: str
    title: str
    date: datetime
    participants: List[str] = []
    summary: Optional[str] = None


class MeetingTranscript(BaseModel):
    """Complete parsed transcript with metadata and segments."""
    metadata: MeetingMetadata
    segments: List[TranscriptSegment]


class QueryRequest(BaseModel):
    """User query request."""
    query: str
    meeting_id: Optional[str] = None
    filters: Optional[dict] = None


class ActionItem(BaseModel):
    """Task or action item from meeting."""
    task: str
    owner: Optional[str] = None
    deadline: Optional[str] = None


class QueryResponse(BaseModel):
    """Response containing answer, sources, and action items."""
    answer: str
    sources: List[str] = []
    retrieved_contexts: List[str] = []
    action_items: List[ActionItem] = []
    confidence_score: float = 0.0
    latency_ms: float = 0.0


class EvaluationResult(BaseModel):
    """Result of a Ragas evaluation."""
    meeting_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)
    faithfulness: float
    answer_relevancy: float
    context_precision: float
    context_recall: float
    average_score: float
    latency_avg_ms: float


class JobStatus(BaseModel):
    """Status of async processing job."""
    job_id: str
    status: str  # pending, processing, completed, failed
    progress: int = 0
