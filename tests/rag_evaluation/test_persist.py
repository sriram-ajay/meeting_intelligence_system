from llama_index.core import Document, VectorStoreIndex, StorageContext, Settings
from llama_index.vector_stores.lancedb import LanceDBVectorStore
from shared_utils.di_container import get_di_container
import lancedb

# Setup
uri = 'data/lancedb'
table_name = 'meeting_segments'

di = get_di_container()
Settings.embed_model = di.get_embedding_provider()._embedding
Settings.llm = di.get_llm_provider()._llm

# Create vector store
vector_store = LanceDBVectorStore(uri=uri, table_name=table_name, mode='append', flat_metadata=True)
storage_context = StorageContext.from_defaults(vector_store=vector_store)

# Check initial count
db = lancedb.connect(uri)
tbl = db.open_table(table_name)
initial_count = len(tbl.search().to_list())
print(f"Initial document count: {initial_count}")

# Create a test document
test_doc = Document(
    text="This is a test document for reproduction.",
    metadata={"meeting_id": "test-id-12345", "title": "test_doc.txt"}
)

print(f"\nCreating index from document...")
index = VectorStoreIndex.from_documents([test_doc], storage_context=storage_context)

# Check count IMMEDIATELY
tbl_after = db.open_table(table_name)
after_count = len(tbl_after.search().to_list())
print(f"After from_documents: {after_count}")

# Try querying
print(f"\nTesting if new doc is queryable...")
query_engine = index.as_query_engine()
response = query_engine.query("test document")
print(f"Query response: {str(response)[:100]}")
print(f"Source nodes: {len(response.source_nodes) if hasattr(response, 'source_nodes') else 0}")

# Check count again
tbl_final = db.open_table(table_name)
final_count = len(tbl_final.search().to_list())
print(f"\nFinal document count: {final_count}")
print(f"Net change: +{final_count - initial_count}")
