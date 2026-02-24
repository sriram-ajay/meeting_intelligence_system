"""
FastAPI backend for Meeting Intelligence System v2/v3.

Endpoints:
    GET  /health                          — Health check
    POST /api/v2/upload                   — Async ingestion (S3 + ECS worker)
    GET  /api/v2/status/{meeting_id}      — Poll ingestion status
    GET  /api/v2/meetings                 — List meetings (optional filters)
    POST /api/v2/query                    — Grounded Q&A with citations
    POST /api/v2/evaluate                 — Run DeepEval metrics on a Q&A pair
    GET  /api/v2/eval/history             — Retrieve evaluation history
    POST /api/v3/upload                   — LangGraph-powered ingestion
    POST /api/v3/query                    — LangGraph-powered Q&A with chat history
    GET  /api/v3/chat/{session_id}        — Get chat session history
    GET  /api/v3/chat/sessions            — List chat sessions for a user
    GET  /api/v3/user/{user_id}/profile   — Get user memory profile
    GET  /api/v3/graph/{graph_name}       — Mermaid visualization of a graph
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
    """Start async ingestion for an uploaded transcript.

    Two modes depending on environment:

    1. **Local dev** (ecs_cluster_name is empty):
       Runs ingestion in a background daemon thread within the API process.
       This is necessary because local dev uses InMemoryVectorStoreAdapter,
       which only exists in the API process's memory. A separate process
       would have its own empty store.

    2. **AWS production** (ecs_cluster_name is set):
       Fires an ECS RunTask via boto3. The worker container picks up
       MEETING_ID and FILENAME from environment overrides, downloads
       the raw file from S3, and runs the full ingestion pipeline.
       The task runs in private subnets with no public IP.
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
    """V2 upload — two-phase async ingestion.

    Phase 1 (synchronous, in this request):
        - Validate and sanitize the filename
        - Upload raw file to S3 via ArtifactStorePort
        - Create a PENDING metadata record in DynamoDB
        - Return 202 Accepted immediately with the meeting_id

    Phase 2 (asynchronous, in background):
        - Trigger ECS worker (or local thread) to parse, chunk, embed,
          and store vectors
        - Worker updates metadata to READY on success or FAILED on error
        - Client polls GET /api/v2/status/{meeting_id} to check progress
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


# ======================================================================
# V3 endpoints — LangGraph-powered
# ======================================================================


@app.post(APIEndpoints.V3_UPLOAD)
@limiter.limit("20/minute")
async def upload_transcript_v3(
    request: Request,
    file: UploadFile = File(...),
) -> JSONResponse:
    """V3 upload — LangGraph ingestion pipeline.

    Same two-phase approach as v2, but uses the LangGraph ingestion
    graph instead of IngestionService for the async processing phase.
    """
    try:
        filename = InputValidator.sanitize_filename(file.filename or "")
        InputValidator.validate_file_extension(filename, ["txt"])

        content = await file.read()
        if not content:
            raise ValidationError("File is empty", context={"filename": filename})

        meeting_id = str(uuid.uuid4())
        logger.info("v3_upload_started", meeting_id=meeting_id, filename=filename)

        container = get_di_container()
        artifact_store = container.get_artifact_store()
        metadata_store = container.get_metadata_store()

        # Phase 1: Store raw + PENDING record
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

        # Phase 2: Trigger LangGraph ingestion
        _trigger_v3_ingestion(meeting_id, filename, content)

        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "meeting_id": meeting_id,
                "status": IngestionStatus.PENDING.value,
                "message": "Transcript accepted for LangGraph processing",
                "pipeline": "v3",
            },
        )

    except AppException as e:
        logger.warning("v3_upload_error", error_code=e.error_code)
        return JSONResponse(status_code=e.http_status, content=e.to_dict())
    except Exception as e:
        error_response = handle_error(e, scope=LogScope.API)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_response,
        )


def _trigger_v3_ingestion(meeting_id: str, filename: str, content: bytes) -> None:
    """Run LangGraph ingestion pipeline in a background thread."""
    def _run():
        try:
            container = get_di_container()
            graph = container.get_ingestion_graph()
            result = graph.invoke({
                "meeting_id": meeting_id,
                "filename": filename,
                "raw_content": content,
            })
            report = result.get("report")
            logger.info(
                "v3_ingestion_complete",
                meeting_id=meeting_id,
                status=report.status.value if report else "unknown",
            )
        except Exception as exc:
            logger.error(
                "v3_ingestion_failed",
                meeting_id=meeting_id,
                error=str(exc),
            )

    threading.Thread(
        target=_run,
        daemon=True,
        name=f"ingest-v3-{meeting_id[:8]}",
    ).start()


@app.post(APIEndpoints.V3_QUERY)
@limiter.limit("20/minute")
async def query_meeting_v3(
    request: Request,
    body: dict,
) -> JSONResponse:
    """V3 query — LangGraph pipeline with chat history and semantic cache.

    Body JSON:
        question (str): Natural-language question.
        meeting_ids (list[str], optional): Restrict search to these meetings.
        session_id (str, optional): Chat session ID for multi-turn context.
        user_id (str, optional): User ID for personalisation.
    """
    try:
        question = body.get("question", "").strip()
        if not question:
            raise ValidationError("question is required", context={"body": body})

        container = get_di_container()
        graph = container.get_query_graph()

        state = {
            "question": question,
        }
        if body.get("meeting_ids"):
            state["meeting_ids"] = body["meeting_ids"]
        if body.get("session_id"):
            state["session_id"] = body["session_id"]
        if body.get("user_id"):
            state["user_id"] = body["user_id"]

        result = graph.invoke(state)
        cited = result.get("cited_answer")

        if cited is None:
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"error": "Query pipeline did not produce an answer"},
            )

        response = cited.model_dump()
        response["pipeline"] = "v3"
        return JSONResponse(content=response)

    except AppException as e:
        logger.warning("v3_query_error", error_code=e.error_code)
        return JSONResponse(status_code=e.http_status, content=e.to_dict())
    except Exception as e:
        error_response = handle_error(e, scope=LogScope.API)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_response,
        )


@app.get("/api/v3/chat/sessions")
@limiter.limit("30/minute")
async def list_chat_sessions(
    request: Request,
    user_id: str = "",
    limit: int = 20,
) -> JSONResponse:
    """List chat sessions for a user."""
    try:
        container = get_di_container()
        chat_history = container.get_chat_history()

        if chat_history is None:
            return JSONResponse(content={"sessions": [], "message": "Chat history not enabled"})

        sessions = chat_history.list_sessions(user_id=user_id, limit=limit)
        return JSONResponse(
            content={
                "sessions": [
                    {
                        "session_id": s.session_id,
                        "user_id": s.user_id,
                        "turns": len(s.turns),
                        "created_at": s.created_at,
                        "updated_at": s.updated_at,
                    }
                    for s in sessions
                ]
            }
        )
    except Exception as e:
        error_response = handle_error(e, scope=LogScope.API)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_response,
        )


@app.get("/api/v3/chat/{session_id}")
@limiter.limit("30/minute")
async def get_chat_session(
    request: Request,
    session_id: str,
) -> JSONResponse:
    """Get full chat session with all turns."""
    try:
        container = get_di_container()
        chat_history = container.get_chat_history()

        if chat_history is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chat history not enabled",
            )

        session = chat_history.get_session(session_id)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session {session_id} not found",
            )

        return JSONResponse(content=session.model_dump())

    except HTTPException:
        raise
    except Exception as e:
        error_response = handle_error(e, scope=LogScope.API)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_response,
        )


@app.get("/api/v3/user/{user_id}/profile")
@limiter.limit("30/minute")
async def get_user_profile(
    request: Request,
    user_id: str,
) -> JSONResponse:
    """Get user memory profile."""
    try:
        container = get_di_container()
        user_memory = container.get_user_memory()

        if user_memory is None:
            return JSONResponse(
                content={"user_id": user_id, "message": "User memory not enabled"}
            )

        profile = user_memory.get_profile(user_id)
        if profile is None:
            return JSONResponse(
                content={"user_id": user_id, "facts": [], "preferences": {}}
            )

        return JSONResponse(content=profile.model_dump())

    except Exception as e:
        error_response = handle_error(e, scope=LogScope.API)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_response,
        )


@app.get("/api/v3/graph/{graph_name}")
async def get_graph_visualization(graph_name: str) -> JSONResponse:
    """Return Mermaid diagram source for a LangGraph pipeline.

    Args:
        graph_name: Either "ingestion" or "query".

    Returns:
        JSON with ``mermaid`` key containing the diagram source.
    """
    try:
        container = get_di_container()

        if graph_name == "ingestion":
            graph = container.get_ingestion_graph()
        elif graph_name == "query":
            graph = container.get_query_graph()
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown graph: {graph_name}. Use 'ingestion' or 'query'.",
            )

        mermaid = graph.get_graph().draw_mermaid()
        return JSONResponse(
            content={
                "graph_name": graph_name,
                "mermaid": mermaid,
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        error_response = handle_error(e, scope=LogScope.API)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_response,
        )
