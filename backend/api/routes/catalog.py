"""Catalog & filter-option endpoints (E7-S3).

Serves the product grid and the traditional filter controls from MySQL (source
of truth). ``GET /api/products`` applies optional structured filters and returns
the matching products (an empty match set is a normal 200 ``[]``, not an error;
AC-4). ``GET /api/filters`` returns the distinct option values present in the
catalog for populating the UI controls (AC-3).

Enum query params (``category``/``gender``) are validated by FastAPI against the
domain enums, so an out-of-vocabulary value yields 422 (AC of api-contracts §3).
Repository failures raise :class:`RepositoryError`, mapped to the envelope by the
error middleware (E7-S1).
"""

from collections.abc import Iterable
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query

from backend.api.dependencies import ProductRepositoryDep
from backend.api.schemas import FilterOptions, PriceRange, ProductOut
from backend.core.logging import get_logger
from backend.domain.enums import Category, Gender
from backend.domain.models import Product, QueryFilters

logger = get_logger(__name__)

router = APIRouter(tags=["catalog"])


@router.get("/api/products", response_model=list[ProductOut])
def list_products(
    repository: ProductRepositoryDep,
    brand: Annotated[str | None, Query()] = None,
    category: Annotated[Category | None, Query()] = None,
    gender: Annotated[Gender | None, Query()] = None,
    color: Annotated[str | None, Query()] = None,
    min_price: Annotated[Decimal | None, Query(ge=0)] = None,
    max_price: Annotated[Decimal | None, Query(ge=0)] = None,
) -> list[ProductOut]:
    """Return catalog products matching the supplied filters (AC-1, AC-2, AC-4)."""
    filters = QueryFilters(
        brand=brand,
        category=category,
        gender=gender,
        color=color,
        min_price=min_price,
        max_price=max_price,
    )
    products = repository.list_products(filters)
    logger.info("api.products.listed", extra={"result_count": len(products)})
    return [ProductOut.from_domain(product) for product in products]


@router.get("/api/filters", response_model=FilterOptions)
def filter_options(repository: ProductRepositoryDep) -> FilterOptions:
    """Return distinct filter option values for the UI controls (AC-3)."""
    products = repository.list_products(QueryFilters())
    return _build_filter_options(products)


def _build_filter_options(products: list[Product]) -> FilterOptions:
    """Compute distinct option values and the price range from the catalog."""
    return FilterOptions(
        brands=_distinct(product.brand for product in products),
        categories=_distinct(product.category.value for product in products),
        genders=_distinct(product.gender.value for product in products if product.gender),
        colors=_distinct(product.color for product in products),
        price_range=_price_range(products),
    )


def _distinct(values: Iterable[str | None]) -> list[str]:
    """Sorted distinct non-empty string values, preserving determinism."""
    return sorted({value for value in values if value})


def _price_range(products: list[Product]) -> PriceRange:
    """Min/max price across the catalog, or a zero range when empty."""
    if not products:
        return PriceRange(min=Decimal("0"), max=Decimal("0"))
    prices = [product.price for product in products]
    return PriceRange(min=min(prices), max=max(prices))
