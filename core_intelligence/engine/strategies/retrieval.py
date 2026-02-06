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
    def get_query_engine(
        self, 
        index: VectorStoreIndex, 
        top_k: int = 5, 
        meeting_id: Optional[str] = None,
        supports_fts: bool = True
    ) -> Any:
        """Create a query engine based on the strategy."""
        pass

class VectorSearchRetriever(RetrievalStrategy):
    """Standard vector similarity search."""
    
    def get_query_engine(
        self, 
        index: VectorStoreIndex, 
        top_k: int = 5, 
        meeting_id: Optional[str] = None,
        supports_fts: bool = True
    ) -> Any:
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
                SimilarityPostprocessor(similarity_cutoff=0.3) # Increased recall for naive search
            ]
        )

class HybridRerankRetriever(RetrievalStrategy):
    """
    High-Efficiency Hybrid Strategy.
    Combines Vector Similarity with Keyword Search (FTS) for maximum 
    coverage, then uses a lightweight re-ranking pass.
    """
    
    def __init__(self, llm: Any = None):
        self.llm = llm

    def get_query_engine(
        self, 
        index: VectorStoreIndex, 
        top_k: int = 7, 
        meeting_id: Optional[str] = None,
        supports_fts: bool = True
    ) -> Any:
        filters = None
        if meeting_id:
            from llama_index.core.vector_stores import MetadataFilters, ExactMatchFilter
            filters = MetadataFilters(filters=[
                ExactMatchFilter(key="meeting_id", value=meeting_id)
            ])

        # 1. Setup Retriever
        # Fallback to pure vector search if FTS is unavailable (e.g. S3 storage)
        mode = VectorStoreQueryMode.HYBRID if supports_fts else VectorStoreQueryMode.DEFAULT
        
        retriever = index.as_retriever(
            similarity_top_k=top_k * 2, 
            filters=filters,
            vector_store_query_mode=mode,
            alpha=0.4 if supports_fts else None # Alpha only applies to hybrid
        )
        
        # 2. Post-processing pipeline
        return RetrieverQueryEngine.from_args(
            retriever=retriever,
            node_postprocessors=[
                # Loosened cutoff (0.35) for broader recall, 
                # especially important for S3/Titan embedding variance
                SimilarityPostprocessor(similarity_cutoff=0.35),
                LLMRerank(
                    choice_batch_size=5, 
                    top_n=5, # Return fewer, higher-quality results
                    llm=self.llm
                )
            ]
        )

class RagFusionStrategy(RetrievalStrategy):
    """
    Optimized RAG Fusion and Reciprocal Rank Fusion (RRF).
    Balanced for performance and accuracy.
    """
    
    def __init__(self, llm: Any = None):
        self.llm = llm

    def get_query_engine(
        self, 
        index: VectorStoreIndex, 
        top_k: int = 10, 
        meeting_id: Optional[str] = None,
        supports_fts: bool = True
    ) -> Any:
        filters = None
        if meeting_id:
            from llama_index.core.vector_stores import MetadataFilters, ExactMatchFilter
            filters = MetadataFilters(filters=[
                ExactMatchFilter(key="meeting_id", value=meeting_id)
            ])

        # Base retriever with fallback for S3
        mode = VectorStoreQueryMode.HYBRID if supports_fts else VectorStoreQueryMode.DEFAULT
        
        base_retriever = index.as_retriever(
            similarity_top_k=top_k * 2, # Increase initial pool
            filters=filters,
            vector_store_query_mode=mode
        )

        # Query Fusion Retriever
        # Optimized: 2 variations + original = 3 total queries (was 4)
        fusion_retriever = QueryFusionRetriever(
            [base_retriever],
            llm=self.llm,
            similarity_top_k=top_k, 
            num_queries=3, 
            mode="reciprocal_rerank",
            use_async=False, 
            verbose=False # Reduced noise
        )

        return RetrieverQueryEngine.from_args(
            retriever=fusion_retriever,
            node_postprocessors=[
                # Precision filter: ensure nodes are actually relevant
                SimilarityPostprocessor(similarity_cutoff=0.35),
                # Final re-ranking of the fused result set
                LLMRerank(choice_batch_size=5, top_n=min(5, top_k), llm=self.llm)
            ]
        )

class MetaDataFilteredRetriever(RetrievalStrategy):
    """Retriever that forces specific metadata focus if needed."""
    
    def __init__(self, meeting_id: Optional[str] = None):
        self.meeting_id = meeting_id

    def get_query_engine(
        self, 
        index: VectorStoreIndex, 
        top_k: int = 5, 
        meeting_id: Optional[str] = None,
        supports_fts: bool = True
    ) -> Any:
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
