"""
Comprehensive tests for shared_utils.config_loader.

Covers all three field validators, get_api_base_url(), v2 settings fields,
get_settings() caching, and get_secret_from_aws().
"""

import os
from functools import lru_cache
from unittest.mock import MagicMock, patch

import pytest

from shared_utils.config_loader import Settings, get_settings, get_secret_from_aws


# ---------------------------------------------------------------------------
# Helpers — minimal required kwargs
# ---------------------------------------------------------------------------

_BASE = {
    "llm_provider": "bedrock",
    "embed_provider": "bedrock",
    "bedrock_region": "eu-west-2",
    "bedrock_llm_model_id": "anthropic.claude-3-haiku-20240307-v1:0",
    "database_uri": "file:///tmp/test.db",
    "environment": "development",
}


def _settings(**overrides) -> Settings:
    kw = {**_BASE, **overrides}
    return Settings(**kw)


# ---------------------------------------------------------------------------
# validate_embed_provider
# ---------------------------------------------------------------------------


class TestValidateEmbedProvider:
    def test_openai_valid(self) -> None:
        s = _settings(embed_provider="openai")
        assert s.embed_provider == "openai"

    def test_bedrock_valid(self) -> None:
        s = _settings(embed_provider="bedrock")
        assert s.embed_provider == "bedrock"

    def test_case_insensitive(self) -> None:
        s = _settings(embed_provider="BEDROCK")
        assert s.embed_provider == "bedrock"

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="embed_provider"):
            _settings(embed_provider="invalid")


# ---------------------------------------------------------------------------
# validate_llm_provider
# ---------------------------------------------------------------------------


class TestValidateLLMProvider:
    def test_openai_valid(self) -> None:
        s = _settings(llm_provider="openai")
        assert s.llm_provider == "openai"

    def test_bedrock_valid(self) -> None:
        s = _settings(llm_provider="bedrock")
        assert s.llm_provider == "bedrock"

    def test_case_insensitive(self) -> None:
        s = _settings(llm_provider="OpenAI")
        assert s.llm_provider == "openai"

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="llm_provider"):
            _settings(llm_provider="google")


# ---------------------------------------------------------------------------
# validate_environment (short + long forms)
# ---------------------------------------------------------------------------


class TestValidateEnvironment:
    @pytest.mark.parametrize(
        "input_val, expected",
        [
            ("development", "development"),
            ("staging", "staging"),
            ("production", "production"),
            ("dev", "development"),
            ("stage", "staging"),
            ("prod", "production"),
            ("DEV", "development"),
            ("PROD", "production"),
        ],
    )
    def test_valid_environments(self, input_val: str, expected: str) -> None:
        s = _settings(environment=input_val)
        assert s.environment == expected

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="environment"):
            _settings(environment="alpha")


# ---------------------------------------------------------------------------
# get_api_base_url
# ---------------------------------------------------------------------------


class TestGetApiBaseUrl:
    def test_default_http(self) -> None:
        s = _settings(api_host="api.test.com", api_port=8000)
        assert s.get_api_base_url() == "http://api.test.com:8000"

    def test_https_443_omits_port(self) -> None:
        s = _settings(api_host="api.test.com", api_port=443, api_protocol="https")
        assert s.get_api_base_url() == "https://api.test.com"

    def test_http_80_omits_port(self) -> None:
        s = _settings(api_host="localhost", api_port=80)
        assert s.get_api_base_url() == "http://localhost"

    def test_https_custom_port(self) -> None:
        s = _settings(api_host="api.com", api_port=8443, api_protocol="https")
        assert s.get_api_base_url() == "https://api.com:8443"


# ---------------------------------------------------------------------------
# V2 settings defaults
# ---------------------------------------------------------------------------


class TestV2SettingsDefaults:
    def test_aws_defaults(self) -> None:
        s = _settings()
        assert s.aws_region == "eu-west-2"
        assert s.s3_raw_prefix == "raw"
        assert s.s3_derived_prefix == "derived"
        assert s.dynamodb_table_name == "MeetingsMetadata"

    def test_ecs_defaults_empty(self) -> None:
        s = _settings()
        assert s.ecs_cluster_name == ""
        assert s.ecs_worker_container_name == "worker"

    def test_eval_defaults(self) -> None:
        s = _settings()
        assert s.enable_eval is False
        assert s.eval_last_n == 10

    def test_v2_overrides(self) -> None:
        s = _settings(
            s3_raw_bucket="my-bucket",
            s3_vectors_bucket="vec-bucket",
            s3_vectors_index_name="my-idx",
        )
        assert s.s3_raw_bucket == "my-bucket"
        assert s.s3_vectors_bucket == "vec-bucket"
        assert s.s3_vectors_index_name == "my-idx"


# ---------------------------------------------------------------------------
# get_secret_from_aws
# ---------------------------------------------------------------------------


class TestGetSecretFromAWS:
    @patch("shared_utils.config_loader.boto3.client")
    def test_success(self, mock_client_ctor) -> None:
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {
            "SecretString": '{"openai_api_key": "sk-test123"}'
        }
        mock_client_ctor.return_value = mock_client

        result = get_secret_from_aws("my-secret", "eu-west-2")
        assert result == "sk-test123"
        mock_client_ctor.assert_called_once_with("secretsmanager", region_name="eu-west-2")

    @patch("shared_utils.config_loader.boto3.client")
    def test_no_secret_string_returns_empty(self, mock_client_ctor) -> None:
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {"SecretBinary": b"binary"}
        mock_client_ctor.return_value = mock_client

        result = get_secret_from_aws("my-secret")
        assert result == ""

    @patch("shared_utils.config_loader.boto3.client")
    def test_missing_key_returns_empty(self, mock_client_ctor) -> None:
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {
            "SecretString": '{"other_key": "val"}'
        }
        mock_client_ctor.return_value = mock_client

        result = get_secret_from_aws("my-secret")
        assert result == ""

    @patch("shared_utils.config_loader.boto3.client")
    def test_exception_returns_empty(self, mock_client_ctor) -> None:
        mock_client_ctor.side_effect = Exception("no credentials")
        result = get_secret_from_aws("my-secret")
        assert result == ""


# ---------------------------------------------------------------------------
# get_settings caching
# ---------------------------------------------------------------------------


class TestGetSettings:
    def test_get_settings_returns_settings(self) -> None:
        """get_settings() is @lru_cache, so we clear it and invoke once."""
        get_settings.cache_clear()
        with patch.dict(os.environ, {
            "LLM_PROVIDER": "bedrock",
            "EMBED_PROVIDER": "bedrock",
            "BEDROCK_REGION": "eu-west-2",
            "BEDROCK_LLM_MODEL_ID": "model-id",
            "DATABASE_URI": "file:///tmp/db",
            "ENVIRONMENT": "dev",
        }, clear=False):
            settings = get_settings()
            assert isinstance(settings, Settings)
            assert settings.environment == "development"  # short form normalised

        get_settings.cache_clear()

