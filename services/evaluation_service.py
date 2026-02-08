"""
EvaluationService — runs DeepEval metrics against query results.

Uses FaithfulnessMetric and AnswerRelevancyMetric as standalone
measurements (no expected_output / ground-truth required).

Depends only on ports; no AWS or framework imports.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from domain.models import CitedAnswer, EvalResult
from ports.eval_store import EvalStorePort
from shared_utils.logging_utils import ContextualLogger
from shared_utils.constants import LogScope


logger = ContextualLogger(scope=LogScope.MONITORING)


class EvaluationService:
    """Stateless evaluation orchestrator backed by DeepEval metrics."""

    def __init__(
        self,
        *,
        eval_store: EvalStorePort,
        model: str = "gpt-4o-mini",
    ) -> None:
        self._store = eval_store
        self._model = model

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        question: str,
        cited_answer: CitedAnswer,
        meeting_id: str = "",
    ) -> EvalResult:
        """Run DeepEval Faithfulness + AnswerRelevancy on a single Q&A pair.

        Args:
            question: The user's original question.
            cited_answer: The CitedAnswer returned by QueryService.
            meeting_id: Optional meeting ID for filtering.

        Returns:
            EvalResult with metric scores, persisted to the eval store.
        """
        from deepeval.metrics import (
            AnswerRelevancyMetric,
            FaithfulnessMetric,
        )
        from deepeval.test_case import LLMTestCase

        started = time.time()

        answer_text = cited_answer.answer
        retrieval_context = cited_answer.retrieved_context

        # Build DeepEval test case
        test_case = LLMTestCase(
            input=question,
            actual_output=answer_text,
            retrieval_context=retrieval_context,
        )

        # ---- Faithfulness ----
        faithfulness_score: Optional[float] = None
        try:
            faith_metric = FaithfulnessMetric(
                threshold=0.7,
                model=self._model,
                include_reason=True,
                async_mode=False,
            )
            faith_metric.measure(test_case)
            faithfulness_score = faith_metric.score
            logger.info(
                "faithfulness_measured",
                score=faithfulness_score,
                reason=getattr(faith_metric, "reason", ""),
            )
        except Exception as exc:
            logger.warning("faithfulness_failed", error=str(exc))

        # ---- Answer Relevancy ----
        relevancy_score: Optional[float] = None
        try:
            relevancy_metric = AnswerRelevancyMetric(
                threshold=0.7,
                model=self._model,
                include_reason=True,
                async_mode=False,
            )
            relevancy_metric.measure(test_case)
            relevancy_score = relevancy_metric.score
            logger.info(
                "answer_relevancy_measured",
                score=relevancy_score,
                reason=getattr(relevancy_metric, "reason", ""),
            )
        except Exception as exc:
            logger.warning("answer_relevancy_failed", error=str(exc))

        # ---- Aggregate ----
        scores = [s for s in [faithfulness_score, relevancy_score] if s is not None]
        overall = sum(scores) / len(scores) if scores else None

        elapsed = (time.time() - started) * 1000

        result = EvalResult(
            eval_id=str(uuid.uuid4()),
            meeting_id=meeting_id or (cited_answer.meeting_ids[0] if cited_answer.meeting_ids else ""),
            question=question,
            answer=answer_text,
            retrieved_context=retrieval_context,
            faithfulness=faithfulness_score,
            answer_relevancy=relevancy_score,
            overall_score=overall,
            evaluated_at=datetime.now(timezone.utc).isoformat(),
            latency_ms=round(elapsed, 1),
        )

        self._store.save(result)
        logger.info(
            "evaluation_complete",
            eval_id=result.eval_id,
            overall_score=overall,
            latency_ms=result.latency_ms,
        )
        return result

    def list_history(
        self,
        meeting_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[EvalResult]:
        """Return historical evaluation results."""
        return self._store.list_results(meeting_id=meeting_id, limit=limit)
