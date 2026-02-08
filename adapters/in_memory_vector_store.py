"""
In-memory vector store adapter for local development.

Implements VectorStorePort using a simple Python dict + brute-force cosine
similarity. Used when S3 Vectors is unavailable (e.g. LocalStack, CI).

NOT for production — no persistence across restarts.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from domain.models import VectorRecord
from shared_utils.logging_utils import get_scoped_logger
from shared_utils.constants import LogScope


logger = get_scoped_logger(LogScope.ADAPTER)


class InMemoryVectorStoreAdapter:
    """Brute-force in-memory implementation of VectorStorePort.

    Stores vectors in a dict keyed by chunk_id.  Search uses cosine similarity.
    """

    def __init__(self) -> None:
        self._store: Dict[str, VectorRecord] = {}

    # ------------------------------------------------------------------
    # VectorStorePort implementation
    # ------------------------------------------------------------------

    def store_vectors(self, vectors: List[VectorRecord]) -> None:
        """Store vectors in memory."""
        for v in vectors:
            self._store[v.chunk_id] = v
        logger.info("inmemory_vectors_stored", count=len(vectors), total=len(self._store))

    def search(
        self,
        embedding: List[float],
        top_k: int = 10,
        meeting_ids: Optional[List[str]] = None,
    ) -> List[VectorRecord]:
        """Brute-force cosine similarity search."""
        candidates = self._store.values()
        if meeting_ids:
            candidates = [v for v in candidates if v.meeting_id in set(meeting_ids)]

        scored: List[Tuple[float, VectorRecord]] = []
        for v in candidates:
            sim = self._cosine_similarity(embedding, v.embedding)
            scored.append((sim, v))

        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        for sim, v in scored[:top_k]:
            results.append(
                VectorRecord(
                    chunk_id=v.chunk_id,
                    meeting_id=v.meeting_id,
                    embedding=[],  # don't return full vectors on search
                    text=v.text,
                    metadata=v.metadata,
                )
            )
        logger.info(
            "inmemory_vector_search",
            top_k=top_k,
            results=len(results),
            meeting_filter=meeting_ids,
        )
        return results

    def delete_by_meeting(self, meeting_id: str) -> None:
        """Remove all vectors for a meeting."""
        keys = [k for k, v in self._store.items() if v.meeting_id == meeting_id]
        for k in keys:
            del self._store[k]
        logger.info(
            "inmemory_vectors_deleted",
            meeting_id=meeting_id,
            deleted_count=len(keys),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if len(a) != len(b) or not a:
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)
