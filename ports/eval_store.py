"""Port interface for evaluation result storage."""

from __future__ import annotations

from typing import List, Optional, Protocol, runtime_checkable

from domain.models import EvalResult


@runtime_checkable
class EvalStorePort(Protocol):
    """Store and retrieve evaluation results (local JSON or S3)."""

    def save(self, result: EvalResult) -> None:
        """Persist one evaluation result."""
        ...

    def list_results(
        self,
        meeting_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[EvalResult]:
        """Return recent evaluation results, optionally filtered by meeting."""
        ...
