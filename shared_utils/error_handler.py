"""
Structured error handling and response formatting.
Provides consistent error responses with error codes and context.
"""

from typing import Optional, Dict, Any
from enum import Enum
import logging

from shared_utils.constants import ErrorCode, LogScope
from shared_utils.logging_utils import get_scoped_logger

class AppException(Exception):
    """Base exception for application errors."""
    
    def __init__(
        self,
        error_code: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        http_status: int = 500
    ):
        self.error_code = error_code
        self.message = message
        self.context = context or {}
        self.http_status = http_status
        super().__init__(self.message)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to response dictionary."""
        return {
            "error": {
                "code": self.error_code,
                "message": self.message,
                "context": self.context
            }
        }


class ValidationError(AppException):
    """Validation/input error."""
    
    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(
            error_code=ErrorCode.INVALID_INPUT.value,
            message=message,
            context=context,
            http_status=400
        )


class ConfigurationError(AppException):
    """Configuration error."""
    
    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(
            error_code=ErrorCode.INVALID_CONFIG.value,
            message=message,
            context=context,
            http_status=500
        )


class ModelError(AppException):
    """Model availability or invocation error."""
    
    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(
            error_code=ErrorCode.MODEL_NOT_AVAILABLE.value,
            message=message,
            context=context,
            http_status=503
        )


class ProcessingError(AppException):
    """Processing/indexing error."""
    
    def __init__(self, message: str, error_type: str = "processing", context: Optional[Dict[str, Any]] = None):
        code = ErrorCode.PARSING_FAILED.value if error_type == "parsing" else ErrorCode.INDEXING_FAILED.value
        super().__init__(
            error_code=code,
            message=message,
            context=context,
            http_status=400
        )


class QueryError(AppException):
    """Query/RAG error."""
    
    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(
            error_code=ErrorCode.QUERY_FAILED.value,
            message=message,
            context=context,
            http_status=400
        )


class ExternalServiceError(AppException):
    """External service unavailable error."""
    
    def __init__(self, service: str, message: str, context: Optional[Dict[str, Any]] = None):
        full_message = f"{service} unavailable: {message}"
        super().__init__(
            error_code=ErrorCode.EXTERNAL_SERVICE_ERROR.value,
            message=full_message,
            context={**(context or {}), "service": service},
            http_status=503
        )


class IngestionError(AppException):
    """Ingestion pipeline error (v2)."""

    def __init__(
        self,
        message: str,
        meeting_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        ctx = {**(context or {})}
        if meeting_id:
            ctx["meeting_id"] = meeting_id
        super().__init__(
            error_code=ErrorCode.INGESTION_FAILED.value,
            message=message,
            context=ctx,
            http_status=500,
        )


def log_exception(
    exc: Exception,
    scope: str = LogScope.ERROR_HANDLER,
    logger: Optional[logging.Logger] = None
) -> None:
    """Log exception with structured context.
    
    Args:
        exc: Exception to log
        scope: Log scope identifier
        logger: Optional custom logger (uses structlog if not provided)
    """
    if logger is None:
        logger = get_scoped_logger(scope)
    
    if isinstance(exc, AppException):
        logger.error(
            "app_exception",
            error_code=exc.error_code,
            message=exc.message,
            http_status=exc.http_status,
            context=exc.context
        )
    else:
        logger.error(
            "unexpected_exception",
            error_type=type(exc).__name__,
            message=str(exc),
            traceback=True
        )


def handle_error(
    exc: Exception,
    scope: str = LogScope.ERROR_HANDLER,
    default_error_code: str = ErrorCode.EXTERNAL_SERVICE_ERROR.value
) -> Dict[str, Any]:
    """Handle exception and return structured error response.
    
    Args:
        exc: Exception to handle
        scope: Log scope
        default_error_code: Default error code for non-AppException errors
    
    Returns:
        Structured error response dictionary
    """
    log_exception(exc, scope)
    
    if isinstance(exc, AppException):
        return exc.to_dict()
    else:
        # Convert unexpected exceptions to structured format
        return {
            "error": {
                "code": default_error_code,
                "message": f"An unexpected error occurred: {str(exc)}",
                "context": {"error_type": type(exc).__name__}
            }
        }
