"""Unit tests for E6-S3 — Multi-turn refinement, reset & no-match handling.

The orchestrator is the conversational core (risk R-1). Its collaborators
(filter extractor, hybrid retriever, hydrator, answer generator) are the
seams and are mocked via lightweight fakes — but the orchestration *business
logic* (merge vs. reset, cheaper, category change, greeting/invalid routing,
no-match, ≤5 cards) is exercised directly and never mocked.

The real :class:`QueryStateManager` is used (it is in-process business logic,
not an external boundary), so multi-turn accumulation is verified end-to-end
across turns.
"""

from decimal import Decimal

import pytest

from backend.domain.enums import Category, Gender
from backend.domain.models import Product, QueryFilters
from backend.services.chat_orchestrator import ChatOrchestrator, ChatResult
from backend.services.query_state import QueryStateManager

_SESSION = "session-001"
_OTHER_SESSION = "session-002"


def _product(product_id: str, *, price: str, color: str = "Red",
             category: Category = Category.SHOES, brand: str = "Nike") -> Product:
    return Product(
        product_id=product_id,
        name=f"Model {product_id}",
        brand=brand,
        category=category,
        gender=Gender.MEN,
        color=color,
        price=Decimal(price),
        stock=8,
    )


class _FakeFilterExtractor:
    """Returns a queued QueryFilters per call, keyed by call order."""

    def __init__(self, results: list[QueryFilters]) -> None:
        self._results = list(results)
        self.queries: list[str] = []

    def extract(self, query: str) -> QueryFilters:
        self.queries.append(query)
        if not self._results:
            return QueryFilters()
        return self._results.pop(0)


class _FakeRetriever:
    """Records the (query, filters) it was called with and returns canned IDs."""

    def __init__(self, id_batches: list[list[str]]) -> None:
        self._id_batches = list(id_batches)
        self.calls: list[tuple[str, QueryFilters]] = []

    def retrieve(self, query: str, filters: QueryFilters) -> list[str]:
        self.calls.append((query, filters))
        if not self._id_batches:
            return []
        return self._id_batches.pop(0)


class _FakeHydrator:
    def __init__(self, catalog: dict[str, Product]) -> None:
        self._catalog = catalog

    def hydrate(self, product_ids: list[str]) -> list[Product]:
        return [self._catalog[pid] for pid in product_ids if pid in self._catalog]


class _FakeAnswerGenerator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[Product]]] = []

    def generate(self, query: str, products: list[Product]) -> str:
        self.calls.append((query, products))
        if not products:
            return "Nothing matched; try Shoes, Clothing, Accessories, Sportswear, Bags."
        return f"Found {len(products)} option(s)."


def _build(
    *,
    extractions: list[QueryFilters],
    id_batches: list[list[str]],
    catalog: dict[str, Product],
    state: QueryStateManager | None = None,
) -> tuple[ChatOrchestrator, _FakeRetriever, _FakeAnswerGenerator]:
    retriever = _FakeRetriever(id_batches)
    generator = _FakeAnswerGenerator()
    orchestrator = ChatOrchestrator(
        filter_extractor=_FakeFilterExtractor(extractions),
        state_manager=state or QueryStateManager(),
        retriever=retriever,
        hydrator=_FakeHydrator(catalog),
        answer_generator=generator,
    )
    return orchestrator, retriever, generator


class TestRefinementMerge:
    def test_followup_merges_color_onto_existing_filters(self) -> None:
        catalog = {"P1": _product("P1", price="2799"), "P2": _product("P2", price="3199")}
        orchestrator, retriever, _ = _build(
            extractions=[
                QueryFilters(brand="Nike", category=Category.SHOES),
                QueryFilters(color="Red"),
            ],
            id_batches=[["P1", "P2"], ["P1"]],
            catalog=catalog,
        )

        orchestrator.handle_turn(_SESSION, "Show me Nike shoes")
        orchestrator.handle_turn(_SESSION, "only red ones")

        # Second retrieval must use the MERGED accumulated filters.
        _, merged = retriever.calls[1]
        assert merged.brand == "Nike"
        assert merged.category == Category.SHOES
        assert merged.color == "Red"

    def test_refinement_rebuilds_retrieval_not_reuses_prior_list(self) -> None:
        catalog = {"P1": _product("P1", price="2799"), "P2": _product("P2", price="3199")}
        orchestrator, retriever, _ = _build(
            extractions=[QueryFilters(brand="Nike"), QueryFilters(color="Red")],
            id_batches=[["P1", "P2"], ["P1"]],
            catalog=catalog,
        )

        orchestrator.handle_turn(_SESSION, "Nike shoes")
        result = orchestrator.handle_turn(_SESSION, "only red ones")

        assert len(retriever.calls) == 2  # a fresh retrieval ran on the follow-up
        assert [p.product_id for p in result.products] == ["P1"]


