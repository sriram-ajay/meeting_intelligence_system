"""
Comprehensive tests for shared_utils.validation.

Covers InputValidator static methods and the validate_input() decorator.
"""

import pytest

from shared_utils.validation import InputValidator, validate_input
from shared_utils.error_handler import ValidationError


# ---------------------------------------------------------------------------
# validate_non_empty_string
# ---------------------------------------------------------------------------


class TestValidateNonEmptyString:
    def test_success(self) -> None:
        assert InputValidator.validate_non_empty_string("hello", "field") == "hello"

    def test_strips_whitespace(self) -> None:
        assert InputValidator.validate_non_empty_string("  hello  ", "field") == "hello"

    def test_empty_raises(self) -> None:
        with pytest.raises(ValidationError, match="cannot be empty"):
            InputValidator.validate_non_empty_string("", "name")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(ValidationError, match="cannot be empty"):
            InputValidator.validate_non_empty_string("   ", "test_field")

    def test_non_string_raises(self) -> None:
        with pytest.raises(ValidationError, match="must be a string"):
            InputValidator.validate_non_empty_string(123, "field")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# validate_positive_int
# ---------------------------------------------------------------------------


class TestValidatePositiveInt:
    def test_positive_value(self) -> None:
        assert InputValidator.validate_positive_int(5, "count") == 5

    def test_zero_not_allowed_by_default(self) -> None:
        with pytest.raises(ValidationError, match="must be >= 1"):
            InputValidator.validate_positive_int(0, "count")

    def test_zero_allowed_when_flag_set(self) -> None:
        assert InputValidator.validate_positive_int(0, "count", allow_zero=True) == 0

    def test_negative_raises(self) -> None:
        with pytest.raises(ValidationError, match="must be >="):
            InputValidator.validate_positive_int(-1, "count")

    def test_non_int_raises(self) -> None:
        with pytest.raises(ValidationError, match="must be an integer"):
            InputValidator.validate_positive_int("5", "count")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# validate_uuid
# ---------------------------------------------------------------------------


class TestValidateUuid:
    def test_valid_uuid(self) -> None:
        valid = "550e8400-e29b-41d4-a716-446655440000"
        assert InputValidator.validate_uuid(valid) == valid

    def test_uppercase_valid(self) -> None:
        upper = "550E8400-E29B-41D4-A716-446655440000"
        assert InputValidator.validate_uuid(upper) == upper

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValidationError, match="Invalid UUID"):
            InputValidator.validate_uuid("not-a-uuid")

    def test_partial_uuid_raises(self) -> None:
        with pytest.raises(ValidationError):
            InputValidator.validate_uuid("550e8400-e29b-41d4")


# ---------------------------------------------------------------------------
# validate_file_extension
# ---------------------------------------------------------------------------


class TestValidateFileExtension:
    def test_allowed(self) -> None:
        assert InputValidator.validate_file_extension("test.txt", ["txt", "pdf"]) == "test.txt"

    def test_case_insensitive(self) -> None:
        assert InputValidator.validate_file_extension("test.TXT", ["txt"]) == "test.TXT"

    def test_not_allowed_raises(self) -> None:
        with pytest.raises(ValidationError, match="not allowed"):
            InputValidator.validate_file_extension("test.exe", ["txt", "pdf"])

    def test_no_extension_raises(self) -> None:
        with pytest.raises(ValidationError, match="must have an extension"):
            InputValidator.validate_file_extension("noext", ["txt"])


# ---------------------------------------------------------------------------
# sanitize_filename
# ---------------------------------------------------------------------------


class TestSanitizeFilename:
    def test_clean_filename(self) -> None:
        assert InputValidator.sanitize_filename("testfile.txt") == "testfile.txt"

    def test_removes_bad_chars(self) -> None:
        assert InputValidator.sanitize_filename('file|with*bad:chars.txt') == "filewithbadchars.txt"

    def test_traversal_double_dot_raises(self) -> None:
        with pytest.raises(ValidationError, match="Invalid filename"):
            InputValidator.sanitize_filename("test/../file.txt")

    def test_traversal_leading_dot_raises(self) -> None:
        with pytest.raises(ValidationError, match="Invalid filename"):
            InputValidator.sanitize_filename("../etc/passwd")

    def test_removes_path_separators(self) -> None:
        result = InputValidator.sanitize_filename("path/to\\file.txt")
        assert "/" not in result
        assert "\\" not in result

    def test_too_long_raises(self) -> None:
        with pytest.raises(ValidationError, match="too long"):
            InputValidator.sanitize_filename("a" * 256 + ".txt")

    def test_custom_max_length(self) -> None:
        with pytest.raises(ValidationError, match="too long"):
            InputValidator.sanitize_filename("longname.txt", max_length=5)


# ---------------------------------------------------------------------------
# validate_input decorator
# ---------------------------------------------------------------------------


class TestValidateInputDecorator:
    def test_validates_kwargs(self) -> None:
        @validate_input({
            "text": lambda x: InputValidator.validate_non_empty_string(x, "text"),
        })
        def search(text: str = "") -> str:
            return text

        result = search(text="hello")
        assert result == "hello"

    def test_rejects_invalid_kwarg(self) -> None:
        @validate_input({
            "text": lambda x: InputValidator.validate_non_empty_string(x, "text"),
        })
        def search(text: str = "") -> str:
            return text

        with pytest.raises(ValidationError, match="cannot be empty"):
            search(text="   ")

    def test_strips_kwarg_value(self) -> None:
        """The validator returns stripped value, which should be used."""
        @validate_input({
            "text": lambda x: InputValidator.validate_non_empty_string(x, "text"),
        })
        def search(text: str = "") -> str:
            return text

        result = search(text="  trimmed  ")
        assert result == "trimmed"

    def test_positional_args_pass_through(self) -> None:
        """Only kwargs are validated, positional args pass through."""
        @validate_input({
            "top_k": lambda x: InputValidator.validate_positive_int(x, "top_k"),
        })
        def search(query: str, top_k: int = 5) -> tuple:
            return (query, top_k)

        result = search("hello", top_k=10)
        assert result == ("hello", 10)
