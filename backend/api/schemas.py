"""API request/response schemas (E7-S2, E7-S3).

The boundary models that define every API payload's shape. Domain
:class:`Product` objects are serialized through :class:`ProductOut` (never
returned raw) so the wire contract matches api-contracts.md exactly and internal
fields cannot leak.

Shared file: E7-S2 owns :class:`ChatRequest`/:class:`ChatResponse`; E7-S3 owns
:class:`FilterOptions`/:class:`PriceRange`. :class:`ProductOut` is shared by
both (chat ``products`` and the catalog grid use the identical product shape).
"""

from decimal import Decimal

from pydantic import BaseModel, Field, field_serializer, field_validator

from backend.domain.enums import Category, Gender
from backend.domain.models import Product


class ProductOut(BaseModel):
    """Wire representation of a catalog product (api-contracts.md §2/§3).

    Mirrors the canonical field set including the derived ``in_stock`` flag so
    the frontend never recomputes availability.
    """

    product_id: str
    name: str
    description: str | None
    brand: str | None
    category: Category
    gender: Gender | None
    color: str | None
    price: Decimal
    image_url: str | None
    stock: int
    in_stock: bool
    tags: list[str]

    @field_serializer("price")
    def _serialize_price(self, price: Decimal) -> float:
        """Emit price as a JSON number to match api-contracts.md (not a string)."""
        return float(price)

    @classmethod
    def from_domain(cls, product: Product) -> "ProductOut":
        """Build the wire model from a domain :class:`Product`."""
        return cls(
            product_id=product.product_id,
            name=product.name,
            description=product.description,
            brand=product.brand,
            category=product.category,
            gender=product.gender,
            color=product.color,
            price=product.price,
            image_url=product.image_url,
            stock=product.stock,
            in_stock=product.in_stock,
            tags=product.tags,
        )


class ChatRequest(BaseModel):
    """Body for ``POST /api/chat`` (E7-S2 AC-1, AC-4).

    Both fields are required and must be non-empty after trimming; a blank or
    missing value fails validation and FastAPI returns 422.
    """

    session_id: str = Field(min_length=1)
    message: str = Field(min_length=1)

    @field_validator("session_id", "message")
    @classmethod
    def _reject_blank(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("must not be empty")
        return trimmed


class ChatResponse(BaseModel):
    """Body for a successful ``POST /api/chat`` turn (E7-S2 AC-2)."""

    reply: str
    products: list[ProductOut]


class PriceRange(BaseModel):
    """The numeric price bounds present in the catalog (E7-S3 AC-3)."""

    min: Decimal
    max: Decimal

    @field_serializer("min", "max")
    def _serialize_bound(self, value: Decimal) -> float:
        """Emit price bounds as JSON numbers to match api-contracts.md."""
        return float(value)


class FilterOptions(BaseModel):
    """Distinct filter option values for the UI controls (E7-S3 AC-3)."""

    brands: list[str]
    categories: list[str]
    genders: list[str]
    colors: list[str]
    price_range: PriceRange
