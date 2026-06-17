"""Application configuration.

All settings are loaded from environment variables or a ``.env`` file at
startup.  Using Pydantic Settings gives us:

* Automatic type coercion and validation.
* A single, explicit source of truth for every configurable value.
* Clear error messages when required variables are missing or malformed.
"""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the FastAPI analytics application.

    Environment variables (or .env keys) are matched case-insensitively.
    Required variables raise ``ValidationError`` on startup if absent.

    Attributes
    ----------
    DATABASE_URL:
        SQLAlchemy connection string for PostgreSQL via psycopg (v3).
        Example: ``postgresql+psycopg://user:pass@localhost:5432/mydb``
    REDIS_URL:
        Redis connection string used by the cache / task-queue layer.
        Example: ``redis://localhost:6379/0``
    SEED:
        Integer seed for reproducible random operations (e.g. data
        sampling, shuffled pagination).  Defaults to ``42``.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # Ignore unknown keys so third-party .env variables don't break startup.
        extra="ignore",
    )

    # ------------------------------------------------------------------ #
    # Database                                                             #
    # ------------------------------------------------------------------ #

    DATABASE_URL: str
    """Full SQLAlchemy URL, e.g. ``postgresql+psycopg://…``."""

    # ------------------------------------------------------------------ #
    # Redis                                                                #
    # ------------------------------------------------------------------ #

    REDIS_URL: str
    """Redis connection URL, e.g. ``redis://localhost:6379/0``."""

    # ------------------------------------------------------------------ #
    # Miscellaneous                                                        #
    # ------------------------------------------------------------------ #

    SEED: int = 42
    """Global integer seed for reproducible random operations."""

    # ------------------------------------------------------------------ #
    # Validators                                                           #
    # ------------------------------------------------------------------ #

    @field_validator("DATABASE_URL")
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        """Ensure the URL targets a supported PostgreSQL driver scheme.

        Accepts the psycopg v3 scheme used by this project as well as the
        legacy psycopg2 and bare ``postgresql`` schemes so that existing
        .env files don't break during driver migrations.
        """
        allowed_schemes = (
            "postgresql+psycopg",
            "postgresql+psycopg2",
            "postgresql",
        )
        if not any(value.startswith(scheme) for scheme in allowed_schemes):
            raise ValueError(
                f"DATABASE_URL must start with one of {allowed_schemes}. "
                f"Got: {value!r}"
            )
        return value

    @field_validator("REDIS_URL")
    @classmethod
    def _validate_redis_url(cls, value: str) -> str:
        """Ensure the URL uses a recognised Redis scheme.

        * ``redis://``  – plain TCP connection
        * ``rediss://`` – TLS-encrypted connection
        * ``unix://``   – Unix domain socket (local deployments)
        """
        allowed_schemes = ("redis://", "rediss://", "unix://")
        if not any(value.startswith(scheme) for scheme in allowed_schemes):
            raise ValueError(
                f"REDIS_URL must start with one of {allowed_schemes}. "
                f"Got: {value!r}"
            )
        return value

    @field_validator("SEED")
    @classmethod
    def _validate_seed(cls, value: int) -> int:
        """Seed must be a non-negative integer."""
        if value < 0:
            raise ValueError(f"SEED must be >= 0. Got: {value!r}")
        return value


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

settings = Settings()
"""Application-wide settings instance.

Import and use this object throughout the codebase::

    from app.core.config import settings

    print(settings.DATABASE_URL)
"""
