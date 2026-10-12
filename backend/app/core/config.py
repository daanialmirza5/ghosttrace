"""Environment-driven configuration.

Every setting can be overridden with an environment variable prefixed ``GHOSTTRACE_``
(for example ``GHOSTTRACE_DATABASE_URL``) or through a ``.env`` file in the backend
directory. Secrets are stored as ``SecretStr`` so they never appear in logs or in the
``/api/v1/settings`` response.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent


def _default_database_url() -> str:
    return f"sqlite:///{(BACKEND_DIR / 'data' / 'ghosttrace.db').as_posix()}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GHOSTTRACE_",
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    database_url: str = Field(default_factory=_default_database_url)
    auto_migrate: bool = True

    # Comma-separated in the environment, e.g. "http://localhost:5173,https://app.example".
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )

    # Ingestion limits.
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    max_records_per_import: int = Field(default=50_000, ge=1)
    max_line_bytes: int = Field(default=64 * 1024, ge=256)
    max_reported_errors: int = Field(default=200, ge=1)
    max_attributes_per_event: int = Field(default=64, ge=1)

    # Data retention: imports older than this are deleted. 0 disables automatic cleanup.
    retention_hours: int = Field(default=24, ge=0)

    # Simple per-client limit for mutating requests (POST/PUT/DELETE). 0 disables it.
    rate_limit_per_minute: int = Field(default=60, ge=0)
    # Only enable behind a trusted reverse proxy that sets X-Forwarded-For.
    trust_proxy_headers: bool = False
    # Serve interactive OpenAPI docs at /docs and /redoc.
    enable_docs: bool = True

    demo_datasets_dir: Path = REPO_DIR / "datasets" / "demo"
    # Serve a built frontend (frontend/dist) from the API process. Unset = API only.
    static_dir: Path | None = None

    # Optional external language-model explanations. Disabled by default.
    ai_provider: Literal["none", "anthropic"] = "none"
    # Optional: without it the Anthropic SDK reads ANTHROPIC_API_KEY or an `ant` CLI profile.
    ai_api_key: SecretStr | None = None
    ai_model: str = "claude-opus-5-5"
    ai_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    ai_max_retries: int = Field(default=2, ge=0, le=5)
    # When false (default) raw event messages are never sent to the provider; only
    # structured, GhostTrace-computed facts (service names, counts, event IDs) are.
    ai_send_event_messages: bool = False

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def ai_enabled(self) -> bool:
        return self.ai_provider != "none"


@lru_cache
def get_settings() -> Settings:
    return Settings()
