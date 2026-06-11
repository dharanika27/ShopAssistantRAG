"""Unit tests for the typed error hierarchy foundation (errors.py).

Only the base ``AppError`` and ``ConfigError`` are created in Group A (needed by
E1-S2). Later stories add ``RepositoryError``, ``RetrievalError``,
``EmbeddingError``, and ``GenerationError`` to this same module.
"""

from backend.core.errors import (
    AppError,
    ConfigError,
    EmbeddingError,
    RepositoryError,
    RetrievalError,
)


class TestAppError:
    def test_app_error_carries_a_code_and_message(self) -> None:
        error = AppError("something broke", code="APP_ERROR")

        assert error.code == "APP_ERROR"
        assert str(error) == "something broke"

    def test_app_error_is_an_exception(self) -> None:
        assert isinstance(AppError("boom", code="APP_ERROR"), Exception)


class TestConfigError:
    def test_config_error_is_an_app_error(self) -> None:
        error = ConfigError("missing GOOGLE_API_KEY")

        assert isinstance(error, AppError)

    def test_config_error_has_config_error_code(self) -> None:
        error = ConfigError("missing GOOGLE_API_KEY")

        assert error.code == "CONFIG_ERROR"

    def test_config_error_preserves_message(self) -> None:
        error = ConfigError("missing GOOGLE_API_KEY, PINECONE_API_KEY")

        assert "GOOGLE_API_KEY" in str(error)
        assert "PINECONE_API_KEY" in str(error)


class TestRepositoryError:
    def test_repository_error_is_an_app_error(self) -> None:
        assert isinstance(RepositoryError("db down"), AppError)

    def test_repository_error_maps_to_mysql_unavailable_code(self) -> None:
        assert RepositoryError("db down").code == "MYSQL_UNAVAILABLE"


class TestEmbeddingError:
    def test_embedding_error_is_an_app_error(self) -> None:
        assert isinstance(EmbeddingError("gemini timed out"), AppError)

    def test_embedding_error_maps_to_embedding_unavailable_code(self) -> None:
        assert EmbeddingError("gemini timed out").code == "EMBEDDING_UNAVAILABLE"


class TestRetrievalError:
    def test_retrieval_error_is_an_app_error(self) -> None:
        assert isinstance(RetrievalError("pinecone refused"), AppError)

    def test_retrieval_error_maps_to_pinecone_unavailable_code(self) -> None:
        assert RetrievalError("pinecone refused").code == "PINECONE_UNAVAILABLE"
