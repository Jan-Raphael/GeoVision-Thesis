"""Every endpoint's type hints must actually resolve at runtime.

Regression test for a bug that was both silent and security-relevant.

``deps.py`` originally imported ``User`` only under ``TYPE_CHECKING`` and
exposed ``OptionalUser = Annotated["User | None", Depends(...)]``. FastAPI
resolves endpoint annotations with :func:`typing.get_type_hints` in the
*router's* module namespace, where that name does not exist — so the forward
reference failed to resolve, the parameter was silently dropped, and
``/public/users/{username}`` treated **every authenticated caller as
anonymous**. The visible symptom was mild (an owner could not see their own
private profile); the same alias is what Module 11 will use to decide what a
signed-in visitor sees on public pages.

Nothing warned about it: no exception, no log line, just a dependency that
quietly evaluated to ``None``. Hence this test.
"""

from __future__ import annotations

import typing
from collections.abc import Iterable

import pytest
from fastapi.routing import APIRoute

from app.core.config import Environment, Settings
from app.main import create_app

pytestmark = pytest.mark.unit


def _collect_routes(routes: Iterable[object]) -> list[APIRoute]:
    """Flatten the route tree.

    ``include_router`` wraps each mounted router in an ``_IncludedRouter`` in
    this FastAPI version rather than copying its routes onto the app, so a
    non-recursive walk finds only the docs endpoints — and every assertion
    below would vacuously pass. The real routes hang off ``original_router``.
    """
    found: list[APIRoute] = []
    for route in routes:
        if isinstance(route, APIRoute):
            found.append(route)
            continue
        nested = getattr(route, "routes", None) or getattr(
            getattr(route, "original_router", None), "routes", None
        )
        if nested:
            found.extend(_collect_routes(nested))
    return found


@pytest.fixture
def app_routes() -> list[APIRoute]:
    """Every registered API route, including those inside nested routers."""
    settings = Settings(
        environment=Environment.CI,
        debug=False,
        jwt_secret_key="x" * 64,
        postgres_password="y" * 16,
        s3_secret_key="z" * 16,
    )
    application = create_app(settings)
    routes = _collect_routes(application.routes)
    # Guard against the test silently passing on an empty set.
    assert len(routes) >= 10, f"expected the full route table, found {len(routes)}"
    return routes


def test_every_endpoint_annotation_resolves(app_routes: list[APIRoute]) -> None:
    """A forward reference that cannot be resolved silently drops a parameter."""
    failures: list[str] = []
    for route in app_routes:
        try:
            typing.get_type_hints(route.endpoint, include_extras=True)
        except NameError as exc:
            failures.append(f"{route.path} ({route.endpoint.__name__}): {exc}")

    assert not failures, "unresolvable endpoint annotations:\n  " + "\n  ".join(failures)


def test_every_dependency_annotation_resolves(app_routes: list[APIRoute]) -> None:
    """The same check for the dependency callables the endpoints pull in."""
    failures: list[str] = []
    seen: set[object] = set()

    for route in app_routes:
        for dependency in route.dependant.dependencies:
            call = dependency.call
            if call is None or call in seen:
                continue
            seen.add(call)
            try:
                typing.get_type_hints(call, include_extras=True)
            except NameError as exc:
                failures.append(f"{getattr(call, '__name__', call)}: {exc}")

    assert not failures, "unresolvable dependency annotations:\n  " + "\n  ".join(failures)


def test_auth_dependencies_are_wired_to_the_right_callables() -> None:
    """`CurrentUser` and `OptionalUser` must point at their intended guards.

    Swapping them would turn a protected endpoint into a public one without
    any test failing on the happy path.
    """
    from app.api.deps import CurrentUser, OptionalUser, get_current_user, get_optional_user

    current_meta = typing.get_args(CurrentUser)[1]
    optional_meta = typing.get_args(OptionalUser)[1]

    assert current_meta.dependency is get_current_user
    assert optional_meta.dependency is get_optional_user


def test_protected_routes_require_authentication(app_routes: list[APIRoute]) -> None:
    """Routes that should be behind auth actually depend on `get_current_user`.

    Paths here are router-local (no ``/api/v1``): the version prefix is applied
    by the including wrapper, so the route objects themselves carry the
    unprefixed path.
    """
    from app.api.deps import get_current_user

    must_be_protected = {
        "/auth/me",
        "/users/me",
        "/users/me/visibility",
        "/users/me/projects",
    }

    def uses_current_user(route: APIRoute) -> bool:
        return any(
            dependency.call is get_current_user for dependency in route.dependant.dependencies
        )

    protected_paths = {route.path for route in app_routes if uses_current_user(route)}
    missing = must_be_protected - protected_paths
    assert not missing, f"these routes are not authenticated: {sorted(missing)}"


def test_public_routes_are_reachable_without_a_token(app_routes: list[APIRoute]) -> None:
    """The genuinely public endpoints must not require authentication.

    The mirror of the test above: an accidental guard on the public feed would
    break every anonymous visitor, which is most of the site's audience.
    """
    from app.api.deps import get_current_user

    must_be_public = {"/health", "/health/ready", "/auth/register", "/auth/login"}

    for route in app_routes:
        if route.path in must_be_public:
            requires_auth = any(
                dependency.call is get_current_user for dependency in route.dependant.dependencies
            )
            assert not requires_auth, f"{route.path} must be reachable anonymously"


def test_registered_paths_are_versioned() -> None:
    """Everything except the health probes lives under ``/api/v1``.

    Probes stay unversioned deliberately: an orchestrator's health check should
    not have to move when the API version changes.
    """
    settings = Settings(
        environment=Environment.CI,
        debug=False,
        jwt_secret_key="x" * 64,
        postgres_password="y" * 16,
        s3_secret_key="z" * 16,
    )
    schema = create_app(settings).openapi()
    paths = set(schema["paths"])

    assert "/health" in paths
    assert "/health/ready" in paths
    for path in paths - {"/health", "/health/ready"}:
        assert path.startswith("/api/v1/"), f"{path} is not versioned"
