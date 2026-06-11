"""Shared fixtures for API integration tests (Group F).

Builds the FastAPI app with the external boundaries (chat orchestration and the
MySQL product repository) replaced by injected fakes. Only those boundaries are
faked — the routers, middleware, schemas, and serialization under test run for
real (code-gen testing rule: mock external boundaries only).
"""

from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.dependencies import get_chat_orchestrator, get_product_repository
from backend.api.main import create_app
from backend.domain.enums import Category, Gender
from backend.domain.models import Product, QueryFilters
from backend.services.chat_orchestrator import ChatResult


def build_product(
    *,
    product_id: str = "P1001",
    name: str = "Nike Revolution 6",
    brand: str = "Nike",
    category: Category = Category.SHOES,
    gender: Gender = Gender.MEN,
    color: str = "Red",
    price: Decimal = Decimal("2799.00"),
    stock: int = 12,
) -> Product:
    """Construct a realistic catalog product for tests."""
    return Product(
        product_id=product_id,
        name=name,
        description="Lightweight running shoes for everyday training.",
        brand=brand,
        category=category,
        gender=gender,
        color=color,
        price=price,
        image_url=f"https://cdn.shopassistant.test/{product_id.lower()}.jpg",
        stock=stock,
        tags=["Running", "Sports"],
    )


class FakeChatOrchestrator:
    """Records turns and returns a scripted :class:`ChatResult` per session."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self._result = ChatResult(reply="Here are some matches.", products=[build_product()])

    def set_result(self, result: ChatResult) -> None:
        self._result = result

    def handle_turn(self, session_id: str, message: str) -> ChatResult:
        self.calls.append((session_id, message))
        return self._result


class FakeProductRepository:
    """In-memory product repository honouring the same filter semantics as MySQL."""

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


@pytest.fixture
def catalog() -> list[Product]:
    return [
        build_product(product_id="P1001", brand="Nike", color="Red", price=Decimal("2799.00")),
        build_product(
            product_id="P1002",
            name="Adidas Ultraboost",
            brand="Adidas",
            color="Black",
            price=Decimal("8999.00"),
            stock=0,
        ),
        build_product(
            product_id="P2001",
            name="Puma Leather Tote",
            brand="Puma",
            category=Category.BAGS,
            gender=Gender.WOMEN,
            color="Black",
            price=Decimal("3499.00"),
            stock=5,
        ),
    ]


@pytest.fixture
def orchestrator() -> FakeChatOrchestrator:
    return FakeChatOrchestrator()


@pytest.fixture
def app(orchestrator: FakeChatOrchestrator, catalog: list[Product]) -> FastAPI:
    application = create_app()
    repository = FakeProductRepository(catalog)
    application.dependency_overrides[get_chat_orchestrator] = lambda: orchestrator
    application.dependency_overrides[get_product_repository] = lambda: repository
    return application


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
