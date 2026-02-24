"""
Ingestion StateGraph — orchestrates the full ingest pipeline as a LangGraph.

Build the graph via ``build_ingestion_graph(...)`` passing the concrete
adapters / providers.  The returned ``CompiledGraph`` can be invoked with
an ``IngestionState`` dict.

Usage:
    container = get_di_container()
    graph = build_ingestion_graph(
        artifact_store=container.get_artifact_store(),
        metadata_store=container.get_metadata_store(),
        vector_store=container.get_vector_store(),
        embedding_provider=container.get_embedding_provider(),
    )
    result = graph.invoke({
        "meeting_id": "abc-123",
        "filename": "standup.txt",
        "raw_content": b"...",
    })
    report = result["report"]
"""

from __future__ import annotations

from functools import partial
from typing import Any

from langgraph.graph import END, StateGraph

from graphs.state import IngestionState
from graphs.nodes.ingestion_nodes import (
    chunk_segments,
    create_pending_record,
    embed_chunks,
    handle_failure,
    mark_ready,
    normalize_transcript,
    parse_transcript,
    store_chunk_map,
    store_raw_artifact,
    store_vectors,
)


def build_ingestion_graph(
    *,
    artifact_store,
    metadata_store,
    vector_store,
    embedding_provider,
    chunk_size: int = 512,
    chunk_overlap_tokens: int = 50,
) -> Any:
    """Build and compile the ingestion StateGraph.

    Args:
        artifact_store: ArtifactStorePort implementation.
        metadata_store: MetadataStorePort implementation.
        vector_store: VectorStorePort implementation.
        embedding_provider: EmbeddingProviderPort implementation.
        chunk_size: Max tokens per chunk (tiktoken cl100k_base).
        chunk_overlap_tokens: Token overlap between adjacent chunks.

    Returns:
        Compiled LangGraph ready for ``.invoke(IngestionState)``.
    """
    graph = StateGraph(IngestionState)

    # --- Bind dependencies to node functions via partial ---
    graph.add_node(
        "store_raw_artifact",
        partial(store_raw_artifact, artifact_store=artifact_store),
    )
    graph.add_node(
        "create_pending_record",
        partial(create_pending_record, metadata_store=metadata_store),
    )
    graph.add_node("parse_transcript", parse_transcript)
    graph.add_node(
        "normalize_transcript",
        partial(normalize_transcript, metadata_store=metadata_store),
    )
    graph.add_node(
        "chunk_segments",
        partial(
            chunk_segments,
            chunk_size=chunk_size,
            chunk_overlap_tokens=chunk_overlap_tokens,
        ),
    )
    graph.add_node(
        "embed_chunks",
        partial(embed_chunks, embedding_provider=embedding_provider),
    )
    graph.add_node(
        "store_vectors",
        partial(store_vectors, vector_store=vector_store),
    )
    graph.add_node(
        "store_chunk_map",
        partial(store_chunk_map, artifact_store=artifact_store),
    )
    graph.add_node(
        "mark_ready",
        partial(mark_ready, metadata_store=metadata_store),
    )
    graph.add_node(
        "handle_failure",
        partial(handle_failure, metadata_store=metadata_store),
    )

    # --- Linear pipeline edges ---
    graph.set_entry_point("store_raw_artifact")
    graph.add_edge("store_raw_artifact", "create_pending_record")
    graph.add_edge("create_pending_record", "parse_transcript")
    graph.add_edge("parse_transcript", "normalize_transcript")
    graph.add_edge("normalize_transcript", "chunk_segments")
    graph.add_edge("chunk_segments", "embed_chunks")
    graph.add_edge("embed_chunks", "store_vectors")
    graph.add_edge("store_vectors", "store_chunk_map")
    graph.add_edge("store_chunk_map", "mark_ready")
    graph.add_edge("mark_ready", END)
    graph.add_edge("handle_failure", END)

    return graph.compile()
