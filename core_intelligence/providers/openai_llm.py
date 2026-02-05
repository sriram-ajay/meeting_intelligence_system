"""
OpenAI LLM provider implementation.
"""

from typing import Optional
from llama_index.llms.openai import OpenAI
from core_intelligence.providers import LLMProviderBase
from shared_utils.constants import LogScope


class OpenAILLMProvider(LLMProviderBase):
    """OpenAI LLM provider."""
    
    def __init__(self, model_id: str, api_key: str):
        super().__init__(name=f"OpenAILLM({model_id})")
        self.model_id = model_id
        self.api_key = api_key
        self._llm = None
    
    def initialize(self) -> None:
        """Initialize OpenAI LLM client."""
        try:
            self._llm = OpenAI(
                model=self.model_id,
                api_key=self.api_key
            )
            self.logger.info(
                "Initialized OpenAI LLM provider",
                extra={
                    "scope": LogScope.CONFIG,
                    "model_id": self.model_id
                }
            )
        except Exception as e:
            self.logger.error(
                "Failed to initialize OpenAI LLM provider",
                extra={"scope": LogScope.CONFIG, "error": str(e)}
            )
            raise
    
    def is_available(self) -> bool:
        """Check if OpenAI LLM is available."""
        return self._llm is not None
    
    def generate(self, prompt: str, context: Optional[str] = None) -> str:
        """Generate response from LLM."""
        if not self.is_available():
            raise RuntimeError("OpenAI LLM provider not initialized")
        
        try:
            # Combine context with prompt if provided
            full_prompt = f"{context}\n\n{prompt}" if context else prompt
            
            response = self._llm.complete(full_prompt)
            return response.text
        except Exception as e:
            self.logger.error(
                "LLM generation failed",
                extra={"scope": LogScope.RAG_ENGINE, "error": str(e)}
            )
            raise
    
    def generate_with_context(self, query: str, context: list[str]) -> str:
        """Generate response with RAG context."""
        if not self.is_available():
            raise RuntimeError("OpenAI LLM provider not initialized")
        
        # Build prompt with context
        context_text = "\n".join(context)
        prompt = f"""Based on the following context, answer the question:

Context:
{context_text}

Question: {query}

Answer:"""
        
        return self.generate(prompt)
