"""End-to-end test of the core user journey (E9-S2, BRD DoD item 14).

Exercises the full browse -> query -> refine -> no-match journey across the real
stack seams: the Streamlit :class:`ApiClient` (frontend) talks HTTP to the real
FastAPI routers, middleware, schemas, and serialization (backend). Only the two
external boundaries are faked -- the chat orchestrator (Gemini/Pinecone) and the
MySQL product repository -- per the code-gen rule "mock external boundaries
only". Every other line of the request path runs for real.

The ``ApiClient`` is pointed at an in-process ``TestClient`` via the
:class:`_HttpSession` protocol it already accepts, so no socket is opened and no
live Gemini/Pinecone/MySQL connection is required (E9-S1/E9-S2 NFR).
"""

from collections.abc import Iterator, Mapping
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.dependencies import get_chat_orchestrator, get_product_repository
from backend.api.main import create_app
from backend.domain.enums import Category, Gender
from backend.domain.models import Product, QueryFilters
from backend.services.chat_orchestrator import ChatResult
from frontend.api_client import ApiClient, ProductQuery

pytestmark = pytest.mark.e2e

_SESSION_ID = "e2e-session-001"


def _build_product(
    *,
    product_id: str,
    name: str,
    brand: str,
    category: Category,
    gender: Gender,
    color: str,
    price: str,
    stock: int = 10,
) -> Product:
    """Construct a realistic seeded catalog product."""
    return Product(
        product_id=product_id,
        name=name,
        description="Comfortable everyday wear for the active shopper.",
        brand=brand,
        category=category,
        gender=gender,
        color=color,
        price=Decimal(price),
        image_url=f"https://cdn.shopassistant.test/{product_id.lower()}.jpg",
        stock=stock,
        tags=["Featured"],
    )


_SEED_CATALOG: list[Product] = [
    _build_product(
        product_id="P1001", name="Nike Revolution 6", brand="Nike",
        category=Category.SHOES, gender=Gender.MEN, color="Red", price="2799.00",
    ),
    _build_product(
        product_id="P1002", name="Nike Pegasus 40", brand="Nike",
        category=Category.SHOES, gender=Gender.MEN, color="Black", price="9499.00",
    ),
    _build_product(
        product_id="P2001", name="Puma Leather Tote", brand="Puma",
        category=Category.BAGS, gender=Gender.WOMEN, color="Black", price="3499.00",
    ),
]


class _ScriptedChatOrchestrator:
    """Plays the no-match journey: shoes -> refine to red -> impossible query.

    Returns a scripted :class:`ChatResult` keyed by the turn number so the test
    drives a deterministic conversation through the real chat endpoint without a
    live Gemini/Pinecone backend.
    """

    def __init__(self) -> None:
        self.turns: list[tuple[str, str]] = []
        self._script: list[ChatResult] = [
            ChatResult(
                reply="Here are some Nike shoes.",
                products=[_SEED_CATALOG[0], _SEED_CATALOG[1]],
            ),
            ChatResult(
                reply="Filtered to the red ones.",
                products=[_SEED_CATALOG[0]],
            ),
            ChatResult(
                reply="I couldn't find any products matching that. "
                "Try Shoes, Clothing, Accessories, Sportswear, or Bags.",
                products=[],
            ),
        ]

    def handle_turn(self, session_id: str, message: str) -> ChatResult:
        index = len(self.turns)
        self.turns.append((session_id, message))
        return self._script[min(index, len(self._script) - 1)]


class _SeededProductRepository:
    """In-memory repository honouring the same filter semantics as MySQL."""

    def __init__(self, products: list[Product]) -> None:
        self._products = products

    def list_products(self, filters: QueryFilters) -> list[Product]:
        return [product for product in self._products if _matches(product, filters)]


def _matches(product: Product, filters: QueryFilters) -> bool:
    checks = (
        filters.brand is None or product.brand == filters.brand,
        filters.color is None or product.color == filters.color,
        filters.category is None or product.category == filters.category,
        filters.gender is None or product.gender == filters.gender,
        filters.min_price is None or product.price >= filters.min_price,
        filters.max_price is None or product.price <= filters.max_price,
    )
    return all(checks)


class _TestClientSession:
    """Adapts a FastAPI ``TestClient`` to the ``ApiClient`` HTTP session seam.

    Lets the real frontend client issue in-process requests against the real
    backend app, so the journey traverses both layers with no network socket.
    """

    def __init__(self, client: TestClient) -> None:
        self._client = client

    def get(
        self,
        url: str,
        params: Mapping[str, object] | None = None,
        timeout: float | None = None,
    ) -> Any:
        return self._client.get(url, params=dict(params or {}))

    def post(
        self,
        url: str,
        json: Mapping[str, object] | None = None,
        timeout: float | None = None,
    ) -> Any:
        return self._client.post(url, json=dict(json or {}))


@pytest.fixture
def orchestrator() -> _ScriptedChatOrchestrator:
    return _ScriptedChatOrchestrator()


@pytest.fixture
def app(orchestrator: _ScriptedChatOrchestrator) -> FastAPI:
    application = create_app()
    repository = _SeededProductRepository(list(_SEED_CATALOG))
    application.dependency_overrides[get_chat_orchestrator] = lambda: orchestrator
    application.dependency_overrides[get_product_repository] = lambda: repository
    return application


@pytest.fixture
def api(app: FastAPI) -> Iterator[ApiClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield ApiClient(base_url="", session=_TestClientSession(test_client))


def test_core_journey_browse_query_refine_no_match(
    api: ApiClient, orchestrator: _ScriptedChatOrchestrator
) -> None:
    """The full journey completes end-to-end with no blocking errors (AC-5)."""
    # Browse: the catalog grid loads and filter options are populated.
    catalog = api.get_products(ProductQuery())
    assert {product.product_id for product in catalog} == {"P1001", "P1002", "P2001"}

    options = api.get_filters()
    assert "Nike" in options.brands
    assert "Shoes" in options.categories

    # Browse with a traditional filter: only Nike shoes remain.
    nike = api.get_products(ProductQuery(brand="Nike", category="Shoes"))
    assert {product.product_id for product in nike} == {"P1001", "P1002"}

    # Query: a conversational turn returns a reply with at most five products.
    first = api.post_chat(_SESSION_ID, "show me Nike shoes")
    assert first.reply
    assert 0 < len(first.products) <= 5

    # Refine: a follow-up in the SAME session narrows the result set.
    refined = api.post_chat(_SESSION_ID, "only the red ones")
    assert [product.product_id for product in refined.products] == ["P1001"]

    # No-match: an impossible query yields a graceful reply and zero cards.
    no_match = api.post_chat(_SESSION_ID, "neon glow stilettos size 99")
    assert no_match.products == []
    assert no_match.reply

    # All three turns reached the backend within the one session (DoD item 14).
    assert [session_id for session_id, _ in orchestrator.turns] == [_SESSION_ID] * 3


def test_no_match_journey_returns_zero_products_without_error(api: ApiClient) -> None:
    """A query with no catalog matches degrades gracefully, not with an error."""
    empty = api.get_products(ProductQuery(brand="Reebok"))
    assert empty == []
