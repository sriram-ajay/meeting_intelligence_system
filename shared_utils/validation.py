"""
Input validation and sanitization utilities.
Provides decorators and functions for validating and cleaning input data.
"""

from typing import Any, Callable, Optional, List
import functools
import re

from shared_utils.error_handler import ValidationError
from shared_utils.logging_utils import get_scoped_logger
from shared_utils.constants import LogScope


class InputValidator:
    """Utility class for input validation."""
    
    @staticmethod
    def validate_non_empty_string(value: str, field_name: str) -> str:
        """Validate non-empty string.
        
        Args:
            value: String to validate
            field_name: Name of field for error messages
        
        Returns:
            Validated string
        
        Raises:
            ValidationError: If validation fails
        """
        if not isinstance(value, str):
            raise ValidationError(f"{field_name} must be a string")
        
        if not value or not value.strip():
            raise ValidationError(f"{field_name} cannot be empty")
        
        return value.strip()
    
    @staticmethod
    def validate_positive_int(value: int, field_name: str, allow_zero: bool = False) -> int:
        """Validate positive integer.
        
        Args:
            value: Integer to validate
            field_name: Name of field for error messages
            allow_zero: Whether zero is valid
        
        Returns:
            Validated integer
        
        Raises:
            ValidationError: If validation fails
        """
        if not isinstance(value, int):
            raise ValidationError(f"{field_name} must be an integer")
        
        min_val = 0 if allow_zero else 1
        if value < min_val:
            raise ValidationError(f"{field_name} must be >= {min_val}")
        
        return value
    
    @staticmethod
    def validate_uuid(value: str) -> str:
        """Validate UUID format.
        
        Args:
            value: UUID string to validate
        
        Returns:
            Validated UUID
        
        Raises:
            ValidationError: If validation fails
        """
        uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        if not re.match(uuid_pattern, value, re.IGNORECASE):
            raise ValidationError("Invalid UUID format")
        
        return value
    
    @staticmethod
    def validate_file_extension(filename: str, allowed_extensions: List[str]) -> str:
        """Validate file extension.
        
        Args:
            filename: Filename to validate
            allowed_extensions: List of allowed extensions (without dots)
        
        Returns:
            Validated filename
        
        Raises:
            ValidationError: If validation fails
        """
        if '.' not in filename:
            raise ValidationError("File must have an extension")
        
        ext = filename.rsplit('.', 1)[1].lower()
        if ext not in [e.lower() for e in allowed_extensions]:
            raise ValidationError(f"File extension .{ext} not allowed. Allowed: {allowed_extensions}")
        
        return filename
    
    @staticmethod
    def sanitize_filename(filename: str, max_length: int = 255) -> str:
        """Sanitize filename to prevent path traversal and other issues.
        
        Args:
            filename: Filename to sanitize
            max_length: Maximum filename length
        
        Returns:
            Sanitized filename
        
        Raises:
            ValidationError: If validation fails
        """
        # Remove path separators and special characters
        filename = filename.replace('\\', '').replace('/', '')
        filename = re.sub(r'[<>:"|?*]', '', filename)
        
        # Prevent path traversal
        if '..' in filename or filename.startswith('.'):
            raise ValidationError("Invalid filename format")
        
        if len(filename) > max_length:
            raise ValidationError(f"Filename too long (max {max_length} characters)")
        
        return filename


def validate_input(
    validation_rules: dict[str, Callable],
    scope: str = LogScope.VALIDATION
):
    """Decorator to validate function arguments against rules.
    
    Args:
        validation_rules: Dict mapping param names to validation functions
        scope: Log scope
    
    Example:
        @validate_input({
            'text': lambda x: InputValidator.validate_non_empty_string(x, 'text'),
            'top_k': lambda x: InputValidator.validate_positive_int(x, 'top_k')
        })
        def query(text, top_k=5):
            return search(text, top_k)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            logger = get_scoped_logger(scope)
            
            try:
                # Validate kwargs
                for param_name, validator in validation_rules.items():
                    if param_name in kwargs:
                        kwargs[param_name] = validator(kwargs[param_name])
                
                logger.debug(
                    f"{func.__name__}_validation_passed",
                    func_name=func.__name__,
                    validated_params=list(validation_rules.keys())
                )
                
                return func(*args, **kwargs)
            
            except ValidationError as e:
                logger.warning(
                    f"{func.__name__}_validation_failed",
                    func_name=func.__name__,
                    error=str(e)
                )
                raise
        
        return wrapper
    return decorator
