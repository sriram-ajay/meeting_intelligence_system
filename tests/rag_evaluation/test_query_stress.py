from llama_index.core import VectorStoreIndex, StorageContext, Settings
from llama_index.vector_stores.lancedb import LanceDBVectorStore
from shared_utils.di_container import get_di_container
import lancedb
import time

# Setup
uri = 'data/lancedb'
table_name = 'meeting_segments'

#  Get providers (simulating what RAGEngine does)
di = get_di_container()
embedding_provider = di.get_embedding_provider()
llm_provider = di.get_llm_provider()

Settings.embed_model = embedding_provider._embedding
Settings.llm = llm_provider._llm

# Create SINGLE vector_store (like RAGEngine does)
vector_store = LanceDBVectorStore(
    uri=uri,
    table_name=table_name,
    mode='append',
    flat_metadata=True
)

# Simulate 15 queries with same vector_store object
print("Simulating 15 consecutive queries on the same vector_store instance...")
for i in range(1, 16):
    try:
        start = time.time()
        index = VectorStoreIndex.from_vector_store(vector_store)
        query_engine = index.as_query_engine()
        response = query_engine.query("What was discussed?")
        elapsed = time.time() - start
        
        src_count = len(response.source_nodes) if hasattr(response, 'source_nodes') else 0
        print(f"Query {i:2d}: {src_count} sources found (took {elapsed:.2f}s) - OK")
    except Exception as e:
        print(f"Query {i:2d}: ✗ ERROR - {type(e).__name__}: {str(e)[:80]}")
