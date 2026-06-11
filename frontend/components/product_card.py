"""Single product card renderer (E8-S1).

Renders one :class:`ProductView` as a Streamlit card showing image, name,
brand/category/gender/color, price in INR, and a stock-status badge. The
formatting logic (INR, stock label) is kept in pure helpers so it is testable
without a Streamlit runtime.
"""

from decimal import Decimal

import streamlit as st
from api_client import ProductView

_RUPEE_SIGN = "₹"


def format_inr(price: Decimal) -> str:
    """Format a price as Indian Rupees with lakh grouping (e.g. ``₹2,799.00``)."""
    quantized = price.quantize(Decimal("0.01"))
    whole, _, fraction = f"{quantized:.2f}".partition(".")
    return f"{_RUPEE_SIGN}{_group_indian(whole)}.{fraction}"


def stock_label(product: ProductView) -> str:
    """Return the stock-status text — count when available, else out-of-stock."""
    if product.in_stock:
        return f"In stock ({product.stock})"
    return "Out of stock"


def render_product_card(product: ProductView) -> None:
    """Render one product card into the current Streamlit container."""
    with st.container(border=True):
        _render_image(product)
        st.markdown(f"**{product.name}**")
        st.caption(_meta_line(product))
        st.markdown(f"### {format_inr(product.price)}")
        _render_stock_badge(product)
        if product.tags:
            st.caption(" · ".join(product.tags))


def _render_image(product: ProductView) -> None:
    if product.image_url:
        st.image(product.image_url, use_container_width=True)


def _render_stock_badge(product: ProductView) -> None:
    label = stock_label(product)
    if product.in_stock:
        st.success(label, icon="✅")
    else:
        st.error(label, icon="🚫")


def _meta_line(product: ProductView) -> str:
    """Join the present descriptive attributes with a dot separator."""
    parts = [product.brand, product.category, product.gender, product.color]
    return " · ".join(part for part in parts if part)


def _group_indian(whole: str) -> str:
    """Group an integer string with the Indian numbering system (12,34,567)."""
    if len(whole) <= 3:
        return whole
    head, last_three = whole[:-3], whole[-3:]
    groups: list[str] = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups) + "," + last_three
