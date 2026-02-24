"""
DynamoDB-backed user memory adapter.

Implements UserMemoryPort for persistent user profiles, facts, and
preferences that enable personalised responses across sessions.

Table schema:
    PK: user_id (string)
    Attributes: display_name, facts (list of maps), preferences (map),
                created_at, updated_at
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

from domain.models import UserFact, UserProfile
from ports.user_memory import UserMemoryPort
from shared_utils.logging_utils import get_scoped_logger
from shared_utils.constants import LogScope
from shared_utils.error_handler import ExternalServiceError


logger = get_scoped_logger(LogScope.ADAPTER)


class DynamoUserMemoryAdapter:
    """DynamoDB implementation of UserMemoryPort.

    Table key: ``user_id`` (partition key, no sort key).
    """

    def __init__(
        self,
        table_name: str = "UserMemory",
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
    # UserMemoryPort implementation
    # ------------------------------------------------------------------

    def get_profile(self, user_id: str) -> Optional[UserProfile]:
        """Retrieve a user's profile."""
        try:
            response = self._table.get_item(Key={"user_id": user_id})
            item = response.get("Item")
            if item is None:
                return None
            return self._from_dynamo_item(item)
        except ClientError as exc:
            logger.error(
                "user_memory_get_failed",
                user_id=user_id,
                error=str(exc),
            )
            raise ExternalServiceError(
                "DynamoDB", f"Failed to get user profile: {exc}"
            ) from exc

    def upsert_profile(self, profile: UserProfile) -> UserProfile:
        """Create or update a user profile."""
        now = datetime.now(timezone.utc).isoformat()
        if not profile.created_at:
            profile.created_at = now
        profile.updated_at = now

        try:
            self._table.put_item(Item=self._to_dynamo_item(profile))
            logger.info("user_profile_saved", user_id=profile.user_id)
            return profile
        except ClientError as exc:
            logger.error(
                "user_memory_save_failed",
                user_id=profile.user_id,
                error=str(exc),
            )
            raise ExternalServiceError(
                "DynamoDB", f"Failed to save user profile: {exc}"
            ) from exc

    def add_fact(self, user_id: str, fact: UserFact) -> UserProfile:
        """Add a fact to a user's profile (creates profile if needed)."""
        existing = self.get_profile(user_id)
        if existing is None:
            existing = UserProfile(
                user_id=user_id,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        existing.facts.append(fact)
        return self.upsert_profile(existing)

    def update_preferences(
        self, user_id: str, preferences: Dict[str, str]
    ) -> UserProfile:
        """Merge preferences into a user's profile."""
        existing = self.get_profile(user_id)
        if existing is None:
            existing = UserProfile(
                user_id=user_id,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        existing.preferences.update(preferences)
        return self.upsert_profile(existing)

    def delete_profile(self, user_id: str) -> bool:
        """Delete a user profile."""
        try:
            self._table.delete_item(Key={"user_id": user_id})
            logger.info("user_profile_deleted", user_id=user_id)
            return True
        except ClientError as exc:
            logger.error(
                "user_memory_delete_failed",
                user_id=user_id,
                error=str(exc),
            )
            return False

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_dynamo_item(profile: UserProfile) -> Dict[str, Any]:
        """Convert UserProfile to DynamoDB item."""
        return {
            "user_id": profile.user_id,
            "display_name": profile.display_name,
            "facts": [
                {
                    "fact_id": f.fact_id,
                    "text": f.text,
                    "source_session_id": f.source_session_id,
                    "created_at": f.created_at,
                }
                for f in profile.facts
            ],
            "preferences": profile.preferences,
            "created_at": profile.created_at,
            "updated_at": profile.updated_at,
        }

    @staticmethod
    def _from_dynamo_item(item: Dict[str, Any]) -> UserProfile:
        """Reconstruct UserProfile from DynamoDB item."""
        facts = [
            UserFact(
                fact_id=f.get("fact_id", ""),
                text=f.get("text", ""),
                source_session_id=f.get("source_session_id", ""),
                created_at=f.get("created_at", ""),
            )
            for f in item.get("facts", [])
        ]
        return UserProfile(
            user_id=item["user_id"],
            display_name=item.get("display_name", ""),
            facts=facts,
            preferences=item.get("preferences", {}),
            created_at=item.get("created_at", ""),
            updated_at=item.get("updated_at", ""),
        )
