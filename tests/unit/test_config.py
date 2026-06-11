"""Unit tests for E1-S2 — centralized configuration & secret loading.

Tests are isolated from any developer `.env` by passing `_env_file=None`, so
"missing key raises" assertions hold regardless of the local environment.
"""

import pytest

from backend.core.config import Settings
from backend.core.errors import ConfigError

REQUIRED_ENV = {
    "GOOGLE_API_KEY": "test-google-key",
    "PINECONE_API_KEY": "test-pinecone-key",
    "MYSQL_HOST": "localhost",
    "MYSQL_PORT": "3306",
    "MYSQL_USER": "shop_user",
    "MYSQL_PASSWORD": "shop_password",
    "MYSQL_DATABASE": "shopassistant",
}


def _set_env(monkeypatch: pytest.MonkeyPatch, values: dict[str, str]) -> None:
    for key, value in values.items():
        monkeypatch.setenv(key, value)


class TestSettingsLoading:
    def test_loads_all_required_keys_from_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_env(monkeypatch, REQUIRED_ENV)

        settings = Settings(_env_file=None)

        assert settings.google_api_key_value() == "test-google-key"
        assert settings.pinecone_api_key_value() == "test-pinecone-key"
        assert settings.MYSQL_HOST == "localhost"
        assert settings.MYSQL_PORT == 3306
        assert settings.MYSQL_USER == "shop_user"
        assert settings.mysql_password_value() == "shop_password"
        assert settings.MYSQL_DATABASE == "shopassistant"

    def test_missing_required_key_raises_config_error_naming_the_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        partial = dict(REQUIRED_ENV)
        del partial["PINECONE_API_KEY"]
        _set_env(monkeypatch, partial)
        monkeypatch.delenv("PINECONE_API_KEY", raising=False)

        with pytest.raises(ConfigError) as exc_info:
            Settings(_env_file=None)

        assert "PINECONE_API_KEY" in str(exc_info.value)

    def test_missing_multiple_keys_names_each_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        partial = dict(REQUIRED_ENV)
        del partial["GOOGLE_API_KEY"]
        del partial["MYSQL_USER"]
        _set_env(monkeypatch, partial)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("MYSQL_USER", raising=False)

        with pytest.raises(ConfigError) as exc_info:
            Settings(_env_file=None)

        message = str(exc_info.value)
        assert "GOOGLE_API_KEY" in message
        assert "MYSQL_USER" in message


class TestTypedDefaults:
    def test_exposes_typed_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_env(monkeypatch, REQUIRED_ENV)

        settings = Settings(_env_file=None)

        assert settings.PINECONE_INDEX_NAME == "shop-products"
        assert settings.EMBEDDING_MODEL == "text-embedding-004"
        assert settings.GENERATION_MODEL == "gemini-1.5-flash"
        assert settings.EMBEDDING_DIM == 768

    def test_defaults_can_be_overridden_via_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_env(monkeypatch, REQUIRED_ENV)
        monkeypatch.setenv("PINECONE_INDEX_NAME", "custom-index")
        monkeypatch.setenv("EMBEDDING_DIM", "1024")

        settings = Settings(_env_file=None)

        assert settings.PINECONE_INDEX_NAME == "custom-index"
        assert settings.EMBEDDING_DIM == 1024


class TestSecretMasking:
    def test_repr_does_not_leak_api_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_env(monkeypatch, REQUIRED_ENV)

        settings = Settings(_env_file=None)
        rendered = repr(settings)

        assert "test-google-key" not in rendered
        assert "test-pinecone-key" not in rendered
        assert "shop_password" not in rendered

    def test_secret_values_remain_accessible_for_use(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_env(monkeypatch, REQUIRED_ENV)

        settings = Settings(_env_file=None)

        assert settings.google_api_key_value() == "test-google-key"
        assert settings.pinecone_api_key_value() == "test-pinecone-key"
        assert settings.mysql_password_value() == "shop_password"
