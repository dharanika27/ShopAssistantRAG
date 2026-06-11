"""Grounded RAG answer generation (E6-S2).

Assembles the hydrated :class:`Product` records into a strictly grounded prompt
and asks the configured LLM provider for a natural-language recommendation that
references only those products — never an invented product, price, or attribute
(BRD grounding requirement, risk R-3; AC-1, AC-2).

The LLM call is delegated to the configured generation provider
(:mod:`backend.services.llm_provider` — Groq by default, Gemini legacy); this
module never imports an LLM SDK directly. The ``generate_fn`` is injected so unit
tests substitute model output without the live API (AC mirrors E3-S2 AC-5).

Two acceptance criteria shape the control flow:

* Empty context (no retrieved products) short-circuits *before* any model call
  and returns a friendly no-match message that suggests the available catalog
  categories rather than inventing products (AC-3).
* A Gemini failure is caught at this service boundary, classified as a typed
  :class:`GenerationError` (so no raw SDK type leaks into our logs/handling),
  logged at ERROR, and translated into the BRD user-facing message
  (:data:`UNAVAILABLE_MESSAGE`) rather than surfacing an exception or stack
  trace to the caller (AC-5). This acceptance-criterion-mandated degradation is
  the documented exception to the "no silent LLM fallback" guideline — the
  failure stays observable via the ERROR log, it is not swallowed silently.
"""

from collections.abc import Callable
from pathlib import Path

from backend.core.config import Settings
from backend.core.errors import GenerationError
from backend.core.logging import get_logger
from backend.domain.enums import Category
from backend.domain.models import Product
from backend.services.llm_provider import build_completion_fn

logger = get_logger(__name__)

GenerateFn = Callable[..., str]

UNAVAILABLE_MESSAGE = (
    "The AI assistant is temporarily unavailable. Please try again in a moment."
)

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "answer_generation.txt"
_PRODUCTS_PLACEHOLDER = "{{PRODUCTS}}"
_QUERY_PLACEHOLDER = "{{QUERY}}"

_CATEGORY_SUGGESTIONS = ", ".join(category.value for category in Category)
_NO_MATCH_MESSAGE = (
    "I couldn't find any products matching that request. "
    f"You might try one of our categories: {_CATEGORY_SUGGESTIONS}."
)


class AnswerGenerator:
    """Grounded Gemini answer generation over hydrated products (E6-S2)."""

    def __init__(self, settings: Settings, *, generate_fn: GenerateFn | None = None) -> None:
        self._model = settings.active_generation_model()
        self._generate_fn = generate_fn or build_completion_fn(settings)
        self._prompt_template = _PROMPT_PATH.read_text(encoding="utf-8")

    def generate(self, query: str, products: list[Product]) -> str:
        """Return a grounded reply for ``query`` over ``products`` (E6-S2 AC-1..AC-5).

        With no products this returns the no-match message without calling the
        model (AC-3). A model failure returns :data:`UNAVAILABLE_MESSAGE` (AC-5).
        """
        if not products:
            logger.info("answer_generator.no_context", extra={"query_length": len(query)})
            return _NO_MATCH_MESSAGE
        prompt = self._build_prompt(query, products)
        return self._invoke(prompt, product_count=len(products))

    def _build_prompt(self, query: str, products: list[Product]) -> str:
        context = _format_products(products)
        return self._prompt_template.replace(_PRODUCTS_PLACEHOLDER, context).replace(
            _QUERY_PLACEHOLDER, query
        )

    def _invoke(self, prompt: str, *, product_count: int) -> str:
        try:
            reply = self._generate_fn(model=self._model, prompt=prompt)
        except Exception as exc:
            logger.error(
                "answer_generator.generation_failed",
                extra={"model": self._model, "product_count": product_count},
            )
            error = GenerationError(f"Gemini generation request failed: {exc}")
            return _user_message_for(error)
        logger.debug(
            "answer_generator.raw_response",
            extra={"model": self._model, "raw_content": reply[:1000]},
        )
        return reply


def _format_products(products: list[Product]) -> str:
    """Render products as a compact, grounded context block (E6-S2 AC-1)."""
    return "\n".join(_format_product(index, product) for index, product in enumerate(products, 1))


def _format_product(index: int, product: Product) -> str:
    parts = [
        f"name={product.name}",
        f"brand={product.brand or 'N/A'}",
        f"category={product.category.value}",
        f"color={product.color or 'N/A'}",
        f"price={product.price}",
        f"in_stock={product.in_stock}",
    ]
    return f"{index}. " + ", ".join(parts)


def _user_message_for(error: GenerationError) -> str:
    """Translate a generation failure into the BRD user-facing message (AC-5)."""
    logger.warning("answer_generator.degraded_response", extra={"code": error.code})
    return UNAVAILABLE_MESSAGE
