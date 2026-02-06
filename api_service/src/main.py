"""
FastAPI backend for Meeting Intelligence System.
Handles transcript upload, parsing, indexing, and RAG queries.
"""

from typing import Optional
from fastapi import FastAPI, UploadFile, File, HTTPException, status, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
import uvicorn
import nest_asyncio

# Apply nest_asyncio to allow LlamaIndex's RagFusion to run nested event loops in FastAPI
nest_asyncio.apply()

from core_intelligence.parser.cleaner import TranscriptParser
from core_intelligence.engine.rag import RAGEngine
from core_intelligence.engine.evaluation import EvaluationEngine
from core_intelligence.schemas.models import QueryRequest, QueryResponse, EvaluationResult
from shared_utils.config_loader import get_settings
from shared_utils.logging_utils import ContextualLogger, get_scoped_logger
from shared_utils.constants import LogScope, APIEndpoints, Defaults
from shared_utils.error_handler import (
    AppException, ValidationError, ProcessingError, 
    QueryError, handle_error
)
from shared_utils.validation import InputValidator
from shared_utils.di_container import get_di_container


# Initialize application
settings = get_settings()
logger = ContextualLogger(scope=LogScope.API)

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=settings.app_description
)

# Initialize rate limiter (20 requests per minute per user)
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

# Initialize RAG engine with dependency injection
try:
    di_container = get_di_container()
    di_container.validate_all_providers()
    rag_engine = RAGEngine(uri=settings.database_uri)
    evaluation_engine = EvaluationEngine(
        llm_provider=di_container.get_llm_provider(),
        embedding_provider=di_container.get_embedding_provider()
    )
    logger.info(
        "api_initialized",
        environment=settings.environment,
        database_uri=settings.database_uri,
        code_status="LATEST_PRODUCTION_VERSION"
    )
except Exception as e:
    logger.error("api_initialization_failed", error=str(e))
    raise


@app.get(APIEndpoints.HEALTH)
def health_check() -> dict:
    """Health check endpoint.
    
    Returns:
        Status information with environment and model configuration
    """
    try:
        logger.debug("health_check_requested")
        return {
            "status": "healthy",
            "environment": settings.environment,
            "embed_provider": settings.embed_provider
        }
    except Exception as e:
        logger.error("health_check_failed", error=str(e))
        return {
            "status": "unhealthy",
            "error": str(e)
        }, status.HTTP_503_SERVICE_UNAVAILABLE


@app.post(APIEndpoints.UPLOAD)
@limiter.limit("20/minute")
async def upload_transcript(request: Request, file: UploadFile = File(...)) -> dict:
    """Upload and index transcript file.
    
    Args:
        file: Text file containing meeting transcript
    
    Returns:
        JSON with meeting_id and segment count
    
    Raises:
        HTTPException: On validation or processing errors
    """
    try:
        # Validate filename
        filename = InputValidator.sanitize_filename(file.filename or "")
        InputValidator.validate_file_extension(filename, ['txt'])
        
        logger.info("upload_started", filename=filename)
        
        # Read and decode file
        content = await file.read()
        if not content:
            raise ValidationError("File is empty", context={"filename": filename})
        
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as e:
            raise ValidationError(
                "File must be valid UTF-8 text",
                context={"filename": filename, "error": str(e)}
            )
        
        # Parse transcript
        try:
            transcript = TranscriptParser.parse_text(text, title=filename)
            logger.debug("parsed_transcript", segment_count=len(transcript.segments))
        except Exception as e:
            logger.error("transcript_parsing_failed", error=str(e))
            raise ProcessingError(
                f"Failed to parse transcript: {e}",
                error_type="parsing",
                context={"filename": filename}
            )
        
        # Index transcript
        try:
            meeting_id = rag_engine.index_transcript(transcript)
            logger.info(
                "upload_completed",
                meeting_id=meeting_id,
                segment_count=len(transcript.segments)
            )
            return {
                "message": "Transcript indexed successfully",
                "meeting_id": meeting_id,
                "segments_count": len(transcript.segments)
            }
        except ProcessingError:
            raise
        except Exception as e:
            logger.error("transcript_indexing_failed", error=str(e))
            raise ProcessingError(
                f"Failed to index transcript: {e}",
                error_type="indexing",
                context={"filename": filename}
            )
    
    except AppException as e:
        logger.warning("upload_validation_error", error_code=e.error_code)
        return JSONResponse(
            status_code=e.http_status,
            content=e.to_dict()
        )
    except Exception as e:
        error_response = handle_error(e, scope=LogScope.API)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_response
        )


@app.post(APIEndpoints.QUERY, response_model=QueryResponse)
@limiter.limit("20/minute")
async def query_meeting(request: Request, query_request: QueryRequest) -> QueryResponse:
    """Execute RAG query against indexed meetings.
    
    Args:
        request: FastAPI request object for rate limiting
        query_request: Query request with query text and optional meeting_id filter
    
    Returns:
        QueryResponse with answer and source documents
    
    Raises:
        HTTPException: On validation or query execution errors
    """
    try:
        # Validate query
        query_text = InputValidator.validate_non_empty_string(
            query_request.query,
            "query"
        )
        
        if query_request.meeting_id:
            meeting_id = InputValidator.validate_uuid(query_request.meeting_id)
        else:
            meeting_id = None
        
        logger.info(
            "query_requested",
            query_length=len(query_text),
            meeting_id=meeting_id
        )
        
        # Execute query
        try:
            response = rag_engine.query(query_text, meeting_id=meeting_id)
            logger.info(
                "query_completed",
                sources_count=len(response.sources),
                meeting_id=meeting_id
            )
            return response
        except QueryError:
            raise
        except Exception as e:
            logger.error("query_execution_failed", error=str(e))
            raise QueryError(
                f"Query execution failed: {e}",
                context={"query": query_text, "meeting_id": meeting_id}
            )
    
    except AppException as e:
        logger.warning("query_application_error", error_code=e.error_code, error_message=e.message)
        raise HTTPException(
            status_code=e.http_status,
            detail=e.message
        )
    except Exception as e:
        error_response = handle_error(e, scope=LogScope.API)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_response.get("error", {}).get("message", "Unknown error")
        )


@app.get(APIEndpoints.METRICS)
async def get_metrics():
    """Retrieve historical evaluation metrics."""
    try:
        return evaluation_engine.get_historical_metrics()
    except Exception as e:
        logger.error("metrics_fetch_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@app.post(APIEndpoints.EVALUATE, response_model=EvaluationResult)
async def run_evaluation(payload: dict):
    """Run Ragas evaluation on a set of queries and responses."""
    try:
        queries = payload.get("queries", [])
        responses = payload.get("responses", [])
        meeting_id = payload.get("meeting_id")
        
        if not queries or not responses:
            raise ValidationError("Missing queries or responses in payload")
            
        result = evaluation_engine.evaluate_batch(queries, responses, meeting_id=meeting_id)
        return result
    except Exception as e:
        logger.error("evaluation_api_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
