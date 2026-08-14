"""The application must start under the configuration it actually ships with.

This exists because it did not, and nothing noticed.

Module 14 added a realtime subscriber to the lifespan, guarded by
``task_queue_backend == "celery"`` — the **default**. Every test builds settings
with ``task_queue_backend="logging"``, so every test took the early return and
never executed the branch that runs in production. A `NameError` in that branch
therefore passed 668 tests, a clean mypy run, and four import contracts, and
still stopped the API from booting the moment it was started without overrides.

The lesson generalises past this one bug: **a config guard whose test value and
default value differ has an untested branch by construction.** So these tests
drive the lifespan under the default configuration, not the convenient one.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI

from app.core.config import Environment, Settings

# The private helper is imported deliberately: the boot path *is* the subject here.
from app.main import _start_realtime, create_app

pytestmark = pytest.mark.unit


def _settings(**overrides: object) -> Settings:
    """Settings with the shipped defaults, hermetic from any local `.env`."""
    values: dict[str, object] = {"environment": Environment.LOCAL}
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


class TestRealtimeWiring:
    """Both branches of the lifespan guard, not just the one tests take."""

    def test_the_celery_branch_constructs_a_subscriber(self) -> None:
        """The default configuration. This is the branch that was broken."""
        subscriber = _start_realtime(_settings(task_queue_backend="celery"))

        assert subscriber is not None
        # Constructed only — `start()` is what opens a connection, and the
        # lifespan owns that.
        assert hasattr(subscriber, "start")
        assert hasattr(subscriber, "stop")

    def test_the_logging_branch_returns_none(self) -> None:
        """No broker configured: the app still serves, and simply does not push."""
        assert _start_realtime(_settings(task_queue_backend="logging")) is None

    def test_celery_is_the_default(self) -> None:
        """If this ever changes, the test above stops covering production."""
        assert _settings().task_queue_backend == "celery"


class TestApplicationBoot:
    """`create_app` succeeds under each supported queue backend."""

    @pytest.mark.parametrize("backend", ["celery", "logging"])
    def test_the_app_builds(self, backend: str) -> None:
        app = create_app(_settings(task_queue_backend=backend))
        assert isinstance(app, FastAPI)

    @pytest.mark.parametrize("backend", ["celery", "logging"])
    async def test_the_lifespan_starts_and_stops(self, backend: str) -> None:
        """Runs startup and shutdown for real.

        Building the app is not enough — the failure was *in the lifespan*, which
        `create_app` never executes. With ``celery`` the subscriber is created
        and its Redis loop begins; it retries in the background if Redis is
        absent, which is the designed behaviour and must not block startup.
        """
        app = create_app(_settings(task_queue_backend=backend))

        async with app.router.lifespan_context(app):
            # Reached only if startup completed without raising.
            assert app.title

    async def test_startup_survives_an_absent_redis(self) -> None:
        """A broker that is down must not stop the API serving.

        Realtime is an optimisation and the dashboard polls; an unreachable
        Redis should cost push updates, never the whole application.
        """
        app = create_app(
            _settings(task_queue_backend="celery", redis_host="127.0.0.1", redis_port=6399)
        )

        async with app.router.lifespan_context(app):
            assert app.title
