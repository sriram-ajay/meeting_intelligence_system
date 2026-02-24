"""
Dependency injection container for managing application dependencies.

Centralises all provider and adapter creation. Every service and adapter
is a lazy singleton — created on first access, then reused for the
lifetime of the process. This ensures:
    - One boto3 client per adapter (avoids reconnecting on every request)
    - One embedding/LLM provider per process
    - Services get their dependencies injected at construction, not
      imported at module level, so tests can swap them out easily

Usage:
    container = get_di_container()
    query_svc = container.get_query_service()   # creates all deps if needed
    result = query_svc.query("What was decided?")

V2 additions: adapter singletons (S3, DynamoDB, S3Vectors) and IngestionService.
"""

from typing import Optional
import logging

from core_intelligence.providers import EmbeddingProviderBase, LLMProviderBase
from core_intelligence.providers.factory import EmbeddingProviderFactory, LLMProviderFactory
from shared_utils.config_loader import get_settings
from shared_utils.constants import LogScope


logger = logging.getLogger(__name__)


class DIContainer:
    """Singleton dependency injection container."""
    
    _instance: Optional['DIContainer'] = None
    _embedding_provider: Optional[EmbeddingProviderBase] = None
    _llm_provider: Optional[LLMProviderBase] = None

    # v2 adapter singletons
    _artifact_store: Optional[object] = None
    _metadata_store: Optional[object] = None
    _vector_store: Optional[object] = None
    _ingestion_service: Optional[object] = None
    _query_service: Optional[object] = None
    _guardrail_service: Optional[object] = None
    _eval_store: Optional[object] = None
    _evaluation_service: Optional[object] = None

    # v3 LangGraph singletons
    _ingestion_graph: Optional[object] = None
    _query_graph: Optional[object] = None
    _query_cache: Optional[object] = None
    _chat_history: Optional[object] = None
    _user_memory: Optional[object] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def reset(self):
        """Reset container (useful for testing)."""
        self._embedding_provider = None
        self._llm_provider = None
        self._artifact_store = None
        self._metadata_store = None
        self._vector_store = None
        self._ingestion_service = None
        self._query_service = None
        self._guardrail_service = None
        self._eval_store = None
        self._evaluation_service = None
        self._ingestion_graph = None
        self._query_graph = None
        self._query_cache = None
        self._chat_history = None
        self._user_memory = None
    
    def get_embedding_provider(self) -> EmbeddingProviderBase:
        """Get or create embedding provider (lazy singleton).
        
        Returns:
            Initialized embedding provider.
        
        Raises:
            RuntimeError: If provider initialization fails.
        """
        if self._embedding_provider is None:
            logger.info(
                "Initializing embedding provider",
                extra={"scope": LogScope.CONFIG}
            )
            try:
                self._embedding_provider = EmbeddingProviderFactory.create()
            except Exception as e:
                logger.error(
                    "Failed to initialize embedding provider",
                    extra={"scope": LogScope.CONFIG, "error": str(e)}
                )
                raise RuntimeError(f"Embedding provider initialization failed: {e}") from e
        
        return self._embedding_provider
    
    def get_llm_provider(self) -> LLMProviderBase:
        """Get or create LLM provider (lazy singleton).
        
        Returns:
            Initialized LLM provider.
        
        Raises:
            RuntimeError: If provider initialization fails.
        """
        if self._llm_provider is None:
            logger.info(
                "Initializing LLM provider",
                extra={"scope": LogScope.CONFIG}
            )
            try:
                self._llm_provider = LLMProviderFactory.create()
            except Exception as e:
                logger.error(
                    "Failed to initialize LLM provider",
                    extra={"scope": LogScope.CONFIG, "error": str(e)}
                )
                raise RuntimeError(f"LLM provider initialization failed: {e}") from e
        
        return self._llm_provider
    
    def validate_all_providers(self) -> bool:
        """Validate that all providers are available.
        
        Returns:
            True if all providers are healthy.
        
        Raises:
            RuntimeError: If any provider is unavailable.
        """
        logger.info(
            "Validating providers",
            extra={"scope": LogScope.CONFIG}
        )
        
        try:
            embedding_ok = self.get_embedding_provider().is_available()
            llm_ok = self.get_llm_provider().is_available()
            
            # Build detailed error message for any failures
            failures = []
            if not embedding_ok:
                failures.append("Embedding provider is not available")
            if not llm_ok:
                failures.append("LLM provider is not available")
            
            if failures:
                error_msg = "; ".join(failures)
                raise RuntimeError(f"Provider validation failed: {error_msg}")
            
            logger.info(
                "All providers validated",
                extra={"scope": LogScope.CONFIG, "embedding": embedding_ok, "llm": llm_ok}
            )
            return True
        
        except Exception as e:
            logger.error(
                "Provider validation failed",
                extra={"scope": LogScope.CONFIG, "error": str(e)}
            )
            raise

    # ------------------------------------------------------------------
    # V2 adapter accessors
    # ------------------------------------------------------------------

    def get_artifact_store(self):
        """Get or create S3ArtifactStoreAdapter (lazy singleton)."""
        if self._artifact_store is None:
            from adapters.s3_artifact_store import S3ArtifactStoreAdapter

            settings = get_settings()
            self._artifact_store = S3ArtifactStoreAdapter(
                raw_bucket=settings.s3_raw_bucket,
                raw_prefix=settings.s3_raw_prefix,
                derived_bucket=settings.s3_derived_bucket,
                derived_prefix=settings.s3_derived_prefix,
                region=settings.aws_region,
                endpoint_url=settings.aws_endpoint_url,
            )
            logger.info("Initialized S3ArtifactStoreAdapter")
        return self._artifact_store

    def get_metadata_store(self):
        """Get or create DynamoMetadataStoreAdapter (lazy singleton)."""
        if self._metadata_store is None:
            from adapters.dynamo_metadata_store import DynamoMetadataStoreAdapter

            settings = get_settings()
            self._metadata_store = DynamoMetadataStoreAdapter(
                table_name=settings.dynamodb_table_name,
                region=settings.aws_region,
                endpoint_url=settings.aws_endpoint_url,
            )
            logger.info("Initialized DynamoMetadataStoreAdapter")
        return self._metadata_store

    def get_vector_store(self):
        """Get or create vector store adapter (lazy singleton).

        Environment-aware: checks S3_VECTORS_BUCKET from config.
        - Empty string → local dev or CI → InMemoryVectorStoreAdapter
          (brute-force cosine search, no persistence across restarts)
        - Non-empty → production → S3VectorsVectorStoreAdapter
          (real ANN search against AWS S3 Vectors service)

        This is how the ports-and-adapters pattern pays off: the services
        never know which adapter they're talking to.
        """
        if self._vector_store is None:
            settings = get_settings()
            if not settings.s3_vectors_bucket:
                from adapters.in_memory_vector_store import InMemoryVectorStoreAdapter
                self._vector_store = InMemoryVectorStoreAdapter()
                logger.info("Initialized InMemoryVectorStoreAdapter (local dev)")
            else:
                from adapters.s3vectors_vector_store import S3VectorsVectorStoreAdapter
                self._vector_store = S3VectorsVectorStoreAdapter(
                    vector_bucket_name=settings.s3_vectors_bucket,
                    index_name=settings.s3_vectors_index_name,
                    region=settings.aws_region,
                    endpoint_url=settings.aws_endpoint_url,
                )
                logger.info("Initialized S3VectorsVectorStoreAdapter")
        return self._vector_store

    def get_ingestion_service(self):
        """Get or create IngestionService (lazy singleton)."""
        if self._ingestion_service is None:
            from services.ingestion_service import IngestionService

            self._ingestion_service = IngestionService(
                artifact_store=self.get_artifact_store(),
                metadata_store=self.get_metadata_store(),
                vector_store=self.get_vector_store(),
                embedding_provider=self.get_embedding_provider(),
            )
            logger.info("Initialized IngestionService")
        return self._ingestion_service

    def get_guardrail_service(self):
        """Get or create GuardrailService (lazy singleton)."""
        if self._guardrail_service is None:
            from services.guardrail_service import GuardrailService

            self._guardrail_service = GuardrailService(
                llm_provider=self.get_llm_provider(),
            )
            logger.info("Initialized GuardrailService")
        return self._guardrail_service

    def get_query_service(self):
        """Get or create QueryService (lazy singleton)."""
        if self._query_service is None:
            from services.query_service import QueryService

            self._query_service = QueryService(
                vector_store=self.get_vector_store(),
                embedding_provider=self.get_embedding_provider(),
                llm_provider=self.get_llm_provider(),
                artifact_store=self.get_artifact_store(),
                guardrails=self.get_guardrail_service(),
            )
            logger.info("Initialized QueryService")
        return self._query_service


    def get_eval_store(self):
        """Get or create JsonEvalStoreAdapter (lazy singleton)."""
        if self._eval_store is None:
            from adapters.json_eval_store import JsonEvalStoreAdapter

            self._eval_store = JsonEvalStoreAdapter()
            logger.info("Initialized JsonEvalStoreAdapter")
        return self._eval_store

    def get_evaluation_service(self):
        """Get or create EvaluationService (lazy singleton)."""
        if self._evaluation_service is None:
            from services.evaluation_service import EvaluationService

            self._evaluation_service = EvaluationService(
                eval_store=self.get_eval_store(),
            )
            logger.info("Initialized EvaluationService")
        return self._evaluation_service


    # ------------------------------------------------------------------
    # V3 LangGraph accessors
    # ------------------------------------------------------------------

    def get_query_cache(self):
        """Get or create DynamoQueryCacheAdapter (lazy singleton).

        If the DYNAMODB_QUERY_CACHE_TABLE env var / setting is empty,
        returns None (cache disabled — graph nodes handle None gracefully).
        """
        if self._query_cache is None:
            settings = get_settings()
            table_name = getattr(settings, "dynamodb_query_cache_table", "")
            if not table_name:
                logger.info("Query cache disabled (no table configured)")
                return None
            from adapters.dynamo_query_cache import DynamoQueryCacheAdapter

            self._query_cache = DynamoQueryCacheAdapter(
                table_name=table_name,
                region=settings.aws_region,
                endpoint_url=settings.aws_endpoint_url,
            )
            logger.info("Initialized DynamoQueryCacheAdapter")
        return self._query_cache

    def get_chat_history(self):
        """Get or create DynamoChatHistoryAdapter (lazy singleton).

        If DYNAMODB_CHAT_HISTORY_TABLE is empty, returns None.
        """
        if self._chat_history is None:
            settings = get_settings()
            table_name = getattr(settings, "dynamodb_chat_history_table", "")
            if not table_name:
                logger.info("Chat history disabled (no table configured)")
                return None
            from adapters.dynamo_chat_history import DynamoChatHistoryAdapter

            self._chat_history = DynamoChatHistoryAdapter(
                table_name=table_name,
                region=settings.aws_region,
                endpoint_url=settings.aws_endpoint_url,
            )
            logger.info("Initialized DynamoChatHistoryAdapter")
        return self._chat_history

    def get_user_memory(self):
        """Get or create DynamoUserMemoryAdapter (lazy singleton).

        If DYNAMODB_USER_MEMORY_TABLE is empty, returns None.
        """
        if self._user_memory is None:
            settings = get_settings()
            table_name = getattr(settings, "dynamodb_user_memory_table", "")
            if not table_name:
                logger.info("User memory disabled (no table configured)")
                return None
            from adapters.dynamo_user_memory import DynamoUserMemoryAdapter

            self._user_memory = DynamoUserMemoryAdapter(
                table_name=table_name,
                region=settings.aws_region,
                endpoint_url=settings.aws_endpoint_url,
            )
            logger.info("Initialized DynamoUserMemoryAdapter")
        return self._user_memory

    def get_ingestion_graph(self):
        """Get or create the LangGraph ingestion pipeline (lazy singleton)."""
        if self._ingestion_graph is None:
            from graphs.ingestion_graph import build_ingestion_graph

            self._ingestion_graph = build_ingestion_graph(
                artifact_store=self.get_artifact_store(),
                metadata_store=self.get_metadata_store(),
                vector_store=self.get_vector_store(),
                embedding_provider=self.get_embedding_provider(),
            )
            logger.info("Initialized LangGraph ingestion pipeline")
        return self._ingestion_graph

    def get_query_graph(self):
        """Get or create the LangGraph query pipeline (lazy singleton)."""
        if self._query_graph is None:
            from graphs.query_graph import build_query_graph

            self._query_graph = build_query_graph(
                vector_store=self.get_vector_store(),
                embedding_provider=self.get_embedding_provider(),
                llm_provider=self.get_llm_provider(),
                artifact_store=self.get_artifact_store(),
                guardrails=self.get_guardrail_service(),
                query_cache=self.get_query_cache(),
                chat_history=self.get_chat_history(),
            )
            logger.info("Initialized LangGraph query pipeline")
        return self._query_graph


# Global singleton instance
_container = DIContainer()


def get_di_container() -> DIContainer:
    """Get global DI container instance."""
    return _container
