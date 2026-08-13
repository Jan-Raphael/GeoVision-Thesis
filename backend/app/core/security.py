"""Password hashing and JSON Web Token handling.

Three properties this module exists to guarantee:

1. **Passwords are hashed with Argon2id**, the current password-hashing
   recommendation, with parameters in settings rather than hardcoded.
2. **Access and refresh tokens are not interchangeable.** Every token carries a
   ``typ`` claim and decoding demands the expected type. Without this, a stolen
   refresh token — which lives for 7 days — could be presented as an access
   token, silently defeating the short access-token lifetime.
3. **Nothing here ever logs or returns a secret.** Hashes go in, booleans come
   out; the plaintext refresh token is returned to the caller exactly once.

Refresh tokens are opaque random strings, **not** JWTs: they are looked up in
the database on every use (to support rotation and family revocation), so
signing them would add cost without adding anything.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID, uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from jose import JWTError, jwt

from app.core.clock import SYSTEM_CLOCK, Clock

if TYPE_CHECKING:
    from app.core.config import Settings

__all__ = [
    "DecodedToken",
    "TokenError",
    "TokenPair",
    "TokenType",
    "generate_refresh_token",
    "hash_password",
    "hash_refresh_token",
    "issue_access_token",
    "needs_rehash",
    "verify_password",
    "verify_token",
]


class TokenType(StrEnum):
    """What a token is allowed to be used for.

    Encoded in the ``typ`` claim and checked on every decode, so a token issued
    for one purpose cannot be replayed for another.
    """

    ACCESS = "access"
    #: Reserved: refresh tokens are opaque strings today, but keeping the
    #: member means a future switch to signed refresh tokens needs no migration
    #: of the claim vocabulary.
    REFRESH = "refresh"
    #: Future use: single-use links for email verification / password reset.
    VERIFY_EMAIL = "verify_email"
    RESET_PASSWORD = "reset_password"  # noqa: S105 - a token type, not a secret


class TokenError(Exception):
    """A token was missing, malformed, expired, or of the wrong type.

    Deliberately one exception for every failure mode. Callers turn this into a
    single generic 401; distinguishing "expired" from "bad signature" in an API
    response tells an attacker which half of their guess was right.
    """


@dataclass(frozen=True, slots=True)
class DecodedToken:
    """The verified contents of an access token.

    Attributes:
        subject: The authenticated user's id.
        token_type: Always the type the caller demanded.
        jti: Unique token id, for correlation and future revocation lists.
        issued_at: When the token was minted.
        expires_at: When it stops being valid.
    """

    subject: UUID
    token_type: TokenType
    jti: str
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class TokenPair:
    """What a successful login or refresh hands back.

    ``refresh_token`` is the **plaintext**; only its hash is stored. It is
    returned to the client once and is unrecoverable afterwards.
    """

    access_token: str
    refresh_token: str
    refresh_token_hash: str
    family_id: UUID
    refresh_expires_at: datetime
    token_type: str = "bearer"  # noqa: S105 - the OAuth scheme name


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------

#: Argon2id parameters. Defaults follow the OWASP recommendation (19 MiB, 2
#: iterations, 1 lane) and are overridable through settings so the cost can be
#: raised as hardware improves without touching code.
DEFAULT_MEMORY_COST: Final = 19456  # KiB
DEFAULT_TIME_COST: Final = 2
DEFAULT_PARALLELISM: Final = 1

_hasher: PasswordHasher | None = None

#: A pre-computed hash used to burn the same CPU time when an account does not
#: exist. See :func:`verify_password_for_unknown_user`.
_DUMMY_HASH: str | None = None


def _get_hasher(settings: Settings | None = None) -> PasswordHasher:
    """Return the process-wide password hasher."""
    global _hasher
    if _hasher is None:
        if settings is None:
            from app.core.config import get_settings

            settings = get_settings()
        _hasher = PasswordHasher(
            memory_cost=settings.argon2_memory_cost,
            time_cost=settings.argon2_time_cost,
            parallelism=settings.argon2_parallelism,
        )
    return _hasher


def hash_password(password: str, settings: Settings | None = None) -> str:
    """Hash a plaintext password with Argon2id.

    Args:
        password: The plaintext password.
        settings: Optional settings override (tests use cheaper parameters).

    Returns:
        The encoded hash, including its own parameters and salt.
    """
    return _get_hasher(settings).hash(password)


def verify_password(password: str, password_hash: str, settings: Settings | None = None) -> bool:
    """Check a plaintext password against a stored hash.

    Returns ``False`` rather than raising for any failure — a wrong password, a
    corrupt hash, and an unparseable hash are all simply "not authenticated".

    Args:
        password: The candidate plaintext.
        password_hash: The stored Argon2 hash.
        settings: Optional settings override.

    Returns:
        Whether the password matches.
    """
    try:
        return _get_hasher(settings).verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def verify_password_for_unknown_user(password: str, settings: Settings | None = None) -> bool:
    """Burn the same CPU time as a real verification, then fail.

    Called when the identifier does not match any account. Without it, login
    for an unknown user returns in microseconds while a real user takes ~50 ms,
    and that difference is a reliable **user-enumeration oracle** — an attacker
    can discover which usernames exist purely by timing the responses.

    Returns:
        Always ``False``.
    """
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("timing-equalisation-placeholder", settings)
    verify_password(password, _DUMMY_HASH, settings)
    return False


def needs_rehash(password_hash: str, settings: Settings | None = None) -> bool:
    """Whether a stored hash was made with weaker parameters than current.

    Lets the cost be raised over time: on the next successful login the hash is
    transparently upgraded, without forcing a password reset.
    """
    try:
        return _get_hasher(settings).check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


# ---------------------------------------------------------------------------
# Access tokens (JWT)
# ---------------------------------------------------------------------------


def issue_access_token(
    user_id: UUID,
    settings: Settings,
    *,
    clock: Clock = SYSTEM_CLOCK,
    extra_claims: dict[str, Any] | None = None,
) -> tuple[str, DecodedToken]:
    """Mint a short-lived access token.

    Args:
        user_id: The subject.
        settings: Provides the signing key, algorithm, and lifetime.
        clock: Time source; injectable so expiry is testable.
        extra_claims: Additional claims to embed. Must not override reserved
            names.

    Returns:
        The encoded token and its decoded representation.
    """
    now = clock.now()
    expires_at = now + timedelta(minutes=settings.access_token_ttl_minutes)
    jti = secrets.token_urlsafe(16)

    claims: dict[str, Any] = {
        "sub": str(user_id),
        "typ": TokenType.ACCESS.value,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "iss": settings.app_name,
    }
    if extra_claims:
        reserved = claims.keys() & extra_claims.keys()
        if reserved:
            msg = f"extra_claims may not override reserved claims: {sorted(reserved)}"
            raise ValueError(msg)
        claims.update(extra_claims)

    encoded = jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    decoded = DecodedToken(
        subject=user_id,
        token_type=TokenType.ACCESS,
        jti=jti,
        issued_at=now,
        expires_at=expires_at,
    )
    return encoded, decoded


def verify_token(
    token: str,
    settings: Settings,
    *,
    expected_type: TokenType = TokenType.ACCESS,
) -> DecodedToken:
    """Decode and validate a token.

    Args:
        token: The encoded JWT.
        settings: Provides the key and algorithm.
        expected_type: The ``typ`` the token must carry.

    Returns:
        The decoded token.

    Raises:
        TokenError: If the token is malformed, expired, wrongly signed, or of
            the wrong type. One exception for all cases, so the API cannot leak
            which check failed.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.app_name,
            options={"require_exp": True, "require_sub": True},
        )
    except JWTError as exc:
        msg = "token is invalid or expired"
        raise TokenError(msg) from exc

    # A refresh token presented as an access token would otherwise be accepted,
    # extending an attacker's window from 15 minutes to 7 days.
    actual_type = payload.get("typ")
    if actual_type != expected_type.value:
        msg = f"expected a {expected_type.value} token"
        raise TokenError(msg)

    try:
        subject = UUID(str(payload["sub"]))
    except (KeyError, ValueError) as exc:
        msg = "token subject is not a valid identifier"
        raise TokenError(msg) from exc

    return DecodedToken(
        subject=subject,
        token_type=expected_type,
        jti=str(payload.get("jti", "")),
        issued_at=datetime.fromtimestamp(int(payload.get("iat", 0)), tz=UTC),
        expires_at=datetime.fromtimestamp(int(payload["exp"]), tz=UTC),
    )


