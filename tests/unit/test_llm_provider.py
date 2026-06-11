"""Unit tests for LLM generation provider selection (Groq default, Gemini legacy).

Provider construction is offline (the SDK clients make no network call until
invoked), so these tests assert selection/validation behavior without hitting any
live API. The completion callables are never invoked here.
"""

import pytest

from backend.core.config import Settings
from backend.core.errors import ConfigError
from backend.services.llm_provider import build_completion_fn

_OVERRIDES = {
    "GOOGLE_API_KEY": "test-google-key",
    "PINECONE_API_KEY": "test-pinecone-key",
    "MYSQL_HOST": "localhost",
    "MYSQL_PORT": 3306,
    "MYSQL_USER": "shop",
    "MYSQL_PASSWORD": "shop-password",
    "MYSQL_DATABASE": "shop_catalog",
}


def _settings(**extra: object) -> Settings:
    return Settings(_env_file=None, **{**_OVERRIDES, **extra})


def test_groq_provider_returns_callable() -> None:
    fn = build_completion_fn(_settings(LLM_PROVIDER="groq", GROQ_API_KEY="gsk-test"))
    assert callable(fn)


def test_provider_value_is_case_and_whitespace_insensitive() -> None:
    fn = build_completion_fn(_settings(LLM_PROVIDER="  GROQ  ", GROQ_API_KEY="gsk-test"))
    assert callable(fn)


def test_groq_provider_without_key_raises_config_error() -> None:
    with pytest.raises(ConfigError):
        build_completion_fn(_settings(LLM_PROVIDER="groq"))


def test_gemini_provider_returns_callable() -> None:
    fn = build_completion_fn(_settings(LLM_PROVIDER="gemini"))
    assert callable(fn)


def test_unsupported_provider_raises_config_error() -> None:
    with pytest.raises(ConfigError):
        build_completion_fn(_settings(LLM_PROVIDER="openai"))
