"""Application settings, loaded from the environment.

Every configurable value in GeoVision arrives here and nowhere else: no module
reads ``os.environ`` directly, and no port, URL, or credential is hardcoded.

Two deliberate behaviours worth knowing about:

1. **Secrets have no usable defaults outside local development.** In ``ci``,
   ``staging``, or ``production`` the app refuses to start unless real values
   are supplied. A loud crash at boot is much safer than a silent fallback to a
   well-known development password.
2. **Settings are cached** (:func:`get_settings`) so the environment is read
   once per process; tests override the cache rather than mutating globals.

See ``GeoVision-Vault/01-Architecture/Tech-Stack.md``.
"""

from __future__ import annotations

import json
import secrets
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, PostgresDsn, RedisDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Environment(StrEnum):
    """Deployment environment. Controls safety checks and documentation exposure."""

    LOCAL = "local"
    CI = "ci"
    STAGING = "staging"
    PRODUCTION = "production"

    @property
    def is_deployed(self) -> bool:
        """Whether this environment must never accept insecure defaults."""
        return self in {Environment.STAGING, Environment.PRODUCTION}


class Settings(BaseSettings):
    """Typed application configuration sourced from environment variables.

    All variables use the ``GV_`` prefix, e.g. ``GV_POSTGRES_HOST``.
    """

    model_config = SettingsConfigDict(
        env_prefix="GV_",
        env_file=(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # -- Application --------------------------------------------------------
    app_name: str = "GeoVision"
    version: str = "0.1.0"
    environment: Environment = Environment.LOCAL
    debug: bool = True
    api_v1_prefix: str = "/api/v1"
    # Where a *device* should send its uploads. Encoded into the pairing QR,
    # so it must be reachable from the construction site - not "localhost".
    public_base_url: str = "http://localhost:8000"

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["json", "console"] = "console"

    # -- Security -----------------------------------------------------------
    jwt_secret_key: str = Field(default="", repr=False)
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = Field(default=15, ge=1, le=1440)
    refresh_token_ttl_days: int = Field(default=7, ge=1, le=90)
    # `NoDecode` is essential, not cosmetic: without it pydantic-settings tries
    # to JSON-decode complex types straight from the .env source and raises
    # before any validator runs, so `GV_CORS_ORIGINS=http://a,http://b` would
    # crash at startup. NoDecode hands the raw string to the validator below.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    # Argon2id cost. Defaults follow the OWASP recommendation; raising them
    # later is safe because `needs_rehash` transparently upgrades stored hashes
    # on the next successful login. Tests override these downward - a 19 MiB
    # hash per login makes a test suite crawl.
    argon2_memory_cost: int = Field(default=19456, ge=8)  # KiB
    argon2_time_cost: int = Field(default=2, ge=1)
    argon2_parallelism: int = Field(default=1, ge=1)

    # -- Rate limiting ------------------------------------------------------
    # "memory://" needs no extra services, which is what we have until Docker
    # lands. Switch to "redis://localhost:6379/1" for a limit shared across API
    # workers: an in-memory limiter counts per process, so N workers silently
    # allow N times the intended rate.
    rate_limit_enabled: bool = True
    rate_limit_storage_uri: str = "memory://"
    login_rate_limit: str = "5/minute"
    register_rate_limit: str = "3/hour"
    search_rate_limit: str = "30/minute"

    # -- Database -----------------------------------------------------------
    postgres_host: str = "localhost"
    # 5433 by default: Windows dev machines commonly already run PostgreSQL on
    # 5432, and the port clash surfaces as a baffling authentication error.
    postgres_port: int = 5433
    postgres_user: str = "geovision"
    postgres_password: str = Field(default="", repr=False)
    postgres_db: str = "geovision"
    db_echo: bool = False
    db_pool_size: int = Field(default=10, ge=1)
    db_max_overflow: int = Field(default=20, ge=0)

    # -- Redis --------------------------------------------------------------
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    # -- Object storage -----------------------------------------------------
    # "local" writes to disk and needs no extra services, which is what makes
    # Module 04 shippable before Docker/MinIO exists. "s3" is the real backend.
    # A deployed environment may not use "local" - enforced below.
    storage_backend: Literal["local", "s3"] = "local"
    local_storage_path: Path = REPO_ROOT / "outputs" / "storage"

    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = Field(default="", repr=False)
    s3_secret_key: str = Field(default="", repr=False)
    s3_bucket: str = "geovision"
    s3_region: str = "us-east-1"
    s3_use_ssl: bool = False

    # -- Uploads ------------------------------------------------------------
    max_image_upload_bytes: int = Field(default=8 * 1024 * 1024, ge=1)
    max_asset_upload_bytes: int = Field(default=25 * 1024 * 1024, ge=1)

    # -- Device ingest ------------------------------------------------------
    device_clock_skew_seconds: int = Field(default=300, ge=30, le=3600)
    pairing_token_ttl_minutes: int = Field(default=15, ge=1, le=120)
    # Replay protection. "memory" is process-local: with several API workers
    # each keeps its own set, so a replayed upload that lands on a different
    # worker is accepted - which is not replay protection at all. Refused
    # outside local development, same as filesystem storage.
    nonce_cache_backend: Literal["memory", "redis"] = "redis"
    # Where ingest hands images off for inference. "logging" records the handoff
    # and returns, which is what runs when no worker is up: images sit at
    # `status='pending'`, which is exactly the state a worker picks them up
    # from, so nothing is lost by deferring.
    task_queue_backend: Literal["logging", "celery"] = "celery"
    # Encrypts device HMAC secrets at rest. A secret must be *recoverable*
    # to verify a signature, so it is encrypted rather than hashed (ADR-020);
    # keeping the key out of the database is what makes a dump useless.
    device_secret_key: str = Field(default="", repr=False)
    min_image_width: int = Field(default=320, ge=1)
    min_image_height: int = Field(default=240, ge=1)
    #: A capture stamped further ahead than this means a corrupt device clock.
    max_capture_future_hours: int = Field(default=24, ge=1, le=168)

    # -- AI -----------------------------------------------------------------
    model_dir: Path = REPO_ROOT / "models"
    inference_device: Literal["auto", "cpu", "cuda"] = "auto"
    classifier_weights: str = ""
    detector_weights: str = ""
    use_stub_models: bool = True

    # -- Project defaults ---------------------------------------------------
    default_timezone: str = "Asia/Manila"

    # -- Validators ---------------------------------------------------------

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        """Accept a comma-separated string as well as a JSON list.

        ``.env`` files carry strings, so ``a,b`` and ``["a","b"]`` must both work.
        """
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            # With NoDecode, pydantic hands us the raw string and will not parse
            # JSON itself, so both supported forms are decoded here.
            if stripped.startswith("["):
                try:
                    return json.loads(stripped)
                except json.JSONDecodeError as exc:
                    msg = f"GV_CORS_ORIGINS looks like JSON but could not be parsed: {exc}"
                    raise ValueError(msg) from exc
            return [origin.strip() for origin in stripped.split(",") if origin.strip()]
        return value

    @field_validator("cors_origins")
    @classmethod
    def _reject_wildcard_origin(cls, value: list[str]) -> list[str]:
        """Reject ``*``: it is incompatible with credentialed CORS requests.

        Browsers refuse ``Access-Control-Allow-Origin: *`` when credentials are
        included, so a wildcard here produces confusing client-side failures.
        """
        if "*" in value:
            msg = "GV_CORS_ORIGINS must list explicit origins, not '*' (credentials are used)"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _enforce_secrets_when_deployed(self) -> Self:
        """Fail fast when a deployed environment is missing real secrets.

        In ``local``/``ci`` a random ephemeral key is generated so the app is
        runnable out of the box; in ``staging``/``production`` a missing secret
        is a startup error.
        """
        required = {
            "GV_JWT_SECRET_KEY": self.jwt_secret_key,
            "GV_POSTGRES_PASSWORD": self.postgres_password,
            "GV_S3_SECRET_KEY": self.s3_secret_key,
            "GV_DEVICE_SECRET_KEY": self.device_secret_key,
        }
        missing = [name for name, value in required.items() if not value]

        if self.environment.is_deployed:
            if missing:
                msg = (
                    f"Missing required secrets for environment "
                    f"'{self.environment}': {', '.join(sorted(missing))}. "
                    "Set them in the environment; there is no safe default."
                )
                raise ValueError(msg)
            if self.debug:
                msg = f"GV_DEBUG must be false in '{self.environment}'"
                raise ValueError(msg)
            if self.nonce_cache_backend == "memory":
                # A per-process nonce set is replay protection in shape only:
                # the replay simply has to land on a different worker.
                msg = (
                    f"GV_NONCE_CACHE_BACKEND='memory' is not permitted in "
                    f"'{self.environment}'; use 'redis'."
                )
                raise ValueError(msg)
            if self.storage_backend == "local":
                # Filesystem storage has no replication, no lifecycle rules, and
                # no real signed URLs. Fine for development, never for a
                # deployment holding a project's only copy of its site imagery.
                msg = (
                    f"GV_STORAGE_BACKEND='local' is not permitted in "
                    f"'{self.environment}'; use 's3'."
                )
                raise ValueError(msg)
        else:
            if not self.device_secret_key:
                # Deterministic, so devices paired in one dev session still
                # authenticate after a restart. Obviously not a secret - and
                # refused outright in any deployed environment by the branch above.
                object.__setattr__(
                    self, "device_secret_key", "geovision-local-development-device-key"
                )
            if not self.jwt_secret_key:
                # Ephemeral, per-process key: tokens do not survive a restart,
                # which is exactly what you want locally and is never valid in
                # production.
                object.__setattr__(self, "jwt_secret_key", secrets.token_urlsafe(64))

        return self

    # -- Derived values -----------------------------------------------------

    @property
    def database_url(self) -> str:
        """Async SQLAlchemy DSN (asyncpg driver)."""
        return str(
            PostgresDsn.build(
                scheme="postgresql+asyncpg",
                username=self.postgres_user,
                password=self.postgres_password,
                host=self.postgres_host,
                port=self.postgres_port,
                path=self.postgres_db,
            )
        )

    @property
    def sync_database_url(self) -> str:
        """Synchronous DSN, used by Alembic which does not run an event loop."""
        return str(
            PostgresDsn.build(
                scheme="postgresql+psycopg2",
                username=self.postgres_user,
                password=self.postgres_password,
                host=self.postgres_host,
                port=self.postgres_port,
                path=self.postgres_db,
            )
        )

    @property
    def redis_url(self) -> str:
        """Redis DSN used for Celery, WebSocket pub/sub, and the nonce cache."""
        return str(
            RedisDsn.build(
                scheme="redis",
                host=self.redis_host,
                port=self.redis_port,
                path=str(self.redis_db),
            )
        )

    @property
    def docs_url(self) -> str | None:
        """Swagger UI path, disabled once deployed."""
        return None if self.environment.is_deployed else "/docs"

    @property
    def openapi_url(self) -> str | None:
        """OpenAPI schema path, disabled once deployed."""
        return None if self.environment.is_deployed else "/openapi.json"


SettingsDep = Annotated[Settings, "injected via app.api.deps.get_settings"]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton.

    Cached so the environment is parsed once. Tests call
    ``get_settings.cache_clear()`` after patching environment variables.
    """
    return Settings()
