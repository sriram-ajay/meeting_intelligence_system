"""
Constants management.
Centralized configuration for all magic values, model IDs, and defaults.
"""

from enum import Enum
from typing import Final


class Environment(str, Enum):
    """Application environment."""
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class EmbeddingProvider(str, Enum):
    """Supported embedding providers."""
    OPENAI = "openai"
    BEDROCK = "bedrock"


class LLMProvider(str, Enum):
    """Supported LLM providers."""
    BEDROCK = "bedrock"
    OPENAI = "openai"


# Model IDs
class ModelIDs:
    """Centralized model identifiers."""
    # Bedrock LLM
    BEDROCK_CLAUDE_3_HAIKU: Final[str] = "anthropic.claude-3-haiku-20240307-v1:0"
    
    # OpenAI Embeddings
    OPENAI_EMBED_MODEL: Final[str] = "text-embedding-3-small"
    OPENAI_EMBEDDING_SMALL: Final[str] = "text-embedding-3-small"
    OPENAI_EMBEDDING_LARGE: Final[str] = "text-embedding-3-large"
    
    # Bedrock Embeddings
    BEDROCK_TITAN_EMBED_V2: Final[str] = "amazon.titan-embed-text-v2:0"


# Default values
class Defaults:
    """Enterprise defaults for all configurations."""
    EMBEDDING_DIMENSION: Final[int] = 1536  # OpenAI small dimension
    BATCH_SIZE: Final[int] = 10
    MAX_RETRIES: Final[int] = 3
    REQUEST_TIMEOUT: Final[float] = 60.0
    LOG_LEVEL: Final[str] = "INFO"
    AWS_REGION: Final[str] = "eu-west-2"


# Database settings
class DatabaseConfig:
    """Vector database configuration."""
    TABLE_NAME: Final[str] = "meeting_segments"
    MODE_APPEND: Final[str] = "append"
    MODE_OVERWRITE: Final[str] = "overwrite"


# Logging scopes
class LogScope:
    """Standardized logging scope names."""
    CONFIG = "config_loader"
    RAG_ENGINE = "rag_engine"
    API = "api"
    UI = "ui"
    PARSER = "transcript_parser"
    VALIDATION = "validation"
    ERROR_HANDLER = "error_handler"
    MONITORING = "monitoring"


# API endpoints and paths
class APIEndpoints:
    """API route definitions."""
    HEALTH = "/health"
    UPLOAD = "/api/upload"
    QUERY = "/api/query"
    MEETINGS = "/api/meetings"
    MEETINGS_BY_ID = "/api/meetings/{meeting_id}"
    METRICS = "/api/metrics"
    EVALUATE = "/api/evaluate"


# Error codes
class ErrorCode(str, Enum):
    """Standardized error codes for consistency."""
    INVALID_CONFIG = "INVALID_CONFIG"
    MODEL_NOT_AVAILABLE = "MODEL_NOT_AVAILABLE"
    UPLOAD_FAILED = "UPLOAD_FAILED"
    PARSING_FAILED = "PARSING_FAILED"
    INDEXING_FAILED = "INDEXING_FAILED"
    QUERY_FAILED = "QUERY_FAILED"
    INVALID_INPUT = "INVALID_INPUT"
    EXTERNAL_SERVICE_ERROR = "EXTERNAL_SERVICE_ERROR"


# Feature flags
class Features:
    """Feature toggles for A/B testing and rollouts."""
    ENABLE_ACTION_ITEM_EXTRACTION: Final[bool] = False  # TODO: implement structured extraction
    ENABLE_SPEAKER_DIARIZATION: Final[bool] = False  # TODO: implement
    ENABLE_METRICS: Final[bool] = True
