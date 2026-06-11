"""Product domain models (E1-S1).

Pure data structures with validation. No I/O and no imports from other project
layers — `domain` sits at the bottom of the dependency graph and is imported
everywhere else.
"""

from decimal import Decimal

from pydantic import BaseModel, Field, computed_field

from backend.domain.enums import Category, Gender


class Product(BaseModel):
    """A catalogue product — the MySQL system-of-record entity (E1-S1 AC-1).

    `name`, `price`, and `category` are required; constructing without any of
    them raises a validation error (AC-5). `stock` defaults to 0 and `stock=0`
    is valid, yielding ``in_stock=False`` (AC-6).
    """

    product_id: str
    name: str
    description: str | None = None
    brand: str | None = None
    category: Category
    gender: Gender | None = None
    color: str | None = None
    price: Decimal = Field(ge=0)
    image_url: str | None = None
    stock: int = Field(default=0, ge=0)
    tags: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def in_stock(self) -> bool:
        """Derived availability flag: ``True`` only when stock is positive."""
        return self.stock > 0


class QueryFilters(BaseModel):
    """Optional retrieval filters produced by filter extraction (E1-S1 AC-4).

    Every field defaults to ``None`` so an unconstrained query carries no
    filters. Out-of-vocabulary extracted values are normalized to ``None`` by
    the filter extractor (E5-S1), not here.
    """

    brand: str | None = None
    color: str | None = None
    category: Category | None = None
    gender: Gender | None = None
    min_price: Decimal | None = None
    max_price: Decimal | None = None
