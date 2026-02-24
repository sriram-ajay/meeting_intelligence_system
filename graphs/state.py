"""
LangGraph state definitions for ingestion and query pipelines.

Each state is a TypedDict that flows through graph nodes.  Nodes read
from and write to the state dict — LangGraph merges the returned keys
automatically.

These states wrap existing domain models (MeetingTranscript,
NormalizedTranscript, CitedAnswer, etc.) so the graph layer adds
orchestration without duplicating business types.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict

from domain.models import (
    CitedAnswer,
    IngestionReport,
    MeetingRecord,
    MeetingTranscript,
    NormalizedTranscript,
    VectorRecord,
)


# ---------------------------------------------------------------------------
# Ingestion graph state
# ---------------------------------------------------------------------------


class IngestionState(TypedDict, total=False):
    """State flowing through the ingestion graph.

    Every key is optional (total=False) because nodes progressively
    populate the state as the pipeline advances.
    """

    # --- Inputs (set before graph invocation) ---
    meeting_id: str
    filename: str
    raw_content: bytes

    # --- Produced by nodes ---
    raw_uri: str
    derived_prefix: str
    doc_hash: str
    record: MeetingRecord
    transcript: MeetingTranscript
    normalized: NormalizedTranscript
    chunks: List[Dict[str, Any]]
    embeddings: List[List[float]]
    vectors: List[VectorRecord]
    chunk_map_uri: str
    report: IngestionReport

    # --- Error handling ---
    error: Optional[str]


# ---------------------------------------------------------------------------
# Query graph state
# ---------------------------------------------------------------------------


class QueryState(TypedDict, total=False):
    """State flowing through the query graph.

    Supports the full pipeline: cache check → embed → search → generate →
    ground → cite, with optional user memory and chat history persistence.
    """

    # --- Inputs ---
    question: str
    meeting_ids: Optional[List[str]]
    session_id: Optional[str]
    user_id: Optional[str]

    # --- Produced by nodes ---
    input_safe: bool
    query_embedding: List[float]
    cache_hit: Optional[CitedAnswer]
    search_results: List[VectorRecord]
    hit_meeting_ids: List[str]
    chunk_map_index: Dict[str, Any]
    context_texts: List[str]
    raw_answer: str
    is_grounded: bool
    cited_answer: CitedAnswer

    # --- Token tracking (Phase 5) ---
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float

    # --- Chat history (Phase 10) ---
    chat_history_messages: List[Any]  # LangChain Message objects

    # --- Error handling ---
    error: Optional[str]
