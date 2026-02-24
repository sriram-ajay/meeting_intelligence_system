"""
Worker entrypoint for ECS Fargate RunTask.

Invoked by the API service via ``ecs:RunTask`` with environment overrides:
    MEETING_ID   — the meeting to process
    FILENAME     — original upload filename
    USE_LANGGRAPH — "1" to use LangGraph pipeline, "0" for legacy (default: "1")

The worker:
    1. Downloads the raw transcript from S3 (already uploaded by the API).
    2. Runs ingestion (LangGraph or legacy IngestionService).
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


def _run_langgraph(container, meeting_id: str, filename: str, raw_bytes: bytes) -> int:
    """Run ingestion via the LangGraph pipeline."""
    graph = container.get_ingestion_graph()
    result = graph.invoke({
        "meeting_id": meeting_id,
        "filename": filename,
        "raw_content": raw_bytes,
    })
    report = result.get("report")
    if report is None:
        logger.error("worker_langgraph_no_report", meeting_id=meeting_id)
        return 1

    logger.info(
        "worker_completed",
        meeting_id=meeting_id,
        status=report.status.value,
        chunks=report.chunks_created,
        pipeline="langgraph",
    )
    return 0 if report.status.value == "ready" else 1


def _run_legacy(container, meeting_id: str, filename: str, raw_bytes: bytes) -> int:
    """Run ingestion via the legacy IngestionService."""
    ingestion_svc = container.get_ingestion_service()
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
        pipeline="legacy",
    )
    return 0


def main() -> int:
    """Worker main — parse env vars, build deps, run ingestion."""
    meeting_id = os.environ.get("MEETING_ID", "")
    filename = os.environ.get("FILENAME", "")
    use_langgraph = os.environ.get("USE_LANGGRAPH", "1") == "1"

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
        pipeline="langgraph" if use_langgraph else "legacy",
    )

    try:
        container = get_di_container()

        # Download raw file that was already stored by the API
        artifact_store = container.get_artifact_store()
        settings = get_settings()
        raw_uri = f"s3://{settings.s3_raw_bucket}/{settings.s3_raw_prefix}/{meeting_id}/{filename}"
        raw_bytes = artifact_store.download_raw(raw_uri)

        if use_langgraph:
            return _run_langgraph(container, meeting_id, filename, raw_bytes)
        else:
            return _run_legacy(container, meeting_id, filename, raw_bytes)

    except Exception as exc:
        logger.error(
            "worker_failed",
            meeting_id=meeting_id,
            error=str(exc),
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
