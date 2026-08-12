"""Settings loading from an actual ``.env`` file.

These exist because of a real bug found during Module 01: every other config
test constructed ``Settings(**kwargs)`` directly, which bypasses the dotenv
source entirely. pydantic-settings JSON-decodes complex types *inside* that
source, before any validator runs, so ``GV_CORS_ORIGINS=http://a,http://b``
crashed at startup while all unit tests stayed green.

The lesson generalises: config that is only ever tested through its Python
constructor is not tested the way it is actually used.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Environment, Settings

pytestmark = pytest.mark.unit


def _write_env(tmp_path: Path, body: str) -> Path:
    """Write a ``.env`` file and return its path."""
    env_file = tmp_path / ".env"
    env_file.write_text(body, encoding="utf-8")
    return env_file


def test_comma_separated_cors_origins_load_from_dotenv(tmp_path: Path) -> None:
    """The documented ``.env`` form must not raise a SettingsError."""
    env_file = _write_env(
        tmp_path,
        "GV_ENVIRONMENT=local\nGV_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173\n",
    )

    settings = Settings(_env_file=env_file)  # type: ignore[call-arg]

    assert settings.cors_origins == ["http://localhost:5173", "http://127.0.0.1:5173"]


def test_single_origin_loads_from_dotenv(tmp_path: Path) -> None:
    env_file = _write_env(tmp_path, "GV_CORS_ORIGINS=http://localhost:5173\n")
    settings = Settings(_env_file=env_file)  # type: ignore[call-arg]
    assert settings.cors_origins == ["http://localhost:5173"]


def test_json_array_still_loads_from_dotenv(tmp_path: Path) -> None:
    """The JSON form remains supported for anyone who prefers it."""
    env_file = _write_env(tmp_path, 'GV_CORS_ORIGINS=["http://a.test","http://b.test"]\n')
    settings = Settings(_env_file=env_file)  # type: ignore[call-arg]
    assert settings.cors_origins == ["http://a.test", "http://b.test"]


def test_scalar_values_load_from_dotenv(tmp_path: Path) -> None:
    """Ints, bools, and enums all round-trip from the file."""
    env_file = _write_env(
        tmp_path,
        "GV_ENVIRONMENT=local\n"
        "GV_DEBUG=false\n"
        "GV_POSTGRES_PORT=5544\n"
        "GV_ACCESS_TOKEN_TTL_MINUTES=30\n"
        "GV_DEFAULT_TIMEZONE=Asia/Manila\n",
    )

    settings = Settings(_env_file=env_file)  # type: ignore[call-arg]

    assert settings.environment is Environment.LOCAL
    assert settings.debug is False
    assert settings.postgres_port == 5544
    assert settings.access_token_ttl_minutes == 30
    assert settings.default_timezone == "Asia/Manila"


def test_committed_env_example_is_loadable() -> None:
    """``.env.example`` must itself parse - it is the onboarding path.

    A broken template is a broken first-run experience, and nobody notices
    until a new machine tries to start the project.
    """
    example = Path(__file__).resolve().parents[3] / ".env.example"
    assert example.is_file(), ".env.example must be committed"

    settings = Settings(_env_file=example)  # type: ignore[call-arg]

    assert settings.environment is Environment.LOCAL
    assert settings.cors_origins  # parsed, non-empty
    assert settings.postgres_port == 5433
