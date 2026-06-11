"""Multi-turn chat orchestration (E6-S3).

The conversational core (risk R-1). One :meth:`ChatOrchestrator.handle_turn`
call runs a full turn: filter extraction -> accumulating session-state
transition -> fresh hybrid retrieval -> MySQL hydration -> grounded generation,
plus the BRD context-reset and edge-case rules.

Transition rules (session-memory-design.md §4):

* **Refine / accumulate** ("only red ones") merges the turn's non-``None``
  extracted fields onto the session's accumulated filters and rebuilds a fresh
  retrieval — it never re-filters the prior result list (AC-1).
* **Cheaper** ("cheaper options") lowers the current upper price ceiling below
  the cheapest product from the previous turn (or below an explicit ceiling) and
  re-runs retrieval (AC-2).
* **Category change** ("Now show me bags") or **explicit reset** ("forget
  previous search") clears the accumulated filters (AC-3).
* **No match** -> friendly message with category suggestions and zero cards
  (AC-4); the answer generator owns that message (E6-S2 AC-3).
* **Greeting / small talk / invalid** -> scoped conversational reply with no
  retrieval (AC-5).
* Every turn returns a natural-language reply plus up to five grounded product
  cards (AC-6).

Collaborators are injected as narrow :class:`Protocol`s so this orchestration
logic is unit-testable without live Gemini/Pinecone/MySQL; intent detection uses
the extractor's structured output plus light keyword rules kept here so the
behavior stays testable with mocked services (session-memory-design.md §4).
"""

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum, auto
from typing import Protocol

from backend.core.logging import get_logger
from backend.domain.enums import Category
from backend.domain.models import Product, QueryFilters
from backend.services.query_state import QueryStateManager, SessionState, TurnRole

logger = get_logger(__name__)

MAX_PRODUCT_CARDS = 5
_CHEAPER_FACTOR = Decimal("0.8")

_GREETING_PHRASES = frozenset(
    {"hi", "hello", "hey", "yo", "hiya", "good morning", "good afternoon",
     "good evening", "what can you do", "help", "how are you", "thanks", "thank you"}
)
_RESET_PHRASES = ("forget previous", "start over", "reset", "clear search",
                  "forget that", "never mind")
_CHEAPER_PHRASES = ("cheaper", "less expensive", "lower price", "more affordable",
                    "budget")
_MERGEABLE_FIELDS = ("brand", "color", "category", "gender", "min_price", "max_price")

# Product types the catalog does not stock. A query naming one of these is a
# clean no-match even when it also carries a parseable filter (e.g. a price), so
# "smartphone under 20000" returns a friendly "not in our catalog" reply instead
# of retrieving unrelated products on the price filter alone. Curated and
# extensible — matched as whole, lower-cased word tokens.
_OUT_OF_CATALOG_TERMS = frozenset({
    "laptop", "laptops", "computer", "computers", "pc", "desktop",
    "smartphone", "smartphones", "phone", "phones", "mobile", "iphone", "android",
    "tablet", "tablets", "ipad", "tv", "television", "televisions", "monitor",
    "camera", "cameras", "headphone", "headphones", "earphone", "earphones",
    "earbud", "earbuds", "speaker", "speakers", "console", "playstation", "xbox",
    "watch", "watches", "smartwatch",
    "grocery", "groceries", "food", "snack", "snacks", "beverage", "drink", "drinks",
    "furniture", "sofa", "mattress", "fridge", "refrigerator", "microwave",
    "book", "books", "toy", "toys", "jewelry", "jewellery", "perfume", "fragrance",
    "makeup", "cosmetic", "cosmetics", "medicine", "car", "bicycle",
})


class TurnIntent(Enum):
    """The orchestrator's classification of an incoming turn."""

    GREETING = auto()
    INVALID = auto()
    OUT_OF_CATALOG = auto()
    RESET = auto()
    CHEAPER = auto()
    CATEGORY_CHANGE = auto()
    REFINE = auto()


@dataclass(frozen=True)
class ChatResult:
    """One chat turn's output: a grounded reply and up to five product cards."""

    reply: str
    products: list[Product]


class SupportsFilterExtraction(Protocol):
    def extract(self, query: str) -> QueryFilters: ...


class SupportsRetrieval(Protocol):
    def retrieve(self, query: str, filters: QueryFilters) -> list[str]: ...


class SupportsHydration(Protocol):
    def hydrate(self, product_ids: list[str]) -> list[Product]: ...


class SupportsAnswerGeneration(Protocol):
    def generate(self, query: str, products: list[Product]) -> str: ...


