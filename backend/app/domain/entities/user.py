"""User and session entities.

Pure data plus invariants. No ORM, no framework — these are what use cases
manipulate, and what repositories translate to and from database rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from app.domain.enums import ProfessionalRole, Visibility

__all__ = ["PublicProfile", "RefreshToken", "User"]


@dataclass(frozen=True, slots=True)
class User:
    """A registered account.

    Attributes:
        professional_role: What the person *is*. Descriptive only — it grants
            no authority. Permissions come from project membership.
        profile_visibility: When ``PRIVATE``, the account is still findable by
            username but exposes nothing else (spec B.5).
    """

    id: UUID
    username: str
    email: str
    full_name: str
    professional_role: ProfessionalRole
    profile_visibility: Visibility = Visibility.PUBLIC
    company: str | None = None
    bio: str | None = None
    avatar_key: str | None = None
    is_active: bool = True
    email_verified_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def is_public(self) -> bool:
        """Whether anonymous visitors may see this profile's details."""
        return self.profile_visibility is Visibility.PUBLIC and self.is_active

    def to_public_profile(self) -> PublicProfile:
        """Project down to what an anonymous visitor is allowed to see.

        For a private account this returns the redacted form. Building the
        public view through this method — rather than filtering fields at the
        serialiser — means a new field cannot leak by being forgotten.
        """
        if not self.is_public:
            return PublicProfile(username=self.username, is_private=True)
        return PublicProfile(
            username=self.username,
            is_private=False,
            full_name=self.full_name,
            professional_role=self.professional_role,
            company=self.company,
            bio=self.bio,
            avatar_key=self.avatar_key,
        )


@dataclass(frozen=True, slots=True)
class PublicProfile:
    """The anonymous-visitor view of a user.

    When ``is_private`` is true every other field is ``None`` by construction,
    which is the point: the private-account response is
    ``{"username": ..., "is_private": true}`` and nothing more.
    """

    username: str
    is_private: bool
    full_name: str | None = None
    professional_role: ProfessionalRole | None = None
    company: str | None = None
    bio: str | None = None
    avatar_key: str | None = None


@dataclass(frozen=True, slots=True)
class RefreshToken:
    """A rotating refresh token.

    Only the hash is ever stored. Presenting a token that has already been
    rotated revokes the entire family, on the assumption that the token was
    stolen (Module 03).
    """

    id: UUID
    user_id: UUID
    token_hash: str
    expires_at: datetime
    family_id: UUID
    revoked_at: datetime | None = None
    user_agent: str | None = None
    ip_address: str | None = None
    created_at: datetime | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def is_valid_at(self, moment: datetime) -> bool:
        """Whether the token is unrevoked and unexpired at *moment*."""
        return self.revoked_at is None and self.expires_at > moment
