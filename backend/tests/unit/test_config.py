"""Tests for settings parsing, validation, and the fail-fast secret policy."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Environment, Settings


def _base(**overrides: object) -> Settings:
    """Build settings with valid deployed-environment defaults."""
    values: dict[str, object] = {
        "environment": Environment.PRODUCTION,
        "debug": False,
        "jwt_secret_key": "a" * 64,
        "postgres_password": "b" * 32,
        "s3_secret_key": "c" * 32,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


pytestmark = pytest.mark.unit


class TestCorsOrigins:
    """CORS origins accept both env-file and JSON forms."""

    def test_comma_separated_string_is_split(self) -> None:
        settings = Settings(cors_origins="http://a.test, http://b.test")  # type: ignore[arg-type]
        assert settings.cors_origins == ["http://a.test", "http://b.test"]

    def test_json_list_is_accepted(self) -> None:
        settings = Settings(cors_origins=["http://a.test"])
        assert settings.cors_origins == ["http://a.test"]

    def test_empty_string_yields_empty_list(self) -> None:
        settings = Settings(cors_origins="")  # type: ignore[arg-type]
        assert settings.cors_origins == []

    def test_wildcard_is_rejected(self) -> None:
        """`*` is incompatible with credentialed requests and must fail loudly."""
        with pytest.raises(ValidationError, match="explicit origins"):
            Settings(cors_origins=["*"])


class TestSecretPolicy:
    """Deployed environments must never fall back to insecure defaults."""

    def test_local_generates_an_ephemeral_jwt_secret(self) -> None:
        settings = Settings(environment=Environment.LOCAL, jwt_secret_key="")
        assert len(settings.jwt_secret_key) >= 43

    def test_two_local_instances_get_different_secrets(self) -> None:
        """Ephemeral keys are per-process, so tokens never outlive a restart."""
        first = Settings(environment=Environment.LOCAL, jwt_secret_key="")
        second = Settings(environment=Environment.LOCAL, jwt_secret_key="")
        assert first.jwt_secret_key != second.jwt_secret_key

    @pytest.mark.parametrize(
        "missing",
        ["jwt_secret_key", "postgres_password", "s3_secret_key"],
    )
    def test_production_refuses_to_start_without_a_secret(self, missing: str) -> None:
        with pytest.raises(ValidationError, match="Missing required secrets"):
            _base(**{missing: ""})

    def test_production_refuses_debug_mode(self) -> None:
        with pytest.raises(ValidationError, match="GV_DEBUG must be false"):
            _base(debug=True)

    def test_production_starts_with_all_secrets_present(self) -> None:
        settings = _base()
        assert settings.environment is Environment.PRODUCTION


class TestDerivedUrls:
    """DSNs are assembled from parts, never hand-written."""

    def test_database_url_uses_asyncpg(self) -> None:
        settings = _base(postgres_host="db", postgres_port=5432, postgres_db="gv")
        assert settings.database_url.startswith("postgresql+asyncpg://")
        assert "db:5432/gv" in settings.database_url

    def test_sync_database_url_is_used_by_alembic(self) -> None:
        assert _base().sync_database_url.startswith("postgresql+psycopg2://")

    def test_redis_url_includes_db_index(self) -> None:
        settings = _base(redis_host="cache", redis_port=6379, redis_db=2)
        assert settings.redis_url == "redis://cache:6379/2"

    def test_default_postgres_port_avoids_the_common_windows_clash(self) -> None:
        """5433 by default: dev machines often already run PostgreSQL on 5432."""
        assert Settings().postgres_port == 5433


class TestDocsExposure:
    """API docs are public in development and hidden once deployed."""

    def test_docs_enabled_locally(self) -> None:
        settings = Settings(environment=Environment.LOCAL)
        assert settings.docs_url == "/docs"
        assert settings.openapi_url == "/openapi.json"

    def test_docs_disabled_in_production(self) -> None:
        settings = _base()
        assert settings.docs_url is None
        assert settings.openapi_url is None


class TestSecretsAreNotLeaked:
    """Secrets must not appear in reprs, which end up in logs and tracebacks."""

    @pytest.mark.parametrize(
        "field",
        ["jwt_secret_key", "postgres_password", "s3_secret_key"],
    )
    def test_secret_absent_from_repr(self, field: str) -> None:
        settings = _base()
        assert getattr(settings, field) not in repr(settings)
