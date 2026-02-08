"""
S3-backed artifact store adapter.

Implements ArtifactStorePort using boto3 for raw and derived transcript artifacts.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError

from domain.models import MeetingRecord
from ports.artifact_store import ArtifactStorePort
from shared_utils.logging_utils import get_scoped_logger
from shared_utils.constants import LogScope
from shared_utils.error_handler import ExternalServiceError


logger = get_scoped_logger(LogScope.ADAPTER)


class S3ArtifactStoreAdapter:
    """Amazon S3 implementation of ArtifactStorePort.

    Stores raw transcripts under ``{raw_bucket}/{raw_prefix}/{meeting_id}/{filename}``
    and derived artifacts under ``{derived_bucket}/{derived_prefix}/{meeting_id}/{artifact_name}``.
    """

    def __init__(
        self,
        raw_bucket: str,
        raw_prefix: str,
        derived_bucket: str,
        derived_prefix: str,
        region: str = "eu-west-2",
        endpoint_url: str = "",
        s3_client: Optional[object] = None,
    ) -> None:
        self.raw_bucket = raw_bucket
        self.raw_prefix = raw_prefix.strip("/")
        self.derived_bucket = derived_bucket
        self.derived_prefix = derived_prefix.strip("/")
        client_kwargs: dict = {"region_name": region}
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
        self._s3 = s3_client or boto3.client("s3", **client_kwargs)

    # ------------------------------------------------------------------
    # ArtifactStorePort implementation
    # ------------------------------------------------------------------

    def upload_raw(self, meeting_id: str, filename: str, content: bytes) -> str:
        """Upload raw transcript to S3."""
        key = f"{self.raw_prefix}/{meeting_id}/{filename}"
        try:
            self._s3.put_object(
                Bucket=self.raw_bucket,
                Key=key,
                Body=content,
                ContentType="text/plain",
            )
            uri = f"s3://{self.raw_bucket}/{key}"
            logger.info(
                "artifact_uploaded_raw",
                meeting_id=meeting_id,
                s3_uri=uri,
                size_bytes=len(content),
            )
            return uri
        except ClientError as exc:
            logger.error("s3_upload_raw_failed", meeting_id=meeting_id, error=str(exc))
            raise ExternalServiceError("S3", f"Failed to upload raw artifact: {exc}") from exc

    def download_raw(self, s3_uri: str) -> bytes:
        """Download raw transcript from S3 URI."""
        bucket, key = self._parse_s3_uri(s3_uri)
        try:
            response = self._s3.get_object(Bucket=bucket, Key=key)
            data: bytes = response["Body"].read()
            logger.info("artifact_downloaded_raw", s3_uri=s3_uri, size_bytes=len(data))
            return data
        except ClientError as exc:
            logger.error("s3_download_raw_failed", s3_uri=s3_uri, error=str(exc))
            raise ExternalServiceError("S3", f"Failed to download raw artifact: {exc}") from exc

    def upload_derived(
        self, meeting_id: str, artifact_name: str, content: bytes
    ) -> str:
        """Upload derived artifact (JSON) to S3."""
        key = f"{self.derived_prefix}/{meeting_id}/{artifact_name}"
        try:
            self._s3.put_object(
                Bucket=self.derived_bucket,
                Key=key,
                Body=content,
                ContentType="application/json",
            )
            uri = f"s3://{self.derived_bucket}/{key}"
            logger.info(
                "artifact_uploaded_derived",
                meeting_id=meeting_id,
                artifact=artifact_name,
                s3_uri=uri,
            )
            return uri
        except ClientError as exc:
            logger.error(
                "s3_upload_derived_failed",
                meeting_id=meeting_id,
                artifact=artifact_name,
                error=str(exc),
            )
            raise ExternalServiceError("S3", f"Failed to upload derived artifact: {exc}") from exc

    def download_derived(self, meeting_id: str, artifact_name: str) -> bytes:
        """Download derived artifact from S3."""
        key = f"{self.derived_prefix}/{meeting_id}/{artifact_name}"
        try:
            response = self._s3.get_object(Bucket=self.derived_bucket, Key=key)
            data: bytes = response["Body"].read()
            logger.info(
                "artifact_downloaded_derived",
                meeting_id=meeting_id,
                artifact=artifact_name,
                size_bytes=len(data),
            )
            return data
        except ClientError as exc:
            logger.error(
                "s3_download_derived_failed",
                meeting_id=meeting_id,
                artifact=artifact_name,
                error=str(exc),
            )
            raise ExternalServiceError("S3", f"Failed to download derived artifact: {exc}") from exc

    def get_derived_prefix(self, meeting_id: str) -> str:
        """Return the canonical S3 URI prefix for derived artifacts."""
        return f"s3://{self.derived_bucket}/{self.derived_prefix}/{meeting_id}/"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_s3_uri(uri: str) -> tuple[str, str]:
        """Parse ``s3://bucket/key`` into (bucket, key)."""
        parsed = urlparse(uri)
        if parsed.scheme != "s3":
            raise ValueError(f"Expected s3:// URI, got: {uri}")
        bucket = parsed.netloc
        key = parsed.path.lstrip("/")
        return bucket, key
