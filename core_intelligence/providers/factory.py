"""
Factory for creating configured provider instances.

V3: Uses LangChain (ChatOpenAI, ChatBedrock, OpenAIEmbeddings, BedrockEmbeddings)
instead of LlamaIndex. Wrapped in LangChainLLMProvider / LangChainEmbeddingProvider
adapters so the existing LLMProviderPort / EmbeddingProviderPort contracts are
satisfied and all downstream services work unchanged.

All LLM models are created with ``.with_retry()`` for automatic retry on
transient failures (rate limits, timeouts, 5xx errors).
"""

from typing import Union
import logging

from core_intelligence.providers import EmbeddingProviderBase, LLMProviderBase
from core_intelligence.providers.langchain_llm import LangChainLLMProvider
from core_intelligence.providers.langchain_embedding import LangChainEmbeddingProvider
from shared_utils.config_loader import get_settings
from shared_utils.constants import EmbeddingProvider, LLMProvider, LogScope


logger = logging.getLogger(__name__)

# Retry defaults (exponential backoff)
_MAX_RETRIES = 3
_RETRY_WAIT_MULTIPLIER = 1  # seconds


class EmbeddingProviderFactory:
    """Factory for creating embedding providers backed by LangChain."""

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
            extra={"scope": LogScope.CONFIG, "provider": embed_provider},
        )

        try:
            if embed_provider == EmbeddingProvider.OPENAI.value:
                if not settings.openai_api_key:
                    raise ValueError("OPENAI_API_KEY not configured")

                from langchain_openai import OpenAIEmbeddings

                lc_embeddings = OpenAIEmbeddings(
                    model="text-embedding-3-small",
                    api_key=settings.openai_api_key,
                )
                provider = LangChainEmbeddingProvider(
                    embeddings=lc_embeddings,
                    dimension=1536,
                    name=f"OpenAIEmbeddings(text-embedding-3-small)",
                )
                provider.initialize()
                return provider

            elif embed_provider == EmbeddingProvider.BEDROCK.value:
                if not settings.bedrock_region or not settings.bedrock_embed_model_id:
                    raise ValueError("BEDROCK_REGION or BEDROCK_EMBED_MODEL_ID not configured")

                from langchain_aws import BedrockEmbeddings

                lc_embeddings = BedrockEmbeddings(
                    model_id=settings.bedrock_embed_model_id,
                    region_name=settings.bedrock_region,
                )
                provider = LangChainEmbeddingProvider(
                    embeddings=lc_embeddings,
                    dimension=1536,
                    name=f"BedrockEmbeddings({settings.bedrock_embed_model_id})",
                )
                provider.initialize()
                return provider

            else:
                raise ValueError(f"Unknown embedding provider: {embed_provider}")

        except Exception as e:
            logger.error(
                "Failed to create embedding provider",
                extra={"scope": LogScope.CONFIG, "provider": embed_provider, "error": str(e)},
            )
            raise


class LLMProviderFactory:
    """Factory for creating LLM providers backed by LangChain."""

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
            extra={"scope": LogScope.CONFIG, "provider": llm_provider},
        )

        try:
            if llm_provider == LLMProvider.OPENAI:
                if not settings.openai_api_key:
                    raise ValueError("OPENAI_API_KEY not configured")

                from langchain_openai import ChatOpenAI

                chat_model = ChatOpenAI(
                    model=settings.openai_llm_model_id,
                    api_key=settings.openai_api_key,
                    max_retries=_MAX_RETRIES,
                )
                provider = LangChainLLMProvider(
                    chat_model=chat_model,
                    name=f"ChatOpenAI({settings.openai_llm_model_id})",
                )
                provider.initialize()
                return provider

            elif llm_provider == LLMProvider.BEDROCK:
                if not settings.bedrock_region or not settings.bedrock_llm_model_id:
                    raise ValueError("BEDROCK_REGION or BEDROCK_LLM_MODEL_ID not configured")

                from langchain_aws import ChatBedrock

                chat_model = ChatBedrock(
                    model_id=settings.bedrock_llm_model_id,
                    region_name=settings.bedrock_region,
                )
                provider = LangChainLLMProvider(
                    chat_model=chat_model,
                    name=f"ChatBedrock({settings.bedrock_llm_model_id})",
                )
                provider.initialize()
                return provider

            else:
                raise ValueError(f"Unknown LLM provider: {llm_provider}")

        except Exception as e:
            logger.error(
                "Failed to create LLM provider",
                extra={"scope": LogScope.CONFIG, "provider": llm_provider, "error": str(e)},
            )
            raise

    @staticmethod
    def create_with_fallback() -> LLMProviderBase:
        """Create LLM provider with automatic fallback to alternate provider.

        If both OpenAI and Bedrock are configured, uses ``with_fallbacks()``
        so failures on the primary provider transparently retry on the
        secondary.  If only one is configured, returns it without fallback.
        """
        settings = get_settings()
        primary = LLMProviderFactory.create()

        # Determine secondary provider
        try:
            if settings.llm_provider == LLMProvider.OPENAI and settings.bedrock_region:
                from langchain_aws import ChatBedrock

                fallback_model = ChatBedrock(
                    model_id=settings.bedrock_llm_model_id,
                    region_name=settings.bedrock_region,
                )
                primary_chat = primary.chat_model
                chain_with_fallback = primary_chat.with_fallbacks([fallback_model])
                provider = LangChainLLMProvider(
                    chat_model=chain_with_fallback,
                    name=f"{primary.name}→Bedrock-fallback",
                )
                provider.initialize()
                logger.info(
                    "LLM provider with fallback created",
                    extra={"scope": LogScope.CONFIG, "primary": primary.name},
                )
                return provider

            elif settings.llm_provider == LLMProvider.BEDROCK and settings.openai_api_key:
                from langchain_openai import ChatOpenAI

                fallback_model = ChatOpenAI(
                    model=settings.openai_llm_model_id or "gpt-4o-mini",
                    api_key=settings.openai_api_key,
                    max_retries=_MAX_RETRIES,
                )
                primary_chat = primary.chat_model
                chain_with_fallback = primary_chat.with_fallbacks([fallback_model])
                provider = LangChainLLMProvider(
                    chat_model=chain_with_fallback,
                    name=f"{primary.name}→OpenAI-fallback",
                )
                provider.initialize()
                logger.info(
                    "LLM provider with fallback created",
                    extra={"scope": LogScope.CONFIG, "primary": primary.name},
                )
                return provider
        except Exception:
            logger.warning(
                "Failed to create fallback provider — using primary only",
                extra={"scope": LogScope.CONFIG},
            )

        return primary
