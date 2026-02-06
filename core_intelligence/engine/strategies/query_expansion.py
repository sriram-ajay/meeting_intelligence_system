from abc import ABC, abstractmethod
from typing import Any, Optional
from llama_index.core import PromptTemplate

class QueryExpander(ABC):
    """Abstract base class for query expansion/refinement."""
    
    @abstractmethod
    def expand(self, query: str, llm: Any) -> str:
        """Expand or refine the user query."""
        pass

class NullExpander(QueryExpander):
    """Pass-through expander (Default)."""
    
    def expand(self, query: str, llm: Any) -> str:
        return query

class LLMQueryEnhancer(QueryExpander):
    """
    Uses the LLM to transform short or vague queries into 
    retrieval-optimized search descriptions.
    """
    
    EXPANSION_PROMPT = (
        "You are an expert retrieval assistant for a Meeting Intelligence System. "
        "The user provided a short query: '{query}'\n\n"
        "Your task is to rewrite this query to be more descriptive while PRESERVING literal keywords. "
        "If the query is asking about participants, speakers, or meeting metadata (date, title), "
        "expand it to search for meeting overviews, context headers, and participation stats.\n"
        "If it is a generic word like 'meeting', expand it to search for the meeting topic, overview and purpose.\n"
        "Output ONLY the refined search query."
    )
    
    def expand(self, query: str, llm: Any) -> str:
        # Only expand very short queries where intent is ambiguous
        if len(query.split()) > 3:
            return query
            
        prompt = PromptTemplate(self.EXPANSION_PROMPT)
        refined_query = llm.complete(prompt.format(query=query))
        return f"{query}. {str(refined_query).strip()}"

class HypotheticalDocumentEmbedder(QueryExpander):
    """
    HyDE Strategy: Generate a fake 'perfect' meeting segment 
    and use its embedding to find similar real segments.
    """
    
    HYDE_PROMPT = (
        "Given the question '{query}', write a single representative paragraph "
        "of a meeting transcript where this topic is being discussed. include "
        "a speaker name and a timestamp. This will be used for similarity search."
    )
    
    def expand(self, query: str, llm: Any) -> str:
        prompt = PromptTemplate(self.HYDE_PROMPT)
        hypothetical_doc = llm.complete(prompt.format(query=query))
        # Keep the original query in the context for hybrid search
        return f"{query}\n{str(hypothetical_doc).strip()}"
