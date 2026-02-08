"""
Port interface for meeting metadata storage.

Implementations: DynamoMetadataStoreAdapter (adapters/)
"""

from __future__ import annotations

from typing import List, Optional, Protocol, runtime_checkable

from domain.models import IngestionStatus, MeetingRecord


@runtime_checkable
class MetadataStorePort(Protocol):
    """Abstract interface for meeting metadata CRUD operations."""

    def put_meeting(self, record: MeetingRecord) -> None:
        """Create or overwrite a meeting metadata record.

        Args:
            record: Complete meeting record to store.

        Raises:
            ExternalServiceError: If the store is unreachable.
        """
        ...

    def get_meeting(self, meeting_id: str) -> Optional[MeetingRecord]:
        """Retrieve a single meeting record by ID.

        Args:
            meeting_id: Primary key.

        Returns:
            MeetingRecord if found, None otherwise.
        """
        ...

    def query_meetings(
        self,
        date: Optional[str] = None,
        title: Optional[str] = None,
        participant: Optional[str] = None,
    ) -> List[MeetingRecord]:
        """Query meetings with optional filters.

        All filters are AND-combined.  Omitted filters are ignored.

        Args:
            date: ISO date string to match meeting_date.
            title: Substring match against title_normalized (case-insensitive).
            participant: Exact match within participants set.

        Returns:
            List of matching MeetingRecords.
        """
        ...

    def update_status(
        self,
        meeting_id: str,
        status: IngestionStatus,
        error_message: Optional[str] = None,
    ) -> None:
        """Transition a meeting's ingestion_status.

        Args:
            meeting_id: Primary key.
            status: New status value.
            error_message: Optional message (typically set on FAILED).

        Raises:
            ExternalServiceError: If the store is unreachable.
        """
        ...
