"""
DynamoDB-backed chat history adapter.

Implements ChatHistoryPort using a DynamoDB table with session_id as
partition key.  Each session stores its full list of turns as a nested
list attribute.

Table schema:
    PK: session_id (string)
    Attributes: user_id, turns (list of maps), created_at, updated_at
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

from domain.models import ChatSession, ChatTurn
from ports.chat_history import ChatHistoryPort
from shared_utils.logging_utils import get_scoped_logger
from shared_utils.constants import LogScope
from shared_utils.error_handler import ExternalServiceError


logger = get_scoped_logger(LogScope.ADAPTER)


class DynamoChatHistoryAdapter:
    """DynamoDB implementation of ChatHistoryPort.

    Table key: ``session_id`` (partition key, no sort key).
    """

    def __init__(
        self,
        table_name: str = "ChatHistory",
        region: str = "eu-west-2",
        endpoint_url: str = "",
        dynamodb_resource: Optional[object] = None,
    ) -> None:
        self._table_name = table_name
        resource_kwargs: dict = {"region_name": region}
        if endpoint_url:
            resource_kwargs["endpoint_url"] = endpoint_url
        self._dynamo = dynamodb_resource or boto3.resource(
            "dynamodb", **resource_kwargs
        )
        self._table = self._dynamo.Table(table_name)

    # ------------------------------------------------------------------
    # ChatHistoryPort implementation
    # ------------------------------------------------------------------

    def get_session(self, session_id: str) -> Optional[ChatSession]:
        """Retrieve a chat session by ID."""
        try:
            response = self._table.get_item(Key={"session_id": session_id})
            item = response.get("Item")
            if item is None:
                return None
            return self._from_dynamo_item(item)
        except ClientError as exc:
            logger.error(
                "chat_history_get_failed",
                session_id=session_id,
                error=str(exc),
            )
            raise ExternalServiceError(
                "DynamoDB", f"Failed to get chat session: {exc}"
            ) from exc

    def save_turn(
        self, session_id: str, turn: ChatTurn, user_id: str = ""
    ) -> ChatSession:
        """Append a turn to a session (creates if new)."""
        now = datetime.now(timezone.utc).isoformat()

        existing = self.get_session(session_id)
        if existing is not None:
            existing.turns.append(turn)
            existing.updated_at = now
            session = existing
        else:
            session = ChatSession(
                session_id=session_id,
                user_id=user_id,
                turns=[turn],
                created_at=now,
                updated_at=now,
            )

        try:
            self._table.put_item(Item=self._to_dynamo_item(session))
            logger.info(
                "chat_turn_saved",
                session_id=session_id,
                turns=len(session.turns),
            )
            return session
        except ClientError as exc:
            logger.error(
                "chat_history_save_failed",
                session_id=session_id,
                error=str(exc),
            )
            raise ExternalServiceError(
                "DynamoDB", f"Failed to save chat turn: {exc}"
            ) from exc

    def list_sessions(self, user_id: str, limit: int = 20) -> List[ChatSession]:
        """List recent sessions for a user."""
        try:
            response = self._table.scan()
            items = response.get("Items", [])
            sessions = [
                self._from_dynamo_item(item)
                for item in items
                if item.get("user_id") == user_id
            ]
            # Sort by updated_at descending
            sessions.sort(key=lambda s: s.updated_at, reverse=True)
            return sessions[:limit]
        except ClientError as exc:
            logger.error(
                "chat_history_list_failed",
                user_id=user_id,
                error=str(exc),
            )
            return []

    def delete_session(self, session_id: str) -> bool:
        """Delete a chat session."""
        try:
            self._table.delete_item(Key={"session_id": session_id})
            logger.info("chat_session_deleted", session_id=session_id)
            return True
        except ClientError as exc:
            logger.error(
                "chat_history_delete_failed",
                session_id=session_id,
                error=str(exc),
            )
            return False

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_dynamo_item(session: ChatSession) -> Dict[str, Any]:
        """Convert ChatSession to DynamoDB item."""
        return {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "turns": [
                {
                    "turn_id": t.turn_id,
                    "question": t.question,
                    "answer": t.answer,
                    "meeting_ids": t.meeting_ids,
                    "timestamp": t.timestamp,
                    "prompt_tokens": t.prompt_tokens,
                    "completion_tokens": t.completion_tokens,
                }
                for t in session.turns
            ],
            "created_at": session.created_at,
            "updated_at": session.updated_at,
        }

    @staticmethod
    def _from_dynamo_item(item: Dict[str, Any]) -> ChatSession:
        """Reconstruct ChatSession from DynamoDB item."""
        turns = [
            ChatTurn(
                turn_id=t.get("turn_id", ""),
                question=t.get("question", ""),
                answer=t.get("answer", ""),
                meeting_ids=t.get("meeting_ids", []),
                timestamp=t.get("timestamp", ""),
                prompt_tokens=int(t.get("prompt_tokens", 0)),
                completion_tokens=int(t.get("completion_tokens", 0)),
            )
            for t in item.get("turns", [])
        ]
        return ChatSession(
            session_id=item["session_id"],
            user_id=item.get("user_id", ""),
            turns=turns,
            created_at=item.get("created_at", ""),
            updated_at=item.get("updated_at", ""),
        )
