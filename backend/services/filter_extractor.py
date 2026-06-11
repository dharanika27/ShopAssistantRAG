"""LLM filter extraction with enum normalization (E5-S1).

Translates a natural-language query into a structured :class:`QueryFilters`
object using LLM structured JSON output, then runs a normalization layer that
maps synonyms onto the canonical catalog vocabulary (Crimson -> Red,
Trainers -> Shoes) and discards values outside that vocabulary (BRD risk R-2).

The LLM call is delegated to the configured generation provider
(:mod:`backend.services.llm_provider` — Groq by default, Gemini legacy); this
module never imports an LLM SDK directly. The ``extract_fn`` is injected so unit
tests substitute model output without any live API.

Per E5-S1 AC-5 the extractor must *never crash* on malformed model output: a
non-JSON or schema-invalid response yields an empty :class:`QueryFilters` (all
``None``) so the downstream retriever simply runs unfiltered. This explicit,
acceptance-criterion-mandated degradation is the one place the "no silent LLM
fallback" guideline yields to a documented product requirement; the raw response
is logged at WARNING so the event remains observable.
"""

import json
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from backend.core.config import Settings
from backend.core.errors import GenerationError
from backend.core.logging import get_logger
from backend.domain.enums import Category, Gender
from backend.domain.models import QueryFilters
from backend.services.llm_provider import build_completion_fn

logger = get_logger(__name__)

ExtractFn = Callable[..., str]

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "filter_extraction.txt"
_QUERY_PLACEHOLDER = "{{QUERY}}"

_COLOR_SYNONYMS: dict[str, str] = {
    "crimson": "Red",
    "scarlet": "Red",
    "ruby": "Red",
    "navy": "Blue",
    "azure": "Blue",
    "cobalt": "Blue",
    "emerald": "Green",
    "olive": "Green",
    "charcoal": "Black",
    "ebony": "Black",
    "ivory": "White",
    "cream": "White",
    "gold": "Yellow",
    "amber": "Yellow",
}

_CATEGORY_SYNONYMS: dict[str, Category] = {
    "trainers": Category.SHOES,
    "sneakers": Category.SHOES,
    "footwear": Category.SHOES,
    "apparel": Category.CLOTHING,
    "clothes": Category.CLOTHING,
    "garments": Category.CLOTHING,
    "activewear": Category.SPORTSWEAR,
    "athleisure": Category.SPORTSWEAR,
    "handbags": Category.BAGS,
    "purses": Category.BAGS,
    "accessory": Category.ACCESSORIES,
}


class _RawFilters(BaseModel):
    """Loose schema the model is asked to emit, before normalization (E5-S1)."""

    brand: str | None = None
    color: str | None = None
    category: str | None = None
    gender: str | None = None
    min_price: Decimal | None = None
    max_price: Decimal | None = None


class FilterExtractor:
    """Natural-language query -> normalized :class:`QueryFilters` (E5-S1)."""

    def __init__(self, settings: Settings, *, extract_fn: ExtractFn | None = None) -> None:
        self._model = settings.active_generation_model()
        self._extract_fn = extract_fn or build_completion_fn(settings)
        self._prompt_template = _PROMPT_PATH.read_text(encoding="utf-8")

    def extract(self, query: str) -> QueryFilters:
        """Extract normalized filters from ``query`` (E5-S1 AC-1..AC-4).

        Two distinct failure modes are handled differently:

        * *Malformed model output* (non-JSON / schema-invalid) degrades to an
          empty :class:`QueryFilters` so retrieval simply runs unfiltered, never
          raising (AC-5).
        * A *Gemini API/transport failure* (e.g. a 503 ``high demand`` response)
          is a service outage, not a parse problem: it is caught at this wrapper
          boundary and re-raised as a typed :class:`GenerationError` so no raw
          SDK type leaks, and the API edge maps it to the BRD "AI assistant is
          temporarily unavailable" envelope (BRD §9.1) instead of a 500.
        """
        prompt = self._prompt_template.replace(_QUERY_PLACEHOLDER, query)
        try:
            raw = self._extract_fn(model=self._model, prompt=prompt)
        except Exception as exc:
            logger.error("filter_extraction.request_failed", extra={"model": self._model})
            raise GenerationError(
                f"Gemini filter-extraction request failed: {exc}"
            ) from exc
        logger.debug("filter_extraction.raw_response", extra={"raw": raw[:1000]})
        parsed = _parse_raw_filters(raw)
        if parsed is None:
            return QueryFilters()
        return _normalize(parsed)


def _parse_raw_filters(raw: str) -> _RawFilters | None:
    """Parse the model text into ``_RawFilters``; ``None`` on any malformation."""
    payload = _extract_json_object(raw)
    if payload is None:
        logger.warning("filter_extraction.unparseable", extra={"raw": raw[:200]})
        return None
    try:
        return _RawFilters.model_validate(payload)
    except ValidationError:
        logger.warning("filter_extraction.schema_invalid", extra={"raw": raw[:200]})
        return None


def _extract_json_object(raw: str) -> dict[str, Any] | None:
    """Return the JSON object encoded in ``raw``, or ``None`` if it is not one.

    Tolerates a Markdown code fence around the JSON; rejects non-object JSON
    (e.g. arrays) so downstream validation always sees a mapping.
    """
    candidate = _strip_code_fence(raw).strip()
    try:
        decoded = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return None
    return decoded if isinstance(decoded, dict) else None


def _strip_code_fence(raw: str) -> str:
    text = raw.strip()
    if not text.startswith("```"):
        return text
    inner = text[3:]
    if inner.lower().startswith("json"):
        inner = inner[4:]
    return inner.rsplit("```", 1)[0]


def _normalize(parsed: _RawFilters) -> QueryFilters:
    """Map raw values onto canonical enums, dropping out-of-vocab ones (AC-2/3)."""
    return QueryFilters(
        brand=_clean_text(parsed.brand),
        color=_normalize_color(parsed.color),
        category=_normalize_category(parsed.category),
        gender=_normalize_gender(parsed.gender),
        min_price=_normalize_price(parsed.min_price),
        max_price=_normalize_price(parsed.max_price),
    )


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_color(value: str | None) -> str | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None
    canonical = _COLOR_SYNONYMS.get(cleaned.lower())
    return canonical or cleaned.capitalize()


def _normalize_category(value: str | None) -> Category | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None
    direct = _match_enum(Category, cleaned)
    if direct is not None:
        return direct
    return _CATEGORY_SYNONYMS.get(cleaned.lower())


def _normalize_gender(value: str | None) -> Gender | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None
    return _match_enum(Gender, cleaned)


_EnumT = TypeVar("_EnumT", Category, Gender)


def _match_enum(enum_cls: type[_EnumT], value: str) -> _EnumT | None:
    """Case-insensitively match ``value`` to a member of ``enum_cls``."""
    lowered = value.lower()
    for member in enum_cls:
        if member.value.lower() == lowered:
            return member
    return None


def _normalize_price(value: Decimal | None) -> Decimal | None:
    """Drop missing or non-positive prices (a price filter must be > 0)."""
    if value is None:
        return None
    try:
        if value <= 0:
            return None
    except InvalidOperation:
        return None
    return value
