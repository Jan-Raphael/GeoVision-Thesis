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

from typing import ClassVar

import pytest
from fastapi import FastAPI

from app.core.config import Environment, Settings
from app.infrastructure.cache import (
    InMemoryNonceCache,
    RedisNonceCache,
    get_nonce_cache,
    reset_nonce_cache,
)
from app.infrastructure.storage import LocalObjectStorage, S3ObjectStorage, build_storage

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


class TestAdapterWiring:
    """`storage_backend` and `nonce_cache_backend` have the same shape of gap
    `TestRealtimeWiring` closes: every test builds settings with
    ``storage_backend="local"`` and ``nonce_cache_backend="memory"``
    (`tests/integration/conftest.py`), so the ``s3``/``redis`` branches —
    what a deployed environment is actually required to run, since
    ``Settings`` refuses ``local``/``memory`` there — were built by *no test
    at all* (Open-Questions Q15). Both adapters connect lazily (a boto3
    client and a `redis.asyncio.Redis` client are local objects until a
    request is made on them), so constructing them here proves the wiring
    without needing MinIO or Redis running.
    """

    def teardown_method(self) -> None:
        """The nonce cache is a module-level singleton; do not leak it across tests."""
        reset_nonce_cache()

    def test_storage_backend_local_builds_the_filesystem_adapter(self) -> None:
        storage = build_storage(_settings(storage_backend="local"))
        assert isinstance(storage, LocalObjectStorage)

    def test_storage_backend_s3_builds_the_s3_adapter_with_no_network_call(self) -> None:
        """The branch every test previously skipped."""
        storage = build_storage(
            _settings(
                storage_backend="s3",
                s3_endpoint_url="http://127.0.0.1:9000",
                s3_access_key="test",
                s3_secret_key="test",
                s3_bucket="geovision-test",
            )
        )
        assert isinstance(storage, S3ObjectStorage)

    def test_nonce_cache_backend_memory_builds_the_in_process_cache(self) -> None:
        cache = get_nonce_cache(_settings(nonce_cache_backend="memory"))
        assert isinstance(cache, InMemoryNonceCache)

    def test_nonce_cache_backend_redis_builds_the_redis_cache_with_no_connection(self) -> None:
        """The branch every test previously skipped."""
        cache = get_nonce_cache(_settings(nonce_cache_backend="redis"))
        assert isinstance(cache, RedisNonceCache)

    #: Every secret `_enforce_secrets_when_deployed` requires before it will
    #: even look at the backend settings, plus `debug=False` — both tests
    #: below supply this in full so the ValueError raised is the one under
    #: test, not an earlier check in the same validator.
    _DEPLOYED_REQUIRED: ClassVar[dict[str, object]] = {
        "debug": False,
        "jwt_secret_key": "x" * 64,
        "postgres_password": "x",
        "s3_secret_key": "x",
        "device_secret_key": "x" * 32,
    }

    def test_a_deployed_environment_refuses_local_storage(self) -> None:
        """The config validator this test coverage exists to actually exercise."""
        with pytest.raises(ValueError, match="GV_STORAGE_BACKEND"):
            _settings(
                environment=Environment.STAGING,
                storage_backend="local",
                **self._DEPLOYED_REQUIRED,
            )

    def test_a_deployed_environment_refuses_memory_nonce_cache(self) -> None:
        with pytest.raises(ValueError, match="GV_NONCE_CACHE_BACKEND"):
            _settings(
                environment=Environment.STAGING,
                nonce_cache_backend="memory",
                storage_backend="s3",
                **self._DEPLOYED_REQUIRED,
            )