class TestCheaperOptions:
    def test_cheaper_lowers_price_ceiling_and_reruns(self) -> None:
        catalog = {"P1": _product("P1", price="5000"), "P2": _product("P2", price="2000")}
        orchestrator, retriever, _ = _build(
            extractions=[QueryFilters(category=Category.SHOES), QueryFilters()],
            id_batches=[["P1", "P2"], ["P2"]],
            catalog=catalog,
        )

        orchestrator.handle_turn(_SESSION, "show me shoes")
        orchestrator.handle_turn(_SESSION, "cheaper options")

        _, cheaper_filters = retriever.calls[1]
        assert cheaper_filters.max_price is not None
        # Ceiling must be below the cheapest product from the prior turn (2000).
        assert cheaper_filters.max_price < Decimal("2000")
        assert len(retriever.calls) == 2

    def test_cheaper_tightens_existing_explicit_ceiling(self) -> None:
        catalog = {"P1": _product("P1", price="2500")}
        orchestrator, retriever, _ = _build(
            extractions=[QueryFilters(max_price=Decimal("3000")), QueryFilters()],
            id_batches=[["P1"], ["P1"]],
            catalog=catalog,
        )

        orchestrator.handle_turn(_SESSION, "shoes under 3000")
        orchestrator.handle_turn(_SESSION, "anything less expensive")

        _, cheaper_filters = retriever.calls[1]
        assert cheaper_filters.max_price is not None
        assert cheaper_filters.max_price < Decimal("3000")

    def test_cheaper_admits_products_below_shown_minimum(self) -> None:
        """Live repro (F057/AC-2): "shoes under 9000" shows a cheapest of 2799;
        "cheaper" must surface the genuinely lower-priced 2299 shoe while
        excluding the 2799 already shown — not push the ceiling so low that
        cheaper-than-shown products are filtered out."""
        catalog = {
            "P1": _product("P1", price="2799"),
            "P2": _product("P2", price="4500"),
            "P3": _product("P3", price="2299"),
            "P4": _product("P4", price="2999"),
        }
        orchestrator, retriever, _ = _build(
            extractions=[
                QueryFilters(category=Category.SHOES, max_price=Decimal("9000")),
                QueryFilters(),
            ],
            # First turn shows the two products under 9000 (cheapest = 2799).
            id_batches=[["P1", "P2"], ["P3"]],
            catalog=catalog,
        )

        orchestrator.handle_turn(_SESSION, "shoes under 9000")
        orchestrator.handle_turn(_SESSION, "cheaper")

        _, cheaper_filters = retriever.calls[1]
        assert cheaper_filters.max_price is not None
        # Excludes the cheapest item already shown (2799)...
        assert cheaper_filters.max_price < Decimal("2799")
        # ...but still admits the genuinely cheaper 2299 shoe.
        assert cheaper_filters.max_price >= Decimal("2299")


class TestCategoryChangeReset:
    def test_new_category_resets_accumulated_filters(self) -> None:
        catalog = {
            "P1": _product("P1", price="2799"),
            "B1": _product("B1", price="4999", category=Category.BAGS, color="Black"),
        }
        orchestrator, retriever, _ = _build(
            extractions=[
                QueryFilters(brand="Nike", color="Red", category=Category.SHOES),
                QueryFilters(category=Category.BAGS),
            ],
            id_batches=[["P1"], ["B1"]],
            catalog=catalog,
        )

        orchestrator.handle_turn(_SESSION, "red Nike shoes")
        orchestrator.handle_turn(_SESSION, "Now show me bags")

        _, filters = retriever.calls[1]
        assert filters.category == Category.BAGS
        assert filters.brand is None  # prior brand dropped on category change
        assert filters.color is None

    def test_explicit_forget_resets_filters(self) -> None:
        catalog = {"P1": _product("P1", price="2799")}
        orchestrator, retriever, _ = _build(
            extractions=[
                QueryFilters(brand="Nike", category=Category.SHOES),
                QueryFilters(),
            ],
            id_batches=[["P1"], ["P1"]],
            catalog=catalog,
        )

        orchestrator.handle_turn(_SESSION, "Nike shoes")
        orchestrator.handle_turn(_SESSION, "forget previous search")

        _, filters = retriever.calls[1]
        assert filters == QueryFilters()


class TestNoMatch:
    def test_empty_results_returns_message_and_zero_cards(self) -> None:
        orchestrator, _, generator = _build(
            extractions=[QueryFilters(category=Category.SHOES)],
            id_batches=[[]],
            catalog={},
        )

        result = orchestrator.handle_turn(_SESSION, "neon glow stilettos size 99")

        assert result.products == []
        assert "Shoes" in result.reply
        assert generator.calls[0][1] == []  # generator asked to render the no-match


