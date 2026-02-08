"""
FastAPI backend for Meeting Intelligence System v2.

Endpoints:
    GET  /health                     — Health check
    POST /api/v2/upload              — Async ingestion (S3 + ECS worker)
    GET  /api/status/{meeting_id}    — Poll ingestion status
    GET  /api/meetings               — List meetings (optional filters)
    POST /api/v2/query               — Grounded Q&A with citations
    POST /api/v2/evaluate            — Run DeepEval metrics on a Q&A pair
    GET  /api/v2/eval/history        — Retrieve evaluation history
"""

import uuid
import threading
from typing import Optional
from fastapi import FastAPI, UploadFile, File, HTTPException, status, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
import boto3
import uvicorn

from shared_utils.config_loader import get_settings
from shared_utils.logging_utils import ContextualLogger
from shared_utils.constants import LogScope, APIEndpoints
from shared_utils.error_handler import (
    AppException, ValidationError, handle_error
)
from shared_utils.validation import InputValidator
from shared_utils.di_container import get_di_container
from domain.models import IngestionStatus, MeetingRecord


# ---------------------------------------------------------------------------
# Application bootstrap
# ---------------------------------------------------------------------------

settings = get_settings()
logger = ContextualLogger(scope=LogScope.API)

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=settings.app_description,
)

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

# Validate providers once at startup so we fail fast
try:
    _container = get_di_container()
    _container.validate_all_providers()
    logger.info(
        "api_initialized",
        environment=settings.environment,
    )
except Exception as e:
    logger.error("api_initialization_failed", error=str(e))
    raise


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get(APIEndpoints.HEALTH)
def health_check() -> dict:
    """Health check endpoint."""
    try:
        logger.debug("health_check_requested")
        return {
            "status": "healthy",
            "environment": settings.environment,
            "embed_provider": settings.embed_provider,
        }
    except Exception as e:
        logger.error("health_check_failed", error=str(e))
        return {
            "status": "unhealthy",
            "error": str(e),
        }, status.HTTP_503_SERVICE_UNAVAILABLE



# ======================================================================
# V2 endpoints
# ======================================================================

def _trigger_ecs_worker(meeting_id: str, filename: str) -> None:
    """Fire-and-forget ECS RunTask for the worker container.

    In local / dev mode (when ecs_cluster_name is empty) runs ingestion
    in-process on a background thread so the in-memory vector store is
    populated within the API process.
    """
    if not settings.ecs_cluster_name:
        logger.info(
            "local_ingestion_triggered",
            meeting_id=meeting_id,
        )

        def _run_local_ingestion() -> None:
            try:
                container = get_di_container()
                ingestion_svc = container.get_ingestion_service()
                artifact_store = container.get_artifact_store()
                raw_uri = (
                    f"s3://{settings.s3_raw_bucket}/"
                    f"{settings.s3_raw_prefix}/{meeting_id}/{filename}"
                )
                raw_bytes = artifact_store.download_raw(raw_uri)
                report = ingestion_svc.ingest(
                    meeting_id=meeting_id,
                    filename=filename,
                    raw_content=raw_bytes,
                )
                logger.info(
                    "local_ingestion_complete",
                    meeting_id=meeting_id,
                    status=report.status.value,
                    chunks=report.chunks_created,
                )
            except Exception as exc:
                logger.error(
                    "local_ingestion_failed",
                    meeting_id=meeting_id,
                    error=str(exc),
                )

        threading.Thread(
            target=_run_local_ingestion,
            daemon=True,
            name=f"ingest-{meeting_id[:8]}",
        ).start()
        return

    ecs = boto3.client("ecs", region_name=settings.aws_region)
    subnets = [s.strip() for s in settings.ecs_worker_subnets.split(",") if s.strip()]

    ecs.run_task(
        cluster=settings.ecs_cluster_name,
        taskDefinition=settings.ecs_worker_task_def,
        launchType="FARGATE",
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": subnets,
                "securityGroups": [settings.ecs_worker_security_group],
                "assignPublicIp": "DISABLED",
            }
        },
        overrides={
            "containerOverrides": [
                {
                    "name": settings.ecs_worker_container_name,
                    "environment": [
                        {"name": "MEETING_ID", "value": meeting_id},
                        {"name": "FILENAME", "value": filename},
                    ],
                }
            ]
        },
    )
    logger.info(
        "ecs_worker_triggered",
        meeting_id=meeting_id,
        cluster=settings.ecs_cluster_name,
    )


@app.post(APIEndpoints.V2_UPLOAD)
@limiter.limit("20/minute")
async def upload_transcript_v2(
    request: Request,
    file: UploadFile = File(...),
) -> JSONResponse:
    """V2 upload — stores raw file in S3, creates PENDING metadata,
    then triggers an ECS worker for async ingestion.

    Returns immediately with meeting_id + PENDING status.
    """
    try:
        filename = InputValidator.sanitize_filename(file.filename or "")
        InputValidator.validate_file_extension(filename, ["txt"])

        content = await file.read()
        if not content:
            raise ValidationError("File is empty", context={"filename": filename})

        meeting_id = str(uuid.uuid4())
        logger.info("v2_upload_started", meeting_id=meeting_id, filename=filename)

        # Store raw file + create PENDING metadata via DI adapters
        container = get_di_container()
        artifact_store = container.get_artifact_store()
        metadata_store = container.get_metadata_store()

        raw_uri = artifact_store.upload_raw(meeting_id, filename, content)

        record = MeetingRecord(
            meeting_id=meeting_id,
            title_normalized=filename.rsplit(".", 1)[0].lower().replace("_", " "),
            meeting_date="",
            s3_uri_raw=raw_uri,
            s3_uri_derived_prefix=artifact_store.get_derived_prefix(meeting_id),
            ingestion_status=IngestionStatus.PENDING,
        )
        metadata_store.put_meeting(record)

        # Trigger async processing
        _trigger_ecs_worker(meeting_id, filename)

        logger.info("v2_upload_accepted", meeting_id=meeting_id)
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "meeting_id": meeting_id,
                "status": IngestionStatus.PENDING.value,
                "message": "Transcript accepted for processing",
            },
        )

    except AppException as e:
        logger.warning("v2_upload_error", error_code=e.error_code)
        return JSONResponse(status_code=e.http_status, content=e.to_dict())
    except Exception as e:
        error_response = handle_error(e, scope=LogScope.API)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_response,
        )


