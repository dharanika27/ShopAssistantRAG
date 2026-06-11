"""Unit tests for E5-S3 — MySQL hydration of retrieved product IDs.

The product repository is the external (MySQL) boundary and is mocked via a
fake that records calls. The hydration business logic (rank-order preservation,
skipping IDs absent from MySQL, short-circuiting on an empty ID list) is
exercised directly. No live database is touched.
"""

from decimal import Decimal

from backend.domain.enums import Category, Gender
from backend.domain.models import Product
from backend.services.hydrator import ProductHydrator


def _product(product_id: str) -> Product:
    return Product(
        product_id=product_id,
        name=f"Product {product_id}",
        category=Category.SHOES,
        gender=Gender.UNISEX,
        color="Red",
        price=Decimal("2499.00"),
        stock=12,
    )


class _FakeProductRepository:
    """Returns the known products whose IDs are requested, in input order."""

    def __init__(self, known: dict[str, Product]) -> None:
        self._known = known
        self.calls: list[list[str]] = []

    def get_products_by_ids(self, product_ids: list[str]) -> list[Product]:
        self.calls.append(list(product_ids))
        return [self._known[pid] for pid in product_ids if pid in self._known]


class TestHydration:
    def test_returns_full_products_for_ids(self) -> None:
        known = {"SKU-001": _product("SKU-001"), "SKU-002": _product("SKU-002")}
        repo = _FakeProductRepository(known)
        hydrator = ProductHydrator(repository=repo)

        products = hydrator.hydrate(["SKU-001", "SKU-002"])

        assert [p.product_id for p in products] == ["SKU-001", "SKU-002"]
        assert all(isinstance(p, Product) for p in products)

    def test_preserves_retrieval_rank_order(self) -> None:
        known = {pid: _product(pid) for pid in ("SKU-A", "SKU-B", "SKU-C")}
        repo = _FakeProductRepository(known)
        hydrator = ProductHydrator(repository=repo)

        products = hydrator.hydrate(["SKU-C", "SKU-A", "SKU-B"])

        assert [p.product_id for p in products] == ["SKU-C", "SKU-A", "SKU-B"]

    def test_id_absent_from_mysql_is_skipped(self) -> None:
        known = {"SKU-001": _product("SKU-001"), "SKU-003": _product("SKU-003")}
        repo = _FakeProductRepository(known)
        hydrator = ProductHydrator(repository=repo)

        products = hydrator.hydrate(["SKU-001", "SKU-002", "SKU-003"])

        assert [p.product_id for p in products] == ["SKU-001", "SKU-003"]

    def test_all_ids_missing_returns_empty_list(self) -> None:
        repo = _FakeProductRepository({})
        hydrator = ProductHydrator(repository=repo)

        products = hydrator.hydrate(["SKU-404", "SKU-405"])

        assert products == []
        assert repo.calls == [["SKU-404", "SKU-405"]]


class TestEmptyInput:
    def test_empty_id_list_returns_empty_without_querying(self) -> None:
        repo = _FakeProductRepository({"SKU-001": _product("SKU-001")})
        hydrator = ProductHydrator(repository=repo)

        products = hydrator.hydrate([])

        assert products == []
        assert repo.calls == []
