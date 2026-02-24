"""
LangChain-based embedding provider — adapts OpenAIEmbeddings / BedrockEmbeddings
to EmbeddingProviderPort.

Replaces the legacy LlamaIndex-based openai_embedding.py and bedrock_embedding.py
with a single adapter that wraps any LangChain ``Embeddings`` instance.  The
adapter satisfies the existing ``EmbeddingProviderPort`` protocol so all
downstream services (IngestionService, QueryService) work unchanged.

Also exposes the underlying LangChain embeddings via ``.embeddings`` for direct
use in LangGraph nodes.
"""

from __future__ import annotations

from typing import List
import logging

from langchain_core.embeddings import Embeddings

from core_intelligence.providers import EmbeddingProviderBase
from shared_utils.constants import LogScope


logger = logging.getLogger(__name__)


class LangChainEmbeddingProvider(EmbeddingProviderBase):
    """Adapter: LangChain Embeddings → EmbeddingProviderPort / EmbeddingProviderBase.

    Wraps any LangChain embedding model (OpenAIEmbeddings, BedrockEmbeddings,
    etc.) and exposes it through the existing provider interface.
    """

    def __init__(
        self,
        embeddings: Embeddings,
        dimension: int = 1536,
        name: str = "LangChainEmbedding",
    ) -> None:
        super().__init__(name=name)
        self._embeddings = embeddings
        self._dimension = dimension

    # -- Expose underlying model for LangGraph / LCEL usage --
    @property
    def embeddings(self) -> Embeddings:
        """Return the raw LangChain embeddings model."""
        return self._embeddings

    # -- EmbeddingProviderBase / EmbeddingProviderPort implementation --

    def initialize(self) -> None:
        """No-op — LangChain embeddings are ready on construction."""
        logger.info(
            "LangChain embedding provider ready",
            extra={
                "scope": LogScope.CONFIG,
                "model": self.name,
                "dimension": self._dimension,
            },
        )

    def is_available(self) -> bool:
        """LangChain embeddings are available once constructed."""
        return self._embeddings is not None

    def embed_text(self, text: str) -> List[float]:
        """Embed a single text string."""
        return self._embeddings.embed_query(text)

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Embed multiple text strings (uses batch API when available)."""
        return self._embeddings.embed_documents(texts)

    def get_embedding_dimension(self) -> int:
        """Return the dimensionality of produced embeddings."""
        return self._dimension
