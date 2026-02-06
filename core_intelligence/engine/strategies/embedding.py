from abc import ABC, abstractmethod
from typing import Any, List
from llama_index.core.base.embeddings.base import BaseEmbedding

class EmbeddingStrategy(ABC):
    """Abstract base class for embedding strategies."""
    
    @abstractmethod
    def get_embed_model(self) -> BaseEmbedding:
        """Return the configured embedding model."""
        pass

class StandardEmbedding(EmbeddingStrategy):
    """Standard embedding strategy utilizing a specific provider's model."""
    
    def __init__(self, embed_model: BaseEmbedding):
        self._embed_model = embed_model
        
    def get_embed_model(self) -> BaseEmbedding:
        return self._embed_model

class PrefixedEmbedding(EmbeddingStrategy):
    """
    Embedding strategy that adds prefixes (e.g., for BGE or E5 models).
    Useful for distinguishing between 'query: ' and 'passage: '.
    """
    
    def __init__(self, embed_model: BaseEmbedding, query_prefix: str = "query: ", text_prefix: str = "passage: "):
        self._embed_model = embed_model
        self.query_prefix = query_prefix
        self.text_prefix = text_prefix
        
    def get_embed_model(self) -> BaseEmbedding:
        # Some models handle this via internal attributes, 
        # but we can also wrap the model if needed.
        # For LlamaIndex models, they often have query_instruction parameters.
        if hasattr(self._embed_model, 'query_instruction'):
            self._embed_model.query_instruction = self.query_prefix
        if hasattr(self._embed_model, 'text_instruction'):
            self._embed_model.text_instruction = self.text_prefix
        return self._embed_model
