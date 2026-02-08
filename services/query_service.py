"""
QueryService — v2 query pipeline with citation support.

Orchestrates:
    1. Embed the user query via EmbeddingProviderPort.
    2. Search VectorStorePort for relevant chunks (optionally filtered by meeting).
    3. Fetch chunk_map.json from ArtifactStorePort for citation metadata.
    4. Build a grounded prompt and call LLMProviderPort.
    5. Assemble and return a CitedAnswer.

No framework / vendor imports — depends only on ports & domain models.
"""

from __future__ import annotations

import json
import time
from typing import Dict, List, Optional

from domain.models import Citation, CitedAnswer, ChunkMapEntry
from ports.artifact_store import ArtifactStorePort
from ports.guardrails import GuardrailPort
from ports.llm_provider import EmbeddingProviderPort, LLMProviderPort
from ports.vector_store import VectorStorePort
from shared_utils.error_handler import QueryError
from shared_utils.logging_utils import ContextualLogger
from shared_utils.constants import LogScope


logger = ContextualLogger(scope=LogScope.QUERY_SERVICE)

# Default prompt template — kept as a module constant so tests can inspect it.
GROUNDED_QA_PROMPT = (
    "You are a meeting intelligence assistant. Answer the user's question "
    "using ONLY the context passages below. If the answer is not in the "
    "context, say so explicitly.\n\n"
    "CONTEXT:\n{context}\n\n"
    "QUESTION: {question}\n\n"
    "Answer:"
)


class QueryService:
    """Stateless query orchestrator that depends on port interfaces."""

    def __init__(
        self,
        *,
        vector_store: VectorStorePort,
        embedding_provider: EmbeddingProviderPort,
        llm_provider: LLMProviderPort,
        artifact_store: ArtifactStorePort,
        guardrails: Optional[GuardrailPort] = None,
        top_k: int = 10,
    ) -> None:
        self._vectors = vector_store
        self._embedder = embedding_provider
        self._llm = llm_provider
        self._artifacts = artifact_store
        self._guardrails = guardrails
        self._top_k = top_k

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def query(
        self,
        question: str,
        meeting_ids: Optional[List[str]] = None,
    ) -> CitedAnswer:
        """Execute a RAG query and return a cited answer.

        Args:
            question: User's natural-language question.
            meeting_ids: Optional list of meeting IDs to restrict the search.

        Returns:
            CitedAnswer with answer text, citations, and latency.

        Raises:
            QueryError: On any pipeline failure.
        """
        started = time.time()
        logger.info(
            "query_started",
            question_len=len(question),
            meeting_filter=meeting_ids,
        )

        try:
            # 0. Input safety check (when guardrails are enabled)
            if self._guardrails is not None:
                if not self._guardrails.validate_input(question):
                    return CitedAnswer(
                        answer="I'm sorry, but I cannot process that query "
                        "for safety or professional reasons.",
                        citations=[],
                        retrieved_context=[],
                        meeting_ids=[],
                        latency_ms=_elapsed_ms(started),
                    )

            # 1. Embed the question
            query_embedding = self._embedder.embed_text(question)

            # 2. Retrieve relevant chunks from vector store
            results = self._vectors.search(
                embedding=query_embedding,
                top_k=self._top_k,
                meeting_ids=meeting_ids,
            )

            if not results:
                return CitedAnswer(
                    answer="I couldn't find any relevant sections in the "
                    "transcripts to answer your question.",
                    citations=[],
                    retrieved_context=[],
                    meeting_ids=[],
                    latency_ms=_elapsed_ms(started),
                )

            # 3. Collect unique meeting IDs from the results
            hit_meeting_ids = sorted({r.meeting_id for r in results})

            # 4. Load chunk maps for citation metadata
            chunk_map_index = self._load_chunk_maps(hit_meeting_ids)

            # 5. Build context string for the LLM
            context_texts: List[str] = [r.text for r in results]
            context_block = "\n---\n".join(context_texts)

            # 6. Call LLM
            prompt = GROUNDED_QA_PROMPT.format(
                context=context_block,
                question=question,
            )
            answer_text = self._llm.generate(prompt)

            # 7. Grounding verification (when guardrails are enabled)
            if self._guardrails is not None:
                is_grounded, safe_answer = self._guardrails.verify_grounding(
                    answer_text, context_texts
                )
                if not is_grounded:
                    logger.warning(
                        "grounding_override",
                        original_len=len(answer_text),
                    )
                    answer_text = safe_answer

            # 8. Assemble citations
            citations = self._build_citations(results, chunk_map_index)

            latency = _elapsed_ms(started)
            logger.info(
                "query_completed",
                chunks_retrieved=len(results),
                citations=len(citations),
                latency_ms=round(latency, 1),
            )

            return CitedAnswer(
                answer=answer_text,
                citations=citations,
                retrieved_context=context_texts,
                meeting_ids=hit_meeting_ids,
                latency_ms=latency,
            )

        except QueryError:
            raise
        except Exception as exc:
            latency = _elapsed_ms(started)
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.error("query_failed", error=error_msg)
            raise QueryError(
                f"Query failed: {error_msg}",
                context={"question": question, "meeting_ids": meeting_ids},
            ) from exc

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_chunk_maps(
        self, meeting_ids: List[str]
    ) -> Dict[str, ChunkMapEntry]:
        """Download chunk_map.json for each meeting and build a lookup dict.

        Returns a dict keyed by chunk_id → ChunkMapEntry.
        Missing or corrupt chunk maps are silently skipped (degrades
        citations but does not block the answer).
        """
        index: Dict[str, ChunkMapEntry] = {}
        for mid in meeting_ids:
            try:
                raw = self._artifacts.download_derived(mid, "chunk_map.json")
                entries = json.loads(raw)
                for entry_dict in entries:
                    entry = ChunkMapEntry(**entry_dict)
                    index[entry.chunk_id] = entry
            except Exception:
                logger.warning(
                    "chunk_map_load_failed",
                    meeting_id=mid,
                )
        return index

    @staticmethod
    def _build_citations(
        results,
        chunk_map_index: Dict[str, ChunkMapEntry],
    ) -> List[Citation]:
        """Map vector results back to chunk-map metadata for citations."""
        citations: List[Citation] = []
        for r in results:
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
                # Fallback: create a citation from the vector record itself
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
        return citations


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _elapsed_ms(started: float) -> float:
    """Return milliseconds elapsed since *started*."""
    return (time.time() - started) * 1000
