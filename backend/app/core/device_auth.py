r"""HMAC authentication for ESP32-CAM devices.

Implements ``GeoVision-Vault/05-Hardware/Device-Pairing-Protocol.md`` exactly.

Devices do **not** use JWTs. A camera sleeps for hours between wakes, has ~200 KB
of usable heap, and can only just afford TLS; a shared secret plus HMAC-SHA256
is small, has no refresh flow to implement in C, and gives per-device revocation
(ADR-006).

Every ``/ingest/*`` request carries::

    X-Device-Id:  <uuid>
    X-Timestamp:  1786550400          # unix seconds
    X-Nonce:      <16 random hex chars>
    X-Signature:  <hex HMAC-SHA256>

signed over the canonical string::

    METHOD \\n PATH \\n X-Timestamp \\n X-Nonce \\n sha256_hex(body)

Five checks, in order: device exists and is not revoked → timestamp within the
skew window → nonce unseen → body hash matches → signature matches. **Every
failure returns the same generic error**, because telling an attacker which
check failed tells them how to fix their forgery.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Protocol
from uuid import UUID

__all__ = [
    "DEVICE_ID_HEADER",
    "NONCE_HEADER",
    "SIGNATURE_HEADER",
    "TIMESTAMP_HEADER",
    "DeviceAuthError",
    "NonceCache",
    "SignedRequest",
    "build_canonical_string",
    "decrypt_device_secret",
    "encrypt_device_secret",
    "generate_device_secret",
    "generate_pairing_code",
    "hash_pairing_code",
    "sign_request",
    "verify_signed_request",
]

DEVICE_ID_HEADER: Final = "X-Device-Id"
TIMESTAMP_HEADER: Final = "X-Timestamp"
NONCE_HEADER: Final = "X-Nonce"
SIGNATURE_HEADER: Final = "X-Signature"

#: 32 bytes of entropy for the per-device secret.
DEVICE_SECRET_BYTES: Final = 32

#: Crockford base32 without I, L, O, U - the pairs a human most often mistypes
#: when reading an 8-character code off a screen and into a captive portal.
PAIRING_ALPHABET: Final = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
PAIRING_CODE_LENGTH: Final = 8

#: One message for every failure mode. See the module docstring.
GENERIC_AUTH_FAILURE: Final = "Device authentication failed."


class DeviceAuthError(Exception):
    """A signed device request could not be verified.

    Carries ``reason`` for the server log and ``message`` for the response.
    They are deliberately different: the log needs to be diagnosable, the
    response must not be.
    """

    def __init__(self, reason: str) -> None:
        """Record why authentication failed, without disclosing it."""
        super().__init__(reason)
        self.reason = reason
        self.message = GENERIC_AUTH_FAILURE


class NonceCache(Protocol):
    """Single-use token store for replay protection.

    Declared here, at the point of use, so :mod:`app.core.device_auth` stays
    free of any Redis import. Implementations live in
    ``app.infrastructure.cache``.
    """

    async def claim(self, key: str, ttl_seconds: int) -> bool:
        """Atomically record *key*, returning whether it was previously unseen.

        Must be atomic (Redis ``SET NX EX``). A check-then-set would let two
        concurrent replays both observe "unseen" and both be accepted.
        """
        ...


@dataclass(frozen=True, slots=True)
class SignedRequest:
    """The signature material extracted from an inbound request."""

    device_id: UUID
    timestamp: int
    nonce: str
    signature: str
    body: bytes

    @property
    def body_hash(self) -> str:
        """SHA-256 of the raw body bytes, hex encoded."""
        return hashlib.sha256(self.body).hexdigest()


# ---------------------------------------------------------------------------
# Secrets and codes
# ---------------------------------------------------------------------------


def generate_device_secret() -> str:
    """Generate a per-device HMAC secret.

    Returned to the firmware exactly once, at pairing. Only its hash is stored,
    so losing it means re-pairing rather than recovery.
    """
    return secrets.token_urlsafe(DEVICE_SECRET_BYTES)


def encrypt_device_secret(secret: str, encryption_key: str) -> str:
    """Encrypt a device secret for storage.

    .. important::
       **A device secret is encrypted, not hashed** — unlike a password or a
       refresh token. HMAC verification requires the server to compute the same
       MAC the device did, which means it needs the *key itself*, not a
       one-way digest of it. ``Device-Pairing-Protocol.md`` originally said
       "hashed"; that was impossible to implement and is corrected in ADR-020.

    Encryption at rest still buys the property that mattered: a leaked database
    dump yields no usable device credentials without ``GV_DEVICE_SECRET_KEY``,
    which lives in the environment rather than the database.
    """
    encrypted: bytes = _fernet(encryption_key).encrypt(secret.encode())
    return encrypted.decode()


def decrypt_device_secret(ciphertext: str, encryption_key: str) -> str | None:
    """Recover a device secret, or ``None`` if it cannot be decrypted.

    Returns ``None`` rather than raising so a rotated or corrupt key degrades to
    "this device fails authentication" instead of a 500 on every upload.
    """
    from cryptography.fernet import InvalidToken

    try:
        decrypted: bytes = _fernet(encryption_key).decrypt(ciphertext.encode())
    except (InvalidToken, ValueError, TypeError):
        return None
    else:
        return decrypted.decode()


def _fernet(encryption_key: str) -> Any:
    """Build a Fernet cipher from the configured key.

    The key is stretched through SHA-256 so any sufficiently random string works
    as ``GV_DEVICE_SECRET_KEY``, rather than requiring operators to produce a
    correctly-formatted 32-byte urlsafe-base64 value by hand.
    """
    import base64

    from cryptography.fernet import Fernet

    digest = hashlib.sha256(encryption_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def device_secret_fingerprint(secret: str) -> str:
    """A short, non-reversible identifier for a secret.

    Safe to log or show in a UI ("secret ending …4f2a") when confirming which
    credential a device is using, without disclosing the credential.
    """
    return hashlib.sha256(secret.encode()).hexdigest()[-8:]


def generate_pairing_code() -> str:
    """Generate a human-typeable pairing code, e.g. ``K7M29XQF``.

    Eight Crockford base32 characters (~40 bits). Short enough to read off a
    screen and type into a captive portal on a phone; the brute-force risk is
    handled by a 15-minute TTL, single use, and rate limiting rather than by
    length.
    """
    return "".join(secrets.choice(PAIRING_ALPHABET) for _ in range(PAIRING_CODE_LENGTH))


def hash_pairing_code(code: str) -> str:
    """Hash a pairing code for storage.

    Normalised first: the code is displayed grouped (``K7M2-9XQF``) and people
    retype it in lower case, so hyphens, spaces, and case must not change the
    result.
    """
    return hashlib.sha256(normalise_pairing_code(code).encode()).hexdigest()


def normalise_pairing_code(code: str) -> str:
    """Strip formatting from a typed pairing code."""
    return code.strip().upper().replace("-", "").replace(" ", "")


def format_pairing_code(code: str) -> str:
    """Render a code for display, grouped for readability: ``K7M2-9XQF``."""
    half = PAIRING_CODE_LENGTH // 2
    return f"{code[:half]}-{code[half:]}"


# ---------------------------------------------------------------------------
# Signing and verification
# ---------------------------------------------------------------------------


def build_canonical_string(
    method: str, path: str, timestamp: int | str, nonce: str, body_hash: str
) -> str:
    r"""Assemble the string that gets signed.

    ``METHOD \\n PATH \\n TIMESTAMP \\n NONCE \\n sha256_hex(body)``

    Every component is load-bearing: the method and path stop a signed request
    being replayed against a different endpoint, the timestamp bounds the replay
    window, the nonce makes each request single-use, and the body hash stops the
    payload being swapped for a different image.
    """
    return f"{method.upper()}\n{path}\n{timestamp}\n{nonce}\n{body_hash}"


def sign_request(
    secret: str, *, method: str, path: str, timestamp: int, nonce: str, body: bytes
) -> str:
    """Produce the signature for a request.

    Used by :mod:`scripts.simulate_device` and by the tests. The ESP32 firmware
    performs the identical computation with mbedTLS - which is why Module 13
    verifies its output against a fixed vector from this function before it ever
    attempts a real upload.
    """
    canonical = build_canonical_string(
        method, path, timestamp, nonce, hashlib.sha256(body).hexdigest()
    )
    return hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()


async def verify_signed_request(
    request: SignedRequest,
    *,
    secret: str | None,
    method: str,
    path: str,
    nonces: NonceCache,
    now: datetime,
    skew_seconds: int,
) -> None:
    """Run every verification step, raising on the first failure.

    Args:
        request: The extracted signature material.
        secret: The device's decrypted secret, or ``None`` if the device is
            unknown, revoked, or its secret cannot be decrypted.
        method: HTTP method as received.
        path: Request path as received.
        nonces: Replay-protection store.
        now: Current UTC moment.
        skew_seconds: Permitted clock difference in either direction.

    Raises:
        DeviceAuthError: On any failure, with a diagnosable ``reason`` and a
            generic ``message``.

    .. note::
       HMAC verification needs the **plaintext** secret, so unlike a password
       the server must be able to recover it. See
       :func:`encrypt_device_secret` and ADR-020.
    """
    if secret is None:
        raise DeviceAuthError("unknown or revoked device")

    # 2. Clock skew. Checked before anything expensive: a wildly wrong clock is
    #    the most common firmware fault and the cheapest thing to reject.
    drift = abs(int(now.timestamp()) - request.timestamp)
    if drift > skew_seconds:
        raise DeviceAuthError(f"timestamp drift {drift}s exceeds {skew_seconds}s")

    # 3. Replay. Atomic claim, scoped per device so two cameras cannot collide.
    nonce_key = f"nonce:{request.device_id}:{request.nonce}"
    if not await nonces.claim(nonce_key, ttl_seconds=skew_seconds):
        raise DeviceAuthError("nonce already used")

    # 4 & 5. Body integrity and signature, in one comparison: the body hash is
    #        part of the canonical string, so a tampered payload produces a
    #        different signature. compare_digest keeps it constant-time.
    expected = sign_request(
        secret,
        method=method,
        path=path,
        timestamp=request.timestamp,
        nonce=request.nonce,
        body=request.body,
    )
    if not hmac.compare_digest(expected, request.signature):
        raise DeviceAuthError("signature mismatch")


def parse_signed_request(headers: dict[str, str] | object, body: bytes) -> SignedRequest:
    """Extract signature material from request headers.

    Args:
        headers: A case-insensitive mapping (Starlette's ``request.headers``).
        body: The raw request body.

    Returns:
        The parsed material.

    Raises:
        DeviceAuthError: If a header is missing or malformed.
    """
    getter = headers.get if hasattr(headers, "get") else None
    if getter is None:  # pragma: no cover - defensive
        raise DeviceAuthError("headers are not a mapping")

    raw_device_id = getter(DEVICE_ID_HEADER)
    raw_timestamp = getter(TIMESTAMP_HEADER)
    nonce = getter(NONCE_HEADER)
    signature = getter(SIGNATURE_HEADER)

    if not all([raw_device_id, raw_timestamp, nonce, signature]):
        raise DeviceAuthError("missing one or more signature headers")

    try:
        device_id = UUID(str(raw_device_id))
    except ValueError as exc:
        raise DeviceAuthError("device id is not a uuid") from exc

    try:
        timestamp = int(str(raw_timestamp))
    except ValueError as exc:
        raise DeviceAuthError("timestamp is not an integer") from exc

    # A short nonce would collide by chance and reject legitimate uploads; an
    # unbounded one is a cheap way to fill the cache.
    nonce_text = str(nonce)
    if not 8 <= len(nonce_text) <= 64:
        raise DeviceAuthError("nonce length out of range")

    return SignedRequest(
        device_id=device_id,
        timestamp=timestamp,
        nonce=nonce_text,
        signature=str(signature),
        body=body,
    )


def utc_from_timestamp(timestamp: int) -> datetime:
    """Convert a unix timestamp to an aware UTC datetime."""
    return datetime.fromtimestamp(timestamp, tz=UTC)