@app.get(APIEndpoints.STATUS)
async def get_ingestion_status(meeting_id: str) -> JSONResponse:
    """Poll ingestion status for a meeting."""
    try:
        container = get_di_container()
        metadata_store = container.get_metadata_store()
        record = metadata_store.get_meeting(meeting_id)

        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Meeting {meeting_id} not found",
            )

        body = {
            "meeting_id": record.meeting_id,
            "status": record.ingestion_status.value,
            "title": record.title_normalized,
        }
        if record.error_message:
            body["error"] = record.error_message

        return JSONResponse(content=body)

    except HTTPException:
        raise
    except Exception as e:
        error_response = handle_error(e, scope=LogScope.API)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_response,
        )


@app.get(APIEndpoints.MEETINGS)
async def list_meetings(
    date: Optional[str] = None,
    title: Optional[str] = None,
    participant: Optional[str] = None,
) -> JSONResponse:
    """List meetings with optional filters."""
    try:
        container = get_di_container()
        metadata_store = container.get_metadata_store()
        records = metadata_store.query_meetings(
            date=date, title=title, participant=participant
        )
        return JSONResponse(
            content=[
                {
                    "meeting_id": r.meeting_id,
                    "title": r.title_normalized,
                    "date": r.meeting_date,
                    "status": r.ingestion_status.value,
                    "participants": r.participants,
                }
                for r in records
            ]
        )
    except Exception as e:
        error_response = handle_error(e, scope=LogScope.API)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_response,
        )


# ======================================================================
# V2 query endpoint — returns CitedAnswer
# ======================================================================

@app.post(APIEndpoints.V2_QUERY)
@limiter.limit("20/minute")
async def query_meeting_v2(
    request: Request,
    body: dict,
) -> JSONResponse:
    """V2 query — returns a CitedAnswer with grounded citations.

    Body JSON:
        question (str): Natural-language question.
        meeting_ids (list[str], optional): Restrict search to these meetings.
    """
    try:
        question = body.get("question", "").strip()
        if not question:
            raise ValidationError("question is required", context={"body": body})

        meeting_ids = body.get("meeting_ids") or None

        container = get_di_container()
        query_svc = container.get_query_service()
        cited = query_svc.query(question=question, meeting_ids=meeting_ids)

        return JSONResponse(
            content=cited.model_dump(),
        )

    except AppException as e:
        logger.warning("v2_query_error", error_code=e.error_code)
        return JSONResponse(status_code=e.http_status, content=e.to_dict())
    except Exception as e:
        error_response = handle_error(e, scope=LogScope.API)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_response,
        )


# ======================================================================
# V2 evaluation endpoints — DeepEval metrics
# ======================================================================

@app.post(APIEndpoints.V2_EVALUATE)
@limiter.limit("10/minute")
async def evaluate_query(
    request: Request,
    body: dict,
) -> JSONResponse:
    """Run DeepEval Faithfulness + AnswerRelevancy on a Q&A pair.

    Body JSON:
        question (str): The user question.
        meeting_ids (list[str], optional): Restrict to these meetings.

    Runs the query pipeline, then evaluates the result.
    """
    try:
        question = body.get("question", "").strip()
        if not question:
            raise ValidationError("question is required", context={"body": body})

        meeting_ids = body.get("meeting_ids") or None

        container = get_di_container()
        query_svc = container.get_query_service()
        eval_svc = container.get_evaluation_service()

        # Run the query pipeline first
        cited = query_svc.query(question=question, meeting_ids=meeting_ids)

        # Evaluate the result
        meeting_id = meeting_ids[0] if meeting_ids else ""
        result = eval_svc.evaluate(
            question=question,
            cited_answer=cited,
            meeting_id=meeting_id,
        )

        return JSONResponse(content=result.model_dump())

    except AppException as e:
        logger.warning("v2_evaluate_error", error_code=e.error_code)
        return JSONResponse(status_code=e.http_status, content=e.to_dict())
    except Exception as e:
        error_response = handle_error(e, scope=LogScope.API)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_response,
        )


@app.get(APIEndpoints.V2_EVAL_HISTORY)
async def get_eval_history(
    meeting_id: Optional[str] = None,
    limit: int = 50,
) -> JSONResponse:
    """Return historical evaluation results."""
    try:
        container = get_di_container()
        eval_svc = container.get_evaluation_service()
        results = eval_svc.list_history(meeting_id=meeting_id, limit=limit)
        return JSONResponse(
            content=[r.model_dump() for r in results]
        )
    except Exception as e:
        error_response = handle_error(e, scope=LogScope.API)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_response,
        )


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
