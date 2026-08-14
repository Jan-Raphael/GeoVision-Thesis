"""Device HMAC authentication.

The canonical-string tests are the important ones. That string is the contract
between this server and C code running on a microcontroller, so every component
of it needs a test that fails loudly if somebody "tidies" the format — Module 13
has no way to debug a mismatch except by bisecting the string.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.device_auth import (
    PAIRING_ALPHABET,
    PAIRING_CODE_LENGTH,
    DeviceAuthError,
    SignedRequest,
    build_canonical_string,
    decrypt_device_secret,
    encrypt_device_secret,
    format_pairing_code,
    generate_device_secret,
    generate_pairing_code,
    hash_pairing_code,
    normalise_pairing_code,
    parse_signed_request,
    sign_request,
    verify_signed_request,
)
from app.infrastructure.cache import InMemoryNonceCache

pytestmark = pytest.mark.unit

SECRET = "test-device-secret-value"
KEY = "test-encryption-key"
NOW = datetime(2026, 8, 14, 7, 0, tzinfo=UTC)


def _signed(body: bytes = b"payload", **overrides: object) -> SignedRequest:
    """Build a correctly signed request."""
    values: dict[str, object] = {
        "device_id": uuid4(),
        "timestamp": int(NOW.timestamp()),
        "nonce": "abcdef0123456789",
        "body": body,
    }
    values.update(overrides)
    signature = sign_request(
        SECRET,
        method="POST",
        path="/api/v1/ingest/images",
        timestamp=int(values["timestamp"]),  # type: ignore[arg-type]
        nonce=str(values["nonce"]),
        body=body,
    )
    return SignedRequest(signature=signature, **values)  # type: ignore[arg-type]


async def _verify(
    request: SignedRequest, *, secret: str | None = SECRET, now: datetime = NOW
) -> None:
    """Run verification with a fresh nonce cache."""
    await verify_signed_request(
        request,
        secret=secret,
        method="POST",
        path="/api/v1/ingest/images",
        nonces=InMemoryNonceCache(),
        now=now,
        skew_seconds=300,
    )


class TestCanonicalString:
    """The exact bytes the ESP32 must reproduce."""

    def test_format_is_newline_separated(self) -> None:
        canonical = build_canonical_string("POST", "/x", 1786550400, "n0nce", "deadbeef")
        assert canonical == "POST\n/x\n1786550400\nn0nce\ndeadbeef"

    def test_method_is_upper_cased(self) -> None:
        assert build_canonical_string("post", "/x", 1, "n", "h").startswith("POST\n")

    def test_every_component_changes_the_signature(self) -> None:
        """None of the five parts is decorative.

        Drop any one and a signed request becomes replayable in a way it should
        not be: a different endpoint, a different moment, or a different image.
        """
        base = sign_request(
            SECRET, method="POST", path="/a", timestamp=1000, nonce="n1", body=b"body"
        )
        variants = [
            sign_request(SECRET, method="GET", path="/a", timestamp=1000, nonce="n1", body=b"body"),
            sign_request(
                SECRET, method="POST", path="/b", timestamp=1000, nonce="n1", body=b"body"
            ),
            sign_request(
                SECRET, method="POST", path="/a", timestamp=1001, nonce="n1", body=b"body"
            ),
            sign_request(
                SECRET, method="POST", path="/a", timestamp=1000, nonce="n2", body=b"body"
            ),
            sign_request(
                SECRET, method="POST", path="/a", timestamp=1000, nonce="n1", body=b"other"
            ),
        ]
        assert all(variant != base for variant in variants)

    def test_signature_matches_an_independent_implementation(self) -> None:
        """A fixed vector the firmware can be checked against.

        Module 13's build order says: verify mbedTLS against this before
        attempting a real upload. Chasing a signature mismatch through a full
        multipart upload is miserable; chasing it with a fixed vector takes
        minutes.
        """
        body = b"geovision"
        expected = hmac.new(
            SECRET.encode(),
            f"POST\n/api/v1/ingest/images\n1786550400\nfixednonce\n"
            f"{hashlib.sha256(body).hexdigest()}".encode(),
            hashlib.sha256,
        ).hexdigest()
        assert (
            sign_request(
                SECRET,
                method="POST",
                path="/api/v1/ingest/images",
                timestamp=1786550400,
                nonce="fixednonce",
                body=body,
            )
            == expected
        )


class TestVerification:
    """The five ordered checks."""

    async def test_valid_request_passes(self) -> None:
        await _verify(_signed())

    async def test_unknown_device_is_rejected(self) -> None:
        with pytest.raises(DeviceAuthError, match="unknown or revoked"):
            await _verify(_signed(), secret=None)

    async def test_clock_skew_beyond_the_window_is_rejected(self) -> None:
        stale = _signed(timestamp=int((NOW - timedelta(minutes=10)).timestamp()))
        with pytest.raises(DeviceAuthError, match="drift"):
            await _verify(stale)

    async def test_skew_inside_the_window_is_accepted(self) -> None:
        """A DS3231 drifts; a few minutes must not lock a camera out."""
        recent = _signed(timestamp=int((NOW - timedelta(seconds=200)).timestamp()))
        await _verify(recent)

    async def test_future_skew_is_also_rejected(self) -> None:
        """The window is symmetric - a fast clock is as wrong as a slow one."""
        ahead = _signed(timestamp=int((NOW + timedelta(minutes=10)).timestamp()))
        with pytest.raises(DeviceAuthError, match="drift"):
            await _verify(ahead)

    async def test_replayed_nonce_is_rejected(self) -> None:
        """The same nonce twice is a replay, even with a valid signature."""
        cache = InMemoryNonceCache()
        request = _signed()

        async def verify() -> None:
            await verify_signed_request(
                request,
                secret=SECRET,
                method="POST",
                path="/api/v1/ingest/images",
                nonces=cache,
                now=NOW,
                skew_seconds=300,
            )

        await verify()
        with pytest.raises(DeviceAuthError, match="nonce"):
            await verify()

    async def test_tampered_body_is_rejected(self) -> None:
        """The body hash is inside the signed string, so swapping the image
        invalidates the signature even though the headers are untouched."""
        request = _signed()
        tampered = SignedRequest(
            device_id=request.device_id,
            timestamp=request.timestamp,
            nonce=request.nonce,
            signature=request.signature,
            body=b"a different image entirely",
        )
        with pytest.raises(DeviceAuthError, match="signature"):
            await _verify(tampered)

    async def test_wrong_secret_is_rejected(self) -> None:
        with pytest.raises(DeviceAuthError, match="signature"):
            await _verify(_signed(), secret="some-other-secret")

    async def test_every_failure_message_is_identical(self) -> None:
        """The reason is logged; the response never distinguishes.

        Telling an attacker *which* check failed tells them how to fix their
        forgery.
        """
        failures = []
        for maker in (
            lambda: _verify(_signed(), secret=None),
            lambda: _verify(_signed(timestamp=1)),
            lambda: _verify(_signed(), secret="wrong"),
        ):
            with pytest.raises(DeviceAuthError) as caught:
                await maker()
            failures.append(caught.value.message)
        assert len(set(failures)) == 1, failures


class TestHeaderParsing:
    """Malformed headers are rejected before any expensive work."""

    @staticmethod
    def _headers(**overrides: str) -> dict[str, str]:
        base = {
            "X-Device-Id": str(uuid4()),
            "X-Timestamp": "1786550400",
            "X-Nonce": "abcdef0123456789",
            "X-Signature": "0" * 64,
        }
        base.update(overrides)
        return base

    def test_valid_headers_parse(self) -> None:
        parsed = parse_signed_request(self._headers(), b"body")
        assert parsed.nonce == "abcdef0123456789"
        assert parsed.body_hash == hashlib.sha256(b"body").hexdigest()

    @pytest.mark.parametrize("missing", ["X-Device-Id", "X-Timestamp", "X-Nonce", "X-Signature"])
    def test_missing_header_is_rejected(self, missing: str) -> None:
        headers = self._headers()
        del headers[missing]
        with pytest.raises(DeviceAuthError, match="missing"):
            parse_signed_request(headers, b"")

    def test_non_uuid_device_id_is_rejected(self) -> None:
        with pytest.raises(DeviceAuthError, match="uuid"):
            parse_signed_request(self._headers(**{"X-Device-Id": "not-a-uuid"}), b"")

    def test_non_integer_timestamp_is_rejected(self) -> None:
        with pytest.raises(DeviceAuthError, match="integer"):
            parse_signed_request(self._headers(**{"X-Timestamp": "yesterday"}), b"")

    @pytest.mark.parametrize("nonce", ["short", "x" * 100])
    def test_nonce_length_is_bounded(self, nonce: str) -> None:
        """Too short collides by chance; unbounded is a cheap way to fill the cache."""
        with pytest.raises(DeviceAuthError, match="nonce length"):
            parse_signed_request(self._headers(**{"X-Nonce": nonce}), b"")


class TestSecretsAndCodes:
    """Secret generation, encryption, and pairing codes."""

    def test_device_secrets_are_unique_and_long(self) -> None:
        secrets_seen = {generate_device_secret() for _ in range(100)}
        assert len(secrets_seen) == 100
        assert all(len(secret) >= 40 for secret in secrets_seen)

    def test_secret_encryption_round_trips(self) -> None:
        """Encrypted, not hashed: HMAC needs the key back (ADR-020)."""
        ciphertext = encrypt_device_secret(SECRET, KEY)
        assert ciphertext != SECRET
        assert decrypt_device_secret(ciphertext, KEY) == SECRET

    def test_wrong_key_yields_none_rather_than_raising(self) -> None:
        """A rotated key must degrade to "cannot authenticate", not a 500."""
        ciphertext = encrypt_device_secret(SECRET, KEY)
        assert decrypt_device_secret(ciphertext, "a-different-key") is None

    def test_corrupt_ciphertext_yields_none(self) -> None:
        assert decrypt_device_secret("not-valid-ciphertext", KEY) is None

    def test_encryption_is_not_deterministic(self) -> None:
        """Two devices with the same secret must not share a ciphertext."""
        assert encrypt_device_secret(SECRET, KEY) != encrypt_device_secret(SECRET, KEY)

    def test_pairing_codes_avoid_confusable_characters(self) -> None:
        """No I, L, O, or U - the characters people mistype off a screen."""
        for excluded in "ILOU":
            assert excluded not in PAIRING_ALPHABET

    def test_pairing_code_shape(self) -> None:
        code = generate_pairing_code()
        assert len(code) == PAIRING_CODE_LENGTH
        assert all(char in PAIRING_ALPHABET for char in code)

    @pytest.mark.parametrize("typed", ["K7M29XQF", "k7m29xqf", "K7M2-9XQF", " k7m2 9xqf "])
    def test_code_normalisation_tolerates_how_people_type(self, typed: str) -> None:
        """It is shown grouped and retyped in lower case; all must match."""
        assert normalise_pairing_code(typed) == "K7M29XQF"
        assert hash_pairing_code(typed) == hash_pairing_code("K7M29XQF")

    def test_code_is_displayed_grouped(self) -> None:
        assert format_pairing_code("K7M29XQF") == "K7M2-9XQF"

    def test_stored_hash_does_not_contain_the_code(self) -> None:
        assert "K7M29XQF" not in hash_pairing_code("K7M29XQF")


class TestNonceCache:
    """Replay protection primitives."""

    async def test_first_claim_succeeds_and_second_fails(self) -> None:
        cache = InMemoryNonceCache()
        assert await cache.claim("nonce:a", 300) is True
        assert await cache.claim("nonce:a", 300) is False

    async def test_different_keys_are_independent(self) -> None:
        cache = InMemoryNonceCache()
        assert await cache.claim("nonce:a", 300) is True
        assert await cache.claim("nonce:b", 300) is True

    async def test_entries_expire(self) -> None:
        cache = InMemoryNonceCache()
        assert await cache.claim("nonce:a", 0) is True
        assert await cache.claim("nonce:a", 0) is True
