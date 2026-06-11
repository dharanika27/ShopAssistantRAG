"""LLM generation provider selection (Gemini -> Groq migration).

The single place that decides which chat-completion backend powers filter
extraction (E5-S1) and answer generation (E6-S2). It returns a provider-agnostic
completion callable with the signature ``(*, model: str, prompt: str) -> str``,
so the existing services and their injected-function unit tests keep the same
shape regardless of provider.

Embeddings are deliberately NOT routed through here — they remain on Gemini
``text-embedding-004`` / the configured embedding model (E3-S2), unchanged, per
the migration scope.

Selection is driven by :attr:`Settings.LLM_PROVIDER`:

* ``groq`` (default) -> :class:`backend.services.groq_client.GroqClient`.
* ``gemini`` (legacy) -> direct Google GenAI ``generate_content`` call, retained
  for backward compatibility.
"""

from collections.abc import Callable

from backend.core.config import Settings
from backend.core.errors import ConfigError, GenerationError
from backend.core.logging import get_logger
from backend.services.groq_client import GroqClient

logger = get_logger(__name__)

CompletionFn = Callable[..., str]


def build_completion_fn(settings: Settings) -> CompletionFn:
    """Return the chat-completion callable for the configured provider.

    Raises :class:`ConfigError` for an unsupported ``LLM_PROVIDER`` value.
    """
    provider = settings.LLM_PROVIDER.strip().lower()
    if provider == "groq":
        logger.info(
            "llm_provider.selected",
            extra={"provider": "groq", "model": settings.GROQ_MODEL},
        )
        return GroqClient(settings).as_completion_fn()
    if provider == "gemini":
        logger.info(
            "llm_provider.selected",
            extra={"provider": "gemini", "model": settings.GENERATION_MODEL},
        )
        return _build_gemini_completion(settings.google_api_key_value())
    raise ConfigError(
        f"Unsupported LLM_PROVIDER {settings.LLM_PROVIDER!r}; expected 'groq' or 'gemini'"
    )


def _build_gemini_completion(api_key: str) -> CompletionFn:
    """Legacy Gemini ``generate_content`` completion (kept for backward compat).

    SDK is imported lazily; failures are re-raised as :class:`GenerationError` so
    no raw SDK type leaks past this boundary.
    """

    def generate(*, model: str, prompt: str) -> str:
        from google import genai

        client = genai.Client(api_key=api_key)
        try:
            response = client.models.generate_content(model=model, contents=prompt)
        except Exception as exc:  # noqa: BLE001 - boundary translation to typed error
            raise GenerationError(f"Gemini generation request failed: {exc}") from exc
        return response.text or ""

    return generate
