import os
import logging
from typing import List, Optional

import lancedb
from llama_index.core import (
    VectorStoreIndex, 
    StorageContext, 
    Document,
    Settings
)
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.vector_stores.lancedb import LanceDBVectorStore
from llama_index.core.vector_stores import MetadataFilters, ExactMatchFilter

from core_intelligence.providers import EmbeddingProviderBase, LLMProviderBase
from core_intelligence.schemas.models import MeetingTranscript, QueryResponse, ActionItem
from core_intelligence.database.manager import SchemaManager
from shared_utils.config_loader import get_settings
from shared_utils.di_container import get_di_container
from shared_utils.logging_utils import ContextualLogger, log_execution
from shared_utils.error_handler import ProcessingError, QueryError
from shared_utils.constants import DatabaseConfig, LogScope


logger = ContextualLogger(scope=LogScope.RAG_ENGINE)


from core_intelligence.engine.strategies.chunking import ChunkingStrategy, SegmentChunker, SemanticChunker
from core_intelligence.engine.strategies.retrieval import RetrievalStrategy, RagFusionStrategy, HybridRerankRetriever
from core_intelligence.engine.strategies.embedding import EmbeddingStrategy, StandardEmbedding
from core_intelligence.engine.strategies.query_expansion import QueryExpander, LLMQueryEnhancer, NullExpander
from core_intelligence.engine.guardrails import GuardrailEngine

