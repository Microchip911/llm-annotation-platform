"""Application configuration.

All runtime settings are read from environment variables (or a local ``.env``
file) via ``pydantic-settings``. Every value has a development-friendly default
so the service boots with ``git clone && uvicorn app.main:app`` out of the box,
yet anything security-sensitive can — and in production MUST — be overridden.
"""

import secrets

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed settings container."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Security ------------------------------------------------------------
    # If ``SECRET_KEY`` is missing OR blank we mint a strong *ephemeral* key at
    # boot (see the validator below). This keeps the demo runnable while
    # guaranteeing no weak, shared secret is ever committed to source control
    # (the original prototype hardcoded ``"your-secret"``). In production you
    # MUST set a stable ``SECRET_KEY`` so tokens survive restarts / scaling.
    secret_key: str = ""
    secret_key_is_ephemeral: bool = False
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    @model_validator(mode="after")
    def _ensure_secret_key(self) -> "Settings":
        # Treat an empty / whitespace-only value exactly like an unset one. A
        # present-but-blank env var (e.g. a copied ``.env`` with ``SECRET_KEY=``)
        # would otherwise sign every JWT with "" — trivially forgeable.
        if not self.secret_key.strip():
            self.secret_key = secrets.token_urlsafe(48)
            self.secret_key_is_ephemeral = True
        return self

    # --- Persistence ---------------------------------------------------------
    database_url: str = "sqlite:///./app.db"
    sql_echo: bool = False

    # --- API metadata / CORS -------------------------------------------------
    project_name: str = "LLM Annotation Platform"
    cors_origins: list[str] = ["*"]


settings = Settings()
