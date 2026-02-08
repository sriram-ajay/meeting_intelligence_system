"""
Comprehensive tests for shared_utils.logging_utils.

Covers get_scoped_logger(), LogLevel enum, log_execution() decorator,
log_with_context() decorator, and ContextualLogger.
"""

from unittest.mock import patch

import pytest

from shared_utils.logging_utils import (
    ContextualLogger,
    LogLevel,
    get_scoped_logger,
    log_execution,
    log_with_context,
)
from shared_utils.constants import LogScope


# ---------------------------------------------------------------------------
# get_scoped_logger
# ---------------------------------------------------------------------------


class TestGetScopedLogger:
    def test_returns_bound_logger(self) -> None:
        logger = get_scoped_logger(LogScope.API)
        # structlog BoundLogger exposes .info, .error, etc.
        assert callable(getattr(logger, "info", None))
        assert callable(getattr(logger, "error", None))

    def test_different_scopes(self) -> None:
        """Calling with different scopes should not crash."""
        for scope in (LogScope.API, LogScope.PARSER, LogScope.INGESTION, LogScope.WORKER):
            logger = get_scoped_logger(scope)
            assert logger is not None


# ---------------------------------------------------------------------------
# LogLevel enum
# ---------------------------------------------------------------------------


class TestLogLevel:
    def test_values(self) -> None:
        assert LogLevel.DEBUG == "DEBUG"
        assert LogLevel.INFO == "INFO"
        assert LogLevel.WARNING == "WARNING"
        assert LogLevel.ERROR == "ERROR"
        assert LogLevel.CRITICAL == "CRITICAL"

    def test_membership(self) -> None:
        assert len(LogLevel) == 5


# ---------------------------------------------------------------------------
# log_execution decorator
# ---------------------------------------------------------------------------


class TestLogExecution:
    def test_passes_through_return_value(self) -> None:
        @log_execution(scope=LogScope.API)
        def add(a: int, b: int) -> int:
            return a + b

        assert add(2, 3) == 5

    def test_propagates_exception(self) -> None:
        @log_execution(scope=LogScope.API)
        def boom() -> None:
            raise ValueError("oops")

        with pytest.raises(ValueError, match="oops"):
            boom()

    def test_preserves_function_name(self) -> None:
        @log_execution(scope=LogScope.API)
        def my_func() -> None:
            pass

        assert my_func.__name__ == "my_func"


# ---------------------------------------------------------------------------
# log_with_context decorator
# ---------------------------------------------------------------------------


class TestLogWithContext:
    def test_passes_through_return_value(self) -> None:
        @log_with_context(scope=LogScope.PARSER, message="test_op")
        def multiply(a: int, b: int) -> int:
            return a * b

        assert multiply(3, 4) == 12

    def test_propagates_exception(self) -> None:
        @log_with_context(scope=LogScope.PARSER)
        def fail() -> None:
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError, match="fail"):
            fail()

    def test_preserves_function_name(self) -> None:
        @log_with_context(scope=LogScope.PARSER)
        def named_func() -> None:
            pass

        assert named_func.__name__ == "named_func"


# ---------------------------------------------------------------------------
# ContextualLogger
# ---------------------------------------------------------------------------


class TestContextualLogger:
    def test_all_levels_callable(self) -> None:
        cl = ContextualLogger(scope=LogScope.INGESTION)
        for method_name in ("info", "debug", "warning", "error", "critical"):
            method = getattr(cl, method_name)
            assert callable(method)

    def test_info_does_not_raise(self) -> None:
        cl = ContextualLogger(scope=LogScope.INGESTION)
        cl.info("test_event", key="value")

    def test_error_does_not_raise(self) -> None:
        cl = ContextualLogger(scope=LogScope.ERROR_HANDLER)
        cl.error("bad_thing_happened", detail="x")

    def test_scope_stored(self) -> None:
        cl = ContextualLogger(scope=LogScope.WORKER)
        assert cl.scope == LogScope.WORKER
