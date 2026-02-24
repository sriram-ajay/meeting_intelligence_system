"""
Port interface for semantic query cache operations.

Implementations: DynamoQueryCacheAdapter (adapters/)
"""

from __future__ import annotations

from typing import List, Optional, Protocol, runtime_checkable

from domain.models import CachedQuery, CitedAnswer


@runtime_checkable
class QueryCachePort(Protocol):
    """Abstract interface for semantic query caching.

    Stores query embeddings alongside their answers so that semantically
    similar future queries can be answered without re-running the full
    RAG pipeline (embed → search → generate → ground → cite).
    """

    def search_similar(
        self,
        query_embedding: List[float],
        meeting_ids: Optional[List[str]] = None,
        similarity_threshold: float = 0.95,
    ) -> Optional[CachedQuery]:
        """Find a cached answer whose query embedding is similar enough.

        Args:
            query_embedding: Embedding of the new question.
            meeting_ids: Optional scope filter (only match caches for these meetings).
            similarity_threshold: Cosine similarity threshold (0–1). Higher
                values require closer matches. 0.95 is a good default — it
                catches near-duplicate questions while avoiding false positives.

        Returns:
            The matching CachedQuery if found, else None.
        """
        ...

    def store(
        self,
        query_text: str,
        query_embedding: List[float],
        meeting_ids: Optional[List[str]],
        cited_answer: CitedAnswer,
        ttl_hours: int = 24,
    ) -> CachedQuery:
        """Store a new query/answer pair in the cache.

        Args:
            query_text: The original question text.
            query_embedding: The question's embedding vector.
            meeting_ids: Meeting scope for this answer.
            cited_answer: The full cited answer to cache.
            ttl_hours: Hours before the entry auto-expires.

        Returns:
            The created CachedQuery record.
        """
        ...

    def invalidate_for_meeting(self, meeting_id: str) -> int:
        """Remove all cache entries scoped to a specific meeting.

        Called after re-ingestion so stale answers are not served.

        Args:
            meeting_id: Meeting whose cache entries should be removed.

        Returns:
            Number of entries invalidated.
        """
        ...
