"""Password hashing and token handling.

The token-type tests matter most: without the ``typ`` check, a stolen refresh
token (7 days) would work wherever an access token (15 minutes) is accepted,
and the short access lifetime would be decorative.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from jose import jwt

from app.core.clock import FrozenClock
from app.core.config import Environment, Settings
from app.core.security import (
    TokenError,
    TokenType,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    issue_access_token,
    needs_rehash,
    refresh_tokens_match,
    verify_password,
    verify_password_for_unknown_user,
    verify_token,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def settings() -> Settings:
    """Cheap Argon2 parameters — production values make tests crawl."""
    return Settings(
        environment=Environment.CI,
        debug=False,
        jwt_secret_key="x" * 64,
        postgres_password="y" * 16,
        s3_secret_key="z" * 16,
        argon2_memory_cost=64,
        argon2_time_cost=1,
        argon2_parallelism=1,
    )


class TestPasswordHashing:
    """Argon2id."""

    def test_hash_and_verify_round_trip(self, settings: Settings) -> None:
        digest = hash_password("correct horse battery staple 1", settings)
        assert verify_password("correct horse battery staple 1", digest, settings) is True

    def test_wrong_password_is_rejected(self, settings: Settings) -> None:
        digest = hash_password("right-password-1", settings)
        assert verify_password("wrong-password-1", digest, settings) is False

    def test_hash_is_argon2id(self, settings: Settings) -> None:
        """Not bcrypt, not SHA - a hard requirement of the module spec."""
        assert hash_password("anything-1", settings).startswith("$argon2id$")

    def test_hashes_are_salted(self, settings: Settings) -> None:
        """The same password twice must not produce the same hash."""
        first = hash_password("same-password-1", settings)
        second = hash_password("same-password-1", settings)
        assert first != second

    def test_plaintext_never_appears_in_the_hash(self, settings: Settings) -> None:
        secret = "supersecret-password-9"
        assert secret not in hash_password(secret, settings)

    def test_corrupt_hash_returns_false_rather_than_raising(self, settings: Settings) -> None:
        """A malformed stored hash is 'not authenticated', not a 500."""
        assert verify_password("anything", "not-a-real-hash", settings) is False

    def test_unknown_user_verification_always_fails(self, settings: Settings) -> None:
        """Burns comparable CPU time, then denies. Defeats timing enumeration."""
        assert verify_password_for_unknown_user("whatever", settings) is False

    def test_weaker_parameters_are_flagged_for_rehash(self, settings: Settings) -> None:
        """Lets the Argon2 cost be raised without forcing password resets."""
        weak = hash_password("password-to-upgrade-1", settings)
        stronger = Settings(
            environment=Environment.CI,
            debug=False,
            jwt_secret_key="x" * 64,
            postgres_password="y" * 16,
            s3_secret_key="z" * 16,
            argon2_memory_cost=256,
            argon2_time_cost=3,
            argon2_parallelism=1,
        )
        # Reset the cached hasher so the new parameters take effect.
        import app.core.security as security_module

        security_module._hasher = None
        assert needs_rehash(weak, stronger) is True
        security_module._hasher = None


class TestAccessTokens:
    """JWT issuance and verification."""

    def test_round_trip(self, settings: Settings) -> None:
        user_id = uuid4()
        token, decoded = issue_access_token(user_id, settings)

        verified = verify_token(token, settings)
        assert verified.subject == user_id
        assert verified.token_type is TokenType.ACCESS
        assert verified.jti == decoded.jti

    def test_token_carries_a_unique_jti(self, settings: Settings) -> None:
        user_id = uuid4()
        first, _ = issue_access_token(user_id, settings)
        second, _ = issue_access_token(user_id, settings)
        assert verify_token(first, settings).jti != verify_token(second, settings).jti

    def test_freshly_issued_token_is_valid(self, settings: Settings) -> None:
        """Issued at the real 'now', so the 15-minute window is genuinely open.

        Pinning the clock to a fixed wall-clock date here would make the test
        pass or fail depending on when it runs — ``verify_token`` checks ``exp``
        against the real clock, which no fixture controls.
        """
        clock = FrozenClock(datetime.now(UTC))
        token, _ = issue_access_token(uuid4(), settings, clock=clock)
        assert verify_token(token, settings) is not None

    def test_expired_token_is_rejected(self, settings: Settings) -> None:
        """A token issued two hours ago is long past its 15-minute lifetime."""
        past = FrozenClock(datetime.now(UTC) - timedelta(hours=2))
        stale, _ = issue_access_token(uuid4(), settings, clock=past)
        with pytest.raises(TokenError):
            verify_token(stale, settings)

    def test_token_expiry_matches_the_configured_lifetime(self, settings: Settings) -> None:
        """The claim reflects `access_token_ttl_minutes`, not a hardcoded value."""
        issued_at = datetime.now(UTC)
        _, decoded = issue_access_token(uuid4(), settings, clock=FrozenClock(issued_at))
        assert decoded.expires_at - decoded.issued_at == timedelta(
            minutes=settings.access_token_ttl_minutes
        )

    def test_tampered_signature_is_rejected(self, settings: Settings) -> None:
        token, _ = issue_access_token(uuid4(), settings)
        head, payload, _ = token.split(".")
        forged = f"{head}.{payload}.{'A' * 43}"
        with pytest.raises(TokenError):
            verify_token(forged, settings)

    def test_token_signed_with_another_key_is_rejected(self, settings: Settings) -> None:
        other = settings.model_copy(update={"jwt_secret_key": "b" * 64})
        token, _ = issue_access_token(uuid4(), other)
        with pytest.raises(TokenError):
            verify_token(token, settings)

    def test_refresh_token_is_not_accepted_as_an_access_token(self, settings: Settings) -> None:
        """The whole point of the ``typ`` claim.

        Without this check a stolen refresh token - which lives for 7 days -
        would authenticate every request, and the 15-minute access lifetime
        would protect nothing.
        """
        now = datetime.now(UTC)
        refresh_like = jwt.encode(
            {
                "sub": str(uuid4()),
                "typ": TokenType.REFRESH.value,
                "iat": int(now.timestamp()),
                "exp": int((now + timedelta(days=7)).timestamp()),
                "iss": settings.app_name,
            },
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(TokenError, match="access"):
            verify_token(refresh_like, settings, expected_type=TokenType.ACCESS)

    def test_token_without_a_type_claim_is_rejected(self, settings: Settings) -> None:
        """A token minted by an older version must not be silently accepted."""
        now = datetime.now(UTC)
        untyped = jwt.encode(
            {
                "sub": str(uuid4()),
                "iat": int(now.timestamp()),
                "exp": int((now + timedelta(minutes=15)).timestamp()),
                "iss": settings.app_name,
            },
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(TokenError):
            verify_token(untyped, settings)

    def test_token_from_another_issuer_is_rejected(self, settings: Settings) -> None:
        now = datetime.now(UTC)
        foreign = jwt.encode(
            {
                "sub": str(uuid4()),
                "typ": TokenType.ACCESS.value,
                "iat": int(now.timestamp()),
                "exp": int((now + timedelta(minutes=15)).timestamp()),
                "iss": "some-other-service",
            },
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(TokenError):
            verify_token(foreign, settings)

    def test_garbage_is_rejected(self, settings: Settings) -> None:
        for value in ("", "not-a-token", "a.b.c"):
            with pytest.raises(TokenError):
                verify_token(value, settings)

    def test_reserved_claims_cannot_be_overridden(self, settings: Settings) -> None:
        """Otherwise a caller could forge a different subject or expiry."""
        with pytest.raises(ValueError, match="reserved"):
            issue_access_token(uuid4(), settings, extra_claims={"sub": "someone-else"})


class TestRefreshTokens:
    """Opaque tokens, hashed at rest."""

    def test_tokens_are_unique_and_long(self) -> None:
        tokens = {generate_refresh_token() for _ in range(100)}
        assert len(tokens) == 100
        assert all(len(token) >= 40 for token in tokens)

    def test_hash_is_deterministic(self) -> None:
        token = generate_refresh_token()
        assert hash_refresh_token(token) == hash_refresh_token(token)

    def test_hash_does_not_contain_the_token(self) -> None:
        token = generate_refresh_token()
        assert token not in hash_refresh_token(token)

    def test_matching_is_constant_time_and_correct(self) -> None:
        token = generate_refresh_token()
        stored = hash_refresh_token(token)
        assert refresh_tokens_match(token, stored) is True
        assert refresh_tokens_match(generate_refresh_token(), stored) is False
