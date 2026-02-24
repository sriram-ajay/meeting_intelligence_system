"""
Query graph node functions.

Each function takes the full QueryState, performs one pipeline step by
delegating to existing services / ports, and returns a partial state dict.

The query graph supports:
    - Input safety validation (guardrails)
    - Embedding the question
    - Semantic cache lookup (Phase 9 — stubbed as cache miss for now)
    - Vector search
    - Chunk map loading for citations
    - LLM answer generation
    - Grounding verification
    - Citation assembly
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from domain.models import ChunkMapEntry, CitedAnswer, Citation
from graphs.state import QueryState
from shared_utils.logging_utils import get_scoped_logger
from shared_utils.constants import LogScope

logger = get_scoped_logger(LogScope.QUERY_SERVICE)


# ---------------------------------------------------------------------------
# Regex pre-filter for obvious-safe queries (Phase 3 optimisation)
# ---------------------------------------------------------------------------

_UNSAFE_PATTERNS = re.compile(
    r"ignore\s+(previous|above|all)\s+(instructions|prompts)"
    r"|jailbreak"
    r"|pretend\s+you\s+are"
    r"|act\s+as\s+if\s+you\s+have\s+no\s+restrictions"
    r"|bypass\s+(safety|filter|guardrail)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------


def validate_input(state: QueryState, *, guardrails=None) -> Dict[str, Any]:
    """Check if the user query is safe.

    Uses a fast regex pre-filter first. Only falls back to the LLM-based
    guardrail if the regex matches (saves ~1,000ms and ~80 tokens for
    the 90%+ of queries that are obviously safe).
    """
    question = state["question"]

    # Fast regex check — skip expensive LLM call for obvious-safe queries
    if _UNSAFE_PATTERNS.search(question):
        # Regex flagged it — confirm with LLM guardrail if available
        if guardrails is not None:
            is_safe = guardrails.validate_input(question)
            return {"input_safe": is_safe}
        return {"input_safe": False}

    # No regex match → safe (skip LLM call entirely)
    return {"input_safe": True}


def reject_unsafe(state: QueryState) -> Dict[str, Any]:
    """Return a safety rejection response."""
    return {
        "cited_answer": CitedAnswer(
            answer="I'm sorry, but I cannot process that query for safety or professional reasons.",
            citations=[],
            retrieved_context=[],
            meeting_ids=[],
        ),
    }


def embed_question(state: QueryState, *, embedding_provider) -> Dict[str, Any]:
    """Embed the user question for vector search."""
    query_embedding = embedding_provider.embed_text(state["question"])
    return {"query_embedding": query_embedding}


def check_cache(state: QueryState, *, query_cache=None) -> Dict[str, Any]:
    """Check semantic query cache for a similar previous answer.

    Phase 9 will implement the full QueryCachePort adapter.
    For now, always returns cache miss.
    """
    if query_cache is not None:
        cached = query_cache.search_similar(
            query_embedding=state["query_embedding"],
            meeting_ids=state.get("meeting_ids"),
        )
        if cached is not None:
            logger.info("cache_hit", question_len=len(state["question"]))
            return {"cache_hit": cached.cited_answer, "cited_answer": cached.cited_answer}

    return {"cache_hit": None}


def return_cached(state: QueryState) -> Dict[str, Any]:
    """Short-circuit: return the cached answer directly."""
    return {"cited_answer": state["cache_hit"]}


def search_vectors(state: QueryState, *, vector_store, top_k: int = 10) -> Dict[str, Any]:
    """Search vector store for relevant chunks."""
    results = vector_store.search(
        embedding=state["query_embedding"],
        top_k=top_k,
        meeting_ids=state.get("meeting_ids"),
    )
    hit_meeting_ids = sorted({r.meeting_id for r in results}) if results else []
    context_texts = [r.text for r in results]

    logger.info("vector_search_complete", results=len(results))
    return {
        "search_results": results,
        "hit_meeting_ids": hit_meeting_ids,
        "context_texts": context_texts,
    }


def return_no_results(state: QueryState) -> Dict[str, Any]:
    """Return a no-results response."""
    return {
        "cited_answer": CitedAnswer(
            answer="I couldn't find any relevant sections in the transcripts to answer your question.",
            citations=[],
            retrieved_context=[],
            meeting_ids=[],
        ),
    }


def load_chunk_maps(state: QueryState, *, artifact_store) -> Dict[str, Any]:
    """Download chunk_map.json for each meeting and build a lookup dict."""
    index: Dict[str, ChunkMapEntry] = {}
    for mid in state["hit_meeting_ids"]:
        try:
            raw = artifact_store.download_derived(mid, "chunk_map.json")
            entries = json.loads(raw)
            for entry_dict in entries:
                entry = ChunkMapEntry(**entry_dict)
                index[entry.chunk_id] = entry
        except Exception:
            logger.warning("chunk_map_load_failed", meeting_id=mid)
    return {"chunk_map_index": index}


def generate_answer(state: QueryState, *, llm_provider) -> Dict[str, Any]:
    """Call LLM with grounded QA prompt and capture token usage.

    Uses the centralised ``QA_PROMPT`` template and the underlying
    LangChain chat model directly to get the ``AIMessage`` response
    including ``usage_metadata`` for accurate token tracking.
    """
    from core_intelligence.prompts import QA_PROMPT

    context_block = "\n---\n".join(state["context_texts"])

    # Use chat_model directly to access AIMessage with usage_metadata
    chat_model = getattr(llm_provider, "chat_model", None)
    if chat_model is not None:
        chain = QA_PROMPT | chat_model
        response = chain.invoke({
            "context": context_block,
            "question": state["question"],
        })
        answer_text = response.content

        # Extract token usage from response metadata
        usage = getattr(response, "usage_metadata", None) or {}
        prompt_tokens = usage.get("input_tokens", 0)
        completion_tokens = usage.get("output_tokens", 0)
        total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)

        # Cost estimation (GPT-4o-mini pricing: $0.15/1M input, $0.60/1M output)
        estimated_cost = (prompt_tokens * 0.15 + completion_tokens * 0.60) / 1_000_000
    else:
        # Fallback to port interface
        answer_text = llm_provider.generate(
            state["question"],
            context="\n".join(state["context_texts"]),
        )
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        estimated_cost = 0.0

    logger.info(
        "answer_generated",
        answer_len=len(answer_text),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )
    return {
        "raw_answer": answer_text,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "estimated_cost_usd": estimated_cost,
    }


def verify_grounding(state: QueryState, *, guardrails=None) -> Dict[str, Any]:
    """Verify the LLM answer is grounded in context."""
    answer = state["raw_answer"]
    if guardrails is not None:
        is_grounded, safe_answer = guardrails.verify_grounding(
            answer, state["context_texts"]
        )
        if not is_grounded:
            logger.warning("grounding_override", original_len=len(answer))
            return {"raw_answer": safe_answer, "is_grounded": False}
    return {"is_grounded": True}


def build_citations(state: QueryState) -> Dict[str, Any]:
    """Map vector search results to human-readable citations and build CitedAnswer."""
    chunk_map_index = state.get("chunk_map_index", {})
    citations: List[Citation] = []

    for r in state["search_results"]:
        entry = chunk_map_index.get(r.chunk_id)
        if entry is not None:
            citations.append(
                Citation(
                    chunk_id=r.chunk_id,
                    meeting_id=r.meeting_id,
                    speaker=entry.speaker,
                    timestamp_start=entry.timestamp_start,
                    timestamp_end=entry.timestamp_end,
                    snippet=entry.snippet,
                )
            )
        else:
            citations.append(
                Citation(
                    chunk_id=r.chunk_id,
                    meeting_id=r.meeting_id,
                    speaker=r.metadata.get("speaker", "Unknown"),
                    timestamp_start="",
                    timestamp_end="",
                    snippet=r.text[:200],
                )
            )

    cited_answer = CitedAnswer(
        answer=state["raw_answer"],
        citations=citations,
        retrieved_context=state["context_texts"],
        meeting_ids=state["hit_meeting_ids"],
        prompt_tokens=state.get("prompt_tokens", 0),
        completion_tokens=state.get("completion_tokens", 0),
        total_tokens=state.get("total_tokens", 0),
        estimated_cost_usd=state.get("estimated_cost_usd", 0.0),
    )
    return {"cited_answer": cited_answer}


def store_in_cache(state: QueryState, *, query_cache=None) -> Dict[str, Any]:
    """Store the result in the semantic query cache."""
    if query_cache is not None:
        query_cache.store(
            query_text=state["question"],
            query_embedding=state["query_embedding"],
            meeting_ids=state.get("meeting_ids"),
            cited_answer=state["cited_answer"],
        )
        logger.info("cache_stored", question_len=len(state["question"]))
    return {}


# ---------------------------------------------------------------------------
# Chat history nodes (Phase 10)
# ---------------------------------------------------------------------------


def load_chat_history(state: QueryState, *, chat_history=None) -> Dict[str, Any]:
    """Load previous turns for the current session.

    Converts stored turns into LangChain message format for injection
    into the QA prompt via ``MessagesPlaceholder``.
    """
    session_id = state.get("session_id")
    if not session_id or chat_history is None:
        return {"chat_history_messages": []}

    from langchain_core.messages import AIMessage, HumanMessage

    session = chat_history.get_session(session_id)
    if session is None:
        return {"chat_history_messages": []}

    messages = []
    for turn in session.turns:
        messages.append(HumanMessage(content=turn.question))
        messages.append(AIMessage(content=turn.answer))

    logger.info(
        "chat_history_loaded",
        session_id=session_id,
        turns=len(session.turns),
    )
    return {"chat_history_messages": messages}


def save_chat_turn(state: QueryState, *, chat_history=None) -> Dict[str, Any]:
    """Persist the current Q/A exchange to chat history."""
    session_id = state.get("session_id")
    if not session_id or chat_history is None:
        return {}

    import uuid
    from datetime import datetime, timezone
    from domain.models import ChatTurn

    cited = state.get("cited_answer")
    answer_text = cited.answer if cited else state.get("raw_answer", "")

    turn = ChatTurn(
        turn_id=str(uuid.uuid4()),
        question=state["question"],
        answer=answer_text,
        meeting_ids=state.get("hit_meeting_ids", []),
        timestamp=datetime.now(timezone.utc).isoformat(),
        prompt_tokens=state.get("prompt_tokens", 0),
        completion_tokens=state.get("completion_tokens", 0),
    )

    chat_history.save_turn(
        session_id=session_id,
        turn=turn,
        user_id=state.get("user_id", ""),
    )
    logger.info("chat_turn_saved", session_id=session_id)
    return {}
