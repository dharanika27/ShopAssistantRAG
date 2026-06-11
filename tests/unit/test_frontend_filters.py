"""Unit tests for traditional filter controls logic (E8-S2).

The Streamlit widget rendering is thin; the testable logic is the translation
of selected control values into a :class:`ProductQuery` and the "cleared" state.
"""

from decimal import Decimal

from api_client import FilterOptionsView, ProductQuery
from components.filters import (
    ANY_OPTION,
    FilterSelection,
    cleared_selection,
    selection_to_query,
)

OPTIONS = FilterOptionsView(
    brands=["Adidas", "Nike", "Puma"],
    categories=["Accessories", "Bags", "Clothing", "Shoes", "Sportswear"],
    genders=["Kids", "Men", "Unisex", "Women"],
    colors=["Black", "Blue", "Red", "White"],
    price_min=Decimal("199.00"),
    price_max=Decimal("14999.00"),
)


def test_cleared_selection_selects_any_for_every_control() -> None:
    # Act — E8-S2 AC-4: clearing restores the full catalog
    selection = cleared_selection(OPTIONS)
    # Assert
    assert selection.brand == ANY_OPTION
    assert selection.category == ANY_OPTION
    assert selection.gender == ANY_OPTION
    assert selection.color == ANY_OPTION
    assert selection.max_price == OPTIONS.price_max


def test_cleared_selection_produces_empty_query() -> None:
    # Arrange — full price range means no bound is applied
    selection = cleared_selection(OPTIONS)
    # Act
    query = selection_to_query(selection, OPTIONS)
    # Assert — no params at all → backend returns the full catalog
    assert query == ProductQuery()
    assert query.to_params() == {}


def test_single_filter_maps_to_query_param() -> None:
    # Arrange
    selection = FilterSelection(
        brand="Nike",
        category=ANY_OPTION,
        gender=ANY_OPTION,
        color=ANY_OPTION,
        max_price=OPTIONS.price_max,
    )
    # Act
    query = selection_to_query(selection, OPTIONS)
    # Assert
    assert query.brand == "Nike"
    assert query.category is None
    assert query.to_params() == {"brand": "Nike"}


def test_combined_filters_map_to_all_params() -> None:
    # Arrange — E8-S2 AC-3: Brand=Nike + Category=Shoes
    selection = FilterSelection(
        brand="Nike",
        category="Shoes",
        gender="Men",
        color="Red",
        max_price=Decimal("3000"),
    )
    # Act
    query = selection_to_query(selection, OPTIONS)
    # Assert
    assert query.to_params() == {
        "brand": "Nike",
        "category": "Shoes",
        "gender": "Men",
        "color": "Red",
        "min_price": 199.0,
        "max_price": 3000.0,
    }


def test_max_price_below_ceiling_applies_price_bounds() -> None:
    # Arrange — narrowing the slider applies both bounds
    selection = FilterSelection(
        brand=ANY_OPTION,
        category=ANY_OPTION,
        gender=ANY_OPTION,
        color=ANY_OPTION,
        max_price=Decimal("5000"),
    )
    # Act
    query = selection_to_query(selection, OPTIONS)
    # Assert
    assert query.min_price == OPTIONS.price_min
    assert query.max_price == Decimal("5000")


def test_full_price_range_omits_price_params() -> None:
    # Arrange — slider at the ceiling means "no price filter"
    selection = FilterSelection(
        brand="Puma",
        category=ANY_OPTION,
        gender=ANY_OPTION,
        color=ANY_OPTION,
        max_price=OPTIONS.price_max,
    )
    # Act
    query = selection_to_query(selection, OPTIONS)
    # Assert
    assert query.min_price is None
    assert query.max_price is None
    assert query.to_params() == {"brand": "Puma"}
