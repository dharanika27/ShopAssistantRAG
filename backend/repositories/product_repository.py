"""Product repository — CRUD + bulk hydrate by IDs (E2-S2).

Data-access layer over the MySQL ``products`` table. Supports upserting products
during ingestion (AC-1), bulk-fetching full :class:`Product` records by a list
of IDs while preserving input ordering (AC-2, AC-4), and listing/filtering
products for the catalog grid (AC-3).

This module (with :mod:`backend.repositories.db`) is the only place that talks
to the MySQL driver. Driver failures are caught and re-raised as
:class:`RepositoryError` so no raw driver exception escapes the layer (AC-5;
error-handling-strategy.md §4). The ``connect`` factory is injected so unit
tests run without a live database.
"""

import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from backend.core.config import Settings
from backend.core.errors import RepositoryError
from backend.core.logging import get_logger
from backend.domain.models import Product, QueryFilters
from backend.repositories.db import connection_params

logger = get_logger(__name__)

ConnectFn = Callable[..., Any]

_COLUMNS = (
    "product_id, name, description, brand, category, gender, color, "
    "price, image_url, stock, tags"
)

_UPSERT_SQL = (
    f"INSERT INTO products ({_COLUMNS}) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
    "ON DUPLICATE KEY UPDATE "
    "name=VALUES(name), description=VALUES(description), brand=VALUES(brand), "
    "category=VALUES(category), gender=VALUES(gender), color=VALUES(color), "
    "price=VALUES(price), image_url=VALUES(image_url), stock=VALUES(stock), "
    "tags=VALUES(tags)"
)


def _default_connect(**kwargs: Any) -> Any:
    """Open a MySQL connection (lazy driver import — see db._default_connect)."""
    import mysql.connector

    return mysql.connector.connect(**kwargs)


class ProductRepository:
    """MySQL-backed product data access (E2-S2)."""

    def __init__(self, settings: Settings, *, connect: ConnectFn = _default_connect) -> None:
        self._settings = settings
        self._connect = connect

    def upsert_product(self, product: Product) -> None:
        """Insert ``product``, or update it when ``product_id`` exists (AC-1)."""
        self._execute_write(_UPSERT_SQL, _upsert_params(product))
        logger.info("product_repo.upserted", extra={"product_id": product.product_id})

    def get_products_by_ids(self, product_ids: list[str]) -> list[Product]:
        """Return products for ``product_ids`` in input order (AC-2/AC-4).

        An empty list returns ``[]`` without querying the database (AC-4). IDs
        absent from the table are skipped.
        """
        if not product_ids:
            return []
        placeholders = ", ".join(["%s"] * len(product_ids))
        sql = f"SELECT {_COLUMNS} FROM products WHERE product_id IN ({placeholders})"
        rows = self._execute_read(sql, tuple(product_ids))
        return _order_by_ids(rows, product_ids)

    def list_products(self, filters: QueryFilters) -> list[Product]:
        """Return products matching ``filters``; no filters returns all (AC-3)."""
        clauses, params = _build_filter_clauses(filters)
        sql = f"SELECT {_COLUMNS} FROM products"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        rows = self._execute_read(sql, tuple(params))
        return [_row_to_product(row) for row in rows]

    def _execute_write(self, sql: str, params: tuple[Any, ...]) -> None:
        try:
            connection = self._connect(**connection_params(self._settings))
            try:
                with connection.cursor() as cursor:
                    cursor.execute(sql, params)
                connection.commit()
            finally:
                connection.close()
        except Exception as exc:
            raise self._wrap(exc, operation="write") from exc

    def _execute_read(
        self, sql: str, params: tuple[Any, ...]
    ) -> list[dict[str, Any]]:
        try:
            connection = self._connect(**connection_params(self._settings))
            try:
                with connection.cursor(dictionary=True) as cursor:
                    cursor.execute(sql, params)
                    return list(cursor.fetchall())
            finally:
                connection.close()
        except Exception as exc:
            raise self._wrap(exc, operation="read") from exc

    def _wrap(self, exc: Exception, *, operation: str) -> RepositoryError:
        logger.error(
            "product_repo.query_failed",
            extra={"operation": operation, "host": self._settings.MYSQL_HOST},
        )
        return RepositoryError(f"MySQL {operation} failed: {exc}")


def _upsert_params(product: Product) -> tuple[Any, ...]:
    return (
        product.product_id,
        product.name,
        product.description,
        product.brand,
        product.category.value,
        product.gender.value if product.gender else None,
        product.color,
        product.price,
        product.image_url,
        product.stock,
        json.dumps(product.tags),
    )


def _build_filter_clauses(filters: QueryFilters) -> tuple[list[str], list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    _add_eq(clauses, params, "brand", filters.brand)
    _add_eq(clauses, params, "color", filters.color)
    _add_eq(clauses, params, "category", filters.category.value if filters.category else None)
    _add_eq(clauses, params, "gender", filters.gender.value if filters.gender else None)
    _add_bound(clauses, params, "price >= %s", filters.min_price)
    _add_bound(clauses, params, "price <= %s", filters.max_price)
    return clauses, params


def _add_eq(clauses: list[str], params: list[Any], column: str, value: Any) -> None:
    if value is not None:
        clauses.append(f"{column} = %s")
        params.append(value)


def _add_bound(
    clauses: list[str], params: list[Any], clause: str, value: Decimal | None
) -> None:
    if value is not None:
        clauses.append(clause)
        params.append(value)


def _order_by_ids(rows: list[dict[str, Any]], product_ids: list[str]) -> list[Product]:
    by_id = {row["product_id"]: _row_to_product(row) for row in rows}
    return [by_id[pid] for pid in product_ids if pid in by_id]


def _row_to_product(row: dict[str, Any]) -> Product:
    return Product(
        product_id=row["product_id"],
        name=row["name"],
        description=row["description"],
        brand=row["brand"],
        category=row["category"],
        gender=row["gender"],
        color=row["color"],
        price=row["price"],
        image_url=row["image_url"],
        stock=row["stock"],
        tags=_parse_tags(row["tags"]),
    )


def _parse_tags(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(tag) for tag in raw]
    return [str(tag) for tag in json.loads(raw)]
