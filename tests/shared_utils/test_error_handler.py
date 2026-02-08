"""
Comprehensive tests for shared_utils.error_handler.

Covers every exception subclass, to_dict() serialisation, HTTP status codes,
log_exception(), and handle_error().
"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from shared_utils.constants import ErrorCode
from shared_utils.error_handler import (
    AppException,
    ConfigurationError,
    ExternalServiceError,
    IngestionError,
    ModelError,
    ProcessingError,
    QueryError,
    ValidationError,
    handle_error,
    log_exception,
)


# ---------------------------------------------------------------------------
# AppException base
# ---------------------------------------------------------------------------


class TestAppException:
    def test_defaults(self) -> None:
        exc = AppException(error_code="TEST", message="boom")
        assert exc.error_code == "TEST"
        assert exc.message == "boom"
        assert exc.http_status == 500
        assert exc.context == {}
        assert str(exc) == "boom"

    def test_custom_context_and_status(self) -> None:
        ctx = {"key": "val"}
        exc = AppException("CODE", "msg", context=ctx, http_status=418)
        assert exc.context == ctx
        assert exc.http_status == 418

    def test_to_dict_structure(self) -> None:
        exc = AppException("CODE", "msg", context={"a": 1})
        d = exc.to_dict()
        assert "error" in d
        err = d["error"]
        assert err["code"] == "CODE"
        assert err["message"] == "msg"
        assert err["context"] == {"a": 1}

    def test_to_dict_empty_context(self) -> None:
        exc = AppException("C", "m")
        assert exc.to_dict()["error"]["context"] == {}

    def test_is_exception(self) -> None:
        exc = AppException("C", "m")
        assert isinstance(exc, Exception)


# ---------------------------------------------------------------------------
# Subclass-specific tests
# ---------------------------------------------------------------------------


class TestValidationError:
    def test_code_and_status(self) -> None:
        exc = ValidationError("bad input")
        assert exc.error_code == ErrorCode.INVALID_INPUT.value
        assert exc.http_status == 400

    def test_with_context(self) -> None:
        exc = ValidationError("bad", context={"field": "name"})
        assert exc.context == {"field": "name"}

    def test_inherits_app_exception(self) -> None:
        assert isinstance(ValidationError("x"), AppException)


class TestConfigurationError:
    def test_code_and_status(self) -> None:
        exc = ConfigurationError("missing key")
        assert exc.error_code == ErrorCode.INVALID_CONFIG.value
        assert exc.http_status == 500

    def test_to_dict(self) -> None:
        d = ConfigurationError("oops").to_dict()
        assert d["error"]["code"] == "INVALID_CONFIG"


class TestModelError:
    def test_code_and_status(self) -> None:
        exc = ModelError("model down")
        assert exc.error_code == ErrorCode.MODEL_NOT_AVAILABLE.value
        assert exc.http_status == 503


class TestProcessingError:
    def test_parsing_type(self) -> None:
        exc = ProcessingError("parse fail", error_type="parsing")
        assert exc.error_code == ErrorCode.PARSING_FAILED.value
        assert exc.http_status == 400

    def test_default_type_is_indexing(self) -> None:
        exc = ProcessingError("index fail")
        assert exc.error_code == ErrorCode.INDEXING_FAILED.value

    def test_context_preserved(self) -> None:
        exc = ProcessingError("err", context={"file": "a.txt"})
        assert exc.context == {"file": "a.txt"}


class TestQueryError:
    def test_code_and_status(self) -> None:
        exc = QueryError("bad query")
        assert exc.error_code == ErrorCode.QUERY_FAILED.value
        assert exc.http_status == 400


class TestExternalServiceError:
    def test_code_and_status(self) -> None:
        exc = ExternalServiceError("S3", "timeout")
        assert exc.error_code == ErrorCode.EXTERNAL_SERVICE_ERROR.value
        assert exc.http_status == 503

    def test_message_includes_service(self) -> None:
        exc = ExternalServiceError("DynamoDB", "throttled")
        assert "DynamoDB" in exc.message
        assert "throttled" in exc.message

    def test_context_includes_service_key(self) -> None:
        exc = ExternalServiceError("Bedrock", "err", context={"extra": 1})
        assert exc.context["service"] == "Bedrock"
        assert exc.context["extra"] == 1


class TestIngestionError:
    def test_code_and_status(self) -> None:
        exc = IngestionError("ingest fail")
        assert exc.error_code == ErrorCode.INGESTION_FAILED.value
        assert exc.http_status == 500

    def test_meeting_id_in_context(self) -> None:
        exc = IngestionError("fail", meeting_id="m-1")
        assert exc.context["meeting_id"] == "m-1"

    def test_no_meeting_id(self) -> None:
        exc = IngestionError("fail")
        assert "meeting_id" not in exc.context

    def test_extra_context_preserved(self) -> None:
        exc = IngestionError("err", meeting_id="m-2", context={"step": "embed"})
        assert exc.context["step"] == "embed"
        assert exc.context["meeting_id"] == "m-2"


# ---------------------------------------------------------------------------
# log_exception
# ---------------------------------------------------------------------------


class TestLogException:
    def test_app_exception_uses_error_level(self) -> None:
        mock_logger = MagicMock()
        exc = ValidationError("oops")
        log_exception(exc, logger=mock_logger)
        mock_logger.error.assert_called_once()

    def test_generic_exception_uses_error_level(self) -> None:
        mock_logger = MagicMock()
        log_exception(RuntimeError("boom"), logger=mock_logger)
        mock_logger.error.assert_called_once()

    def test_default_logger_does_not_raise(self) -> None:
        """Calling without explicit logger should not crash."""
        log_exception(ValidationError("x"))
        log_exception(RuntimeError("y"))


# ---------------------------------------------------------------------------
# handle_error
# ---------------------------------------------------------------------------


class TestHandleError:
    def test_app_exception_returns_to_dict(self) -> None:
        exc = QueryError("bad query", context={"q": "abc"})
        result = handle_error(exc)
        assert result["error"]["code"] == ErrorCode.QUERY_FAILED.value
        assert result["error"]["context"]["q"] == "abc"

    def test_generic_exception_returns_structured_dict(self) -> None:
        result = handle_error(RuntimeError("unexpected"))
        err = result["error"]
        assert err["code"] == ErrorCode.EXTERNAL_SERVICE_ERROR.value
        assert "unexpected" in err["message"]
        assert err["context"]["error_type"] == "RuntimeError"

    def test_custom_default_error_code(self) -> None:
        result = handle_error(
            ValueError("bad"), default_error_code=ErrorCode.INVALID_INPUT.value
        )
        assert result["error"]["code"] == ErrorCode.INVALID_INPUT.value

    def test_handle_always_returns_dict(self) -> None:
        """Regardless of exception type, output is always a dict with 'error' key."""
        for exc in (
            ValidationError("a"),
            ConfigurationError("b"),
            ModelError("c"),
            ProcessingError("d"),
            QueryError("e"),
            ExternalServiceError("svc", "f"),
            IngestionError("g"),
            TypeError("h"),
        ):
            result = handle_error(exc)
            assert isinstance(result, dict)
            assert "error" in result
            assert "code" in result["error"]
            assert "message" in result["error"]