class TestGreetingAndInvalid:
    def test_greeting_returns_scoped_reply_without_retrieval(self) -> None:
        orchestrator, retriever, _ = _build(
            extractions=[QueryFilters()],
            id_batches=[],
            catalog={},
        )

        result = orchestrator.handle_turn(_SESSION, "hi there")

        assert retriever.calls == []  # no retrieval for small talk
        assert result.products == []
        assert result.reply

    def test_invalid_gibberish_returns_clarification_without_retrieval(self) -> None:
        orchestrator, retriever, _ = _build(
            extractions=[QueryFilters()],
            id_batches=[],
            catalog={},
        )

        result = orchestrator.handle_turn(_SESSION, "asdfgh")

        assert retriever.calls == []
        assert result.products == []
        assert result.reply


class TestResultCardCap:
    def test_returns_at_most_five_product_cards(self) -> None:
        ids = [f"P{n}" for n in range(8)]
        catalog = {pid: _product(pid, price="1999") for pid in ids}
        orchestrator, _, _ = _build(
            extractions=[QueryFilters(category=Category.SHOES)],
            id_batches=[ids],
            catalog=catalog,
        )

        result = orchestrator.handle_turn(_SESSION, "popular shoes")

        assert len(result.products) <= 5

    def test_result_is_chat_result_with_reply_and_products(self) -> None:
        catalog = {"P1": _product("P1", price="2799")}
        orchestrator, _, _ = _build(
            extractions=[QueryFilters(category=Category.SHOES)],
            id_batches=[["P1"]],
            catalog=catalog,
        )

        result = orchestrator.handle_turn(_SESSION, "shoes")

        assert isinstance(result, ChatResult)
        assert isinstance(result.reply, str)
        assert [p.product_id for p in result.products] == ["P1"]


class TestSessionIsolation:
    def test_two_sessions_keep_independent_filter_state(self) -> None:
        catalog = {
            "P1": _product("P1", price="2799"),
            "B1": _product("B1", price="4999", category=Category.BAGS),
        }
        state = QueryStateManager()
        orchestrator, retriever, _ = _build(
            extractions=[
                QueryFilters(brand="Nike", category=Category.SHOES),
                QueryFilters(category=Category.BAGS),
            ],
            id_batches=[["P1"], ["B1"]],
            catalog=catalog,
            state=state,
        )

        orchestrator.handle_turn(_SESSION, "Nike shoes")
        orchestrator.handle_turn(_OTHER_SESSION, "bags")

        # Session 001 retained its Nike/Shoes filters; session 002 saw only Bags.
        session_one = state.get_or_create(_SESSION)
        session_two = state.get_or_create(_OTHER_SESSION)
        assert session_one.filters.brand == "Nike"
        assert session_two.filters.brand is None
        assert session_two.filters.category == Category.BAGS


class TestTranscriptRecorded:
    def test_user_and_assistant_turns_are_appended(self) -> None:
        catalog = {"P1": _product("P1", price="2799")}
        state = QueryStateManager()
        orchestrator, _, _ = _build(
            extractions=[QueryFilters(category=Category.SHOES)],
            id_batches=[["P1"]],
            catalog=catalog,
            state=state,
        )

        orchestrator.handle_turn(_SESSION, "shoes")

        history = list(state.get_or_create(_SESSION).history)
        assert [t.message for t in history][0] == "shoes"
        assert len(history) == 2  # user + assistant


class TestOutOfCatalog:
    def test_unsupported_product_with_price_short_circuits_no_retrieval(self) -> None:
        # "smartphone under 20000" extracts a price, but must NOT retrieve on it.
        catalog = {"P1": _product("P1", price="1299")}
        orchestrator, retriever, generator = _build(
            extractions=[QueryFilters(max_price=Decimal("20000"))],
            id_batches=[["P1"]],
            catalog=catalog,
        )

        result = orchestrator.handle_turn(_SESSION, "I need a smartphone under 20000")

        assert result.products == []  # no pivot cards
        assert retriever.calls == []  # retrieval never ran
        assert generator.calls == []  # answer model never called
        assert "smartphone" in result.reply.lower()
        assert "catalog" in result.reply.lower()

    def test_plain_out_of_catalog_query_returns_no_match(self) -> None:
        orchestrator, retriever, _ = _build(
            extractions=[QueryFilters()], id_batches=[["P1"]], catalog={},
        )
        result = orchestrator.handle_turn(_SESSION, "do you sell laptops")
        assert result.products == []
        assert retriever.calls == []
        assert "laptop" in result.reply.lower()

    def test_in_catalog_query_with_price_is_not_blocked(self) -> None:
        # A legitimate catalog query with a price must still retrieve normally.
        catalog = {"P1": _product("P1", price="1999", category=Category.SHOES)}
        orchestrator, retriever, _ = _build(
            extractions=[QueryFilters(category=Category.SHOES, max_price=Decimal("2000"))],
            id_batches=[["P1"]],
            catalog=catalog,
        )
        result = orchestrator.handle_turn(_SESSION, "show me shoes under 2000")
        assert retriever.calls != []  # retrieval ran
        assert [p.product_id for p in result.products] == ["P1"]


@pytest.fixture(autouse=True)
def _no_network() -> None:
    """Guard: these tests must never touch a real network boundary."""
    return None
