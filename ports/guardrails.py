"""
Port interface for guardrail operations (input safety + grounding verification).

Implementations: GuardrailService (services/)
"""

from __future__ import annotations

from typing import List, Protocol, Tuple, runtime_checkable


@runtime_checkable
class GuardrailPort(Protocol):
    """Abstract interface for safety and grounding checks."""

    def validate_input(self, query: str) -> bool:
        """Check whether a user query is safe for processing.

        Returns True if safe, False if the query should be rejected.
        On internal failure, implementations should fail-open (return True).
        """
        ...

    def verify_grounding(
        self, answer: str, contexts: List[str]
    ) -> Tuple[bool, str]:
        """Verify that *answer* is grounded in the given context passages.

        Returns:
            (is_grounded, safe_answer) — when *is_grounded* is False the
            *safe_answer* contains a corrected version that only uses the
            provided contexts.  On internal failure, fail-open by returning
            ``(True, answer)``.
        """
        ...
