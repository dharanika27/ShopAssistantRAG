"""Product catalog grid (E8-S1).

Fetches products from the backend via :class:`ApiClient` and renders them as a
responsive grid of cards. On a backend failure it shows the friendly,
trace-free message carried by :class:`ApiUnavailableError` (AC-4) rather than an
exception. An empty result set renders a neutral "no products" notice.
"""

import streamlit as st
from api_client import ApiClient, ApiUnavailableError, ProductQuery, ProductView
from components.product_card import render_product_card

_COLUMNS_PER_ROW = 3
_EMPTY_MESSAGE = "No products match the current view."


def friendly_error_message(error: ApiUnavailableError) -> str:
    """Return the user-facing message for a backend failure (AC-4, no trace)."""
    return str(error)


def render_catalog_grid(client: ApiClient, query: ProductQuery) -> None:
    """Fetch and render the catalog grid for ``query`` (AC-1, AC-2, AC-4)."""
    try:
        products = client.get_products(query)
    except ApiUnavailableError as error:
        st.error(friendly_error_message(error))
        return
    render_products(products)


def render_products(products: list[ProductView]) -> None:
    """Render an already-fetched product list as a grid of cards."""
    if not products:
        st.info(_EMPTY_MESSAGE)
        return
    for row_start in range(0, len(products), _COLUMNS_PER_ROW):
        row = products[row_start : row_start + _COLUMNS_PER_ROW]
        columns = st.columns(_COLUMNS_PER_ROW)
        for column, product in zip(columns, row, strict=False):
            with column:
                render_product_card(product)
