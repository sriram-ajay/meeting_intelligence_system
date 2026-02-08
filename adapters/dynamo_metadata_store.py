"""
DynamoDB-backed metadata store adapter.

Implements MetadataStorePort using boto3 for the MeetingsMetadata table.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

from domain.models import IngestionStatus, MeetingRecord
from ports.metadata_store import MetadataStorePort
from shared_utils.logging_utils import get_scoped_logger
from shared_utils.constants import LogScope
from shared_utils.error_handler import ExternalServiceError


logger = get_scoped_logger(LogScope.ADAPTER)


class DynamoMetadataStoreAdapter:
    """Amazon DynamoDB implementation of MetadataStorePort.

    Table key: ``meeting_id`` (partition key, no sort key).
    """

    def __init__(
        self,
        table_name: str,
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
    # MetadataStorePort implementation
    # ------------------------------------------------------------------

    def put_meeting(self, record: MeetingRecord) -> None:
        """Create or overwrite a meeting metadata record."""
        item = self._to_dynamo_item(record)
        try:
            self._table.put_item(Item=item)
            logger.info(
                "dynamo_put_meeting",
                meeting_id=record.meeting_id,
                status=record.ingestion_status.value,
            )
        except ClientError as exc:
            logger.error(
                "dynamo_put_meeting_failed",
                meeting_id=record.meeting_id,
                error=str(exc),
            )
            raise ExternalServiceError(
                "DynamoDB", f"Failed to put meeting record: {exc}"
            ) from exc

    def get_meeting(self, meeting_id: str) -> Optional[MeetingRecord]:
        """Retrieve a single meeting record by ID."""
        try:
            response = self._table.get_item(Key={"meeting_id": meeting_id})
            item = response.get("Item")
            if item is None:
                return None
            return self._from_dynamo_item(item)
        except ClientError as exc:
            logger.error(
                "dynamo_get_meeting_failed",
                meeting_id=meeting_id,
                error=str(exc),
            )
            raise ExternalServiceError(
                "DynamoDB", f"Failed to get meeting record: {exc}"
            ) from exc

    def query_meetings(
        self,
        date: Optional[str] = None,
        title: Optional[str] = None,
        participant: Optional[str] = None,
    ) -> List[MeetingRecord]:
        """Scan with optional filters (DynamoDB scan — acceptable for Phase 1 scale)."""
        filter_expr = None

        if date:
            condition = Attr("meeting_date").eq(date)
            filter_expr = condition if filter_expr is None else filter_expr & condition

        if title:
            condition = Attr("title_normalized").contains(title.lower())
            filter_expr = condition if filter_expr is None else filter_expr & condition

        if participant:
            condition = Attr("participants").contains(participant)
            filter_expr = condition if filter_expr is None else filter_expr & condition

        try:
            scan_kwargs: Dict[str, Any] = {}
            if filter_expr is not None:
                scan_kwargs["FilterExpression"] = filter_expr

            items: List[Dict[str, Any]] = []
            # Handle pagination
            while True:
                response = self._table.scan(**scan_kwargs)
                items.extend(response.get("Items", []))
                last_key = response.get("LastEvaluatedKey")
                if last_key is None:
                    break
                scan_kwargs["ExclusiveStartKey"] = last_key

            logger.info("dynamo_query_meetings", results=len(items))
            return [self._from_dynamo_item(item) for item in items]

        except ClientError as exc:
            logger.error("dynamo_query_meetings_failed", error=str(exc))
            raise ExternalServiceError(
                "DynamoDB", f"Failed to query meetings: {exc}"
            ) from exc

    def update_status(
        self,
        meeting_id: str,
        status: IngestionStatus,
        error_message: Optional[str] = None,
    ) -> None:
        """Update ingestion_status (and optionally error_message, ingested_at)."""
        update_expr = "SET ingestion_status = :s, ingested_at = :t"
        expr_values: Dict[str, Any] = {
            ":s": status.value,
            ":t": datetime.now(timezone.utc).isoformat(),
        }

        if error_message is not None:
            update_expr += ", error_message = :e"
            expr_values[":e"] = error_message
        else:
            # Clear any previous error on success
            update_expr += " REMOVE error_message"

        try:
            self._table.update_item(
                Key={"meeting_id": meeting_id},
                UpdateExpression=update_expr,
                ExpressionAttributeValues=expr_values,
            )
            logger.info(
                "dynamo_update_status",
                meeting_id=meeting_id,
                status=status.value,
            )
        except ClientError as exc:
            logger.error(
                "dynamo_update_status_failed",
                meeting_id=meeting_id,
                error=str(exc),
            )
            raise ExternalServiceError(
                "DynamoDB", f"Failed to update status: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_dynamo_item(record: MeetingRecord) -> Dict[str, Any]:
        """Convert domain MeetingRecord → DynamoDB item dict."""
        item: Dict[str, Any] = {
            "meeting_id": record.meeting_id,
            "title_normalized": record.title_normalized,
            "meeting_date": record.meeting_date,
            "s3_uri_raw": record.s3_uri_raw,
            "s3_uri_derived_prefix": record.s3_uri_derived_prefix,
            "doc_hash": record.doc_hash,
            "version": record.version,
            "ingestion_status": record.ingestion_status.value,
        }
        # participants is stored as a DynamoDB String Set
        if record.participants:
            item["participants"] = set(record.participants)
        if record.ingested_at:
            item["ingested_at"] = record.ingested_at
        if record.error_message:
            item["error_message"] = record.error_message
        return item

    @staticmethod
    def _from_dynamo_item(item: Dict[str, Any]) -> MeetingRecord:
        """Convert DynamoDB item dict → domain MeetingRecord."""
        participants_raw = item.get("participants", set())
        # DynamoDB returns sets; convert to sorted list for determinism
        participants = sorted(list(participants_raw)) if participants_raw else []

        return MeetingRecord(
            meeting_id=item["meeting_id"],
            title_normalized=item.get("title_normalized", ""),
            meeting_date=item.get("meeting_date", ""),
            participants=participants,
            s3_uri_raw=item.get("s3_uri_raw", ""),
            s3_uri_derived_prefix=item.get("s3_uri_derived_prefix", ""),
            doc_hash=item.get("doc_hash", ""),
            version=int(item.get("version", 1)),
            ingestion_status=IngestionStatus(
                item.get("ingestion_status", IngestionStatus.PENDING.value)
            ),
            ingested_at=item.get("ingested_at"),
            error_message=item.get("error_message"),
        )
