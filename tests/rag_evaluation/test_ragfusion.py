from llama_index.core import VectorStoreIndex, StorageContext, Settings
from llama_index.vector_stores.lancedb import LanceDBVectorStore
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.postprocessor import LLMRerank
import lancedb
import pytest
from shared_utils.di_container import get_di_container

pytestmark = pytest.mark.rag_eval

def run_test():
    # Setup
    uri = 'data/lancedb'
    table_name = 'meeting_segments'

    # Get DI providers
    di = get_di_container()
    embedding_provider = di.get_embedding_provider()
    llm_provider = di.get_llm_provider()

    # Configure Settings
    Settings.embed_model = embedding_provider._embedding
    Settings.llm = llm_provider._llm

    # Create vector store
    try:
        vector_store = LanceDBVectorStore(
            uri=uri,
            table_name=table_name,
            mode='append',
            flat_metadata=True
        )
    except Exception as e:
        print(f"Skipping: {e}")
        return

    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    index = VectorStoreIndex.from_vector_store(vector_store)

    # Test 1: Basic query engine (should work)
    print("=" * 50)
    print("Test 1: Basic Query Engine")
    print("=" * 50)
    try:
        basic_engine = index.as_query_engine()
        response = basic_engine.query("What was discussed?")
        print(f"✓ Basic query returned {len(response.source_nodes) if hasattr(response, 'source_nodes') else 0} source nodes")
    except Exception as e:
        print(f"✗ Error: {e}")

    # Test 2: QueryFusionRetriever (might fail)
    print("\n" + "=" * 50)
    print("Test 2: RagFusionStrategy (QueryFusionRetriever)")
    print("=" * 50)
    try:
        base_retriever = index.as_retriever(
            similarity_top_k=10,
            vector_store_query_mode="hybrid"
        )
        
        fusion_retriever = QueryFusionRetriever(
            [base_retriever],
            llm=llm_provider._llm,
            similarity_top_k=10,
            num_queries=4,
            mode="reciprocal_rerank",
            use_async=False,
            verbose=False
        )
        
        fusion_engine = RetrieverQueryEngine.from_args(
            retriever=fusion_retriever,
            node_postprocessors=[
                LLMRerank(choice_batch_size=5, top_n=10, llm=llm_provider._llm)
            ]
        )
        
        response = fusion_engine.query("What was discussed?")
        print(f"✓ RagFusion query returned {len(response.source_nodes) if hasattr(response, 'source_nodes') else 0} source nodes")
        print(f"  Response: {str(response)[:100]}")
    except Exception as e:
        print(f"✗ Error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run_test()
