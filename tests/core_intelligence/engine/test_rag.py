import pytest
from unittest.mock import MagicMock, patch
from core_intelligence.engine.rag import RAGEngine
from core_intelligence.schemas.models import MeetingTranscript, MeetingMetadata, TranscriptSegment
from datetime import datetime

@pytest.fixture
def mock_providers():
    with patch('core_intelligence.engine.rag.get_di_container') as mock_di:
        container = MagicMock()
        embed = MagicMock()
        llm = MagicMock()
        
        embed.name = "MockEmbed"
        embed.get_embedding_dimension.return_value = 1536
        embed._embedding = MagicMock()
        
        llm.name = "MockLLM"
        llm._llm = MagicMock()
        
        container.get_embedding_provider.return_value = embed
        container.get_llm_provider.return_value = llm
        mock_di.return_value = container
        
        # Patch GuardrailEngine and SemanticChunker to avoid side effects during init
        with patch('core_intelligence.engine.rag.SemanticChunker') as mock_chunk:
            with patch('core_intelligence.engine.rag.GuardrailEngine') as mock_guard:
                yield embed, llm, mock_chunk, mock_guard

@pytest.fixture
def mock_lancedb():
    with patch('lancedb.connect') as mock_connect:
        db = MagicMock()
        db.table_names.return_value = []
        mock_connect.return_value = db
        yield db

@patch('core_intelligence.engine.rag.LanceDBVectorStore')
@patch('core_intelligence.engine.rag.StorageContext')
def test_rag_engine_initialization(mock_storage, mock_vec_store, mock_providers, mock_lancedb):
    embed, llm, _, _ = mock_providers
    engine = RAGEngine(uri="data/test_db")
    assert engine.uri == "data/test_db"
    assert engine.embedding_provider.name == "MockEmbed"

@patch('core_intelligence.engine.rag.VectorStoreIndex')
@patch('core_intelligence.engine.rag.LanceDBVectorStore')
@patch('core_intelligence.engine.rag.StorageContext')
def test_index_transcript(mock_storage, mock_vec_store, mock_index, mock_providers, mock_lancedb):
    embed, llm, _, _ = mock_providers
    engine = RAGEngine(uri="data/test_db")
    
    transcript = MeetingTranscript(
        metadata=MeetingMetadata(
            meeting_id="test-id",
            title="Test",
            date=datetime.now()
        ),
        segments=[
            TranscriptSegment(speaker="A", content="Hello", timestamp="00:01")
        ]
    )
    
    meeting_id = engine.index_transcript(transcript)
    assert meeting_id == "test-id"
    mock_index.from_documents.assert_called_once()
