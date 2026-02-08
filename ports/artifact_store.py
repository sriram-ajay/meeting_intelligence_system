"""
Port interface for artifact (file) storage.

Implementations: S3ArtifactStoreAdapter (adapters/)
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ArtifactStorePort(Protocol):
    """Abstract interface for raw and derived artifact storage."""

    def upload_raw(self, meeting_id: str, filename: str, content: bytes) -> str:
        """Upload a raw transcript file.

        Args:
            meeting_id: Associated meeting identifier.
            filename: Original filename.
            content: Raw file bytes.

        Returns:
            Canonical URI of the stored object (e.g. s3://bucket/prefix/key).
        """
        ...

    def download_raw(self, s3_uri: str) -> bytes:
        """Download a raw transcript by its URI.

        Args:
            s3_uri: URI returned by upload_raw.

        Returns:
            Raw file bytes.

        Raises:
            ExternalServiceError: If download fails.
        """
        ...

    def upload_derived(
        self, meeting_id: str, artifact_name: str, content: bytes
    ) -> str:
        """Upload a derived artifact (e.g. chunk_map.json, ingestion_report.json).

        Args:
            meeting_id: Associated meeting identifier.
            artifact_name: Filename within the derived prefix.
            content: Serialized artifact bytes (typically JSON).

        Returns:
            Canonical URI of the stored object.
        """
        ...

    def download_derived(self, meeting_id: str, artifact_name: str) -> bytes:
        """Download a derived artifact.

        Args:
            meeting_id: Associated meeting identifier.
            artifact_name: Filename within the derived prefix.

        Returns:
            Artifact bytes.
        """
        ...

    def get_derived_prefix(self, meeting_id: str) -> str:
        """Return the canonical URI prefix for a meeting's derived artifacts.

        Args:
            meeting_id: Meeting identifier.

        Returns:
            URI prefix string (e.g. s3://bucket/derived/meeting_id/).
        """
        ...
