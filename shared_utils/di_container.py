"""
Dependency injection container for managing application dependencies.
Centralizes provider creation and lifecycle management.
"""

from typing import Optional
import logging

from core_intelligence.providers import EmbeddingProviderBase, LLMProviderBase
from core_intelligence.providers.factory import EmbeddingProviderFactory, LLMProviderFactory
from shared_utils.constants import LogScope


logger = logging.getLogger(__name__)


class DIContainer:
    """Singleton dependency injection container."""
    
    _instance: Optional['DIContainer'] = None
    _embedding_provider: Optional[EmbeddingProviderBase] = None
    _llm_provider: Optional[LLMProviderBase] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def reset(self):
        """Reset container (useful for testing)."""
        self._embedding_provider = None
        self._llm_provider = None
    
    def get_embedding_provider(self) -> EmbeddingProviderBase:
        """Get or create embedding provider (lazy singleton).
        
        Returns:
            Initialized embedding provider.
        
        Raises:
            RuntimeError: If provider initialization fails.
        """
        if self._embedding_provider is None:
            logger.info(
                "Initializing embedding provider",
                extra={"scope": LogScope.CONFIG}
            )
            try:
                self._embedding_provider = EmbeddingProviderFactory.create()
            except Exception as e:
                logger.error(
                    "Failed to initialize embedding provider",
                    extra={"scope": LogScope.CONFIG, "error": str(e)}
                )
                raise RuntimeError(f"Embedding provider initialization failed: {e}") from e
        
        return self._embedding_provider
    
    def get_llm_provider(self) -> LLMProviderBase:
        """Get or create LLM provider (lazy singleton).
        
        Returns:
            Initialized LLM provider.
        
        Raises:
            RuntimeError: If provider initialization fails.
        """
        if self._llm_provider is None:
            logger.info(
                "Initializing LLM provider",
                extra={"scope": LogScope.CONFIG}
            )
            try:
                self._llm_provider = LLMProviderFactory.create()
            except Exception as e:
                logger.error(
                    "Failed to initialize LLM provider",
                    extra={"scope": LogScope.CONFIG, "error": str(e)}
                )
                raise RuntimeError(f"LLM provider initialization failed: {e}") from e
        
        return self._llm_provider
    
    def validate_all_providers(self) -> bool:
        """Validate that all providers are available.
        
        Returns:
            True if all providers are healthy.
        
        Raises:
            RuntimeError: If any provider is unavailable.
        """
        logger.info(
            "Validating providers",
            extra={"scope": LogScope.CONFIG}
        )
        
        try:
            embedding_ok = self.get_embedding_provider().is_available()
            llm_ok = self.get_llm_provider().is_available()
            
            # Build detailed error message for any failures
            failures = []
            if not embedding_ok:
                failures.append("Embedding provider is not available")
            if not llm_ok:
                failures.append("LLM provider is not available")
            
            if failures:
                error_msg = "; ".join(failures)
                raise RuntimeError(f"Provider validation failed: {error_msg}")
            
            logger.info(
                "All providers validated",
                extra={"scope": LogScope.CONFIG, "embedding": embedding_ok, "llm": llm_ok}
            )
            return True
        
        except Exception as e:
            logger.error(
                "Provider validation failed",
                extra={"scope": LogScope.CONFIG, "error": str(e)}
            )
            raise


# Global singleton instance
_container = DIContainer()


def get_di_container() -> DIContainer:
    """Get global DI container instance."""
    return _container
