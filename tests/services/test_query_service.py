"""
Tests for services.query_service.QueryService.

Covers:
    - Happy-path query with citations
    - Empty results (no matching chunks)
    - Chunk-map partially missing (fallback citations)
    - Chunk-map fully missing (fallback citations from vector metadata)
    - meeting_ids filter forwarded to vector store
    - LLM receives the correct prompt shape
    - QueryError raised on embedding failure
    - QueryError raised on LLM failure
    - Custom top_k forwarded to vector store
    - Multiple meetings in results
    - Latency is recorded
"""

from __future__ import annotations

import json
from typing import Dict, List
from unittest.mock import MagicMock, call

import pytest

from domain.models import ChunkMapEntry, Citation, CitedAnswer, VectorRecord
from services.query_service import GROUNDED_QA_PROMPT, QueryService
from shared_utils.error_handler import QueryError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_vector_record(
    chunk_id: str = "c-1",
    meeting_id: str = "m-1",
    text: str = "Alice: We need to deploy by Friday.",
    speaker: str = "Alice",
) -> VectorRecord:
    return VectorRecord(
        chunk_id=chunk_id,
        meeting_id=meeting_id,
        embedding=[0.1, 0.2],
        text=text,
        metadata={"speaker": speaker},
    )


def _make_chunk_map_entry(
    chunk_id: str = "c-1",
    meeting_id: str = "m-1",
    speaker: str = "Alice",
) -> ChunkMapEntry:
    return ChunkMapEntry(
        chunk_id=chunk_id,
        meeting_id=meeting_id,
        timestamp_start="00:00:00",
        timestamp_end="00:01:00",
        speaker=speaker,
        snippet="Alice: We need to deploy by Friday.",
        raw_s3_uri="s3://bucket/raw/m-1/file.txt",
    )


def _build_artifact_mock(
    chunk_map_entries: List[ChunkMapEntry] | None = None,
) -> MagicMock:
    """Artifact store that returns a serialised chunk_map.json."""
    mock = MagicMock()
    if chunk_map_entries is not None:
        payload = json.dumps(
            [e.model_dump() for e in chunk_map_entries]
        ).encode()
        mock.download_derived.return_value = payload
    else:
        mock.download_derived.side_effect = FileNotFoundError("not found")
    return mock


def _build_embedder_mock(embedding: List[float] | None = None) -> MagicMock:
    mock = MagicMock()
    mock.embed_text.return_value = embedding or [0.1, 0.2, 0.3]
    return mock


def _build_llm_mock(answer: str = "The team will deploy by Friday.") -> MagicMock:
    mock = MagicMock()
    mock.generate.return_value = answer
    return mock


def _build_vector_mock(
    results: List[VectorRecord] | None = None,
) -> MagicMock:
    mock = MagicMock()
    mock.search.return_value = results if results is not None else []
    return mock


