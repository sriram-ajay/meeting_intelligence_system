"""
Port interface for chat history persistence.

Implementations: DynamoChatHistoryAdapter (adapters/)
"""

from __future__ import annotations

from typing import List, Optional, Protocol, runtime_checkable

from domain.models import ChatSession, ChatTurn


@runtime_checkable
class ChatHistoryPort(Protocol):
    """Abstract interface for multi-turn chat session persistence."""

    def get_session(self, session_id: str) -> Optional[ChatSession]:
        """Retrieve a chat session by ID.

        Returns None if the session does not exist.
        """
        ...

    def save_turn(self, session_id: str, turn: ChatTurn, user_id: str = "") -> ChatSession:
        """Append a turn to a session (creates the session if new).

        Args:
            session_id: Unique session identifier.
            turn: The question/answer exchange to append.
            user_id: Optional user identifier.

        Returns:
            Updated ChatSession with the new turn appended.
        """
        ...

    def list_sessions(self, user_id: str, limit: int = 20) -> List[ChatSession]:
        """List recent sessions for a user (newest first).

        Args:
            user_id: Filter sessions by this user.
            limit: Maximum number of sessions to return.

        Returns:
            List of ChatSession summaries (turns may be truncated).
        """
        ...

    def delete_session(self, session_id: str) -> bool:
        """Delete a chat session.

        Returns True if the session was deleted, False if it didn't exist.
        """
        ...
