"""
Pure domain models for Meeting Intelligence System v2.

These models contain NO AWS dependencies. They represent core business concepts
that flow through ports and services.

Existing v1 models (TranscriptSegment, MeetingMetadata, MeetingTranscript)
remain in core_intelligence/schemas/models.py and are reused unchanged.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Legacy v1 models (moved from core_intelligence.schemas.models)
# Still used by TranscriptParser and IngestionService.
# ---------------------------------------------------------------------------


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


class IngestionStatus(str, Enum):
    """Meeting ingestion pipeline status."""

    PENDING = "PENDING"
    READY = "READY"
    FAILED = "FAILED"


class MeetingRecord(BaseModel):
    """Meeting metadata record (maps to DynamoDB item).

    Pure domain representation — no AWS types.
    """

    meeting_id: str
    title_normalized: str
    meeting_date: str  # ISO 8601 date string
    participants: List[str] = []
    s3_uri_raw: str = ""
    s3_uri_derived_prefix: str = ""
    doc_hash: str = ""
    version: int = 1
    ingestion_status: IngestionStatus = IngestionStatus.PENDING
    ingested_at: Optional[str] = None  # ISO 8601
    error_message: Optional[str] = None


class ChunkMapEntry(BaseModel):
    """Maps a chunk_id to its source location and a text snippet.

    Built during ingestion and stored as ``chunk_map.json`` in the S3
    derived prefix. Used by QueryService to assemble citations — when
    a vector search returns a chunk_id, we look it up here to get the
    speaker name, timestamp range, and a snippet for the UI.
    """

    chunk_id: str
    meeting_id: str
    timestamp_start: str
    timestamp_end: str
    speaker: str
    snippet: str  # First 200 chars of the chunk text
    raw_s3_uri: str  # Points back to the original uploaded transcript


class VectorRecord(BaseModel):
    """A single embedding vector with metadata for storage.

    Used both for writing (embedding populated) and reading
    (embedding is empty on search results to save bandwidth —
    we only need the text and metadata for building context).
    """

    chunk_id: str
    meeting_id: str
    embedding: List[float]  # 1536-dim for OpenAI text-embedding-3-small
    text: str  # The full chunk text (reconstructed [timestamp] Speaker: text)
    metadata: Dict[str, str] = {}  # Extra fields like 'speaker'


class Citation(BaseModel):
    """A citation referencing a specific chunk in a meeting transcript."""

    chunk_id: str
    meeting_id: str
    speaker: str
    timestamp_start: str
    timestamp_end: str
    snippet: str


class CitedAnswer(BaseModel):
    """Query response with grounded citations and token usage."""

    answer: str
    citations: List[Citation] = []
    retrieved_context: List[str] = []
    meeting_ids: List[str] = []
    latency_ms: float = 0.0
    # Token tracking (Phase 5 — populated by LangChain callback)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0


class IngestionReport(BaseModel):
    """Report generated after ingestion completes or fails."""

    meeting_id: str
    status: IngestionStatus
    chunks_created: int = 0
    embeddings_stored: int = 0
    derived_artifacts: List[str] = []
    error_message: Optional[str] = None
    started_at: str = ""  # ISO 8601
    completed_at: str = ""  # ISO 8601
    duration_ms: float = 0.0


class NormalizedSegment(BaseModel):
    """Internally normalized transcript segment with strict schema."""

    timestamp: str
    speaker: str
    text: str


class NormalizedTranscript(BaseModel):
    """Normalized transcript ready for chunking and embedding."""

    meeting_id: str
    title: str
    date: str  # ISO 8601
    participants: List[str]
    segments: List[NormalizedSegment]
    raw_text_hash: str


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


class EvalResult(BaseModel):
    """Result of a single DeepEval evaluation run against a query."""

    eval_id: str
    meeting_id: str
    question: str
    answer: str
    retrieved_context: List[str] = []
    # DeepEval metric scores (0.0 – 1.0)
    faithfulness: Optional[float] = None
    answer_relevancy: Optional[float] = None
    contextual_precision: Optional[float] = None
    contextual_recall: Optional[float] = None
    # Aggregate
    overall_score: Optional[float] = None
    evaluated_at: str = ""  # ISO 8601
    latency_ms: float = 0.0
    metadata: Dict[str, str] = {}


# ---------------------------------------------------------------------------
# Semantic query cache (Phase 9)
# ---------------------------------------------------------------------------


class CachedQuery(BaseModel):
    """A previously-answered query stored for semantic cache lookup.

    The embedding is used for cosine similarity search — if a new query
    is close enough (above ``similarity_threshold``) the cached answer
    is returned immediately, saving an LLM call + vector search.
    """

    cache_id: str
    query_text: str
    query_embedding: List[float]
    meeting_ids: List[str] = []
    cited_answer: CitedAnswer
    created_at: str = ""  # ISO 8601
    ttl: int = 0  # Unix timestamp for DynamoDB TTL auto-expiry


# ---------------------------------------------------------------------------
# Chat history (Phase 10)
# ---------------------------------------------------------------------------


class ChatTurn(BaseModel):
    """Single question/answer exchange in a conversation."""

    turn_id: str
    question: str
    answer: str
    meeting_ids: List[str] = []
    timestamp: str = ""  # ISO 8601
    prompt_tokens: int = 0
    completion_tokens: int = 0


class ChatSession(BaseModel):
    """A multi-turn conversation session.

    Stores the full history so the QA prompt can include previous
    turns for context-aware follow-up questions.
    """

    session_id: str
    user_id: str = ""
    turns: List[ChatTurn] = []
    created_at: str = ""  # ISO 8601
    updated_at: str = ""  # ISO 8601


# ---------------------------------------------------------------------------
# User memory (Phase 11)
# ---------------------------------------------------------------------------


class UserFact(BaseModel):
    """A single fact extracted from a user's interactions."""

    fact_id: str
    text: str
    source_session_id: str = ""
    created_at: str = ""  # ISO 8601


class UserProfile(BaseModel):
    """Persistent user memory — stores facts and preferences learned
    across sessions for personalised responses.
    """

    user_id: str
    display_name: str = ""
    facts: List[UserFact] = []
    preferences: Dict[str, str] = {}
    created_at: str = ""  # ISO 8601
    updated_at: str = ""  # ISO 8601
