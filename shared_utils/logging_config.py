"""
DEPRECATED: This module is no longer used.

This logging configuration has been replaced by:
- logging_utils.py (scoped loggers with structlog)
- ContextualLogger (context-aware logging)
- get_scoped_logger() (factory function)

All services should use logging_utils.py instead:

    from shared_utils.logging_utils import get_scoped_logger
    from shared_utils.constants import LogScope
    
    logger = get_scoped_logger(LogScope.API)
    logger.info("message", key=value)

This file will be removed in the next refactoring phase.
Keep it only for backwards compatibility during transition.
"""

# Original implementation (DEPRECATED - DO NOT USE)
import logging
import sys
import structlog

def setup_logging(service_name: str, environment: str = "production"):
    """
    DEPRECATED: Use logging_utils.py instead.
    
    Configures structlog for the application.
    In production, it outputs JSON for CloudWatch/Logs ingestion.
    In development, it outputs console-friendly formatted text.
    """
    
    # Shared processors for both JSON and Console output
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if environment == "production":
        # JSON output for structured logging in CloudWatch
        processors = shared_processors + [
            structlog.processors.JSONRenderer()
        ]
    else:
        # Pretty console output for local development
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer()
        ]

    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Standard logging bridge (optional but useful for third-party libs)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )

    return structlog.get_logger(service_name=service_name)

