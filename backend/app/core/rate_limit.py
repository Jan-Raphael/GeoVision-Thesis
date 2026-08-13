"""Request rate limiting.

Used by Module 03 for ``/auth/*``, and reused unchanged by Module 04 (search,
contact), Module 05 (pairing claims), and Module 09 (ad-hoc ``/predict``).

Two keying strategies, because they defend against different attacks:

``by_ip``
    Stops one host hammering an endpoint. Defeated by an attacker with many
    source addresses.
``by_identifier``
    Keys on the *account* being targeted, so a credential-stuffing run spread
    across a botnet still trips the limit for the account under attack.

Login uses both. Using only per-IP limiting — as the module spec originally
said — leaves single-account attacks from rotating IPs unthrottled.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import get_settings

if TYPE_CHECKING:
    from fastapi import Request

__all__ = ["get_limiter", "ip_key"]

_limiter: Limiter | None = None


def ip_key(request: Request) -> str:
    """Rate-limit key: the client's address.

    Honours ``X-Forwarded-For`` only when the app sits behind a trusted proxy
    (Module 16 sets that up); otherwise a client could spoof the header and
    bypass the limit entirely by varying it.
    """
    return get_remote_address(request)


# NOTE: there is deliberately no per-identifier key function here.
#
# slowapi evaluates its key function *before* the endpoint runs, so the request
# body - and therefore the login identifier - is not available yet. An earlier
# version read `request.state.rate_limit_identifier`, which the handler set;
# that state was always empty at key time, and every request silently fell back
# to the IP key. Per-account throttling lives in `app.core.throttle` instead,
# where it runs inside the use case and can see the identifier.


def get_limiter() -> Limiter:
    """Return the process-wide limiter.

    Storage comes from settings: in-memory by default (works with no extra
    services), Redis once it is available so the limit is shared across
    workers.
    """
    global _limiter
    if _limiter is None:
        settings = get_settings()
        _limiter = Limiter(
            key_func=ip_key,
            storage_uri=settings.rate_limit_storage_uri,
            enabled=settings.rate_limit_enabled,
            headers_enabled=True,
            strategy="fixed-window",
        )
    return _limiter


def reset_limiter() -> None:
    """Drop the cached limiter. Tests call this after changing settings."""
    global _limiter
    _limiter = None
