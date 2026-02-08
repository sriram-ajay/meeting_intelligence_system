"""
Comprehensive tests for shared_utils.di_container.

Tests singleton behaviour, lazy initialisation, reset(), and all v2
adapter accessors.  All external dependencies (providers, adapters,
settings) are mocked — no AWS calls.
"""

from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from shared_utils.di_container import DIContainer, get_di_container


# ---------------------------------------------------------------------------
# Ensure each test gets a fresh singleton
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the DIContainer singleton before and after each test."""
    DIContainer._instance = None
    yield
    DIContainer._instance = None


# ---------------------------------------------------------------------------
# Singleton behaviour
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_same_instance(self) -> None:
        a = DIContainer()
        b = DIContainer()
        assert a is b

    def test_get_di_container_returns_singleton(self) -> None:
        c1 = get_di_container()
        c2 = get_di_container()
        assert c1 is c2
        assert isinstance(c1, DIContainer)


# ---------------------------------------------------------------------------
# reset()
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_clears_providers(self) -> None:
        container = DIContainer()
        container._embedding_provider = "fake"
        container._llm_provider = "fake"
        container._artifact_store = "fake"
        container._metadata_store = "fake"
        container._vector_store = "fake"
        container._ingestion_service = "fake"
        container._query_service = "fake"
        container._guardrail_service = "fake"

        container.reset()

        assert container._embedding_provider is None
        assert container._llm_provider is None
        assert container._artifact_store is None
        assert container._metadata_store is None
        assert container._vector_store is None
        assert container._ingestion_service is None
        assert container._query_service is None
        assert container._guardrail_service is None


# ---------------------------------------------------------------------------
# V1 provider accessors
# ---------------------------------------------------------------------------


class TestEmbeddingProvider:
    @patch(
        "shared_utils.di_container.EmbeddingProviderFactory.create",
        return_value=MagicMock(),
    )
    def test_lazy_creation(self, mock_create) -> None:
        container = DIContainer()
        provider = container.get_embedding_provider()
        assert provider is not None
        mock_create.assert_called_once()

    @patch(
        "shared_utils.di_container.EmbeddingProviderFactory.create",
        return_value=MagicMock(),
    )
    def test_returns_same_instance(self, mock_create) -> None:
        container = DIContainer()
        p1 = container.get_embedding_provider()
        p2 = container.get_embedding_provider()
        assert p1 is p2
        mock_create.assert_called_once()

    @patch(
        "shared_utils.di_container.EmbeddingProviderFactory.create",
        side_effect=RuntimeError("fail"),
    )
    def test_raises_on_factory_error(self, mock_create) -> None:
        container = DIContainer()
        with pytest.raises(RuntimeError, match="Embedding provider initialization failed"):
            container.get_embedding_provider()


class TestLLMProvider:
    @patch(
        "shared_utils.di_container.LLMProviderFactory.create",
        return_value=MagicMock(),
    )
    def test_lazy_creation(self, mock_create) -> None:
        container = DIContainer()
        provider = container.get_llm_provider()
        assert provider is not None
        mock_create.assert_called_once()

    @patch(
        "shared_utils.di_container.LLMProviderFactory.create",
        return_value=MagicMock(),
    )
    def test_returns_same_instance(self, mock_create) -> None:
        container = DIContainer()
        p1 = container.get_llm_provider()
        p2 = container.get_llm_provider()
        assert p1 is p2
        mock_create.assert_called_once()

    @patch(
        "shared_utils.di_container.LLMProviderFactory.create",
        side_effect=RuntimeError("fail"),
    )
    def test_raises_on_factory_error(self, mock_create) -> None:
        container = DIContainer()
        with pytest.raises(RuntimeError, match="LLM provider initialization failed"):
            container.get_llm_provider()


# ---------------------------------------------------------------------------
# validate_all_providers
# ---------------------------------------------------------------------------


class TestValidateAllProviders:
    @patch(
        "shared_utils.di_container.LLMProviderFactory.create",
    )
    @patch(
        "shared_utils.di_container.EmbeddingProviderFactory.create",
    )
    def test_all_healthy(self, mock_embed_create, mock_llm_create) -> None:
        embed_mock = MagicMock()
        embed_mock.is_available.return_value = True
        mock_embed_create.return_value = embed_mock

        llm_mock = MagicMock()
        llm_mock.is_available.return_value = True
        mock_llm_create.return_value = llm_mock

        container = DIContainer()
        assert container.validate_all_providers() is True

    @patch(
        "shared_utils.di_container.LLMProviderFactory.create",
    )
    @patch(
        "shared_utils.di_container.EmbeddingProviderFactory.create",
    )
    def test_embedding_unavailable(self, mock_embed_create, mock_llm_create) -> None:
        embed_mock = MagicMock()
        embed_mock.is_available.return_value = False
        mock_embed_create.return_value = embed_mock

        llm_mock = MagicMock()
        llm_mock.is_available.return_value = True
        mock_llm_create.return_value = llm_mock

        container = DIContainer()
        with pytest.raises(RuntimeError, match="Provider validation failed"):
            container.validate_all_providers()


# ---------------------------------------------------------------------------
# V2 adapter accessors
# ---------------------------------------------------------------------------

_MOCK_SETTINGS_KWARGS = {
    "s3_raw_bucket": "raw-bucket",
    "s3_raw_prefix": "raw",
    "s3_derived_bucket": "derived-bucket",
    "s3_derived_prefix": "derived",
    "aws_region": "eu-west-2",
    "dynamodb_table_name": "TestTable",
    "s3_vectors_bucket": "vec-bucket",
    "s3_vectors_index_name": "vec-index",
}


def _mock_settings():
    """Return a MagicMock that responds to all v2 settings attrs."""
    mock = MagicMock()
    for k, v in _MOCK_SETTINGS_KWARGS.items():
        setattr(mock, k, v)
    return mock


class TestGetArtifactStore:
    @patch("shared_utils.di_container.get_settings")
    @patch("adapters.s3_artifact_store.S3ArtifactStoreAdapter.__init__", return_value=None)
    def test_creates_adapter(self, mock_init, mock_get_settings) -> None:
        mock_get_settings.return_value = _mock_settings()
        container = DIContainer()
        store = container.get_artifact_store()
        assert store is not None
        mock_init.assert_called_once()

    @patch("shared_utils.di_container.get_settings")
    @patch("adapters.s3_artifact_store.S3ArtifactStoreAdapter.__init__", return_value=None)
    def test_lazy_singleton(self, mock_init, mock_get_settings) -> None:
        mock_get_settings.return_value = _mock_settings()
        container = DIContainer()
        s1 = container.get_artifact_store()
        s2 = container.get_artifact_store()
        assert s1 is s2
        mock_init.assert_called_once()


class TestGetMetadataStore:
    @patch("shared_utils.di_container.get_settings")
    @patch("adapters.dynamo_metadata_store.DynamoMetadataStoreAdapter.__init__", return_value=None)
    def test_creates_adapter(self, mock_init, mock_get_settings) -> None:
        mock_get_settings.return_value = _mock_settings()
        container = DIContainer()
        store = container.get_metadata_store()
        assert store is not None
        mock_init.assert_called_once()

    @patch("shared_utils.di_container.get_settings")
    @patch("adapters.dynamo_metadata_store.DynamoMetadataStoreAdapter.__init__", return_value=None)
    def test_lazy_singleton(self, mock_init, mock_get_settings) -> None:
        mock_get_settings.return_value = _mock_settings()
        container = DIContainer()
        s1 = container.get_metadata_store()
        s2 = container.get_metadata_store()
        assert s1 is s2
        mock_init.assert_called_once()


class TestGetVectorStore:
    @patch("shared_utils.di_container.get_settings")
    @patch("adapters.s3vectors_vector_store.S3VectorsVectorStoreAdapter.__init__", return_value=None)
    def test_creates_adapter(self, mock_init, mock_get_settings) -> None:
        mock_get_settings.return_value = _mock_settings()
        container = DIContainer()
        store = container.get_vector_store()
        assert store is not None
        mock_init.assert_called_once()

    @patch("shared_utils.di_container.get_settings")
    @patch("adapters.s3vectors_vector_store.S3VectorsVectorStoreAdapter.__init__", return_value=None)
    def test_lazy_singleton(self, mock_init, mock_get_settings) -> None:
        mock_get_settings.return_value = _mock_settings()
        container = DIContainer()
        s1 = container.get_vector_store()
        s2 = container.get_vector_store()
        assert s1 is s2
        mock_init.assert_called_once()


class TestGetIngestionService:
    @patch("shared_utils.di_container.get_settings")
    @patch("adapters.s3vectors_vector_store.S3VectorsVectorStoreAdapter.__init__", return_value=None)
    @patch("adapters.dynamo_metadata_store.DynamoMetadataStoreAdapter.__init__", return_value=None)
    @patch("adapters.s3_artifact_store.S3ArtifactStoreAdapter.__init__", return_value=None)
    @patch("shared_utils.di_container.EmbeddingProviderFactory.create", return_value=MagicMock())
    @patch("services.ingestion_service.IngestionService.__init__", return_value=None)
    def test_creates_service(
        self,
        mock_svc_init,
        mock_embed,
        mock_s3_init,
        mock_dynamo_init,
        mock_vec_init,
        mock_get_settings,
    ) -> None:
        mock_get_settings.return_value = _mock_settings()
        container = DIContainer()
        svc = container.get_ingestion_service()
        assert svc is not None
        mock_svc_init.assert_called_once()

    @patch("shared_utils.di_container.get_settings")
    @patch("adapters.s3vectors_vector_store.S3VectorsVectorStoreAdapter.__init__", return_value=None)
    @patch("adapters.dynamo_metadata_store.DynamoMetadataStoreAdapter.__init__", return_value=None)
    @patch("adapters.s3_artifact_store.S3ArtifactStoreAdapter.__init__", return_value=None)
    @patch("shared_utils.di_container.EmbeddingProviderFactory.create", return_value=MagicMock())
    @patch("services.ingestion_service.IngestionService.__init__", return_value=None)
    def test_lazy_singleton(
        self,
        mock_svc_init,
        mock_embed,
        mock_s3_init,
        mock_dynamo_init,
        mock_vec_init,
        mock_get_settings,
    ) -> None:
        mock_get_settings.return_value = _mock_settings()
        container = DIContainer()
        s1 = container.get_ingestion_service()
        s2 = container.get_ingestion_service()
        assert s1 is s2
        mock_svc_init.assert_called_once()


class TestGetGuardrailService:
    @patch("shared_utils.di_container.LLMProviderFactory.create", return_value=MagicMock())
    @patch("services.guardrail_service.GuardrailService.__init__", return_value=None)
    def test_creates_service(
        self,
        mock_svc_init,
        mock_llm,
    ) -> None:
        container = DIContainer()
        svc = container.get_guardrail_service()
        assert svc is not None
        mock_svc_init.assert_called_once()

    @patch("shared_utils.di_container.LLMProviderFactory.create", return_value=MagicMock())
    @patch("services.guardrail_service.GuardrailService.__init__", return_value=None)
    def test_lazy_singleton(
        self,
        mock_svc_init,
        mock_llm,
    ) -> None:
        container = DIContainer()
        s1 = container.get_guardrail_service()
        s2 = container.get_guardrail_service()
        assert s1 is s2
        mock_svc_init.assert_called_once()


class TestGetQueryService:
    @patch("shared_utils.di_container.get_settings")
    @patch("adapters.s3vectors_vector_store.S3VectorsVectorStoreAdapter.__init__", return_value=None)
    @patch("adapters.dynamo_metadata_store.DynamoMetadataStoreAdapter.__init__", return_value=None)
    @patch("adapters.s3_artifact_store.S3ArtifactStoreAdapter.__init__", return_value=None)
    @patch("shared_utils.di_container.EmbeddingProviderFactory.create", return_value=MagicMock())
    @patch("shared_utils.di_container.LLMProviderFactory.create", return_value=MagicMock())
    @patch("services.query_service.QueryService.__init__", return_value=None)
    def test_creates_service(
        self,
        mock_svc_init,
        mock_llm,
        mock_embed,
        mock_s3_init,
        mock_dynamo_init,
        mock_vec_init,
        mock_get_settings,
    ) -> None:
        mock_get_settings.return_value = _mock_settings()
        container = DIContainer()
        svc = container.get_query_service()
        assert svc is not None
        mock_svc_init.assert_called_once()

    @patch("shared_utils.di_container.get_settings")
    @patch("adapters.s3vectors_vector_store.S3VectorsVectorStoreAdapter.__init__", return_value=None)
    @patch("adapters.dynamo_metadata_store.DynamoMetadataStoreAdapter.__init__", return_value=None)
    @patch("adapters.s3_artifact_store.S3ArtifactStoreAdapter.__init__", return_value=None)
    @patch("shared_utils.di_container.EmbeddingProviderFactory.create", return_value=MagicMock())
    @patch("shared_utils.di_container.LLMProviderFactory.create", return_value=MagicMock())
    @patch("services.query_service.QueryService.__init__", return_value=None)
    def test_lazy_singleton(
        self,
        mock_svc_init,
        mock_llm,
        mock_embed,
        mock_s3_init,
        mock_dynamo_init,
        mock_vec_init,
        mock_get_settings,
    ) -> None:
        mock_get_settings.return_value = _mock_settings()
        container = DIContainer()
        s1 = container.get_query_service()
        s2 = container.get_query_service()
        assert s1 is s2
        mock_svc_init.assert_called_once()
