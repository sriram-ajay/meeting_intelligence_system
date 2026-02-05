"""
Abstract base classes for swappable providers.
Enables dependency injection and flexible component swapping.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import logging


class BaseProvider(ABC):
    """Base class for all providers."""
    
    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(f"{self.__class__.__module__}.{self.__class__.__name__}")
    
    @abstractmethod
    def initialize(self) -> None:
        """Initialize provider. Called after instantiation."""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if provider is available and credentials are valid."""
        pass


class EmbeddingProviderBase(BaseProvider):
    """Abstract base for embedding providers."""
    
    @abstractmethod
    def embed_text(self, text: str) -> List[float]:
        """Generate embedding for single text."""
        pass
    
    @abstractmethod
    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts."""
        pass
    
    @abstractmethod
    def get_embedding_dimension(self) -> int:
        """Return dimensionality of embeddings."""
        pass


class LLMProviderBase(BaseProvider):
    """Abstract base for LLM providers."""
    
    @abstractmethod
    def generate(self, prompt: str, context: Optional[str] = None) -> str:
        """Generate response from LLM."""
        pass
    
    @abstractmethod
    def generate_with_context(self, query: str, context: List[str]) -> str:
        """Generate response with RAG context."""
        pass


class VectorStoreBase(BaseProvider):
    """Abstract base for vector store providers."""
    
    @abstractmethod
    def initialize_table(self, table_name: str, mode: str = "overwrite") -> None:
        """Initialize or create vector store table."""
        pass
    
    @abstractmethod
    def add_documents(self, documents: List[Dict[str, Any]]) -> None:
        """Add documents to vector store."""
        pass
    
    @abstractmethod
    def search(self, query_embedding: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
        """Search for similar documents."""
        pass
    
    @abstractmethod
    def search_with_filters(self, query_embedding: List[float], filters: Dict[str, Any], top_k: int = 5) -> List[Dict[str, Any]]:
        """Search with metadata filters."""
        pass


class ProviderFactory(ABC):
    """Base factory for creating providers."""
    
    @staticmethod
    @abstractmethod
    def create(**kwargs) -> BaseProvider:
        """Create and initialize provider instance."""
        pass
