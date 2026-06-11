"""Category-aware fallback images for product cards (frontend-only).

When a product's remote ``image_url`` cannot be loaded (missing, unreachable, or
throttled by the image host), the card falls back to a **category placeholder**
instead of a broken image. Resolution order for the fallback:

1. A user-supplied asset at ``frontend/assets/<category>-placeholder.jpg`` if it
   exists (e.g. ``shoe-placeholder.jpg``).
2. Otherwise a simple labelled placeholder generated in-memory with Pillow
   (which Streamlit already depends on) — so the feature works with zero binary
   assets checked in.

This is purely a Streamlit rendering concern: **no backend API, schema, or
contract is touched.** ``image_url`` still flows unchanged from MySQL → API → UI;
this module only decides what to show when that URL fails.

Detection note: ``st.image`` renders a URL as an ``<img>`` the browser loads, and
Streamlit cannot observe a client-side load failure. We therefore probe
reachability from the Streamlit server (cached), which is the most reliable
fallback ``st.image`` supports. The probe result is cached so each distinct URL
is checked at most once per TTL.
"""

import io
from pathlib import Path

import streamlit as st

# Category (lower-cased) -> placeholder asset filename. Covers the app's own
# Category enum (Shoes/Clothing/Accessories/Sportswear/Bags) plus the
# finer-grained terms requested (Shirts/Dresses/Watches) for forward-compat.
CATEGORY_PLACEHOLDERS: dict[str, str] = {
    "shoes": "shoe-placeholder.jpg",
    "shoe": "shoe-placeholder.jpg",
    "shirt": "shirt-placeholder.jpg",
    "shirts": "shirt-placeholder.jpg",
    "clothing": "shirt-placeholder.jpg",
    "sportswear": "shirt-placeholder.jpg",
    "dress": "dress-placeholder.jpg",
    "dresses": "dress-placeholder.jpg",
    "watch": "watch-placeholder.jpg",
    "watches": "watch-placeholder.jpg",
    "accessories": "watch-placeholder.jpg",
    "bags": "bag-placeholder.jpg",
}

_DEFAULT_PLACEHOLDER = "product-placeholder.jpg"
_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
_PROBE_TIMEOUT_SECONDS = 3.0


def placeholder_filename(category: str | None) -> str:
    """Return the placeholder asset filename for ``category`` (pure, testable)."""
    if not category:
        return _DEFAULT_PLACEHOLDER
    return CATEGORY_PLACEHOLDERS.get(category.strip().lower(), _DEFAULT_PLACEHOLDER)


def placeholder_asset_path(category: str | None) -> Path:
    """Return the on-disk asset path for ``category``'s placeholder (pure)."""
    return _ASSETS_DIR / placeholder_filename(category)


@st.cache_data(show_spinner=False, ttl=300)
def _url_reachable(url: str) -> bool:
    """Return True if ``url`` responds < 400 (cached for 5 min). Never raises."""
    import requests

    try:
        resp = requests.get(
            url, timeout=_PROBE_TIMEOUT_SECONDS, stream=True, allow_redirects=True
        )
        resp.close()
    except requests.RequestException:
        return False
    return resp.status_code < 400


@st.cache_data(show_spinner=False)
def _generated_placeholder_png(label: str) -> bytes:
    """Generate a simple labelled placeholder PNG in-memory (cached per label)."""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (600, 600), (235, 237, 240))
    draw = ImageDraw.Draw(image)
    text = label or "Product"
    try:
        from PIL import ImageFont

        font = ImageFont.load_default(size=44)
    except Exception:  # noqa: BLE001 - any Pillow/font issue falls back to default
        font = None
    draw.rectangle((40, 40, 560, 560), outline=(189, 195, 199), width=3)
    draw.text((300, 300), text, fill=(127, 140, 141), anchor="mm", font=font)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def fallback_source(category: str | None) -> str | bytes:
    """Return the category placeholder: asset file if present, else generated."""
    asset = placeholder_asset_path(category)
    if asset.exists():
        return str(asset)
    return _generated_placeholder_png(category or "Product")


def image_source_for(image_url: str | None, category: str | None) -> str | bytes:
    """Return the product image URL when reachable, else a category placeholder."""
    if image_url and _url_reachable(image_url):
        return image_url
    return fallback_source(category)
