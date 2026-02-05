import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from api_service.src.main import app
from shared_utils.constants import APIEndpoints

client = TestClient(app)

@pytest.fixture
def mock_rag_engine():
    with patch('api_service.src.main.rag_engine') as mock:
        yield mock

def test_health_check():
    response = client.get(APIEndpoints.HEALTH)
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

def test_upload_transcript_validation_failure():
    # Test with wrong file extension
    files = {"file": ("test.exe", b"some content", "text/plain")}
    response = client.post(APIEndpoints.UPLOAD, files=files)
    assert response.status_code == 400
    assert "not allowed" in response.json()["error"]["message"]

@patch('api_service.src.main.rag_engine')
def test_upload_transcript_success(mock_rag):
    mock_rag.index_transcript.return_value = "meeting-123"
    
    files = {"file": ("test.txt", b"Speaker: Hello world", "text/plain")}
    response = client.post(APIEndpoints.UPLOAD, files=files)
    
    assert response.status_code == 200
    assert response.json()["meeting_id"] == "meeting-123"

@patch('api_service.src.main.rag_engine')
def test_query_meeting_success(mock_rag):
    mock_response = MagicMock()
    mock_response.answer = "The answer is 42"
    mock_response.sources = ["doc1"]
    mock_rag.query.return_value = mock_response
    
    query_data = {
        "query": "What is the answer?",
        "meeting_id": "550e8400-e29b-41d4-a716-446655440000"
    }
    
    response = client.post(APIEndpoints.QUERY, json=query_data)
    
    assert response.status_code == 200
    assert response.json()["answer"] == "The answer is 42"
