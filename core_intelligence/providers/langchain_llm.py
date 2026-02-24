"""
LangChain-based LLM provider — adapts ChatOpenAI / ChatBedrock to LLMProviderPort.

Replaces the legacy LlamaIndex-based openai_llm.py and bedrock_llm.py with a
single adapter that wraps any LangChain ``BaseChatModel``.  The adapter
satisfies the existing ``LLMProviderPort`` protocol (``generate`` and
``generate_with_context``) so all downstream services work unchanged.

Also exposes the underlying LangChain model via ``.chat_model`` for direct
use in LangGraph nodes and LCEL chains.
"""

from __future__ import annotations

from typing import List, Optional
import logging

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from core_intelligence.providers import LLMProviderBase
from shared_utils.constants import LogScope


logger = logging.getLogger(__name__)


class LangChainLLMProvider(LLMProviderBase):
    """Adapter: LangChain BaseChatModel → LLMProviderPort / LLMProviderBase.

    Wraps any LangChain chat model (ChatOpenAI, ChatBedrock, etc.) and
    exposes it through the existing provider interface used by services.
    """

    def __init__(self, chat_model: BaseChatModel, name: str = "LangChainLLM") -> None:
        super().__init__(name=name)
        self._chat_model = chat_model

    # -- Expose underlying model for LangGraph / LCEL usage --
    @property
    def chat_model(self) -> BaseChatModel:
        """Return the raw LangChain chat model for direct chain usage."""
        return self._chat_model

    # -- LLMProviderBase / LLMProviderPort implementation --

    def initialize(self) -> None:
        """No-op — LangChain models are ready on construction."""
        logger.info(
            "LangChain LLM provider ready",
            extra={"scope": LogScope.CONFIG, "model": self.name},
        )

    def is_available(self) -> bool:
        """LangChain models are available once constructed."""
        return self._chat_model is not None

    def generate(self, prompt: str, context: Optional[str] = None) -> str:
        """Generate text from a prompt, optionally prepending context."""
        messages = []
        if context:
            messages.append(SystemMessage(content=context))
        messages.append(HumanMessage(content=prompt))

        response = self._chat_model.invoke(messages)
        return response.content

    def generate_with_context(self, query: str, context: List[str]) -> str:
        """Generate a response grounded in provided context chunks."""
        context_text = "\n".join(context)
        messages = [
            SystemMessage(
                content=(
                    "You are a meeting intelligence assistant. Answer the user's "
                    "question using ONLY the context below. If the answer is not "
                    "in the context, say so explicitly.\n\n"
                    f"CONTEXT:\n{context_text}"
                )
            ),
            HumanMessage(content=query),
        ]
        response = self._chat_model.invoke(messages)
        return response.content