class ChatOrchestrator:
    """End-to-end conversational turn orchestration (E6-S3)."""

    def __init__(
        self,
        *,
        filter_extractor: SupportsFilterExtraction,
        state_manager: QueryStateManager,
        retriever: SupportsRetrieval,
        hydrator: SupportsHydration,
        answer_generator: SupportsAnswerGeneration,
    ) -> None:
        self._filter_extractor = filter_extractor
        self._state_manager = state_manager
        self._retriever = retriever
        self._hydrator = hydrator
        self._answer_generator = answer_generator

    def handle_turn(self, session_id: str, message: str) -> ChatResult:
        """Run one full conversational turn for ``session_id`` (E6-S3 AC-1..AC-6)."""
        self._state_manager.append_turn(session_id, TurnRole.USER, message)
        extracted = self._filter_extractor.extract(message)
        intent = _classify_intent(message, extracted, self._state_manager.get_or_create(session_id))
        logger.info(
            "chat_orchestrator.turn",
            extra={"session_id": session_id, "intent": intent.name},
        )
        result = self._dispatch(session_id, message, extracted, intent)
        self._state_manager.append_turn(session_id, TurnRole.ASSISTANT, result.reply)
        return result

    def _dispatch(
        self, session_id: str, message: str, extracted: QueryFilters, intent: TurnIntent
    ) -> ChatResult:
        if intent is TurnIntent.OUT_OF_CATALOG:
            return ChatResult(reply=_out_of_catalog_reply(message), products=[])
        if intent in (TurnIntent.GREETING, TurnIntent.INVALID):
            return ChatResult(reply=_conversational_reply(intent), products=[])
        filters = self._apply_transition(session_id, extracted, intent)
        return self._retrieve_and_generate(session_id, message, filters)

    def _apply_transition(
        self, session_id: str, extracted: QueryFilters, intent: TurnIntent
    ) -> QueryFilters:
        """Update accumulated session filters for a retrieval intent (AC-1..AC-3)."""
        if intent is TurnIntent.RESET:
            return self._state_manager.reset(session_id).filters
        state = self._state_manager.get_or_create(session_id)
        if intent is TurnIntent.CATEGORY_CHANGE:
            _reset_to_category(state, extracted)
        else:
            _merge_extracted(state, extracted)
        if intent is TurnIntent.CHEAPER:
            _lower_price_ceiling(state)
        return state.filters

    def _retrieve_and_generate(
        self, session_id: str, message: str, filters: QueryFilters
    ) -> ChatResult:
        product_ids = self._retriever.retrieve(message, filters)
        products = self._hydrator.hydrate(product_ids)[:MAX_PRODUCT_CARDS]
        self._record_result_floor(session_id, products)
        reply = self._answer_generator.generate(message, products)
        return ChatResult(reply=reply, products=products)

    def _record_result_floor(self, session_id: str, products: list[Product]) -> None:
        """Remember the cheapest current product so 'cheaper' can undercut it."""
        if not products:
            return
        state = self._state_manager.get_or_create(session_id)
        state.last_result_min_price = min(product.price for product in products)


def _classify_intent(
    message: str, extracted: QueryFilters, state: SessionState
) -> TurnIntent:
    """Classify the turn from keywords + extracted filters (session-design §4)."""
    normalized = message.strip().lower()
    if _matches_any(normalized, _RESET_PHRASES):
        return TurnIntent.RESET
    if _out_of_catalog_term(message) is not None:
        return TurnIntent.OUT_OF_CATALOG
    if _matches_any(normalized, _CHEAPER_PHRASES):
        return TurnIntent.CHEAPER
    if _is_category_change(extracted, state):
        return TurnIntent.CATEGORY_CHANGE
    if _has_any_filter(extracted):
        return TurnIntent.REFINE
    if _is_greeting(normalized):
        return TurnIntent.GREETING
    return TurnIntent.INVALID


def _matches_any(normalized: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in normalized for phrase in phrases)


def _is_greeting(normalized: str) -> bool:
    if normalized in _GREETING_PHRASES:
        return True
    first_word = normalized.split(" ", 1)[0] if normalized else ""
    return first_word in _GREETING_PHRASES


def _is_category_change(extracted: QueryFilters, state: SessionState) -> bool:
    return (
        extracted.category is not None
        and state.last_category is not None
        and extracted.category != state.last_category
    )


def _has_any_filter(filters: QueryFilters) -> bool:
    return any(getattr(filters, field) is not None for field in _MERGEABLE_FIELDS)


def _reset_to_category(state: SessionState, extracted: QueryFilters) -> None:
    """Category change: drop accumulated filters, keep only the new category (AC-3)."""
    state.filters = QueryFilters(category=extracted.category)
    state.last_category = extracted.category
    state.last_result_min_price = None


def _merge_extracted(state: SessionState, extracted: QueryFilters) -> None:
    """Merge the turn's non-``None`` extracted fields onto accumulated state (AC-1)."""
    for field in _MERGEABLE_FIELDS:
        value = getattr(extracted, field)
        if value is not None:
            setattr(state.filters, field, value)
    if extracted.category is not None:
        state.last_category = extracted.category


def _lower_price_ceiling(state: SessionState) -> None:
    """Lower ``max_price`` below the current ceiling / cheapest result (AC-2)."""
    candidates = [
        ceiling
        for ceiling in (state.filters.max_price, state.last_result_min_price)
        if ceiling is not None
    ]
    if not candidates:
        return
    state.filters.max_price = min(candidates) * _CHEAPER_FACTOR


def _out_of_catalog_term(message: str) -> str | None:
    """Return the first out-of-catalog product token in ``message``, else None."""
    for token in re.findall(r"[a-z]+", message.lower()):
        if token in _OUT_OF_CATALOG_TERMS:
            return token
    return None


def _out_of_catalog_reply(message: str) -> str:
    """Friendly no-match for an unsupported product type, listing real categories."""
    term = _out_of_catalog_term(message) or "that"
    categories = ", ".join(category.value for category in Category)
    return (
        f'Sorry, "{term}" isn\'t in our catalog. We carry {categories}. '
        "Tell me what you'd like from those and I'll find matches."
    )


def _conversational_reply(intent: TurnIntent) -> str:
    """Scoped reply for greetings/small talk and unrecognized queries (AC-5)."""
    if intent is TurnIntent.GREETING:
        return (
            "Hi! I'm your shopping assistant. Tell me what you're looking for — "
            "for example 'red Nike running shoes under 3000' — and I'll find matches."
        )
    return (
        "I'm not sure what you're after. Try describing a product, like "
        "'black leather bags' or 'women's sportswear under 2000'."
    )
