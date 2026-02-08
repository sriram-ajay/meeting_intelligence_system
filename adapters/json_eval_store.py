"""
Local JSON-file adapter for EvalStorePort.

Stores evaluation results in a single JSON file on disk.
Simple, no extra infra — good for local dev and small-scale monitoring.
For production, swap to a DynamoDB or S3 adapter behind the same port.
"""

from __future__ import annotations

import json
import os
import threading
from typing import List, Optional

from domain.models import EvalResult
from ports.eval_store import EvalStorePort  # noqa: F401 (runtime_checkable)
from shared_utils.logging_utils import ContextualLogger
from shared_utils.constants import LogScope


logger = ContextualLogger(scope=LogScope.ADAPTER)

_DEFAULT_PATH = "data/metrics/eval_history.json"


class JsonEvalStoreAdapter:
    """Thread-safe, append-only JSON file store for EvalResults."""

    def __init__(self, path: str = _DEFAULT_PATH) -> None:
        self._path = path
        self._lock = threading.Lock()
        # Ensure directory exists
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)

    # ------------------------------------------------------------------
    # EvalStorePort implementation
    # ------------------------------------------------------------------

    def save(self, result: EvalResult) -> None:
        """Append one evaluation result to the JSON file."""
        with self._lock:
            data = self._read_all()
            data.append(result.model_dump())
            self._write_all(data)
        logger.info(
            "eval_result_saved",
            eval_id=result.eval_id,
            meeting_id=result.meeting_id,
            overall_score=result.overall_score,
        )

    def list_results(
        self,
        meeting_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[EvalResult]:
        """Return recent results, optionally filtered by meeting_id."""
        with self._lock:
            data = self._read_all()

        if meeting_id:
            data = [d for d in data if d.get("meeting_id") == meeting_id]

        # Most recent first, capped at limit
        data = data[-limit:][::-1]
        return [EvalResult(**d) for d in data]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_all(self) -> list:
        if not os.path.exists(self._path):
            return []
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            logger.warning("eval_store_corrupt_file", path=self._path)
            return []

    def _write_all(self, data: list) -> None:
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
