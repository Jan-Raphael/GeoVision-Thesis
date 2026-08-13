"""Request/response schemas for authentication and profiles.

Field names are ``snake_case`` on the wire, matching
``GeoVision-Vault/04-API/API-Contract.md`` — there is no casing translation
layer to keep in sync.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Final, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.domain.enums import ProfessionalRole, Visibility

__all__ = [
    "LoginRequest",
    "PublicProfileResponse",
    "RefreshRequest",
    "RegisterRequest",
    "SessionResponse",
    "UpdateProfileRequest",
    "UserResponse",
    "UsernameAvailabilityResponse",
    "VisibilityRequest",
]

USERNAME_PATTERN: Final = re.compile(r"^[a-zA-Z0-9_.]{3,30}$")
MIN_PASSWORD_LENGTH: Final = 8
#: bcrypt-style truncation does not apply to Argon2, but an unbounded password
#: is a cheap denial-of-service: hashing a 10 MB string costs real CPU.
MAX_PASSWORD_LENGTH: Final = 128

#: Rejected outright regardless of length. A short list of the passwords that
#: actually appear in credential-stuffing lists; full dictionary checking is
#: out of scope for v1.
COMMON_PASSWORDS: Final = frozenset(
    {
        "password",
        "password1",
        "password123",
        "12345678",
        "123456789",
        "qwerty123",
        "letmein1",
        "admin123",
        "welcome1",
        "iloveyou",
        "geovision",
        "geovision1",
    }
)


def _validate_password(value: str) -> str:
    """Enforce the password policy.

    Deliberately modest: length plus a letter and a digit, and no famously
    common choices. Elaborate composition rules (symbols, mixed case) push
    people toward ``Password1!`` and written-down passwords without measurably
    improving strength.
    """
    if len(value) < MIN_PASSWORD_LENGTH:
        msg = f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        raise ValueError(msg)
    if len(value) > MAX_PASSWORD_LENGTH:
        msg = f"Password must be at most {MAX_PASSWORD_LENGTH} characters."
        raise ValueError(msg)
    if not any(char.isalpha() for char in value):
        msg = "Password must contain at least one letter."
        raise ValueError(msg)
    if not any(char.isdigit() for char in value):
        msg = "Password must contain at least one digit."
        raise ValueError(msg)
    if value.lower() in COMMON_PASSWORDS:
        msg = "That password is too common. Please choose another."
        raise ValueError(msg)
    return value


class RegisterRequest(BaseModel):
    """The registration form: username, email, role, password (+ name, company)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    username: Annotated[str, Field(min_length=3, max_length=30, examples=["jan_m"])]
    email: EmailStr
    password: Annotated[str, Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)]
    full_name: Annotated[str, Field(min_length=1, max_length=120, examples=["Jan Macabulos"])]
    professional_role: ProfessionalRole
    company: Annotated[str | None, Field(default=None, max_length=160)]

    @field_validator("username")
    @classmethod
    def _check_username(cls, value: str) -> str:
        """Letters, digits, underscore, and dot only."""
        if not USERNAME_PATTERN.match(value):
            msg = (
                "Username must be 3-30 characters using only letters, digits, "
                "underscores, and dots."
            )
            raise ValueError(msg)
        if value.startswith(".") or value.endswith("."):
            msg = "Username cannot start or end with a dot."
            raise ValueError(msg)
        return value

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        """Apply the password policy."""
        return _validate_password(value)

    @model_validator(mode="after")
    def _password_is_not_the_username_or_email(self) -> Self:
        """Reject a password that merely repeats another supplied field."""
        lowered = self.password.lower()
        if lowered == self.username.lower() or lowered == self.email.lower():
            msg = "Password must not be the same as your username or email."
            raise ValueError(msg)
        return self


class LoginRequest(BaseModel):
    """Login. One ``identifier`` field accepts a username **or** an email."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    identifier: Annotated[str, Field(min_length=3, max_length=254, examples=["jan_m"])]
    password: Annotated[str, Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)]


class RefreshRequest(BaseModel):
    """Exchange a refresh token for a new pair."""

    model_config = ConfigDict(extra="forbid")

    refresh_token: Annotated[str, Field(min_length=16, max_length=512)]


class UserResponse(BaseModel):
    """The caller's own profile. Never returned for anyone else."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    email: EmailStr
    full_name: str
    professional_role: ProfessionalRole
    profile_visibility: Visibility
    company: str | None = None
    bio: str | None = None
    avatar_key: str | None = None
    is_active: bool = True
    created_at: datetime | None = None


class SessionResponse(BaseModel):
    """What register, login, and refresh all return."""

    model_config = ConfigDict(from_attributes=True)

    user: UserResponse
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 - the OAuth scheme name
    expires_in: int = Field(description="Access token lifetime in seconds")


class PublicProfileResponse(BaseModel):
    """A profile as an anonymous visitor sees it.

    For a private account, ``is_private`` is true and **every other field is
    null** — enforced by the entity's ``to_public_profile()``, so a field added
    later cannot leak by somebody forgetting to filter it here.
    """

    model_config = ConfigDict(from_attributes=True)

    username: str
    is_private: bool = False
    full_name: str | None = None
    professional_role: ProfessionalRole | None = None
    company: str | None = None
    bio: str | None = None
    avatar_key: str | None = None


class PublicProfileDetailResponse(PublicProfileResponse):
    """A public profile plus the public projects the person is involved in."""

    projects: list[PublicProjectSummary] = Field(default_factory=list)


class PublicProjectSummary(BaseModel):
    """Minimal project card shown on a public profile."""

    model_config = ConfigDict(from_attributes=True)

    project_code: str
    name: str
    location_label: str
    progress_pct: float
    status: str
    macro_stage: str | None = None


class UpdateProfileRequest(BaseModel):
    """Partial profile update. Omitted fields are left unchanged."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    full_name: Annotated[str | None, Field(default=None, min_length=1, max_length=120)]
    company: Annotated[str | None, Field(default=None, max_length=160)]
    bio: Annotated[str | None, Field(default=None, max_length=2000)]
    professional_role: ProfessionalRole | None = None
    profile_visibility: Visibility | None = None
    # `None` means "unchanged", so clearing an optional field needs an explicit
    # flag - otherwise a company could be set but never removed.
    clear_company: bool = False
    clear_bio: bool = False


class VisibilityRequest(BaseModel):
    """Toggle the profile between public and private (spec B.5)."""

    model_config = ConfigDict(extra="forbid")

    profile_visibility: Visibility


class UsernameAvailabilityResponse(BaseModel):
    """Live availability check for the registration form."""

    username: str
    available: bool
    reason: str | None = None


PublicProfileDetailResponse.model_rebuild()
