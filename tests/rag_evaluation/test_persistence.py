from llama_index.core import VectorStoreIndex, StorageContext, Settings, Document
from llama_index.vector_stores.lancedb import LanceDBVectorStore
from shared_utils.di_container import get_di_container
import lancedb

# Setup
uri = 'data/lancedb'
table_name = 'meeting_segments'

di = get_di_container()
embedding = di.get_embedding_provider()._embedding
llm = di.get_llm_provider()._llm

Settings.embed_model = embedding
Settings.llm = llm

# Check DB before
db_before = lancedb.connect(uri)
tbl_before = db_before.open_table(table_name)
count_before = len(tbl_before.search().to_list())
print(f"Documents BEFORE: {count_before}")

# Create vector store in APPEND mode
vector_store = LanceDBVectorStore(
    uri=uri,
    table_name=table_name,
    mode='append',
    flat_metadata=True
)
storage_context = StorageContext.from_defaults(vector_store=vector_store)

# Create test document
test_doc = Document(
    text="This is a test document to verify persistence.",
    metadata={
        "meeting_id": "test-12345",
        "title": "test.txt",
        "date": "2026-02-06",
        "chunk_type": "test"
    }
)

print("\nCreating index from 1 document...")
index = VectorStoreIndex.from_documents(
    [test_doc],
    storage_context=storage_context
)

# Check DB immediately after
db_after = lancedb.connect(uri)
tbl_after = db_after.open_table(table_name)
count_after = len(tbl_after.search().to_list())
print(f"Documents AFTER: {count_after}")
print(f"Difference: {count_after - count_before}")

if count_after > count_before:
    print("✓ Documents ARE persisted!")
else:
    print("✗ Documents NOT persisted - index is only in memory!")

# Check if we can query the new document
print("\nTrying to query...")
engine = index.as_query_engine()
response = engine.query("test document")
print(f"Query response: {str(response)[:80]}")
