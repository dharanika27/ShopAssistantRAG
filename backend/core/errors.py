"""Typed error hierarchy (error-handling-strategy.md §2).

The single place where domain error types live. Repository/service layers catch
raw driver/SDK exceptions and raise one of these; the API middleware (E7-S1) is
the single place that maps them to an HTTP envelope.

Group A creates the base ``AppError`` and ``ConfigError`` (consumed by E1-S2).
Later stories extend this module:

* ``RepositoryError``  — E2-S2 (MySQL failures)
* ``RetrievalError``   — E4-S1 (Pinecone failures)
* ``EmbeddingError``   — E3-S2 (Gemini embedding failures)
* ``GenerationError``  — E6-S2 (Gemini generation failures)
"""


class AppError(Exception):
    """Base class for all typed domain errors.

    Carries a machine-readable ``code`` (UPPER_SNAKE_CASE) so the API layer can
    map errors to a stable error envelope without string matching on messages.
    """

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class ConfigError(AppError):
    """Missing or invalid configuration / secrets (E1-S2 AC-4)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="CONFIG_ERROR")


class RepositoryError(AppError):
    """MySQL connection / query / schema failures.

    Maps to HTTP 503 ``MYSQL_UNAVAILABLE`` at the API edge
    (error-handling-strategy.md §3). Created here for the schema-init runner
    (E2-S1); the product repository (E2-S2) raises the same type.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, code="MYSQL_UNAVAILABLE")


class EmbeddingError(AppError):
    """Gemini embedding failures (E3-S2 AC-3).

    The embedding client (E3-S2) catches raw Google GenAI SDK exceptions and
    re-raises this so no SDK type leaks to callers. Maps to the BRD "service
    temporarily unavailable" user message at the API edge.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, code="EMBEDDING_UNAVAILABLE")


class RetrievalError(AppError):
    """Pinecone connection / provisioning / query failures (E4-S1 AC-4).

    The Pinecone client (E4-S1) catches raw SDK exceptions and re-raises this
    so no SDK type leaks to callers. Maps to HTTP 503 at the API edge
    (error-handling-strategy.md §3).
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, code="PINECONE_UNAVAILABLE")


class GenerationError(AppError):
    """LLM generation failures — filter extraction (E5-S1) & answer generation (E6-S2).

    The generation provider wrapper (Groq by default, Gemini legacy) catches raw
    SDK exceptions — rate limit, invalid key, timeout, connection/server error —
    and classifies them as this typed error so no SDK type leaks into handling.
    The answer generator translates it into the BRD user-facing "AI assistant is
    temporarily unavailable" message; at the API edge it maps to the same 503
    degraded response (code ``GEMINI_UNAVAILABLE``, kept stable per api-contracts).
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, code="GENERATION_UNAVAILABLE")
