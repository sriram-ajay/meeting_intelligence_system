from pydantic_settings import BaseSettings
from pydantic import Field, field_validator, ConfigDict
from functools import lru_cache
from typing import Optional
import os
import json
import logging
import boto3

logger = logging.getLogger(__name__)


def get_secret_from_aws(secret_name: str, region: str = "eu-west-2") -> str:
    """Fetch secret from AWS Secrets Manager.
    
    Args:
        secret_name: Name of the secret in Secrets Manager
        region: AWS region
    
    Returns:
        Secret value or empty string if fetch fails
    """
    try:
        client = boto3.client("secretsmanager", region_name=region)
        response = client.get_secret_value(SecretId=secret_name)
        if "SecretString" in response:
            secret = json.loads(response["SecretString"])
            return secret.get("openai_api_key", "")
        return ""
    except Exception as e:
        logger.warning(f"Could not fetch secret from Secrets Manager: {e}")
        return ""


class Settings(BaseSettings):
    """Application configuration with environment variable precedence.
    
    Precedence: 1) Environment Variables > 2).env file > 3) Class defaults (required fields have no defaults)
    
    All configuration is externalized - no hardcoded defaults except for optional fields.
    """
    # Application metadata
    app_name: str = "Meeting Intelligence System"  # Configurable via APP_NAME env var
    app_version: str = "1.1.0"  # Updated with Hybrid Retrieval V2
    app_description: str = "RAG-powered meeting intelligence system"  # API description
    api_version: str = "v1"  # API version (v1, v2, etc.) - configurable
    
    # API Base URL Configuration
    api_host: str = "localhost"  # Host for API (localhost, 0.0.0.0, or domain)
    api_port: int = 8000  # Port for API service
    api_protocol: str = "http"  # "http" or "https"
    
    # LLM Configuration
    llm_provider: str  # "bedrock" or "openai"
    openai_llm_model_id: str = "gpt-4o-mini"
    bedrock_region: str
    bedrock_llm_model_id: str
    
    # Embedding Configuration (Bedrock or OpenAI)
    embed_provider: str  # "bedrock" or "openai"
    bedrock_embed_model_id: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_secret_name: Optional[str] = None
    
    # Database
    database_uri: str
    
    # Environment
    environment: str
    
    model_config = ConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    @field_validator('embed_provider')
    @classmethod
    def validate_embed_provider(cls, v: str) -> str:
        """Validate embedding provider is supported."""
        valid_providers = {"openai", "bedrock"}
        if v.lower() not in valid_providers:
            raise ValueError(f"embed_provider must be one of {valid_providers}, got {v}")
        return v.lower()
    
    @field_validator('llm_provider')
    @classmethod
    def validate_llm_provider(cls, v: str) -> str:
        """Validate LLM provider is supported."""
        valid_providers = {"openai", "bedrock"}
        if v.lower() not in valid_providers:
            raise ValueError(f"llm_provider must be one of {valid_providers}, got {v}")
        return v.lower()
    
    @field_validator('environment')
    @classmethod
    def validate_environment(cls, v: str) -> str:
        """Validate environment is recognized."""
        valid_envs = {"development", "staging", "production"}
        if v.lower() not in valid_envs:
            raise ValueError(f"environment must be one of {valid_envs}, got {v}")
        return v.lower()
    
    def get_api_base_url(self) -> str:
        """Get full API base URL constructed from host, port and protocol.
        
        Returns:
            Full API base URL (e.g., "http://localhost:8000")
        """
        # Don't add port if it's standard (80 for http, 443 for https)
        port_str = "" if (
            (self.api_protocol == "http" and self.api_port == 80) or
            (self.api_protocol == "https" and self.api_port == 443)
        ) else f":{self.api_port}"
        
        return f"{self.api_protocol}://{self.api_host}{port_str}"


@lru_cache()
def get_settings() -> Settings:
    """Load and cache application settings.
    
    If OpenAI provider is configured and OPENAI_SECRET_NAME is provided,
    fetches API key from AWS Secrets Manager.
    
    Returns:
        Validated Settings instance
    
    Raises:
        ValueError: If required settings are missing or invalid
    """
    settings = Settings()
    
    # Fetch OpenAI key from Secrets Manager if needed
    # Check both embed_provider AND llm_provider since we might need it for evaluation
    needs_openai = (
        settings.embed_provider == "openai" or 
        settings.llm_provider == "openai" or 
        os.environ.get("OPENAI_API_KEY") is None # Default assumption for evaluation
    )
    
    if needs_openai and settings.openai_secret_name:
        secret_key = get_secret_from_aws(settings.openai_secret_name, settings.bedrock_region)
        if secret_key:
            settings.openai_api_key = secret_key
            # IMPORTANT: Ragas and LangChain look for the standard Environment Variable
            os.environ["OPENAI_API_KEY"] = secret_key
            logger.debug("fetched_openai_key_from_secrets_manager")
    
    # Log loaded configuration (sensitive values masked)
    logger.info(
        "configuration_loaded",
        environment=settings.environment,
        bedrock_region=settings.bedrock_region,
        llm_model_id=settings.bedrock_llm_model_id,
        embed_provider=settings.embed_provider,
        database_uri=settings.database_uri
    )
    
    return settings
