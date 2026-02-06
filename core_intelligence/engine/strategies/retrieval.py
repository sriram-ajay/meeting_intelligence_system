from abc import ABC, abstractmethod
from typing import List, Optional, Any
from llama_index.core import VectorStoreIndex, QueryBundle
from llama_index.core.retrievers import VectorIndexRetriever
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.postprocessor import SimilarityPostprocessor
from llama_index.core.postprocessor import LLMRerank
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.core.vector_stores.types import VectorStoreQueryMode

class RetrievalStrategy(ABC):
    """Abstract base class for retrieval and querying strategies."""
    
    @abstractmethod
    def get_query_engine(self, index: VectorStoreIndex, top_k: int = 5, meeting_id: Optional[str] = None) -> Any:
        """Create a query engine based on the strategy."""
        pass

class VectorSearchRetriever(RetrievalStrategy):
    """Standard vector similarity search."""
    
    def get_query_engine(self, index: VectorStoreIndex, top_k: int = 5, meeting_id: Optional[str] = None) -> Any:
        filters = None
        if meeting_id:
            from llama_index.core.vector_stores import MetadataFilters, ExactMatchFilter
            filters = MetadataFilters(filters=[
                ExactMatchFilter(key="meeting_id", value=meeting_id)
            ])

        retriever = index.as_retriever(
            similarity_top_k=top_k,
            filters=filters
        )
        
        return RetrieverQueryEngine.from_args(
            retriever=retriever,
            node_postprocessors=[
                SimilarityPostprocessor(similarity_cutoff=0.5) # Lowered to increase recall
            ]
        )

class HybridRerankRetriever(RetrievalStrategy):
    """
    Advanced strategy: Hybrid search (Keyword + Vector) + LLM Reranking.
    This 'super powers' retrieval by finding relevant terms AND semantic matches,
    then uses the LLM to pick the absolute best context.
    """
    
    def __init__(self, llm: Any = None):
        self.llm = llm

    def get_query_engine(self, index: VectorStoreIndex, top_k: int = 10, meeting_id: Optional[str] = None) -> Any:
        filters = None
        if meeting_id:
            from llama_index.core.vector_stores import MetadataFilters, ExactMatchFilter
            filters = MetadataFilters(filters=[
                ExactMatchFilter(key="meeting_id", value=meeting_id)
            ])

        # 1. Setup Hybrid Retriever (Keyword + Vector)
        # This allows finding literal terms like "date" or "Bob" reliably
        retriever = index.as_retriever(
            similarity_top_k=top_k * 3, # Increased pool for reranker
            filters=filters,
            vector_store_query_mode=VectorStoreQueryMode.HYBRID
        )
        
        # 2. Add LLM Reranker for precision
        reranker = LLMRerank(
            choice_batch_size=5, 
            top_n=top_k, 
            llm=self.llm
        )
        
        return RetrieverQueryEngine.from_args(
            retriever=retriever,
            node_postprocessors=[reranker]
        )

class RagFusionStrategy(RetrievalStrategy):
    """
    State-of-the-art strategy using RAG Fusion and Reciprocal Rank Fusion (RRF).
    It generates multiple versions of the user query to capture different 
    perspectives and combines the results for maximum recall and precision.
    """
    
    def __init__(self, llm: Any = None):
        self.llm = llm

    def get_query_engine(self, index: VectorStoreIndex, top_k: int = 10, meeting_id: Optional[str] = None) -> Any:
        filters = None
        if meeting_id:
            from llama_index.core.vector_stores import MetadataFilters, ExactMatchFilter
            filters = MetadataFilters(filters=[
                ExactMatchFilter(key="meeting_id", value=meeting_id)
            ])

        # Base retriever (Hybrid)
        base_retriever = index.as_retriever(
            similarity_top_k=top_k,
            filters=filters,
            vector_store_query_mode=VectorStoreQueryMode.HYBRID
        )

        # Query Fusion Retriever
        # - num_queries: how many query variations to generate
        # - mode: redundant retrieval fusion mode (reciprocal_rerank)
        fusion_retriever = QueryFusionRetriever(
            [base_retriever],
            llm=self.llm,
            similarity_top_k=top_k,
            num_queries=4,  # Generate 3 variations + 1 original
            mode="reciprocal_rerank", # RRF
            use_async=False, # Switched to False for stability in FastAPI sync context
            verbose=True
        )

        return RetrieverQueryEngine.from_args(
            retriever=fusion_retriever,
            node_postprocessors=[
                # LLM Reranker for precision
                LLMRerank(choice_batch_size=5, top_n=top_k, llm=self.llm)
            ]
        )

class MetaDataFilteredRetriever(RetrievalStrategy):
    """Retriever that forces specific metadata focus if needed."""
    
    def __init__(self, meeting_id: Optional[str] = None):
        self.meeting_id = meeting_id

    def get_query_engine(self, index: VectorStoreIndex, top_k: int = 5, meeting_id: Optional[str] = None) -> Any:
        # Prioritize passed meeting_id over instance one
        m_id = meeting_id or self.meeting_id
        
        filters = None
        if m_id:
            from llama_index.core.vector_stores import MetadataFilters, ExactMatchFilter
            filters = MetadataFilters(filters=[
                ExactMatchFilter(key="meeting_id", value=m_id)
            ])
            
        return index.as_query_engine(
            similarity_top_k=top_k,
            filters=filters
        )
