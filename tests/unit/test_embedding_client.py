"""Unit tests for E3-S2 — Gemini embedding client.

Google GenAI is the external boundary and is mocked via an injected embed
function. Business logic (768-dim contract, ordering, settings-driven config,
typed error translation) is exercised directly. No live API call is made.
"""

import pytest

from backend.core.config import Settings
from backend.core.errors import EmbeddingError
from backend.services.embedding_client import EmbeddingClient

REQUIRED_ENV = {
    "GOOGLE_API_KEY": "test-google-key",
    "PINECONE_API_KEY": "test-pinecone-key",
    "MYSQL_HOST": "localhost",
    "MYSQL_PORT": "3306",
    "MYSQL_USER": "shop_user",
    "MYSQL_PASSWORD": "shop_password",
    "MYSQL_DATABASE": "shopassistant",
}


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


def _vector(seed: float = 0.1) -> list[float]:
    return [seed] * 768


class _FakeEmbedder:
    """Records calls and returns one 768-dim vector per input text."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, *, model: str, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        self.model = model
        return [[float(index)] * 768 for index, _ in enumerate(texts)]


class TestEmbedText:
    def test_returns_768_dim_vector(self, settings: Settings) -> None:
        client = EmbeddingClient(settings, embed_fn=_FakeEmbedder())

        vector = client.embed_text("Nike running shoes for men")

        assert len(vector) == 768
        assert all(isinstance(value, float) for value in vector)

    def test_uses_model_from_settings(self, settings: Settings) -> None:
        embedder = _FakeEmbedder()
        client = EmbeddingClient(settings, embed_fn=embedder)

        client.embed_text("query text")

        assert embedder.model == settings.EMBEDDING_MODEL


class TestEmbedBatch:
    def test_returns_one_vector_per_input_in_order(self, settings: Settings) -> None:
        client = EmbeddingClient(settings, embed_fn=_FakeEmbedder())

        vectors = client.embed_batch(["first text", "second text", "third text"])

        assert len(vectors) == 3
        assert all(len(vector) == 768 for vector in vectors)
        assert vectors[0][0] == 0.0
        assert vectors[1][0] == 1.0
        assert vectors[2][0] == 2.0

    def test_empty_batch_returns_empty_without_calling_api(
        self, settings: Settings
    ) -> None:
        embedder = _FakeEmbedder()
        client = EmbeddingClient(settings, embed_fn=embedder)

        vectors = client.embed_batch([])

        assert vectors == []
        assert embedder.calls == []


class TestErrorTranslation:
    def test_sdk_failure_is_reraised_as_embedding_error(
        self, settings: Settings
    ) -> None:
        def failing_embed(*, model: str, texts: list[str]) -> list[list[float]]:
            raise RuntimeError("gemini 503 service unavailable")

        client = EmbeddingClient(settings, embed_fn=failing_embed)

        with pytest.raises(EmbeddingError) as exc_info:
            client.embed_text("query text")

        assert exc_info.value.code == "EMBEDDING_UNAVAILABLE"
        assert "gemini" not in type(exc_info.value).__module__

    def test_wrong_dimension_raises_embedding_error(self, settings: Settings) -> None:
        def short_embed(*, model: str, texts: list[str]) -> list[list[float]]:
            return [[0.1] * 512 for _ in texts]

        client = EmbeddingClient(settings, embed_fn=short_embed)

        with pytest.raises(EmbeddingError):
            client.embed_text("query text")

    def test_batch_failure_is_reraised_as_embedding_error(
        self, settings: Settings
    ) -> None:
        def failing_embed(*, model: str, texts: list[str]) -> list[list[float]]:
            raise ConnectionError("connection reset by peer")

        client = EmbeddingClient(settings, embed_fn=failing_embed)

        with pytest.raises(EmbeddingError):
            client.embed_batch(["a text", "another text"])