def _make_service(
    *,
    vector: MagicMock | None = None,
    embedder: MagicMock | None = None,
    llm: MagicMock | None = None,
    artifact: MagicMock | None = None,
    guardrails: MagicMock | None = None,
    top_k: int = 10,
) -> QueryService:
    return QueryService(
        vector_store=vector or _build_vector_mock(),
        embedding_provider=embedder or _build_embedder_mock(),
        llm_provider=llm or _build_llm_mock(),
        artifact_store=artifact or _build_artifact_mock(),
        guardrails=guardrails,
        top_k=top_k,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestQueryHappyPath:
    """Full pipeline: embed → search → chunk_map → LLM → CitedAnswer."""

    def test_returns_cited_answer(self) -> None:
        vr = _make_vector_record()
        cme = _make_chunk_map_entry()
        svc = _make_service(
            vector=_build_vector_mock([vr]),
            artifact=_build_artifact_mock([cme]),
            llm=_build_llm_mock("Deploy on Friday."),
        )
        result = svc.query("When do we deploy?")

        assert isinstance(result, CitedAnswer)
        assert result.answer == "Deploy on Friday."
        assert len(result.citations) == 1
        assert result.citations[0].chunk_id == "c-1"
        assert result.citations[0].speaker == "Alice"
        assert result.meeting_ids == ["m-1"]
        assert len(result.retrieved_context) == 1

    def test_latency_is_positive(self) -> None:
        vr = _make_vector_record()
        cme = _make_chunk_map_entry()
        svc = _make_service(
            vector=_build_vector_mock([vr]),
            artifact=_build_artifact_mock([cme]),
        )
        result = svc.query("test?")
        assert result.latency_ms >= 0

    def test_prompt_contains_question_and_context(self) -> None:
        vr = _make_vector_record(text="Carol: Sprint review is Tuesday.")
        cme = _make_chunk_map_entry()
        llm = _build_llm_mock()
        svc = _make_service(
            vector=_build_vector_mock([vr]),
            artifact=_build_artifact_mock([cme]),
            llm=llm,
        )
        svc.query("When is the sprint review?")

        prompt_arg = llm.generate.call_args[0][0]
        assert "Carol: Sprint review is Tuesday." in prompt_arg
        assert "When is the sprint review?" in prompt_arg


class TestEmptyResults:
    """When the vector store has no matching chunks."""

    def test_returns_no_citations(self) -> None:
        svc = _make_service(vector=_build_vector_mock([]))
        result = svc.query("anything")

        assert "couldn't find" in result.answer.lower()
        assert result.citations == []
        assert result.meeting_ids == []

    def test_empty_results_have_latency(self) -> None:
        svc = _make_service(vector=_build_vector_mock([]))
        result = svc.query("anything")
        assert result.latency_ms >= 0


class TestChunkMapMissing:
    """chunk_map.json is unavailable — citations fallback to vector metadata."""

    def test_fallback_citation_from_vector_metadata(self) -> None:
        vr = _make_vector_record(speaker="Bob")
        svc = _make_service(
            vector=_build_vector_mock([vr]),
            artifact=_build_artifact_mock(None),  # raises FileNotFoundError
        )
        result = svc.query("test?")

        assert len(result.citations) == 1
        c = result.citations[0]
        assert c.speaker == "Bob"
        assert c.timestamp_start == ""  # no chunk_map data
        assert c.snippet == vr.text[:200]

    def test_partial_chunk_map_uses_fallback_for_missing(self) -> None:
        vr1 = _make_vector_record(chunk_id="c-1", meeting_id="m-1")
        vr2 = _make_vector_record(chunk_id="c-2", meeting_id="m-1", speaker="Dan")
        cme1 = _make_chunk_map_entry(chunk_id="c-1")
        # c-2 is NOT in the chunk map

        svc = _make_service(
            vector=_build_vector_mock([vr1, vr2]),
            artifact=_build_artifact_mock([cme1]),
        )
        result = svc.query("test?")

        assert len(result.citations) == 2
        # c-1 gets a proper citation
        assert result.citations[0].timestamp_start == "00:00:00"
        # c-2 gets fallback
        assert result.citations[1].speaker == "Dan"
        assert result.citations[1].timestamp_start == ""


class TestMeetingFilter:
    """meeting_ids are forwarded to vector_store.search()."""

    def test_single_meeting_filter(self) -> None:
        vector = _build_vector_mock()
        svc = _make_service(vector=vector)
        svc.query("anything", meeting_ids=["m-42"])

        vector.search.assert_called_once()
        kwargs = vector.search.call_args[1]
        assert kwargs["meeting_ids"] == ["m-42"]

    def test_no_filter_passes_none(self) -> None:
        vector = _build_vector_mock()
        svc = _make_service(vector=vector)
        svc.query("anything")

        kwargs = vector.search.call_args[1]
        assert kwargs["meeting_ids"] is None


class TestCustomTopK:
    """top_k parameter is forwarded to vector_store.search()."""

    def test_custom_top_k(self) -> None:
        vector = _build_vector_mock()
        svc = _make_service(vector=vector, top_k=3)
        svc.query("anything")

        kwargs = vector.search.call_args[1]
        assert kwargs["top_k"] == 3


class TestMultipleMeetings:
    """Results spanning multiple meetings produce sorted meeting_ids."""

    def test_meeting_ids_sorted_and_unique(self) -> None:
        vr1 = _make_vector_record(chunk_id="c-1", meeting_id="m-3")
        vr2 = _make_vector_record(chunk_id="c-2", meeting_id="m-1")
        vr3 = _make_vector_record(chunk_id="c-3", meeting_id="m-3")
        cme1 = _make_chunk_map_entry(chunk_id="c-1", meeting_id="m-3")
        cme2 = _make_chunk_map_entry(chunk_id="c-2", meeting_id="m-1")
        cme3 = _make_chunk_map_entry(chunk_id="c-3", meeting_id="m-3")

        artifact = MagicMock()

        def _download_derived(mid: str, name: str) -> bytes:
            if mid == "m-1":
                return json.dumps([cme2.model_dump()]).encode()
            return json.dumps([cme1.model_dump(), cme3.model_dump()]).encode()

        artifact.download_derived.side_effect = _download_derived

        svc = _make_service(
            vector=_build_vector_mock([vr1, vr2, vr3]),
            artifact=artifact,
        )
        result = svc.query("test?")

        assert result.meeting_ids == ["m-1", "m-3"]
        assert len(result.citations) == 3

    def test_chunk_map_downloaded_per_meeting(self) -> None:
        vr1 = _make_vector_record(chunk_id="c-1", meeting_id="m-1")
        vr2 = _make_vector_record(chunk_id="c-2", meeting_id="m-2")
        artifact = _build_artifact_mock(None)  # raises but we count calls

        svc = _make_service(
            vector=_build_vector_mock([vr1, vr2]),
            artifact=artifact,
        )
        svc.query("test?")

        # Should attempt download for both meetings
        assert artifact.download_derived.call_count == 2
        calls = {c[0][0] for c in artifact.download_derived.call_args_list}
        assert calls == {"m-1", "m-2"}


class TestQueryErrors:
    """Service wraps failures in QueryError."""

    def test_embedding_failure_raises_query_error(self) -> None:
        embedder = MagicMock()
        embedder.embed_text.side_effect = RuntimeError("Bedrock down")
        svc = _make_service(embedder=embedder)

        with pytest.raises(QueryError, match="Query failed"):
            svc.query("test?")

    def test_llm_failure_raises_query_error(self) -> None:
        vr = _make_vector_record()
        llm = MagicMock()
        llm.generate.side_effect = RuntimeError("LLM timeout")
        svc = _make_service(
            vector=_build_vector_mock([vr]),
            artifact=_build_artifact_mock([_make_chunk_map_entry()]),
            llm=llm,
        )

        with pytest.raises(QueryError, match="Query failed"):
            svc.query("test?")

    def test_query_error_passthrough(self) -> None:
        """If a QueryError is raised internally it should not be re-wrapped."""
        embedder = MagicMock()
        embedder.embed_text.side_effect = QueryError("Direct error")
        svc = _make_service(embedder=embedder)

        with pytest.raises(QueryError, match="Direct error"):
            svc.query("test?")


class TestEmbedCalled:
    """Ensure embed_text is called with the question."""

    def test_embed_called_with_question(self) -> None:
        embedder = _build_embedder_mock()
        svc = _make_service(embedder=embedder)
        svc.query("What blockers exist?")

        embedder.embed_text.assert_called_once_with("What blockers exist?")


class TestGroundedPromptShape:
    """The prompt sent to the LLM must match the template."""

    def test_prompt_uses_template(self) -> None:
        vr = _make_vector_record(text="CTX_CHUNK_1")
        llm = _build_llm_mock()
        svc = _make_service(
            vector=_build_vector_mock([vr]),
            artifact=_build_artifact_mock([_make_chunk_map_entry()]),
            llm=llm,
        )
        svc.query("MY_QUESTION")

        prompt = llm.generate.call_args[0][0]
        expected = GROUNDED_QA_PROMPT.format(
            context="CTX_CHUNK_1",
            question="MY_QUESTION",
        )
        assert prompt == expected


# ---------------------------------------------------------------------------
# Guardrail integration
# ---------------------------------------------------------------------------

def _build_guardrail_mock(
    *,
    safe: bool = True,
    grounded: bool = True,
    safe_answer: str = "safe fallback",
) -> MagicMock:
    mock = MagicMock()
    mock.validate_input.return_value = safe
    mock.verify_grounding.return_value = (grounded, safe_answer)
    return mock


class TestGuardrailInputGate:
    """QueryService should reject unsafe queries when guardrails are enabled."""

    def test_unsafe_query_returns_rejection(self) -> None:
        guard = _build_guardrail_mock(safe=False)
        svc = _make_service(guardrails=guard)
        result = svc.query("hack the system")

        assert "cannot process" in result.answer.lower()
        assert result.citations == []
        guard.validate_input.assert_called_once_with("hack the system")

    def test_safe_query_proceeds(self) -> None:
        vr = _make_vector_record()
        cme = _make_chunk_map_entry()
        guard = _build_guardrail_mock(safe=True, grounded=True)
        svc = _make_service(
            vector=_build_vector_mock([vr]),
            artifact=_build_artifact_mock([cme]),
            guardrails=guard,
        )
        result = svc.query("legit question")
        assert result.answer != ""
        guard.validate_input.assert_called_once()

    def test_no_guardrails_skips_input_check(self) -> None:
        svc = _make_service(guardrails=None)
        # Should not raise even without guardrails
        result = svc.query("anything")
        assert isinstance(result, CitedAnswer)


class TestGuardrailGroundingGate:
    """QueryService should override hallucinated answers."""

    def test_hallucinated_answer_replaced(self) -> None:
        vr = _make_vector_record()
        cme = _make_chunk_map_entry()
        guard = _build_guardrail_mock(
            safe=True, grounded=False, safe_answer="Corrected answer."
        )
        svc = _make_service(
            vector=_build_vector_mock([vr]),
            artifact=_build_artifact_mock([cme]),
            guardrails=guard,
        )
        result = svc.query("test?")

        assert result.answer == "Corrected answer."
        guard.verify_grounding.assert_called_once()

    def test_grounded_answer_kept(self) -> None:
        vr = _make_vector_record()
        cme = _make_chunk_map_entry()
        guard = _build_guardrail_mock(
            safe=True, grounded=True, safe_answer="not used"
        )
        llm = _build_llm_mock("Original LLM answer.")
        svc = _make_service(
            vector=_build_vector_mock([vr]),
            artifact=_build_artifact_mock([cme]),
            llm=llm,
            guardrails=guard,
        )
        result = svc.query("test?")

        assert result.answer == "Original LLM answer."

    def test_no_guardrails_skips_grounding(self) -> None:
        vr = _make_vector_record()
        cme = _make_chunk_map_entry()
        svc = _make_service(
            vector=_build_vector_mock([vr]),
            artifact=_build_artifact_mock([cme]),
            guardrails=None,
        )
        result = svc.query("test?")
        assert isinstance(result.answer, str)
