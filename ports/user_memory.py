"""
Port interface for persistent user memory.

Implementations: DynamoUserMemoryAdapter (adapters/)
"""

from __future__ import annotations

from typing import Dict, List, Optional, Protocol, runtime_checkable

from domain.models import UserFact, UserProfile


@runtime_checkable
class UserMemoryPort(Protocol):
    """Abstract interface for persistent user memory.

    Stores facts and preferences learned from user interactions so
    that future responses can be personalised.
    """

    def get_profile(self, user_id: str) -> Optional[UserProfile]:
        """Retrieve a user's profile and stored facts.

        Returns None if the user has no profile yet.
        """
        ...

    def upsert_profile(self, profile: UserProfile) -> UserProfile:
        """Create or update a user profile.

        Args:
            profile: The full profile to store (overwrites existing).

        Returns:
            The stored profile.
        """
        ...

    def add_fact(self, user_id: str, fact: UserFact) -> UserProfile:
        """Add a new fact to a user's profile.

        Creates the profile if it doesn't exist.

        Args:
            user_id: The user to add the fact to.
            fact: The fact to store.

        Returns:
            Updated UserProfile with the new fact appended.
        """
        ...

    def update_preferences(
        self, user_id: str, preferences: Dict[str, str]
    ) -> UserProfile:
        """Merge new preferences into the existing user profile.

        Args:
            user_id: The user to update.
            preferences: Key-value pairs to merge (existing keys are overwritten).

        Returns:
            Updated UserProfile.
        """
        ...

    def delete_profile(self, user_id: str) -> bool:
        """Delete a user's profile and all associated data.

        Returns True if deleted, False if profile didn't exist.
        """
        ...
