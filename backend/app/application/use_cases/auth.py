"""Authentication use cases: register, login, refresh, logout.

Framework-free: these take repositories and settings, and raise
:class:`~app.core.exceptions.DomainError` subclasses. The API layer turns those
into HTTP. That separation is what lets the refresh-rotation logic — the
subtlest thing in this module — be tested without a web server.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from app.core.clock import SYSTEM_CLOCK, Clock
from app.core.exceptions import ConflictError, UnauthenticatedError
from app.core.security import (
    TokenPair,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    issue_access_token,
    needs_rehash,
    verify_password,
    verify_password_for_unknown_user,
)
from app.core.throttle import AttemptThrottle, get_login_throttle, throttle_key
from app.domain.entities import RefreshToken, User
from app.domain.enums import ProfessionalRole, Visibility

if TYPE_CHECKING:
    from app.core.config import Settings
    from app.domain.repositories import RefreshTokenRepository, UserRepository

__all__ = [
    "AuthenticateUser",
    "LogoutUser",
    "RefreshSession",
    "RegisterUser",
    "SessionResult",
]

#: One generic message for every login failure. Distinguishing "no such user"
#: from "wrong password" hands an attacker a free account-enumeration oracle.
INVALID_CREDENTIALS = "Incorrect username/email or password."


@dataclass(frozen=True, slots=True)
class SessionResult:
    """A newly established session."""

    user: User
    tokens: TokenPair


class RegisterUser:
    """Create an account and log the new user straight in."""

    def __init__(
        self,
        users: UserRepository,
        refresh_tokens: RefreshTokenRepository,
        settings: Settings,
        *,
        clock: Clock = SYSTEM_CLOCK,
    ) -> None:
        """Wire the use case to its collaborators."""
        self._users = users
        self._refresh_tokens = refresh_tokens
        self._settings = settings
        self._clock = clock

    async def execute(
        self,
        *,
        username: str,
        email: str,
        password: str,
        full_name: str,
        professional_role: ProfessionalRole,
        company: str | None = None,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> SessionResult:
        """Register a user.

        Args:
            username: Unique handle; matched case-insensitively.
            email: Unique address; matched case-insensitively.
            password: Plaintext, already format-validated by the schema.
            full_name: Display name.
            professional_role: What the person does. Descriptive only — it
                confers no permissions.
            company: Optional; the spec allows setting it later from the profile.
            user_agent: Recorded against the session.
            ip_address: Recorded against the session.

        Returns:
            The created user and their first token pair.

        Raises:
            ConflictError: If the username or email is already taken.
        """
        if await self._users.username_exists(username):
            raise ConflictError(
                "That username is already taken.",
                code="USERNAME_TAKEN",
                details={"field": "username"},
            )
        if await self._users.email_exists(email):
            # Note: this does disclose that an address is registered. It is a
            # deliberate usability trade-off - the alternative (silently
            # accepting and emailing the existing owner) needs the email
            # delivery that v1 does not have. Recorded in Open-Questions.
            raise ConflictError(
                "That email address is already registered.",
                code="EMAIL_TAKEN",
                details={"field": "email"},
            )

        user = User(
            id=uuid4(),
            username=username,
            email=email,
            full_name=full_name,
            professional_role=professional_role,
            profile_visibility=Visibility.PUBLIC,
            company=company,
        )
        created = await self._users.add(user, password_hash=hash_password(password, self._settings))

        tokens = await _start_session(
            created,
            self._refresh_tokens,
            self._settings,
            clock=self._clock,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        return SessionResult(user=created, tokens=tokens)


class AuthenticateUser:
    """Verify credentials and start a session."""

    def __init__(
        self,
        users: UserRepository,
        refresh_tokens: RefreshTokenRepository,
        settings: Settings,
        *,
        clock: Clock = SYSTEM_CLOCK,
        throttle: AttemptThrottle | None = None,
    ) -> None:
        """Wire the use case to its collaborators."""
        self._users = users
        self._refresh_tokens = refresh_tokens
        self._settings = settings
        self._clock = clock
        self._throttle = throttle or get_login_throttle()

    async def execute(
        self,
        *,
        identifier: str,
        password: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> SessionResult:
        """Log a user in.

        Args:
            identifier: Username **or** email — the login form has one field.
            password: Plaintext candidate.
            user_agent: Recorded against the session.
            ip_address: Recorded against the session.

        Returns:
            The user and a fresh token pair.

        Raises:
            UnauthenticatedError: For any failure, with one generic message.
        """
        # Per-account throttling, checked before any work is done. The per-IP
        # limiter alone is bypassed by rotating source addresses; this counts
        # failures against the account under attack, wherever they come from.
        key = throttle_key(identifier)
        await self._throttle.check(key)

        user = await self._users.get_by_identifier(identifier)

        if user is None:
            # Hash anyway, so an unknown account takes the same time as a known
            # one. Returning early here would leak account existence by timing.
            verify_password_for_unknown_user(password, self._settings)
            await self._throttle.record_failure(key)
            raise UnauthenticatedError(INVALID_CREDENTIALS)

        stored_hash = await self._users.get_password_hash(user.id)
        if stored_hash is None or not verify_password(password, stored_hash, self._settings):
            await self._throttle.record_failure(key)
            raise UnauthenticatedError(INVALID_CREDENTIALS)

        if not user.is_active:
            # Same generic message: a deactivated account should not be
            # distinguishable from a wrong password.
            await self._throttle.record_failure(key)
            raise UnauthenticatedError(INVALID_CREDENTIALS)

        # Transparently upgrade hashes made with weaker parameters, so raising
        # the Argon2 cost never requires a password reset.
        if needs_rehash(stored_hash, self._settings):
            await self._users.set_password_hash(user.id, hash_password(password, self._settings))

        # Success clears the counter, so a user who mistypes twice then gets
        # it right is not left part-way to a lockout.
        await self._throttle.reset(key)

        tokens = await _start_session(
            user,
            self._refresh_tokens,
            self._settings,
            clock=self._clock,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        return SessionResult(user=user, tokens=tokens)


class RefreshSession:
    """Exchange a refresh token for a new pair, rotating the old one."""

    def __init__(
        self,
        users: UserRepository,
        refresh_tokens: RefreshTokenRepository,
        settings: Settings,
        *,
        clock: Clock = SYSTEM_CLOCK,
    ) -> None:
        """Wire the use case to its collaborators."""
        self._users = users
        self._refresh_tokens = refresh_tokens
        self._settings = settings
        self._clock = clock

    async def execute(
        self,
        *,
        refresh_token: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> SessionResult:
        """Rotate a refresh token.

        **Theft detection.** Each refresh token is single-use. Presenting one
        that has already been rotated means two parties hold it — the
        legitimate user and somebody who stole it — and there is no way to tell
        which one is calling. So the entire family (that whole login session) is
        revoked, logging out both. Losing a session is a far better outcome
        than letting an attacker keep refreshing indefinitely.

        Args:
            refresh_token: The plaintext token presented by the client.
            user_agent: Recorded against the new session.
            ip_address: Recorded against the new session.

        Returns:
            The user and a new token pair.

        Raises:
            UnauthenticatedError: If the token is unknown, expired, or reused.
        """
        stored = await self._refresh_tokens.get_by_hash(hash_refresh_token(refresh_token))
        if stored is None:
            raise UnauthenticatedError("Invalid refresh token.")

        now = self._clock.now()

        if stored.revoked_at is not None:
            # Already rotated or revoked, yet somebody still holds it.
            await self._refresh_tokens.revoke_family(stored.family_id)
            raise UnauthenticatedError(
                "Refresh token reuse detected; this session has been revoked.",
                code="TOKEN_REUSE_DETECTED",
            )

        if stored.expires_at <= now:
            raise UnauthenticatedError("Refresh token has expired.")

        user = await self._users.get(stored.user_id)
        if user is None or not user.is_active:
            await self._refresh_tokens.revoke_family(stored.family_id)
            raise UnauthenticatedError("Invalid refresh token.")

        # Rotate: burn the presented token, mint a successor in the same family
        # so that a later reuse still revokes the whole chain.
        await self._refresh_tokens.revoke(stored.id, revoked_at=now)
        tokens = await _start_session(
            user,
            self._refresh_tokens,
            self._settings,
            clock=self._clock,
            family_id=stored.family_id,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        return SessionResult(user=user, tokens=tokens)


class LogoutUser:
    """End a session by revoking its whole refresh-token family."""

    def __init__(self, refresh_tokens: RefreshTokenRepository) -> None:
        """Wire the use case to its collaborators."""
        self._refresh_tokens = refresh_tokens

    async def execute(self, *, refresh_token: str) -> bool:
        """Revoke the session the token belongs to.

        Returns ``True`` whether or not the token existed — logout must not
        become a way to probe which tokens are valid.
        """
        stored = await self._refresh_tokens.get_by_hash(hash_refresh_token(refresh_token))
        if stored is not None:
            await self._refresh_tokens.revoke_family(stored.family_id)
        return True


async def _start_session(
    user: User,
    refresh_tokens: RefreshTokenRepository,
    settings: Settings,
    *,
    clock: Clock,
    family_id: object | None = None,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> TokenPair:
    """Mint an access token and a stored refresh token.

    Shared by register, login, and refresh so all three produce identical
    session shapes — a divergence here would be a subtle security bug.
    """
    from uuid import UUID as _UUID

    now = clock.now()
    access_token, _ = issue_access_token(user.id, settings, clock=clock)

    plaintext = generate_refresh_token()
    token_hash = hash_refresh_token(plaintext)
    expires_at = now + timedelta(days=settings.refresh_token_ttl_days)
    resolved_family = family_id if isinstance(family_id, _UUID) else uuid4()

    await refresh_tokens.add(
        RefreshToken(
            id=uuid4(),
            user_id=user.id,
            token_hash=token_hash,
            family_id=resolved_family,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
        )
    )

    return TokenPair(
        access_token=access_token,
        refresh_token=plaintext,
        refresh_token_hash=token_hash,
        family_id=resolved_family,
        refresh_expires_at=expires_at,
    )
