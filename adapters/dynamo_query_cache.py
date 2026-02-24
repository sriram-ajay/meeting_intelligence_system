"""
DynamoDB-backed semantic query cache adapter.

Implements QueryCachePort using a DynamoDB table with brute-force cosine
similarity search over stored embeddings.  For production volumes, consider
backing this with S3 Vectors or a dedicated ANN index.

Table schema:
    PK: cache_id (UUID)
    Attributes: query_text, query_embedding, meeting_ids, cited_answer (JSON),
                created_at, ttl (Unix epoch for DynamoDB TTL)
"""

from __future__ import annotations

import json
import math
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

from domain.models import CachedQuery, CitedAnswer
from ports.query_cache import QueryCachePort
from shared_utils.logging_utils import get_scoped_logger
from shared_utils.constants import LogScope
from shared_utils.error_handler import ExternalServiceError


logger = get_scoped_logger(LogScope.ADAPTER)


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class DynamoQueryCacheAdapter:
    """DynamoDB implementation of QueryCachePort.

    Stores cached queries with their embeddings and answers.
    Uses brute-force cosine similarity for cache lookup.

    Table key: ``cache_id`` (partition key, no sort key).
    DynamoDB TTL attribute: ``ttl`` (Unix epoch for auto-expiry).
    """

    def __init__(
        self,
        table_name: str = "QueryCache",
        region: str = "eu-west-2",
        endpoint_url: str = "",
        dynamodb_resource: Optional[object] = None,
    ) -> None:
        self._table_name = table_name
        resource_kwargs: dict = {"region_name": region}
        if endpoint_url:
            resource_kwargs["endpoint_url"] = endpoint_url
        self._dynamo = dynamodb_resource or boto3.resource(
            "dynamodb", **resource_kwargs
        )
        self._table = self._dynamo.Table(table_name)

    # ------------------------------------------------------------------
    # QueryCachePort implementation
    # ------------------------------------------------------------------

    def search_similar(
        self,
        query_embedding: List[float],
        meeting_ids: Optional[List[str]] = None,
        similarity_threshold: float = 0.95,
    ) -> Optional[CachedQuery]:
        """Search for a cached query with similar embedding.

        Scans the table and computes cosine similarity. For production
        scale, replace with an ANN index.
        """
        try:
            now = int(time.time())
            response = self._table.scan()
            items = response.get("Items", [])

            best_match: Optional[CachedQuery] = None
            best_sim = 0.0

            for item in items:
                # Skip expired entries (TTL may not have been cleaned yet)
                ttl = int(item.get("ttl", 0))
                if ttl > 0 and ttl < now:
                    continue

                # Scope filter: if meeting_ids provided, only match entries
                # that overlap with the requested meeting scope
                if meeting_ids is not None:
                    cached_mids = item.get("meeting_ids", [])
                    if cached_mids and not set(cached_mids) & set(meeting_ids):
                        continue

                stored_embedding = [float(x) for x in item.get("query_embedding", [])]
                if not stored_embedding:
                    continue

                sim = _cosine_similarity(query_embedding, stored_embedding)
                if sim >= similarity_threshold and sim > best_sim:
                    best_sim = sim
                    best_match = self._from_dynamo_item(item)

            if best_match is not None:
                logger.info(
                    "cache_hit",
                    cache_id=best_match.cache_id,
                    similarity=round(best_sim, 4),
                )

            return best_match

        except ClientError as exc:
            logger.error("cache_search_failed", error=str(exc))
            return None  # Fail-open: cache miss on error

    def store(
        self,
        query_text: str,
        query_embedding: List[float],
        meeting_ids: Optional[List[str]],
        cited_answer: CitedAnswer,
        ttl_hours: int = 24,
    ) -> CachedQuery:
        """Store a query/answer pair in the cache."""
        cache_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        ttl_epoch = int(now.timestamp()) + (ttl_hours * 3600)

        cached = CachedQuery(
            cache_id=cache_id,
            query_text=query_text,
            query_embedding=query_embedding,
            meeting_ids=meeting_ids or [],
            cited_answer=cited_answer,
            created_at=now.isoformat(),
            ttl=ttl_epoch,
        )

        try:
            item = self._to_dynamo_item(cached)
            self._table.put_item(Item=item)
            logger.info("cache_stored", cache_id=cache_id)
            return cached
        except ClientError as exc:
            logger.error("cache_store_failed", error=str(exc))
            raise ExternalServiceError(
                "DynamoDB", f"Failed to store cache entry: {exc}"
            ) from exc

    def invalidate_for_meeting(self, meeting_id: str) -> int:
        """Remove all cache entries scoped to a specific meeting."""
        try:
            response = self._table.scan()
            items = response.get("Items", [])
            deleted = 0
            for item in items:
                cached_mids = item.get("meeting_ids", [])
                if meeting_id in cached_mids:
                    self._table.delete_item(
                        Key={"cache_id": item["cache_id"]}
                    )
                    deleted += 1
            logger.info(
                "cache_invalidated",
                meeting_id=meeting_id,
                entries_deleted=deleted,
            )
            return deleted
        except ClientError as exc:
            logger.error(
                "cache_invalidate_failed",
                meeting_id=meeting_id,
                error=str(exc),
            )
            return 0

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_dynamo_item(cached: CachedQuery) -> Dict[str, Any]:
        """Convert CachedQuery to DynamoDB item (JSON-serializable)."""
        return {
            "cache_id": cached.cache_id,
            "query_text": cached.query_text,
            # Store embedding as list of strings (DynamoDB Number type)
            "query_embedding": [str(x) for x in cached.query_embedding],
            "meeting_ids": cached.meeting_ids,
            "cited_answer": json.loads(cached.cited_answer.model_dump_json()),
            "created_at": cached.created_at,
            "ttl": cached.ttl,
        }

    @staticmethod
    def _from_dynamo_item(item: Dict[str, Any]) -> CachedQuery:
        """Reconstruct CachedQuery from DynamoDB item."""
        cited_data = item.get("cited_answer", {})
        cited_answer = CitedAnswer(**cited_data)
        return CachedQuery(
            cache_id=item["cache_id"],
            query_text=item.get("query_text", ""),
            query_embedding=[float(x) for x in item.get("query_embedding", [])],
            meeting_ids=item.get("meeting_ids", []),
            cited_answer=cited_answer,
            created_at=item.get("created_at", ""),
            ttl=int(item.get("ttl", 0)),
        )