class RAGEngine:
    """RAG engine with pluggable providers and strategies."""
    
    def __init__(
        self,
        uri: str = None,
        embedding_provider: Optional[EmbeddingProviderBase] = None,
        llm_provider: Optional[LLMProviderBase] = None,
        chunking_strategy: Optional[ChunkingStrategy] = None,
        retrieval_strategy: Optional[RetrievalStrategy] = None,
        embedding_strategy: Optional[EmbeddingStrategy] = None,
        query_expander: Optional[QueryExpander] = None
    ):
        """Initialize RAG engine with optional provider and strategy overrides.
        
        Args:
            uri: Optional database URI override
            embedding_provider: Optional custom embedding provider
            llm_provider: Optional custom LLM provider
            chunking_strategy: Strategy for chunking documents (pluggable)
            retrieval_strategy: Strategy for querying (pluggable)
            embedding_strategy: Strategy for embedding handling (pluggable)
            query_expander: Strategy for query enhancement (pluggable)
        """
        settings = get_settings()
        self.uri = uri or settings.database_uri
        
        # Create database directory if needed (only for local paths)
        if not self.uri.startswith(("s3://", "gs://", "az://")):
            db_dir = os.path.dirname(self.uri)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)
        
        # Get providers from DI container or use provided instances
        di_container = get_di_container()
        self.embedding_provider = embedding_provider or di_container.get_embedding_provider()
        self.llm_provider = llm_provider or di_container.get_llm_provider()
        
        # Strategies configuration - DEFAULTS
        # 1. Semantic Hybrid Chunking (Optimized)
        self.chunking_strategy = chunking_strategy or SemanticChunker(
            embed_model=self.embedding_provider._embedding,
            breakpoint_percentile=85 # Balanced granularity
        )
        
        # 2. Optimized Hybrid Retrieval (More efficient than RagFusion)
        self.retrieval_strategy = retrieval_strategy or HybridRerankRetriever(llm=self.llm_provider._llm)
        
        # 3. Use LLMQueryEnhancer to sharpen intent
        self.query_expander = query_expander or LLMQueryEnhancer()
        
        # 4. Production Guardrails
        self.guardrails = GuardrailEngine(llm=self.llm_provider._llm)
        
        # 5. Standard Provider-based Embeddings
        self.embedding_strategy = embedding_strategy or StandardEmbedding(self.embedding_provider._embedding)
        
        # 6. Check if FTS is supported (LanceDB only supports FTS on local filesystem)
        self.supports_fts = not self.uri.startswith(("s3://", "gs://", "az://"))
        
        logger.info(
            "initializing_rag_engine",
            uri=self.uri,
            chunk_strategy=self.chunking_strategy.__class__.__name__,
            retrieval_strategy=self.retrieval_strategy.__class__.__name__,
            supports_fts=self.supports_fts,
            version_update="LATEST_HYBRID_RETRIEVAL_V3"
        )
        
        # Configure LlamaIndex global settings with injected providers
        try:
            # LlamaIndex expects specific provider types, so we access the underlying instances
            Settings.embed_model = self.embedding_strategy.get_embed_model()
            Settings.llm = self.llm_provider._llm
            
            logger.info(
                "configured_llm_and_embedding",
                embedding_dim=self.embedding_provider.get_embedding_dimension()
            )
        except Exception as e:
            logger.error("failed_to_configure_providers", error=str(e))
            raise ProcessingError(f"Provider configuration failed: {e}", error_type="indexing")
        
        # Initialize vector store
        self.db = lancedb.connect(self.uri)
        self.table_name = DatabaseConfig.TABLE_NAME
        
        # Check initial state (will be updated during indexing)
        table_exists = self.table_name in self.db.table_names()
        initial_mode = DatabaseConfig.MODE_APPEND if table_exists else DatabaseConfig.MODE_OVERWRITE
        
        try:
            # Senior Engineering: We enable flat_metadata=True to ensure that 
            # meeting_id filters are executed as direct column queries in LanceDB.
            self.vector_store = LanceDBVectorStore(
                uri=self.uri,
                table_name=self.table_name,
                mode=initial_mode,
                flat_metadata=True
            )
            self.storage_context = StorageContext.from_defaults(vector_store=self.vector_store)
            self._is_append_mode = (initial_mode == DatabaseConfig.MODE_APPEND)
            
            # --- Production Schema Safeguard ---
            self.schema_manager = SchemaManager(self.db, self.table_name)
            if not self.schema_manager.validate_or_repair():
                error_msg = (
                    "DATABASE_SCHEMA_MISMATCH: The existing database schema is incompatible with the current metadata requirements. "
                    "This usually happens when changing chunking strategies. Please run 'python -m scripts.resync_db' to reset the database."
                )
                logger.error("schema_mismatch_detected", details=error_msg)
                raise ProcessingError(error_msg, error_type="indexing")
            
            logger.info("initialized_vector_store", mode=initial_mode, table=self.table_name)
        except Exception as e:
            logger.error("failed_to_initialize_vector_store", error=str(e))
            raise ProcessingError(f"Vector store initialization failed: {e}", error_type="indexing")
    
    def _ensure_append_mode(self):
        """Ensure vector store is in append mode if table exists."""
        if not self._is_append_mode and self.table_name in self.db.table_names():
            # Refresh vector store with append mode
            try:
                self.vector_store = LanceDBVectorStore(
                    uri=self.uri,
                    table_name=self.table_name,
                    mode=DatabaseConfig.MODE_APPEND,
                    flat_metadata=True
                )
                self.storage_context = StorageContext.from_defaults(vector_store=self.vector_store)
                self._is_append_mode = True
                logger.info("switched_to_append_mode")
            except Exception as e:
                logger.error("failed_to_switch_to_append_mode", error=str(e))
                # Don't raise here, try to continue but log the risk

    @log_execution(scope=LogScope.RAG_ENGINE)
    def index_transcript(self, transcript: MeetingTranscript) -> str:
        """Index meeting transcript segments as documents.
        
        Args:
            transcript: Meeting transcript with segments to index
        
        Returns:
            Meeting ID
        
        Raises:
            ProcessingError: If indexing fails
        """
        try:
            logger.info("indexing_transcript", meeting_id=transcript.metadata.meeting_id, strategy=self.chunking_strategy.__class__.__name__)
            self._ensure_append_mode()
            
            # Use pluggable chunking strategy
            documents = self.chunking_strategy.chunk(transcript)
            
            logger.debug(
                "created_documents",
                document_count=len(documents),
                meeting_id=transcript.metadata.meeting_id
            )
            
            # Create index from documents
            index = VectorStoreIndex.from_documents(
                documents, 
                storage_context=self.storage_context
            )

            # Ensure Full Text Search index is created for Hybrid Search
            try:
                table = self.db.open_table(self.table_name)
                # LanceDB needs an FTS index for keyword/hybrid search
                table.create_fts_index("text", replace=True)
                logger.info("created_fts_index", table=self.table_name)
            except Exception as e:
                logger.warning("failed_to_create_fts_index", error=str(e))
            
            logger.info(
                "indexed_transcript_successfully",
                meeting_id=transcript.metadata.meeting_id,
                chunk_count=len(documents)
            )
            
            return transcript.metadata.meeting_id
        
        except Exception as e:
            logger.error("transcript_indexing_failed", error=str(e))
            raise ProcessingError(
                f"Failed to index transcript: {e}",
                error_type="indexing",
                context={"meeting_id": transcript.metadata.meeting_id}
            )

    @log_execution(scope=LogScope.RAG_ENGINE)
    def query(self, query_str: str, meeting_id: Optional[str] = None) -> QueryResponse:
        """Perform RAG query optionally filtered by meeting.
        
        Args:
            query_str: Query text
            meeting_id: Optional meeting ID filter
        
        Returns:
            Query response with answer and sources
        
        Raises:
            QueryError: If query execution fails
        """
        try:
            # Step 0: Input Guardrail
            if not self.guardrails.validate_input(query_str):
                return QueryResponse(
                    answer="I'm sorry, but I cannot process that query for safety or professional reasons.",
                    sources=[],
                    retrieved_contexts=[],
                    action_items=[]
                )

            # Step 1: Query Enhancement
            original_query = query_str
            # Only expand if it's very short or ambiguous
            query_str = self.query_expander.expand(query_str, self.llm_provider._llm)
            
            if query_str != original_query:
                logger.debug("query_enhanced", original=original_query, expanded=query_str)

            logger.info("executing_query", query_str=query_str, meeting_id=meeting_id, strategy=self.retrieval_strategy.__class__.__name__)
            
            index = VectorStoreIndex.from_vector_store(self.vector_store)

            # Retrieve query engine with a healthy top_k pool
            query_engine = self.retrieval_strategy.get_query_engine(
                index, 
                top_k=7, 
                meeting_id=meeting_id,
                supports_fts=self.supports_fts
            )
            
            # Execute query
            response = query_engine.query(query_str)
            
            # Handle RAG failures or empty yields
            source_nodes = getattr(response, 'source_nodes', [])
            if not source_nodes or not str(response).strip() or "Empty Response" in str(response):
                logger.warning("retrieval_insufficient", query=query_str, nodes_found=len(source_nodes))
                
                # FALLBACK: If Hybrid/Rerank failed to find content, try a broad vector search
                # This fixes the "cannot find answer" regression for similar queries
                logger.info("attempting_fallback_search")
                fallback_retriever = index.as_retriever(similarity_top_k=5)
                if meeting_id:
                    from llama_index.core.vector_stores import MetadataFilters, ExactMatchFilter
                    fallback_retriever.filters = MetadataFilters(filters=[
                        ExactMatchFilter(key="meeting_id", value=meeting_id)
                    ])
                
                fallback_engine = RetrieverQueryEngine.from_args(retriever=fallback_retriever)
                response = fallback_engine.query(query_str)
                source_nodes = getattr(response, 'source_nodes', [])

            if not source_nodes:
                return QueryResponse(
                    answer="I couldn't find any relevant sections in the transcripts to answer your question. Could you try rephrasing or mentioning specific topics?",
                    sources=[],
                    action_items=[]
                )
            
            # Extract sources and unique titles
            sources_metadata = []
            retrieved_texts = []
            for node in source_nodes:
                text = node.node.get_content()
                retrieved_texts.append(text)
                
                meta = getattr(node.node, 'metadata', {})
                sources_metadata.append(meta.get('title', 'Transcript Chunk'))
            
            unique_sources = list(set(sources_metadata))
            
            # Step 4: Output Grounding Guardrail (Production Grade)
            final_answer = str(response)
            is_grounded, safe_answer = self.guardrails.verify_grounding(final_answer, retrieved_texts)
            
            if not is_grounded:
                logger.warning("hallucination_detected", original_answer=final_answer[:50])
                final_answer = safe_answer

            logger.info(
                "query_synthesis_complete",
                sources_count=len(unique_sources),
                answer_preview=final_answer[:50]
            )
            
            return QueryResponse(
                answer=final_answer,
                sources=unique_sources,
                retrieved_contexts=retrieved_texts,
                action_items=[]
            )
        
        except Exception as e:
            error_msg = str(e)
            logger.error("query_execution_failed", error=error_msg)
            
            # If it's a "no results" type error from the engine, return a friendly message
            if "empty" in error_msg.lower() or "not found" in error_msg.lower():
                return QueryResponse(
                    answer="I couldn't find any relevant information to answer your query.",
                    sources=[],
                    action_items=[]
                )
                
            raise QueryError(
                f"Query execution failed: {error_msg}",
                context={"query": query_str, "meeting_id": meeting_id}
            )
