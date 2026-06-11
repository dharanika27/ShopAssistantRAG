"""Unit tests for catalog rendering helpers (E8-S1).

The Streamlit ``st.*`` calls are thin; the testable logic — price formatting,
stock labelling, and choosing the friendly error message — lives in pure
helpers asserted here. No Streamlit runtime is required.
"""

from decimal import Decimal

from api_client import ApiUnavailableError, ProductView
from components.catalog_grid import friendly_error_message
from components.product_card import format_inr, stock_label


def _product(**overrides: object) -> ProductView:
    base = dict(
        product_id="P1001",
        name="Nike Revolution 6",
        description="Lightweight everyday running shoes.",
        brand="Nike",
        category="Shoes",
        gender="Men",
        color="Red",
        price=Decimal("2799.00"),
        image_url="https://cdn.example.com/p1001.jpg",
        stock=12,
        in_stock=True,
        tags=["Running", "Sports"],
    )
    base.update(overrides)
    return ProductView(**base)  # type: ignore[arg-type]


def test_format_inr_uses_rupee_symbol_and_indian_grouping() -> None:
    # Act / Assert
    assert format_inr(Decimal("2799.00")) == "₹2,799.00"
    assert format_inr(Decimal("14999")) == "₹14,999.00"
    assert format_inr(Decimal("599.5")) == "₹599.50"


def test_stock_label_shows_count_when_in_stock() -> None:
    # Arrange
    product = _product(stock=12, in_stock=True)
    # Act / Assert
    assert stock_label(product) == "In stock (12)"


def test_stock_label_shows_out_of_stock_when_zero() -> None:
    # Arrange — E8-S1 AC-3: stock=0 must be visibly out of stock
    product = _product(stock=0, in_stock=False)
    # Act / Assert
    assert stock_label(product) == "Out of stock"


def test_friendly_error_message_uses_envelope_text() -> None:
    # Arrange — E8-S1 AC-4: show the friendly message, never a stack trace
    error = ApiUnavailableError(
        "We are unable to load product details right now. Please try again later.",
        code="MYSQL_UNAVAILABLE",
    )
    # Act
    message = friendly_error_message(error)
    # Assert
    assert message == "We are unable to load product details right now. Please try again later."
    assert "Traceback" not in message
