"""Centralized typed configuration & secret loading (E1-S2).

A single ``Settings`` object loads every secret and connection parameter from
the process environment / a ``.env`` file. No secret is hardcoded. Secrets are
stored as ``SecretStr`` so ``repr(settings)`` never leaks their values
(logging-strategy.md §4); explicit accessor methods expose the raw value where
it is actually needed (DB driver, SDK clients).
"""

from typing import Any

from pydantic import SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.core.errors import ConfigError

_REQUIRED_FIELDS: tuple[str, ...] = (
    "GOOGLE_API_KEY",
    "PINECONE_API_KEY",
    "MYSQL_HOST",
    "MYSQL_PORT",
    "MYSQL_USER",
    "MYSQL_PASSWORD",
    "MYSQL_DATABASE",
)


class Settings(BaseSettings):
    """Typed application settings loaded from environment / ``.env`` (E1-S2 AC-1).

    Raises :class:`ConfigError` naming each missing required key when a required
    value is absent (AC-4). Non-secret defaults are provided for the model and
    index configuration (AC-5).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    GOOGLE_API_KEY: SecretStr
    PINECONE_API_KEY: SecretStr
    MYSQL_HOST: str
    MYSQL_PORT: int
    MYSQL_USER: str
    MYSQL_PASSWORD: SecretStr
    MYSQL_DATABASE: str

    PINECONE_INDEX_NAME: str = "shop-products"
    EMBEDDING_MODEL: str = "text-embedding-004"
    GENERATION_MODEL: str = "gemini-1.5-flash"
    EMBEDDING_DIM: int = 768
    LOG_LEVEL: str = "INFO"
    ALLOWED_ORIGINS: str = "http://localhost:8501"

    # LLM generation provider (filter extraction + answer generation). Embeddings
    # are NOT affected — they remain on Gemini (EMBEDDING_MODEL) regardless.
    LLM_PROVIDER: str = "groq"
    GROQ_API_KEY: SecretStr | None = None
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    def allowed_origins_list(self) -> list[str]:
        """Return the configured CORS origins as a list (E7-S1 AC-2).

        Origins are stored as a comma-separated string so they can come from a
        single environment variable; empty entries are dropped.
        """
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",") if origin.strip()]

    def __init__(self, **kwargs: Any) -> None:
        try:
            super().__init__(**kwargs)
        except ValidationError as exc:
            missing = _missing_required_keys(exc)
            if missing:
                raise ConfigError(
                    "Missing required configuration: " + ", ".join(missing)
                ) from exc
            raise ConfigError(f"Invalid configuration: {exc}") from exc

    def google_api_key_value(self) -> str:
        """Return the raw Google API key for SDK construction (embeddings)."""
        return self.GOOGLE_API_KEY.get_secret_value()

    def groq_api_key_value(self) -> str:
        """Return the raw Groq API key; raise ``ConfigError`` if unset.

        Required only when ``LLM_PROVIDER == 'groq'`` (the default). Kept optional
        on the model so non-Groq setups and unit tests need not supply it.
        """
        if self.GROQ_API_KEY is None or not self.GROQ_API_KEY.get_secret_value():
            raise ConfigError("GROQ_API_KEY is required when LLM_PROVIDER='groq'")
        return self.GROQ_API_KEY.get_secret_value()

    def active_generation_model(self) -> str:
        """Return the generation model for the active LLM provider.

        Groq uses :attr:`GROQ_MODEL`; the legacy Gemini provider uses
        :attr:`GENERATION_MODEL`. Embeddings are unaffected.
        """
        if self.LLM_PROVIDER.strip().lower() == "groq":
            return self.GROQ_MODEL
        return self.GENERATION_MODEL

    def pinecone_api_key_value(self) -> str:
        """Return the raw Pinecone API key for SDK construction."""
        return self.PINECONE_API_KEY.get_secret_value()

    def mysql_password_value(self) -> str:
        """Return the raw MySQL password for connection-string construction."""
        return self.MYSQL_PASSWORD.get_secret_value()


def _missing_required_keys(exc: ValidationError) -> list[str]:
    """Extract the names of required fields reported missing by pydantic."""
    missing: list[str] = []
    for error in exc.errors():
        if error["type"] == "missing" and error["loc"]:
            field = str(error["loc"][0])
            if field in _REQUIRED_FIELDS:
                missing.append(field)
    return missing
