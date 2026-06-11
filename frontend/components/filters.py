"""Traditional filter controls (E8-S2).

Renders Brand / Category / Gender / Color select boxes and a max-price slider,
populated from ``GET /api/filters`` (AC-1). The selection is translated into a
:class:`ProductQuery` that drives ``GET /api/products`` (AC-2, AC-3). A "Clear
filters" reset restores the full catalog (AC-4).

The widget calls are thin; the selection-to-query mapping and the cleared state
are pure helpers so they are unit-testable without a Streamlit runtime.
"""

from dataclasses import dataclass
from decimal import Decimal

import streamlit as st
from api_client import FilterOptionsView, ProductQuery

ANY_OPTION = "Any"


@dataclass(frozen=True)
class FilterSelection:
    """The raw values chosen in the filter controls."""

    brand: str
    category: str
    gender: str
    color: str
    max_price: Decimal


def cleared_selection(options: FilterOptionsView) -> FilterSelection:
    """Return the selection representing "no filters" (AC-4)."""
    return FilterSelection(
        brand=ANY_OPTION,
        category=ANY_OPTION,
        gender=ANY_OPTION,
        color=ANY_OPTION,
        max_price=options.price_max,
    )


def selection_to_query(selection: FilterSelection, options: FilterOptionsView) -> ProductQuery:
    """Translate the chosen controls into a backend product query."""
    apply_price = selection.max_price < options.price_max
    return ProductQuery(
        brand=_chosen(selection.brand),
        category=_chosen(selection.category),
        gender=_chosen(selection.gender),
        color=_chosen(selection.color),
        min_price=options.price_min if apply_price else None,
        max_price=selection.max_price if apply_price else None,
    )


def render_filter_controls(options: FilterOptionsView) -> FilterSelection:
    """Render the sidebar filter controls and return the current selection."""
    st.subheader("Filters")
    selection = FilterSelection(
        brand=_select("Brand", options.brands),
        category=_select("Category", options.categories),
        gender=_select("Gender", options.genders),
        color=_select("Color", options.colors),
        max_price=_price_slider(options),
    )
    if st.button("Clear filters"):
        _reset_widgets()
        st.rerun()
    return selection


def _select(label: str, values: list[str]) -> str:
    """Render a select box with a leading "Any" option."""
    return st.selectbox(label, [ANY_OPTION, *values], key=f"filter_{label.lower()}")


def _price_slider(options: FilterOptionsView) -> Decimal:
    """Render the max-price slider and return the chosen ceiling."""
    chosen = st.slider(
        "Max price (₹)",
        min_value=float(options.price_min),
        max_value=float(options.price_max),
        value=float(options.price_max),
        key="filter_max_price",
    )
    return Decimal(str(chosen))


def _reset_widgets() -> None:
    """Remove stored widget state so controls fall back to defaults (AC-4)."""
    for key in ("brand", "category", "gender", "color", "max_price"):
        st.session_state.pop(f"filter_{key}", None)


def _chosen(value: str) -> str | None:
    """Map the "Any" sentinel to ``None`` (no filter for that field)."""
    return None if value == ANY_OPTION else value
