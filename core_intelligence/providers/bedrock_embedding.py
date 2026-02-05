"""
Bedrock embedding provider implementation.
"""

from typing import List
from llama_index.embeddings.bedrock import BedrockEmbedding
from core_intelligence.providers import EmbeddingProviderBase
from shared_utils.constants import Defaults, LogScope


class BedrockEmbeddingProvider(EmbeddingProviderBase):
    """AWS Bedrock embedding provider."""
    
    def __init__(self, model_id: str, region: str):
        super().__init__(name=f"BedrockEmbedding({model_id})")
        self.model_id = model_id
        self.region = region
        self._embedding = None
    
    def initialize(self) -> None:
        """Initialize Bedrock embedding client."""
        try:
            self._embedding = BedrockEmbedding(
                model_name=self.model_id,
                region_name=self.region
            )
            self.logger.info(
                "Initialized Bedrock embedding provider",
                extra={
                    "scope": LogScope.CONFIG,
                    "model_id": self.model_id,
                    "region": self.region,
                    "dimension": self.get_embedding_dimension()
                }
            )
        except Exception as e:
            self.logger.error(
                "Failed to initialize Bedrock embedding provider",
                extra={"scope": LogScope.CONFIG, "error": str(e)}
            )
            raise
    
    def is_available(self) -> bool:
        """Check if Bedrock embedding is available."""
        return self._embedding is not None
    
    def embed_text(self, text: str) -> List[float]:
        """Generate embedding for single text."""
        if not self.is_available():
            raise RuntimeError("Bedrock embedding provider not initialized")
        
        try:
            embedding = self._embedding.get_text_embedding(text)
            return embedding
        except Exception as e:
            self.logger.error(
                "Bedrock embedding generation failed",
                extra={"scope": LogScope.RAG_ENGINE, "error": str(e)}
            )
            raise
    
    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts."""
        if not self.is_available():
            raise RuntimeError("Bedrock embedding provider not initialized")
        
        embeddings = []
        for text in texts:
            embedding = self.embed_text(text)
            embeddings.append(embedding)
        return embeddings
    
    def get_embedding_dimension(self) -> int:
        """Return dimensionality of Bedrock embeddings."""
        return Defaults.EMBEDDING_DIMENSION