# ---------------------------------------------------------------------------
# Refresh tokens (opaque, hashed at rest)
# ---------------------------------------------------------------------------

#: 32 bytes of entropy, URL-safe encoded.
REFRESH_TOKEN_BYTES: Final = 32


def generate_refresh_token() -> str:
    """Generate a cryptographically random opaque refresh token.

    Not a JWT: refresh tokens are looked up in the database on every use so
    that rotation and family revocation work, and a signature would add cost
    without adding security.
    """
    return secrets.token_urlsafe(REFRESH_TOKEN_BYTES)


def hash_refresh_token(token: str) -> str:
    """Hash a refresh token for storage.

    Plain SHA-256 rather than Argon2 — deliberately. Argon2's cost exists to
    slow brute force against *low-entropy human passwords*. A refresh token has
    256 bits of entropy and cannot be brute-forced, so the only requirement is
    that a database leak does not yield usable tokens. SHA-256 satisfies that
    while keeping refresh cheap enough to run on every request cycle.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def refresh_tokens_match(candidate: str, stored_hash: str) -> bool:
    """Compare a presented refresh token against a stored hash in constant time."""
    return hmac.compare_digest(hash_refresh_token(candidate), stored_hash)


def new_token_family() -> UUID:
    """Start a new refresh-token family.

    A family is one login session. Rotation keeps the family id; detecting
    reuse of an already-rotated token revokes the whole family, which logs out
    the thief *and* the legitimate user — the safe outcome when you cannot tell
    which is which.
    """
    return uuid4()
