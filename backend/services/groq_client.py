"""Groq chat-completion client — LLM generation provider (Gemini migration).

Single integration point for the Groq SDK: the only module that imports it.
Business logic depends on this typed wrapper, never on the SDK (code-gen wrapper
pattern, mirroring :mod:`backend.repositories.pinecone_client` and
:mod:`backend.services.embedding_client`).

It powers the two generation call sites — filter extraction (E5-S1) and answer
generation (E6-S2) — via a callable with the signature
``(*, model: str, prompt: str) -> str`` so the existing services and their
injected-function tests are unchanged in shape. Embeddings are NOT routed here;
they remain on Gemini (E3-S2), unchanged.

All SDK failures (rate limit, invalid key, timeout, connection/server error) are
caught at this boundary and re-raised as a typed :class:`GenerationError` so no
raw SDK type leaks; the API edge maps it to the BRD "AI assistant is temporarily
unavailable" 503 envelope. The originating error class is recorded in the log
for observability without coupling callers to SDK exception types.
"""

from collections.abc import Callable
from typing import Any

from backend.core.config import Settings
from backend.core.errors import GenerationError
from backend.core.logging import get_logger

logger = get_logger(__name__)

CompletionFn = Callable[..., str]
SdkFactory = Callable[[str, float, int], Any]

_DEFAULT_TIMEOUT_SECONDS = 30.0
_DEFAULT_MAX_RETRIES = 2


def _default_sdk_factory(api_key: str, timeout: float, max_retries: int) -> Any:
    """Construct the live Groq SDK client (lazy import).

    Imported lazily so importing this module never requires the SDK to be
    installed — unit tests inject a fake ``sdk_factory`` instead.
    """
    from groq import Groq

    return Groq(api_key=api_key, timeout=timeout, max_retries=max_retries)


class GroqClient:
    """Typed wrapper over Groq chat completions (LLM generation provider)."""

    def __init__(
        self,
        settings: Settings,
        *,
        sdk_factory: SdkFactory = _default_sdk_factory,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = _DEFAULT_MAX_RETRIES,
    ) -> None:
        self._model = settings.GROQ_MODEL
        # A missing key is a configuration error (fail fast at startup); resolve
        # it outside the try so ``ConfigError`` propagates rather than being
        # reclassified as a transient generation failure.
        api_key = settings.groq_api_key_value()
        self._client = self._connect(api_key, sdk_factory, timeout, max_retries)

    def _connect(
        self, api_key: str, sdk_factory: SdkFactory, timeout: float, max_retries: int
    ) -> Any:
        try:
            return sdk_factory(api_key, timeout, max_retries)
        except Exception as exc:
            logger.error("groq.connect_failed", extra={"error_type": type(exc).__name__})
            raise GenerationError(f"Failed to initialize Groq client: {exc}") from exc

    def complete(self, *, model: str, prompt: str) -> str:
        """Return the model's completion text for ``prompt`` (single user turn).

        Raises :class:`GenerationError` on any SDK failure — rate limit, invalid
        key, timeout, connection/server error — with the error class recorded for
        observability.
        """
        try:
            completion = self._client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
        except Exception as exc:
            logger.error(
                "groq.completion_failed",
                extra={"model": model, "error_type": type(exc).__name__},
            )
            raise GenerationError(f"Groq generation request failed: {exc}") from exc
        return _first_choice_content(completion)

    def as_completion_fn(self) -> CompletionFn:
        """Expose :meth:`complete` as the provider-agnostic completion callable."""
        return self.complete


def _first_choice_content(completion: Any) -> str:
    """Extract the assistant message text from a Groq chat completion."""
    try:
        return completion.choices[0].message.content or ""
    except (AttributeError, IndexError, TypeError) as exc:
        logger.error("groq.malformed_response", extra={"error_type": type(exc).__name__})
        raise GenerationError(f"Malformed Groq response: {exc}") from exc
