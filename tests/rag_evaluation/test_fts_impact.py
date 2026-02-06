import lancedb
from llama_index.core import VectorStoreIndex, StorageContext, Settings
from llama_index.vector_stores.lancedb import LanceDBVectorStore
from shared_utils.di_container import get_di_container

# Setup
uri = 'data/lancedb'
table_name = 'meeting_segments'

di = get_di_container()
embedding = di.get_embedding_provider()._embedding
llm = di.get_llm_provider()._llm

Settings.embed_model = embedding
Settings.llm = llm

# Connect to DB
db = lancedb.connect(uri)
table = db.open_table(table_name)

# Test 1: Query BEFORE FTS index
print("=" * 50)
print("Test 1: Query BEFORE removing FTS")
print("=" * 50)
vector_store = LanceDBVectorStore(uri=uri, table_name=table_name, mode='append', flat_metadata=True)
index = VectorStoreIndex.from_vector_store(vector_store)
engine = index.as_query_engine()
try:
    response = engine.query("What was discussed?")
    print(f"✓ Query returned {len(response.source_nodes) if hasattr(response, 'source_nodes') else 0} results")
except Exception as e:
    print(f"✗ Error: {e}")

# Check what indices exist
print("\n" + "=" * 50)
print("Current indices on table:")
print("=" * 50)
try:
    indices = table.list_indices()
    for idx in indices:
        print(f"  - {idx}")
except:
    print("  (Could not list indices)")

# Test 2: Try creating FTS index (like the upload endpoint does)
print("\n" + "=" * 50)
print("Test 2: Creating FTS index (replace=True)")
print("=" * 50)
try:
    table.create_fts_index("text", replace=True)
    print("✓ FTS index created")
except Exception as e:
    print(f"⚠️  FTS creation failed: {e}")

# Test 3: Query AFTER FTS index creation
print("\n" + "=" * 50)
print("Test 3: Query AFTER creating FTS")
print("=" * 50)
vector_store2 = LanceDBVectorStore(uri=uri, table_name=table_name, mode='append', flat_metadata=True)
index2 = VectorStoreIndex.from_vector_store(vector_store2)
engine2 = index2.as_query_engine()
try:
    response2 = engine2.query("What was discussed?")
    print(f"✓ Query returned {len(response2.source_nodes) if hasattr(response2, 'source_nodes') else 0} results")
except Exception as e:
    print(f"✗ Error: {e}")
