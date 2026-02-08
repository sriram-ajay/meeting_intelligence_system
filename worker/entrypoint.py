"""
Worker entrypoint for ECS Fargate RunTask.

Invoked by the API service via ``ecs:RunTask`` with environment overrides:
    MEETING_ID   — the meeting to process
    FILENAME     — original upload filename

The worker:
    1. Downloads the raw transcript from S3 (already uploaded by the API).
    2. Runs IngestionService.ingest().
    3. Exits 0 on success, 1 on failure.

All logging is JSON (structlog) and ships to CloudWatch via the awslogs driver.
"""

from __future__ import annotations

import os
import sys

from shared_utils.config_loader import get_settings
from shared_utils.constants import LogScope
from shared_utils.logging_utils import get_scoped_logger
from shared_utils.di_container import get_di_container

logger = get_scoped_logger(LogScope.WORKER)


def main() -> int:
    """Worker main — parse env vars, build deps, run ingestion."""
    meeting_id = os.environ.get("MEETING_ID", "")
    filename = os.environ.get("FILENAME", "")

    if not meeting_id or not filename:
        logger.error(
            "worker_missing_env",
            meeting_id=meeting_id,
            filename=filename,
        )
        print("ERROR: MEETING_ID and FILENAME env vars are required", file=sys.stderr)
        return 1

    logger.info(
        "worker_started",
        meeting_id=meeting_id,
        filename=filename,
    )

    try:
        container = get_di_container()
        ingestion_svc = container.get_ingestion_service()

        # Download raw file that was already stored by the API
        artifact_store = container.get_artifact_store()
        settings = get_settings()
        raw_uri = f"s3://{settings.s3_raw_bucket}/{settings.s3_raw_prefix}/{meeting_id}/{filename}"
        raw_bytes = artifact_store.download_raw(raw_uri)

        report = ingestion_svc.ingest(
            meeting_id=meeting_id,
            filename=filename,
            raw_content=raw_bytes,
        )

        logger.info(
            "worker_completed",
            meeting_id=meeting_id,
            status=report.status.value,
            chunks=report.chunks_created,
            duration_ms=round(report.duration_ms, 1),
        )
        return 0

    except Exception as exc:
        logger.error(
            "worker_failed",
            meeting_id=meeting_id,
            error=str(exc),
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
