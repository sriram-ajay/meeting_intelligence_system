import pytest
from unittest.mock import patch, MagicMock
from shared_utils.config_loader import Settings, get_settings

def test_settings_validation_embed_provider():
    # Valid
    Settings(
        bedrock_region="eu-west-2",
        bedrock_llm_model_id="id",
        embed_provider="openai",
        database_uri="uri",
        environment="development",
        llm_provider="openai"
    )
    
    # Invalid
    with pytest.raises(ValueError):
        Settings(
            bedrock_region="eu-west-2",
            bedrock_llm_model_id="id",
            embed_provider="invalid",
            database_uri="uri",
            environment="development",
            llm_provider="openai"
        )

def test_get_api_base_url():
    settings = Settings(
        api_host="api.test.com",
        api_port=8000,
        api_version="v1",
        bedrock_region="eu-west-2",
        bedrock_llm_model_id="id",
        embed_provider="openai",
        database_uri="uri",
        environment="development",
        llm_provider="openai"
    )
    assert settings.get_api_base_url() == "http://api.test.com:8000"

def test_get_api_base_url_production():
    settings = Settings(
        api_host="api.test.com",
        api_port=443,
        api_version="v1",
        bedrock_region="eu-west-2",
        bedrock_llm_model_id="id",
        embed_provider="openai",
        database_uri="uri",
        environment="production",
        llm_provider="openai"
    )
    assert settings.get_api_base_url() == "https://api.test.com"
