import pytest

def pytest_configure(config):
    config.addinivalue_line("markers", "integration: mark test as integration test")
    config.addinivalue_line("markers", "rag_eval: mark test as RAG evaluation test")
