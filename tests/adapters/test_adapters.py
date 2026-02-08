"""
Unit tests for adapter implementations.

Uses mocked boto3 clients — no live AWS calls.
"""

import json
import pytest
from unittest.mock import MagicMock, patch
from botocore.exceptions import ClientError

from domain.models import IngestionStatus, MeetingRecord, VectorRecord
from adapters.s3_artifact_store import S3ArtifactStoreAdapter
from adapters.dynamo_metadata_store import DynamoMetadataStoreAdapter
from adapters.s3vectors_vector_store import S3VectorsVectorStoreAdapter
from shared_utils.error_handler import ExternalServiceError


# ======================================================================
# S3ArtifactStoreAdapter
# ======================================================================

class TestS3ArtifactStoreAdapter:
    @pytest.fixture()
    def mock_s3(self) -> MagicMock:
        return MagicMock()

    @pytest.fixture()
    def adapter(self, mock_s3: MagicMock) -> S3ArtifactStoreAdapter:
        return S3ArtifactStoreAdapter(
            raw_bucket="test-raw",
            raw_prefix="raw",
            derived_bucket="test-derived",
            derived_prefix="derived",
            s3_client=mock_s3,
        )

    def test_upload_raw(self, adapter: S3ArtifactStoreAdapter, mock_s3: MagicMock) -> None:
        uri = adapter.upload_raw("m-1", "transcript.txt", b"hello world")
        assert uri == "s3://test-raw/raw/m-1/transcript.txt"
        mock_s3.put_object.assert_called_once()
        call_kwargs = mock_s3.put_object.call_args[1]
        assert call_kwargs["Bucket"] == "test-raw"
        assert call_kwargs["Body"] == b"hello world"

    def test_download_raw(self, adapter: S3ArtifactStoreAdapter, mock_s3: MagicMock) -> None:
        mock_s3.get_object.return_value = {"Body": MagicMock(read=lambda: b"content")}
        data = adapter.download_raw("s3://test-raw/raw/m-1/file.txt")
        assert data == b"content"

    def test_upload_derived(self, adapter: S3ArtifactStoreAdapter, mock_s3: MagicMock) -> None:
        uri = adapter.upload_derived("m-1", "chunk_map.json", b'{"key":"val"}')
        assert uri == "s3://test-derived/derived/m-1/chunk_map.json"

    def test_download_derived(self, adapter: S3ArtifactStoreAdapter, mock_s3: MagicMock) -> None:
        mock_s3.get_object.return_value = {"Body": MagicMock(read=lambda: b'{"k":"v"}')}
        data = adapter.download_derived("m-1", "chunk_map.json")
        assert json.loads(data) == {"k": "v"}

    def test_get_derived_prefix(self, adapter: S3ArtifactStoreAdapter) -> None:
        prefix = adapter.get_derived_prefix("m-1")
        assert prefix == "s3://test-derived/derived/m-1/"

    def test_upload_raw_client_error(self, adapter: S3ArtifactStoreAdapter, mock_s3: MagicMock) -> None:
        mock_s3.put_object.side_effect = ClientError(
            {"Error": {"Code": "500", "Message": "fail"}}, "PutObject"
        )
        with pytest.raises(ExternalServiceError, match="S3"):
            adapter.upload_raw("m-1", "file.txt", b"data")

    def test_parse_s3_uri(self) -> None:
        bucket, key = S3ArtifactStoreAdapter._parse_s3_uri("s3://my-bucket/some/key.txt")
        assert bucket == "my-bucket"
        assert key == "some/key.txt"

    def test_parse_invalid_uri(self) -> None:
        with pytest.raises(ValueError, match="Expected s3://"):
            S3ArtifactStoreAdapter._parse_s3_uri("https://example.com/file")


# ======================================================================
# DynamoMetadataStoreAdapter
# ======================================================================

