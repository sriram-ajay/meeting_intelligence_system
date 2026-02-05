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
from llama_index.vector_stores.lancedb import LanceDBVectorStore
from llama_index.core.vector_stores import MetadataFilters, ExactMatchFilter

from core_intelligence.providers import EmbeddingProviderBase, LLMProviderBase
from core_intelligence.schemas.models import MeetingTranscript, QueryResponse, ActionItem
from shared_utils.config_loader import get_settings
from shared_utils.di_container import get_di_container
from shared_utils.logging_utils import ContextualLogger, log_execution
from shared_utils.error_handler import ProcessingError, QueryError
from shared_utils.constants import DatabaseConfig, LogScope


logger = ContextualLogger(scope=LogScope.RAG_ENGINE)


class RAGEngine:
    """RAG engine with pluggable providers and dependency injection."""
    
    def __init__(
        self,
        uri: str = None,
        embedding_provider: Optional[EmbeddingProviderBase] = None,
        llm_provider: Optional[LLMProviderBase] = None
    ):
        """Initialize RAG engine with optional provider overrides.
        
        Args:
            uri: Optional database URI override
            embedding_provider: Optional custom embedding provider (uses DI if not provided)
            llm_provider: Optional custom LLM provider (uses DI if not provided)
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
        
        logger.info(
            "initializing_rag_engine",
            uri=self.uri,
            embedding_provider=self.embedding_provider.name,
            llm_provider=self.llm_provider.name
        )
        
        # Configure LlamaIndex global settings with injected providers
        try:
            # LlamaIndex expects specific provider types, so we access the underlying instances
            Settings.embed_model = self.embedding_provider._embedding
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
        
        # Check if table exists to decide on mode
        table_exists = self.table_name in self.db.table_names()
        mode = DatabaseConfig.MODE_APPEND if table_exists else DatabaseConfig.MODE_OVERWRITE
        
        try:
            self.vector_store = LanceDBVectorStore(
                uri=self.uri,
                table_name=self.table_name,
                mode=mode
            )
            self.storage_context = StorageContext.from_defaults(vector_store=self.vector_store)
            logger.info("initialized_vector_store", mode=mode, table=self.table_name)
        except Exception as e:
            logger.error("failed_to_initialize_vector_store", error=str(e))
            raise ProcessingError(f"Vector store initialization failed: {e}", error_type="indexing")
    
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
            logger.info("indexing_transcript", meeting_id=transcript.metadata.meeting_id)
            
            # Convert segments to documents with metadata
            documents = []
            for segment in transcript.segments:
                doc = Document(
                    text=segment.content,
                    metadata={
                        "meeting_id": transcript.metadata.meeting_id,
                        "title": transcript.metadata.title,
                        "speaker": segment.speaker,
                        "timestamp": segment.timestamp,
                        "date": transcript.metadata.date.isoformat()
                    }
                )
                documents.append(doc)
            
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
            
            logger.info(
                "indexed_transcript_successfully",
                meeting_id=transcript.metadata.meeting_id,
                segment_count=len(transcript.segments)
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
            logger.info("executing_query", query_str=query_str, meeting_id=meeting_id)
            
            index = VectorStoreIndex.from_vector_store(self.vector_store)
            
            # Apply filters if meeting_id provided
            filters = None
            if meeting_id:
                filters = MetadataFilters(filters=[
                    ExactMatchFilter(key="meeting_id", value=meeting_id)
                ])
                logger.debug("applied_meeting_filter", meeting_id=meeting_id)
            
            query_engine = index.as_query_engine(filters=filters)
            response = query_engine.query(query_str)
            
            # Extract sources from response nodes
            sources = []
            for node in response.source_nodes:
                metadata = getattr(node.node, 'metadata', {})
                sources.append({
                    "title": metadata.get('title', 'Unknown'),
                    "speaker": metadata.get('speaker', 'Unknown'),
                    "timestamp": metadata.get('timestamp', 'Unknown')
                })
            
            logger.info(
                "query_completed",
                sources_count=len(sources),
                meeting_id=meeting_id
            )
            
            return QueryResponse(
                answer=str(response),
                sources=[s['title'] for s in sources],
                action_items=[]  # TODO: Implement structured action item extraction
            )
        
        except Exception as e:
            logger.error("query_execution_failed", error=str(e))
            raise QueryError(
                f"Query execution failed: {e}",
                context={"query": query_str, "meeting_id": meeting_id}
            )
