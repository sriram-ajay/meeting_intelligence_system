"""
Factory for creating configured provider instances.
Handles provider instantiation with dependency injection.
"""

from typing import Union
import logging

from core_intelligence.providers import EmbeddingProviderBase, LLMProviderBase
from core_intelligence.providers.openai_embedding import OpenAIEmbeddingProvider
from core_intelligence.providers.bedrock_embedding import BedrockEmbeddingProvider
from core_intelligence.providers.bedrock_llm import BedrockLLMProvider
from core_intelligence.providers.openai_llm import OpenAILLMProvider
from shared_utils.config_loader import get_settings
from shared_utils.constants import EmbeddingProvider, LLMProvider, LogScope


logger = logging.getLogger(__name__)


class EmbeddingProviderFactory:
    """Factory for creating embedding providers."""
    
    @staticmethod
    def create(provider_type: str = None) -> EmbeddingProviderBase:
        """Create configured embedding provider.
        
        Args:
            provider_type: Optional override. If None, uses config value.
        
        Returns:
            Initialized embedding provider.
        
        Raises:
            ValueError: If provider type is unknown or config is invalid.
        """
        settings = get_settings()
        embed_provider = provider_type or settings.embed_provider
        
        logger.info(
            "Creating embedding provider",
            extra={"scope": LogScope.CONFIG, "provider": embed_provider}
        )
        
        try:
            if embed_provider == EmbeddingProvider.OPENAI.value:
                if not settings.openai_api_key:
                    raise ValueError("OPENAI_API_KEY not configured")
                
                provider = OpenAIEmbeddingProvider(
                    api_key=settings.openai_api_key
                )
                provider.initialize()
                return provider
            
            elif embed_provider == EmbeddingProvider.BEDROCK.value:
                if not settings.bedrock_region or not settings.bedrock_embed_model_id:
                    raise ValueError("BEDROCK_REGION or BEDROCK_EMBED_MODEL_ID not configured")
                
                provider = BedrockEmbeddingProvider(
                    model_id=settings.bedrock_embed_model_id,
                    region=settings.bedrock_region
                )
                provider.initialize()
                return provider
            
            else:
                raise ValueError(f"Unknown embedding provider: {embed_provider}")
        
        except Exception as e:
            logger.error(
                "Failed to create embedding provider",
                extra={"scope": LogScope.CONFIG, "provider": embed_provider, "error": str(e)}
            )
            raise


class LLMProviderFactory:
    """Factory for creating LLM providers."""
    
    @staticmethod
    def create() -> LLMProviderBase:
        """Create configured LLM provider.
        
        Returns:
            Initialized LLM provider.
        
        Raises:
            ValueError: If config is invalid.
        """
        settings = get_settings()
        llm_provider = settings.llm_provider
        
        logger.info(
            "Creating LLM provider",
            extra={"scope": LogScope.CONFIG, "provider": llm_provider}
        )
        
        try:
            if llm_provider == LLMProvider.OPENAI:
                if not settings.openai_api_key:
                    raise ValueError("OPENAI_API_KEY not configured")
                
                provider = OpenAILLMProvider(
                    model_id=settings.openai_llm_model_id,
                    api_key=settings.openai_api_key
                )
                provider.initialize()
                return provider
            
            elif llm_provider == LLMProvider.BEDROCK:
                if not settings.bedrock_region or not settings.bedrock_llm_model_id:
                    raise ValueError("BEDROCK_REGION or BEDROCK_LLM_MODEL_ID not configured")
                
                provider = BedrockLLMProvider(
                    model_id=settings.bedrock_llm_model_id,
                    region=settings.bedrock_region
                )
                provider.initialize()
                return provider
            else:
                raise ValueError(f"Unknown LLM provider: {llm_provider}")
        
        except Exception as e:
            logger.error(
                "Failed to create LLM provider",
                extra={"scope": LogScope.CONFIG, "provider": llm_provider, "error": str(e)}
            )
            raise