class TestDynamoMetadataStoreAdapter:
    @pytest.fixture()
    def mock_table(self) -> MagicMock:
        return MagicMock()

    @pytest.fixture()
    def adapter(self, mock_table: MagicMock) -> DynamoMetadataStoreAdapter:
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        a = DynamoMetadataStoreAdapter(
            table_name="TestTable",
            dynamodb_resource=mock_resource,
        )
        return a

    def _sample_record(self) -> MeetingRecord:
        return MeetingRecord(
            meeting_id="m-1",
            title_normalized="standup",
            meeting_date="2026-01-15",
            participants=["Alice", "Bob"],
            s3_uri_raw="s3://bucket/raw/m-1/file.txt",
            s3_uri_derived_prefix="s3://bucket/derived/m-1/",
            doc_hash="abc",
        )

    def test_put_meeting(self, adapter: DynamoMetadataStoreAdapter, mock_table: MagicMock) -> None:
        adapter.put_meeting(self._sample_record())
        mock_table.put_item.assert_called_once()
        item = mock_table.put_item.call_args[1]["Item"]
        assert item["meeting_id"] == "m-1"
        assert item["ingestion_status"] == "PENDING"
        # participants stored as set
        assert isinstance(item["participants"], set)

    def test_get_meeting_found(self, adapter: DynamoMetadataStoreAdapter, mock_table: MagicMock) -> None:
        mock_table.get_item.return_value = {
            "Item": {
                "meeting_id": "m-1",
                "title_normalized": "standup",
                "meeting_date": "2026-01-15",
                "participants": {"Alice", "Bob"},
                "s3_uri_raw": "s3://b/r",
                "s3_uri_derived_prefix": "s3://b/d/",
                "doc_hash": "x",
                "version": 1,
                "ingestion_status": "READY",
            }
        }
        record = adapter.get_meeting("m-1")
        assert record is not None
        assert record.ingestion_status == IngestionStatus.READY
        assert "Alice" in record.participants

    def test_get_meeting_not_found(self, adapter: DynamoMetadataStoreAdapter, mock_table: MagicMock) -> None:
        mock_table.get_item.return_value = {}
        assert adapter.get_meeting("nonexistent") is None

    def test_update_status(self, adapter: DynamoMetadataStoreAdapter, mock_table: MagicMock) -> None:
        adapter.update_status("m-1", IngestionStatus.READY)
        mock_table.update_item.assert_called_once()
        kwargs = mock_table.update_item.call_args[1]
        assert kwargs["ExpressionAttributeValues"][":s"] == "READY"

    def test_update_status_with_error(self, adapter: DynamoMetadataStoreAdapter, mock_table: MagicMock) -> None:
        adapter.update_status("m-1", IngestionStatus.FAILED, error_message="parse failed")
        kwargs = mock_table.update_item.call_args[1]
        assert kwargs["ExpressionAttributeValues"][":e"] == "parse failed"

    def test_query_meetings_no_filter(self, adapter: DynamoMetadataStoreAdapter, mock_table: MagicMock) -> None:
        mock_table.scan.return_value = {
            "Items": [
                {
                    "meeting_id": "m-1",
                    "title_normalized": "standup",
                    "meeting_date": "2026-01-15",
                    "ingestion_status": "READY",
                }
            ]
        }
        results = adapter.query_meetings()
        assert len(results) == 1

    def test_put_meeting_client_error(self, adapter: DynamoMetadataStoreAdapter, mock_table: MagicMock) -> None:
        mock_table.put_item.side_effect = ClientError(
            {"Error": {"Code": "500", "Message": "fail"}}, "PutItem"
        )
        with pytest.raises(ExternalServiceError, match="DynamoDB"):
            adapter.put_meeting(self._sample_record())


# ======================================================================
# S3VectorsVectorStoreAdapter
# ======================================================================

class TestS3VectorsVectorStoreAdapter:
    @pytest.fixture()
    def mock_client(self) -> MagicMock:
        return MagicMock()

    @pytest.fixture()
    def adapter(self, mock_client: MagicMock) -> S3VectorsVectorStoreAdapter:
        return S3VectorsVectorStoreAdapter(
            vector_bucket_name="test-vectors",
            index_name="test-index",
            s3vectors_client=mock_client,
        )

    def test_store_vectors(self, adapter: S3VectorsVectorStoreAdapter, mock_client: MagicMock) -> None:
        vectors = [
            VectorRecord(chunk_id="c-1", meeting_id="m-1", embedding=[0.1, 0.2], text="hello"),
            VectorRecord(chunk_id="c-2", meeting_id="m-1", embedding=[0.3, 0.4], text="world"),
        ]
        adapter.store_vectors(vectors)
        mock_client.put_vectors.assert_called_once()
        call_kwargs = mock_client.put_vectors.call_args[1]
        assert call_kwargs["vectorBucketName"] == "test-vectors"
        assert len(call_kwargs["vectors"]) == 2

    def test_store_empty_vectors(self, adapter: S3VectorsVectorStoreAdapter, mock_client: MagicMock) -> None:
        adapter.store_vectors([])
        mock_client.put_vectors.assert_not_called()

    def test_search_no_filter(self, adapter: S3VectorsVectorStoreAdapter, mock_client: MagicMock) -> None:
        mock_client.query_vectors.return_value = {
            "vectors": [
                {"key": "c-1", "metadata": {"meeting_id": "m-1", "text": "hello"}},
            ]
        }
        results = adapter.search(embedding=[0.1, 0.2], top_k=5)
        assert len(results) == 1
        assert results[0].chunk_id == "c-1"

    def test_search_with_meeting_filter(self, adapter: S3VectorsVectorStoreAdapter, mock_client: MagicMock) -> None:
        mock_client.query_vectors.return_value = {"vectors": []}
        adapter.search(embedding=[0.1], top_k=5, meeting_ids=["m-1"])
        call_kwargs = mock_client.query_vectors.call_args[1]
        assert call_kwargs["filter"] == {"meeting_id": {"$eq": "m-1"}}

    def test_search_with_multiple_meetings(self, adapter: S3VectorsVectorStoreAdapter, mock_client: MagicMock) -> None:
        mock_client.query_vectors.return_value = {"vectors": []}
        adapter.search(embedding=[0.1], top_k=5, meeting_ids=["m-1", "m-2"])
        call_kwargs = mock_client.query_vectors.call_args[1]
        assert call_kwargs["filter"] == {"meeting_id": {"$in": ["m-1", "m-2"]}}

    def test_delete_by_meeting(self, adapter: S3VectorsVectorStoreAdapter, mock_client: MagicMock) -> None:
        mock_client.query_vectors.return_value = {
            "vectors": [{"key": "c-1"}, {"key": "c-2"}]
        }
        adapter.delete_by_meeting("m-1")
        mock_client.delete_vectors.assert_called_once()

    def test_store_vectors_client_error(self, adapter: S3VectorsVectorStoreAdapter, mock_client: MagicMock) -> None:
        mock_client.put_vectors.side_effect = ClientError(
            {"Error": {"Code": "500", "Message": "fail"}}, "PutVectors"
        )
        with pytest.raises(ExternalServiceError, match="S3Vectors"):
            adapter.store_vectors([
                VectorRecord(chunk_id="c-1", meeting_id="m-1", embedding=[0.1], text="x")
            ])
