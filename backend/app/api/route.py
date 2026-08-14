"""A route class that commits before the response leaves.

Fixes the defect recorded as Open-Questions **Q12**.

``get_session`` used to commit in a ``yield`` dependency's exit code. FastAPI
runs that exit code from ``AsyncExitStackMiddleware``, the *outermost*
middleware — which means it runs **after the response has been delivered**. The
consequence was measurable and ugly: a project row committed ~7 ms after its
``201`` reached the client, so a caller that read its own write immediately got
a ``404``. Create-then-navigate is exactly what a dashboard does.

The whole test suite was blind to it, and that is worth understanding rather
than patching around: ``httpx.ASGITransport`` awaits the entire ASGI call —
teardown included — before handing back a response, so tests always observe the
committed state. **Only a real network client can see the gap.**

The fix is to commit inside the endpoint's own scope. Starlette calls the route
handler, gets a ``Response`` back, and only *then* sends it; committing in a
wrapper around that handler therefore lands before the first byte goes out,
while still being inside the exit stack so the session is very much alive.

On an exception nothing is committed — the handler raises, this wrapper does not
run its commit, and the dependency's teardown rolls back. That is the same
all-or-nothing behaviour as before; only the *timing* of the success path moved.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from fastapi import Request, Response
from fastapi.routing import APIRoute

from app.infrastructure.db.session import SESSION_STATE_KEY

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["TransactionalRoute", "session_from"]


def session_from(request: Request) -> AsyncSession | None:
    """The session bound to *request*, if a dependency opened one.

    ``None`` for endpoints that never touched the database — a health probe
    should not pay for a transaction, and committing one that was never begun
    would be a wasted round trip on the hottest path in the system.
    """
    session: AsyncSession | None = getattr(request.state, SESSION_STATE_KEY, None)
    return session


class TransactionalRoute(APIRoute):
    """Commits the request's session after the handler, before the response.

    Applied via ``APIRouter(route_class=TransactionalRoute)``. Every router that
    writes must use it; a router that forgets will still *work* — the session's
    teardown is unchanged — but its writes land late, which is the bug this
    class exists to prevent.
    """

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        """Wrap the generated handler with the commit."""
        handle = super().get_route_handler()

        async def commit_then_respond(request: Request) -> Response:
            response = await handle(request)
            session = session_from(request)
            if session is not None and session.in_transaction():
                # `in_transaction()` keeps a read-only endpoint from issuing a
                # pointless COMMIT: SQLAlchemy begins lazily, so a request that
                # only selected has nothing open to commit.
                await session.commit()
            return response

        return commit_then_respond
