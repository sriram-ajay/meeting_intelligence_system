"""
Port interface for LLM and embedding operations.

The existing core_intelligence/providers/ already implement concrete versions.
This port formalises the contract so services depend on the interface, not the impl.
"""

from __future__ import annotations

from typing import List, Optional, Protocol, runtime_checkable


@runtime_checkable
class LLMProviderPort(Protocol):
    """Abstract interface for LLM text generation."""

    def generate(self, prompt: str, context: Optional[str] = None) -> str:
        """Generate text from a prompt.

        Args:
            prompt: User/system prompt.
            context: Optional context to prepend.

        Returns:
            Generated text string.
        """
        ...

    def generate_with_context(self, query: str, context: List[str]) -> str:
        """Generate a response grounded in provided context chunks.

        Args:
            query: User query.
            context: Retrieved context passages.

        Returns:
            Generated answer string.
        """
        ...


@runtime_checkable
class EmbeddingProviderPort(Protocol):
    """Abstract interface for text embedding."""

    def embed_text(self, text: str) -> List[float]:
        """Embed a single text string.

        Args:
            text: Input text.

        Returns:
            Embedding vector.
        """
        ...

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Embed multiple text strings.

        Args:
            texts: List of input texts.

        Returns:
            List of embedding vectors (same order as input).
        """
        ...

    def get_embedding_dimension(self) -> int:
        """Return the dimensionality of produced embeddings."""
        ...
