"""
Centralized logging utilities with scoped loggers and decorators.
Provides structured logging with consistent field names across services.
"""

import functools
import logging
import time
from typing import Any, Callable, Optional
from enum import Enum

import structlog

from shared_utils.constants import LogScope


# Configure structlog for JSON output to CloudWatch
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)


def get_scoped_logger(scope: str) -> structlog.BoundLogger:
    """Get a scoped logger for a specific service/component.
    
    Args:
        scope: LogScope value (config, rag_engine, api, ui, parser, validation, error_handler)
    
    Returns:
        Structured logger bound to scope.
    """
    logger = structlog.get_logger()
    return logger.bind(scope=scope)


class LogLevel(str, Enum):
    """Log level enumeration."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


def log_execution(scope: str = LogScope.API, level: str = LogLevel.INFO.value):
    """Decorator to automatically log function execution time and results.
    
    Args:
        scope: Log scope identifier
        level: Log level (INFO, DEBUG, WARNING, ERROR)
    
    Example:
        @log_execution(scope=LogScope.RAG_ENGINE)
        def process_document(doc):
            return doc.upper()
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            logger = get_scoped_logger(scope)
            start_time = time.time()
            
            logger.info(
                f"{func.__name__}_start",
                func_name=func.__name__,
                args_count=len(args),
                kwargs_keys=list(kwargs.keys())
            )
            
            try:
                result = func(*args, **kwargs)
                elapsed = time.time() - start_time
                
                logger.info(
                    f"{func.__name__}_success",
                    func_name=func.__name__,
                    elapsed_seconds=elapsed,
                    result_type=type(result).__name__
                )
                return result
            
            except Exception as e:
                elapsed = time.time() - start_time
                logger.error(
                    f"{func.__name__}_failed",
                    func_name=func.__name__,
                    elapsed_seconds=elapsed,
                    error_type=type(e).__name__,
                    error_message=str(e)
                )
                raise
        
        return wrapper
    return decorator


def log_with_context(
    scope: str = LogScope.API,
    level: str = LogLevel.INFO.value,
    message: Optional[str] = None
):
    """Decorator to add contextual logging to functions.
    
    Args:
        scope: Log scope identifier
        level: Log level
        message: Optional custom message prefix
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            logger = get_scoped_logger(scope)
            msg = message or func.__name__
            
            try:
                result = func(*args, **kwargs)
                logger.log(level.lower(), f"{msg}_completed")
                return result
            except Exception as e:
                logger.error(f"{msg}_failed", error=str(e))
                raise
        
        return wrapper
    return decorator


class ContextualLogger:
    """Helper class for managing contextual logging within a scope."""
    
    def __init__(self, scope: str):
        self.scope = scope
        self.logger = get_scoped_logger(scope)
    
    def info(self, event_name: str, **kwargs):
        """Log info message with scope."""
        self.logger.info(event_name, **kwargs)
    
    def debug(self, event_name: str, **kwargs):
        """Log debug message with scope."""
        self.logger.debug(event_name, **kwargs)
    
    def warning(self, event_name: str, **kwargs):
        """Log warning message with scope."""
        self.logger.warning(event_name, **kwargs)
    
    def error(self, event_name: str, **kwargs):
        """Log error message with scope."""
        self.logger.error(event_name, **kwargs)
    
    def critical(self, event_name: str, **kwargs):
        """Log critical message with scope."""
        self.logger.critical(event_name, **kwargs)
