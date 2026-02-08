"""
Port interface for vector store operations.

Implementations: S3VectorsVectorStoreAdapter (adapters/)
"""

from __future__ import annotations

from typing import List, Optional, Protocol, runtime_checkable

from domain.models import VectorRecord


@runtime_checkable
class VectorStorePort(Protocol):
    """Abstract interface for vector storage and retrieval."""

    def store_vectors(self, vectors: List[VectorRecord]) -> None:
        """Store embedding vectors with metadata.

        Args:
            vectors: List of vector records to store.

        Raises:
            ExternalServiceError: If the store is unreachable.
        """
        ...

    def search(
        self,
        embedding: List[float],
        top_k: int = 10,
        meeting_ids: Optional[List[str]] = None,
    ) -> List[VectorRecord]:
        """Search for similar vectors, optionally scoped to meetings.

        Args:
            embedding: Query embedding vector.
            top_k: Maximum results to return.
            meeting_ids: Optional filter to restrict search to specific meetings.

        Returns:
            Ranked list of matching VectorRecords (closest first).
        """
        ...

    def delete_by_meeting(self, meeting_id: str) -> None:
        """Delete all vectors associated with a meeting.

        Args:
            meeting_id: Meeting identifier whose vectors should be removed.
        """
        ...
