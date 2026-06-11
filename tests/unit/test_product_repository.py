"""Unit tests for E2-S2 — product repository (CRUD + bulk hydrate).

The MySQL driver is the external boundary and is mocked via an injected
``connect`` factory (same pattern as the schema-init runner). Business logic
(upsert SQL, ID-order preservation, filter SQL, empty-list short-circuit, typed
error translation) is exercised directly. No live database is touched.
"""

from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from backend.core.config import Settings
from backend.core.errors import RepositoryError
from backend.domain.enums import Category, Gender
from backend.domain.models import Product, QueryFilters
from backend.repositories.product_repository import ProductRepository

REQUIRED_ENV = {
    "GOOGLE_API_KEY": "test-google-key",
    "PINECONE_API_KEY": "test-pinecone-key",
    "MYSQL_HOST": "localhost",
    "MYSQL_PORT": "3306",
    "MYSQL_USER": "shop_user",
    "MYSQL_PASSWORD": "shop_password",
    "MYSQL_DATABASE": "shopassistant",
}


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


def _row(product_id: str, name: str, category: str = "Shoes") -> dict[str, Any]:
    return {
        "product_id": product_id,
        "name": name,
        "description": "A product",
        "brand": "Nike",
        "category": category,
        "gender": "Men",
        "color": "Red",
        "price": Decimal("2799.00"),
        "image_url": "https://cdn.example.com/x.jpg",
        "stock": 5,
        "tags": '["Running", "Sports"]',
    }


def _connection_returning(rows: list[dict[str, Any]]) -> tuple[MagicMock, MagicMock]:
    cursor = MagicMock()
    cursor.fetchall.return_value = rows
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    return connection, cursor


def _make_repo(settings: Settings, connection: MagicMock) -> ProductRepository:
    return ProductRepository(settings, connect=MagicMock(return_value=connection))


def _sample_product() -> Product:
    return Product(
        product_id="P1001",
        name="Nike Revolution 6",
        description="Running shoes",
        brand="Nike",
        category=Category.SHOES,
        gender=Gender.MEN,
        color="Red",
        price=Decimal("2799.00"),
        stock=12,
        tags=["Running", "Sports"],
    )


class TestUpsert:
    def test_upsert_executes_insert_on_duplicate_key_update(
        self, settings: Settings
    ) -> None:
        connection, cursor = _connection_returning([])
        repo = _make_repo(settings, connection)

        repo.upsert_product(_sample_product())

        sql = cursor.execute.call_args.args[0].upper()
        assert "INSERT INTO PRODUCTS" in sql
        assert "ON DUPLICATE KEY UPDATE" in sql
        connection.commit.assert_called_once()

    def test_upsert_failure_raises_repository_error(self, settings: Settings) -> None:
        def failing_connect(**_: object) -> object:
            raise ConnectionError("mysql refused the connection")

        repo = ProductRepository(settings, connect=failing_connect)

        with pytest.raises(RepositoryError) as exc_info:
            repo.upsert_product(_sample_product())

        assert exc_info.value.code == "MYSQL_UNAVAILABLE"


class TestGetProductsByIds:
    def test_empty_id_list_returns_empty_without_querying(
        self, settings: Settings
    ) -> None:
        connect = MagicMock()
        repo = ProductRepository(settings, connect=connect)

        result = repo.get_products_by_ids([])

        assert result == []
        connect.assert_not_called()

    def test_preserves_input_ordering(self, settings: Settings) -> None:
        # DB returns rows in arbitrary order; repository must re-order to input.
        connection, _ = _connection_returning(
            [_row("P3", "Third"), _row("P1", "First"), _row("P2", "Second")]
        )
        repo = _make_repo(settings, connection)

        result = repo.get_products_by_ids(["P1", "P2", "P3"])

        assert [p.product_id for p in result] == ["P1", "P2", "P3"]

    def test_skips_ids_absent_from_database(self, settings: Settings) -> None:
        connection, _ = _connection_returning([_row("P1", "First")])
        repo = _make_repo(settings, connection)

        result = repo.get_products_by_ids(["P1", "P_MISSING"])

        assert [p.product_id for p in result] == ["P1"]

    def test_connection_failure_raises_repository_error(
        self, settings: Settings
    ) -> None:
        def failing_connect(**_: object) -> object:
            raise OSError("connection reset")

        repo = ProductRepository(settings, connect=failing_connect)

        with pytest.raises(RepositoryError):
            repo.get_products_by_ids(["P1"])


class TestListProducts:
    def test_no_filters_selects_all(self, settings: Settings) -> None:
        connection, cursor = _connection_returning([_row("P1", "First")])
        repo = _make_repo(settings, connection)

        repo.list_products(QueryFilters())

        sql = cursor.execute.call_args.args[0].upper()
        assert "WHERE" not in sql
        assert "SELECT" in sql

    def test_filters_build_where_clause_with_bound_params(
        self, settings: Settings
    ) -> None:
        connection, cursor = _connection_returning([_row("P1", "First")])
        repo = _make_repo(settings, connection)

        repo.list_products(
            QueryFilters(
                brand="Nike",
                category=Category.SHOES,
                min_price=Decimal("1000"),
                max_price=Decimal("3000"),
            )
        )

        sql, params = cursor.execute.call_args.args
        assert "WHERE" in sql.upper()
        assert "brand = %s" in sql
        assert "price >= %s" in sql
        assert "price <= %s" in sql
        assert "Nike" in params
        assert Decimal("1000") in params
        assert Decimal("3000") in params

    def test_returns_typed_products(self, settings: Settings) -> None:
        connection, _ = _connection_returning([_row("P1", "First")])
        repo = _make_repo(settings, connection)

        result = repo.list_products(QueryFilters())

        assert isinstance(result[0], Product)
        assert result[0].tags == ["Running", "Sports"]

    def test_query_failure_raises_repository_error(self, settings: Settings) -> None:
        connection = MagicMock()
        connection.cursor.side_effect = RuntimeError("lost connection during query")
        repo = _make_repo(settings, connection)

        with pytest.raises(RepositoryError):
            repo.list_products(QueryFilters())
