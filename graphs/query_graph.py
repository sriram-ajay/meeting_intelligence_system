"""
Query StateGraph — orchestrates the RAG query pipeline as a LangGraph.

Build via ``build_query_graph(...)`` passing concrete adapters / providers.
The returned ``CompiledGraph`` can be invoked with a ``QueryState`` dict.

Features:
    - Regex pre-filter for input safety (skips LLM call for obvious-safe queries)
    - Semantic query cache lookup (Phase 9 — returns cache miss until implemented)
    - Conditional edges for safety rejection, no-results, and cache hit short-circuit
    - Grounding verification with structured output
    - Citation assembly from chunk maps

Usage:
    container = get_di_container()
    graph = build_query_graph(
        vector_store=container.get_vector_store(),
        embedding_provider=container.get_embedding_provider(),
        llm_provider=container.get_llm_provider(),
        artifact_store=container.get_artifact_store(),
        guardrails=container.get_guardrail_service(),
    )
    result = graph.invoke({"question": "What were the action items?"})
    cited_answer = result["cited_answer"]
"""

from __future__ import annotations

from functools import partial
from typing import Any

from langgraph.graph import END, StateGraph

from graphs.state import QueryState
from graphs.nodes.query_nodes import (
    build_citations,
    check_cache,
    embed_question,
    generate_answer,
    load_chat_history,
    load_chunk_maps,
    reject_unsafe,
    return_cached,
    return_no_results,
    save_chat_turn,
    search_vectors,
    store_in_cache,
    validate_input,
    verify_grounding,
)


# ---------------------------------------------------------------------------
# Routing functions for conditional edges
# ---------------------------------------------------------------------------


def _route_safety(state: QueryState) -> str:
    """Route based on input safety check."""
    if state.get("input_safe", True):
        return "embed_question"
    return "reject_unsafe"


def _route_cache(state: QueryState) -> str:
    """Route based on cache hit/miss."""
    if state.get("cache_hit") is not None:
        return "return_cached"
    return "search_vectors"


def _route_results(state: QueryState) -> str:
    """Route based on whether vector search found results."""
    if not state.get("search_results"):
        return "return_no_results"
    return "load_chunk_maps"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_query_graph(
    *,
    vector_store,
    embedding_provider,
    llm_provider,
    artifact_store,
    guardrails=None,
    query_cache=None,
    chat_history=None,
    top_k: int = 10,
) -> Any:
    """Build and compile the query StateGraph.

    Args:
        vector_store: VectorStorePort implementation.
        embedding_provider: EmbeddingProviderPort implementation.
        llm_provider: LLMProviderPort implementation.
        artifact_store: ArtifactStorePort implementation.
        guardrails: Optional GuardrailPort implementation.
        query_cache: Optional QueryCachePort implementation (Phase 9).
        chat_history: Optional ChatHistoryPort implementation (Phase 10).
        top_k: Number of vector search results to retrieve.

    Returns:
        Compiled LangGraph ready for ``.invoke(QueryState)``.
    """
    graph = StateGraph(QueryState)

    # --- Bind dependencies to node functions ---
    graph.add_node(
        "validate_input",
        partial(validate_input, guardrails=guardrails),
    )
    graph.add_node("reject_unsafe", reject_unsafe)
    graph.add_node(
        "embed_question",
        partial(embed_question, embedding_provider=embedding_provider),
    )
    graph.add_node(
        "check_cache",
        partial(check_cache, query_cache=query_cache),
    )
    graph.add_node("return_cached", return_cached)
    graph.add_node(
        "search_vectors",
        partial(search_vectors, vector_store=vector_store, top_k=top_k),
    )
    graph.add_node("return_no_results", return_no_results)
    graph.add_node(
        "load_chunk_maps",
        partial(load_chunk_maps, artifact_store=artifact_store),
    )
    graph.add_node(
        "generate_answer",
        partial(generate_answer, llm_provider=llm_provider),
    )
    graph.add_node(
        "verify_grounding",
        partial(verify_grounding, guardrails=guardrails),
    )
    graph.add_node("build_citations", build_citations)
    graph.add_node(
        "store_in_cache",
        partial(store_in_cache, query_cache=query_cache),
    )
    graph.add_node(
        "load_chat_history",
        partial(load_chat_history, chat_history=chat_history),
    )
    graph.add_node(
        "save_chat_turn",
        partial(save_chat_turn, chat_history=chat_history),
    )

    # --- Entry ---
    graph.set_entry_point("validate_input")

    # --- Conditional: safe → embed, unsafe → reject ---
    graph.add_conditional_edges("validate_input", _route_safety)

    # --- Reject ends the graph ---
    graph.add_edge("reject_unsafe", END)

    # --- Embed → cache check ---
    graph.add_edge("embed_question", "check_cache")

    # --- Conditional: cache hit → return, miss → search ---
    graph.add_conditional_edges("check_cache", _route_cache)

    # --- Cache hit short-circuit ---
    graph.add_edge("return_cached", END)

    # --- Conditional: results → load maps, empty → no results ---
    graph.add_conditional_edges("search_vectors", _route_results)

    # --- No results ends the graph ---
    graph.add_edge("return_no_results", END)

    # --- Main pipeline: load maps → generate → ground → cite → cache → history → end ---
    graph.add_edge("load_chunk_maps", "load_chat_history")
    graph.add_edge("load_chat_history", "generate_answer")
    graph.add_edge("generate_answer", "verify_grounding")
    graph.add_edge("verify_grounding", "build_citations")
    graph.add_edge("build_citations", "store_in_cache")
    graph.add_edge("store_in_cache", "save_chat_turn")
    graph.add_edge("save_chat_turn", END)

    return graph.compile()
