"""Gemini embedding client (E3-S2).

Single integration point for Google Gemini ``text-embedding-004``. This is the
only module that talks to the Google GenAI SDK; business logic depends on this
typed wrapper, never on the SDK (code-gen wrapper pattern). The wrapper:

* returns 768-dim vectors for one text (``embed_text``) or a batch
  (``embed_batch``), preserving input order (AC-1, AC-2);
* reads the API key and model name from centralized :class:`Settings`, never
  hardcoded (AC-4);
* catches raw SDK exceptions and re-raises :class:`EmbeddingError` so no SDK
  type leaks to callers (AC-3);
* accepts an injected ``embed_fn`` so tests substitute embedding output without
  the live API (AC-5).
"""

from collections.abc import Callable

from backend.core.config import Settings
from backend.core.errors import EmbeddingError
from backend.core.logging import get_logger

logger = get_logger(__name__)

_EXPECTED_DIM = 768

EmbedFn = Callable[..., list[list[float]]]


def _build_default_embed(api_key: str, output_dim: int) -> EmbedFn:
    """Build the live Google GenAI embed function bound to ``api_key``.

    ``output_dim`` is requested explicitly via ``output_dimensionality`` so the
    available Gemini embedding models (which default to 3072 dims) emit vectors
    matching the configured index dimension (768). The SDK is imported lazily so
    importing this module never requires the SDK to be installed — unit tests
    inject a fake ``embed_fn`` instead.
    """

    def embed(*, model: str, texts: list[str]) -> list[list[float]]:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        response = client.models.embed_content(
            model=model,
            contents=texts,  # type: ignore[arg-type]
            config=types.EmbedContentConfig(output_dimensionality=output_dim),
        )
        embeddings = response.embeddings or []
        return [list(embedding.values or []) for embedding in embeddings]

    return embed


class EmbeddingClient:
    """Typed wrapper over Gemini ``text-embedding-004`` (E3-S2)."""

    def __init__(self, settings: Settings, *, embed_fn: EmbedFn | None = None) -> None:
        self._model = settings.EMBEDDING_MODEL
        self._embed_fn = embed_fn or _build_default_embed(
            settings.google_api_key_value(), settings.EMBEDDING_DIM
        )

    def embed_text(self, text: str) -> list[float]:
        """Return a 768-dim embedding for ``text`` (E3-S2 AC-1)."""
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return one 768-dim vector per input text, in order (E3-S2 AC-2).

        Raises :class:`EmbeddingError` on any SDK failure or dimension mismatch
        (AC-3). An empty input returns an empty list without calling the API.
        """
        if not texts:
            return []
        vectors = self._invoke(texts)
        self._verify_dimensions(vectors, expected_count=len(texts))
        return vectors

    def _invoke(self, texts: list[str]) -> list[list[float]]:
        try:
            return self._embed_fn(model=self._model, texts=texts)
        except EmbeddingError:
            raise
        except Exception as exc:
            logger.error(
                "embedding.request_failed",
                extra={"model": self._model, "batch_size": len(texts)},
            )
            raise EmbeddingError(
                f"Gemini embedding request failed for {len(texts)} text(s): {exc}"
            ) from exc

    def _verify_dimensions(
        self, vectors: list[list[float]], *, expected_count: int
    ) -> None:
        if len(vectors) != expected_count:
            raise EmbeddingError(
                f"Expected {expected_count} embeddings, received {len(vectors)}"
            )
        for vector in vectors:
            if len(vector) != _EXPECTED_DIM:
                raise EmbeddingError(
                    f"Expected {_EXPECTED_DIM}-dim embedding, received {len(vector)}"
                )
