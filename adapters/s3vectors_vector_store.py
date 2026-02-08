"""
S3 Vectors-backed vector store adapter.

Implements VectorStorePort using the Amazon S3 Vectors boto3 client
for embedding storage and ANN retrieval.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

from domain.models import VectorRecord
from ports.vector_store import VectorStorePort
from shared_utils.logging_utils import get_scoped_logger
from shared_utils.constants import LogScope
from shared_utils.error_handler import ExternalServiceError


logger = get_scoped_logger(LogScope.ADAPTER)


class S3VectorsVectorStoreAdapter:
    """Amazon S3 Vectors implementation of VectorStorePort.

    Uses the ``s3vectors`` boto3 client for:
    - ``put_vectors``  – store embeddings with metadata
    - ``query_vectors`` – ANN search with optional metadata filters
    - ``delete_vectors`` – remove vectors by key
    """

    def __init__(
        self,
        vector_bucket_name: str,
        index_name: str,
        region: str = "eu-west-2",
        endpoint_url: str = "",
        s3vectors_client: Optional[object] = None,
    ) -> None:
        self._bucket = vector_bucket_name
        self._index = index_name
        client_kwargs: dict = {"region_name": region}
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
        self._client = s3vectors_client or boto3.client(
            "s3vectors", **client_kwargs
        )

    # ------------------------------------------------------------------
    # VectorStorePort implementation
    # ------------------------------------------------------------------

    def store_vectors(self, vectors: List[VectorRecord]) -> None:
        """Store embedding vectors in S3 Vectors index."""
        if not vectors:
            return

        records = []
        for v in vectors:
            records.append(
                {
                    "key": v.chunk_id,
                    "data": {"float32": v.embedding},
                    "metadata": {
                        "meeting_id": v.meeting_id,
                        "text": v.text[:1000],  # cap metadata text
                        **v.metadata,
                    },
                }
            )

        try:
            # S3 Vectors supports batches; send in chunks of 100
            for i in range(0, len(records), 100):
                batch = records[i : i + 100]
                self._client.put_vectors(
                    vectorBucketName=self._bucket,
                    indexName=self._index,
                    vectors=batch,
                )
            logger.info(
                "s3vectors_stored",
                count=len(vectors),
                index=self._index,
            )
        except ClientError as exc:
            logger.error("s3vectors_store_failed", error=str(exc))
            raise ExternalServiceError(
                "S3Vectors", f"Failed to store vectors: {exc}"
            ) from exc

    def search(
        self,
        embedding: List[float],
        top_k: int = 10,
        meeting_ids: Optional[List[str]] = None,
    ) -> List[VectorRecord]:
        """ANN search with optional meeting_id filter."""
        query_params: Dict[str, Any] = {
            "vectorBucketName": self._bucket,
            "indexName": self._index,
            "queryVector": {"float32": embedding},
            "topK": top_k,
            "returnMetadata": True,
        }

        if meeting_ids:
            # S3 Vectors supports metadata filters
            if len(meeting_ids) == 1:
                query_params["filter"] = {
                    "meeting_id": {"$eq": meeting_ids[0]}
                }
            else:
                query_params["filter"] = {
                    "meeting_id": {"$in": meeting_ids}
                }

        try:
            response = self._client.query_vectors(**query_params)
            results: List[VectorRecord] = []
            for hit in response.get("vectors", []):
                meta = hit.get("metadata", {})
                results.append(
                    VectorRecord(
                        chunk_id=hit.get("key", str(uuid.uuid4())),
                        meeting_id=meta.get("meeting_id", ""),
                        embedding=[],  # don't return full vectors on search
                        text=meta.get("text", ""),
                        metadata={
                            k: v
                            for k, v in meta.items()
                            if k not in ("meeting_id", "text")
                        },
                    )
                )
            logger.info(
                "s3vectors_search",
                top_k=top_k,
                results=len(results),
                meeting_filter=meeting_ids,
            )
            return results
        except ClientError as exc:
            logger.error("s3vectors_search_failed", error=str(exc))
            raise ExternalServiceError(
                "S3Vectors", f"Vector search failed: {exc}"
            ) from exc

    def delete_by_meeting(self, meeting_id: str) -> None:
        """Delete all vectors for a given meeting_id.

        Note: S3 Vectors may require listing keys by metadata filter first,
        then deleting by key. This is a best-effort implementation.
        """
        try:
            # Query to find all keys for this meeting
            response = self._client.query_vectors(
                vectorBucketName=self._bucket,
                indexName=self._index,
                queryVector={"float32": [0.0]},  # dummy vector
                topK=10000,
                filter={"meeting_id": {"$eq": meeting_id}},
            )
            keys = [hit["key"] for hit in response.get("vectors", []) if "key" in hit]

            if keys:
                # Delete in batches
                for i in range(0, len(keys), 100):
                    batch = keys[i : i + 100]
                    self._client.delete_vectors(
                        vectorBucketName=self._bucket,
                        indexName=self._index,
                        keys=batch,
                    )
                logger.info(
                    "s3vectors_deleted",
                    meeting_id=meeting_id,
                    deleted_count=len(keys),
                )
            else:
                logger.info(
                    "s3vectors_delete_noop",
                    meeting_id=meeting_id,
                )
        except ClientError as exc:
            logger.error(
                "s3vectors_delete_failed",
                meeting_id=meeting_id,
                error=str(exc),
            )
            raise ExternalServiceError(
                "S3Vectors", f"Failed to delete vectors: {exc}"
            ) from exc
