"""
OpenAI embedding provider implementation.
"""

from typing import List
from llama_index.embeddings.openai import OpenAIEmbedding
from core_intelligence.providers import EmbeddingProviderBase
from shared_utils.constants import ModelIDs, Defaults, LogScope


class OpenAIEmbeddingProvider(EmbeddingProviderBase):
    """OpenAI text embedding provider."""
    
    def __init__(self, api_key: str, model: str = ModelIDs.OPENAI_EMBED_MODEL):
        super().__init__(name=f"OpenAIEmbedding({model})")
        self.api_key = api_key
        self.model = model
        self._embedding = None
    
    def initialize(self) -> None:
        """Initialize OpenAI embedding client."""
        try:
            self._embedding = OpenAIEmbedding(
                api_key=self.api_key,
                model=self.model
            )
            self.logger.info(
                "Initialized OpenAI embedding provider",
                extra={
                    "scope": LogScope.CONFIG,
                    "model": self.model,
                    "dimension": self.get_embedding_dimension()
                }
            )
        except Exception as e:
            self.logger.error(
                "Failed to initialize OpenAI embedding provider",
                extra={"scope": LogScope.CONFIG, "error": str(e)}
            )
            raise
    
    def is_available(self) -> bool:
        """Check if OpenAI API is available."""
        return self._embedding is not None
    
    def embed_text(self, text: str) -> List[float]:
        """Generate embedding for single text."""
        if not self.is_available():
            raise RuntimeError("OpenAI embedding provider not initialized")
        
        try:
            embedding = self._embedding.get_text_embedding(text)
            return embedding
        except Exception as e:
            self.logger.error(
                "Embedding generation failed",
                extra={"scope": LogScope.RAG_ENGINE, "error": str(e)}
            )
            raise
    
    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts."""
        if not self.is_available():
            raise RuntimeError("OpenAI embedding provider not initialized")
        
        embeddings = []
        for text in texts:
            embedding = self.embed_text(text)
            embeddings.append(embedding)
        return embeddings
    
    def get_embedding_dimension(self) -> int:
        """Return dimensionality of OpenAI embeddings."""
        return Defaults.EMBEDDING_DIMENSION
