import pytest
from shared_utils.validation import InputValidator, ValidationError

def test_validate_non_empty_string_success():
    assert InputValidator.validate_non_empty_string("hello", "field") == "hello"

def test_validate_non_empty_string_failure():
    with pytest.raises(ValidationError) as excinfo:
        InputValidator.validate_non_empty_string("  ", "test_field")
    assert "test_field cannot be empty" in str(excinfo.value)

def test_validate_uuid_success():
    valid_uuid = "550e8400-e29b-41d4-a716-446655440000"
    assert InputValidator.validate_uuid(valid_uuid) == valid_uuid

def test_validate_uuid_failure():
    with pytest.raises(ValidationError):
        InputValidator.validate_uuid("not-a-uuid")

def test_sanitize_filename_success():
    assert InputValidator.sanitize_filename("testfile.txt") == "testfile.txt"
    assert InputValidator.sanitize_filename("file|with*bad:chars.txt") == "filewithbadchars.txt"

def test_sanitize_filename_traversal_failure():
    with pytest.raises(ValidationError):
        InputValidator.sanitize_filename("test/../file.txt")
    with pytest.raises(ValidationError):
        InputValidator.sanitize_filename("../etc/passwd")

def test_validate_file_extension_success():
    InputValidator.validate_file_extension("test.txt", ["txt", "pdf"])

def test_validate_file_extension_failure():
    with pytest.raises(ValidationError):
        InputValidator.validate_file_extension("test.exe", ["txt", "pdf"])
