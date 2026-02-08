"""
Tests for shared_utils.constants.

Validates enum membership, constant values, and the overall structure
so that accidental additions or removals are caught.
"""

import pytest

from shared_utils.constants import (
    APIEndpoints,
    DatabaseConfig,
    Defaults,
    Environment,
    EmbeddingProvider,
    ErrorCode,
    Features,
    LLMProvider,
    LogScope,
    ModelIDs,
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TestEnvironment:
    def test_long_forms(self) -> None:
        assert Environment.DEVELOPMENT.value == "development"
        assert Environment.STAGING.value == "staging"
        assert Environment.PRODUCTION.value == "production"

    def test_short_forms(self) -> None:
        assert Environment.DEV.value == "dev"
        assert Environment.STAGE.value == "stage"
        assert Environment.PROD.value == "prod"

    def test_member_count(self) -> None:
        assert len(Environment) == 6


class TestEmbeddingProvider:
    def test_values(self) -> None:
        assert EmbeddingProvider.OPENAI.value == "openai"
        assert EmbeddingProvider.BEDROCK.value == "bedrock"

    def test_member_count(self) -> None:
        assert len(EmbeddingProvider) == 2


class TestLLMProvider:
    def test_values(self) -> None:
        assert LLMProvider.BEDROCK.value == "bedrock"
        assert LLMProvider.OPENAI.value == "openai"


class TestErrorCode:
    def test_v1_codes(self) -> None:
        assert ErrorCode.INVALID_CONFIG.value == "INVALID_CONFIG"
        assert ErrorCode.MODEL_NOT_AVAILABLE.value == "MODEL_NOT_AVAILABLE"
        assert ErrorCode.QUERY_FAILED.value == "QUERY_FAILED"
        assert ErrorCode.INVALID_INPUT.value == "INVALID_INPUT"
        assert ErrorCode.UPLOAD_FAILED.value == "UPLOAD_FAILED"
        assert ErrorCode.PARSING_FAILED.value == "PARSING_FAILED"
        assert ErrorCode.INDEXING_FAILED.value == "INDEXING_FAILED"
        assert ErrorCode.EXTERNAL_SERVICE_ERROR.value == "EXTERNAL_SERVICE_ERROR"

    def test_v2_codes(self) -> None:
        assert ErrorCode.INGESTION_FAILED.value == "INGESTION_FAILED"
        assert ErrorCode.STORAGE_ERROR.value == "STORAGE_ERROR"
        assert ErrorCode.WORKER_ERROR.value == "WORKER_ERROR"


# ---------------------------------------------------------------------------
# Constant classes
# ---------------------------------------------------------------------------


class TestModelIDs:
    def test_bedrock_model(self) -> None:
        assert "claude" in ModelIDs.BEDROCK_CLAUDE_3_HAIKU.lower()

    def test_openai_embed(self) -> None:
        assert "embedding" in ModelIDs.OPENAI_EMBED_MODEL

    def test_titan_embed(self) -> None:
        assert "titan" in ModelIDs.BEDROCK_TITAN_EMBED_V2.lower()


class TestDefaults:
    def test_embedding_dimension(self) -> None:
        assert Defaults.EMBEDDING_DIMENSION == 1536

    def test_region(self) -> None:
        assert Defaults.AWS_REGION == "eu-west-2"

    def test_positive_integers(self) -> None:
        assert Defaults.BATCH_SIZE > 0
        assert Defaults.MAX_RETRIES > 0
        assert Defaults.REQUEST_TIMEOUT > 0


class TestDatabaseConfig:
    def test_table_name(self) -> None:
        assert DatabaseConfig.TABLE_NAME == "meeting_segments"


class TestLogScope:
    def test_core_scopes(self) -> None:
        assert LogScope.CONFIG == "config_loader"
        assert LogScope.API == "api"
        assert LogScope.PROVIDER == "provider"

    def test_v2_scopes(self) -> None:
        assert LogScope.INGESTION == "ingestion"
        assert LogScope.QUERY_SERVICE == "query_service"
        assert LogScope.WORKER == "worker"
        assert LogScope.ADAPTER == "adapter"
        assert LogScope.ORCHESTRATION == "orchestration"


class TestAPIEndpoints:
    def test_health_endpoint(self) -> None:
        assert APIEndpoints.HEALTH == "/health"

    def test_meetings_endpoint(self) -> None:
        assert APIEndpoints.MEETINGS == "/api/meetings"

    def test_v2_status_endpoint(self) -> None:
        assert "{meeting_id}" in APIEndpoints.STATUS

    def test_v2_upload_endpoint(self) -> None:
        assert APIEndpoints.V2_UPLOAD == "/api/v2/upload"

    def test_v2_query_endpoint(self) -> None:
        assert APIEndpoints.V2_QUERY == "/api/v2/query"


class TestFeatures:
    def test_metrics_enabled(self) -> None:
        assert Features.ENABLE_METRICS is True

    def test_unimplemented_features_off(self) -> None:
        assert Features.ENABLE_ACTION_ITEM_EXTRACTION is False
        assert Features.ENABLE_SPEAKER_DIARIZATION is False
