"""
Bedrock LLM provider implementation.
"""

from typing import Optional
from llama_index.llms.bedrock import Bedrock
from core_intelligence.providers import LLMProviderBase
from shared_utils.constants import LogScope


class BedrockLLMProvider(LLMProviderBase):
    """AWS Bedrock LLM provider."""
    
    def __init__(self, model_id: str, region: str):
        super().__init__(name=f"BedrockLLM({model_id})")
        self.model_id = model_id
        self.region = region
        self._llm = None
    
    def initialize(self) -> None:
        """Initialize Bedrock LLM client."""
        try:
            self._llm = Bedrock(
                model=self.model_id,
                region_name=self.region
            )
            self.logger.info(
                "Initialized Bedrock LLM provider",
                extra={
                    "scope": LogScope.CONFIG,
                    "model_id": self.model_id,
                    "region": self.region
                }
            )
        except Exception as e:
            self.logger.error(
                "Failed to initialize Bedrock LLM provider",
                extra={"scope": LogScope.CONFIG, "error": str(e)}
            )
            raise
    
    def is_available(self) -> bool:
        """Check if Bedrock LLM is available."""
        return self._llm is not None
    
    def generate(self, prompt: str, context: Optional[str] = None) -> str:
        """Generate response from LLM."""
        if not self.is_available():
            raise RuntimeError("Bedrock LLM provider not initialized")
        
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
            raise RuntimeError("Bedrock LLM provider not initialized")
        
        # Build prompt with context
        context_text = "\n".join(context)
        prompt = f"""Based on the following context, answer the question:

Context:
{context_text}

Question: {query}

Answer:"""
        
        return self.generate(prompt)
