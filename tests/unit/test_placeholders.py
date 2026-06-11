"""Unit tests for the category placeholder mapping (frontend fallback images).

Only the pure mapping is exercised here — the reachability probe and the
in-memory image generation are Streamlit/Pillow/network concerns rendered at
runtime, not unit-tested.
"""

from components.placeholders import (
    CATEGORY_PLACEHOLDERS,
    placeholder_asset_path,
    placeholder_filename,
)


def test_shoes_maps_to_shoe_placeholder() -> None:
    assert placeholder_filename("Shoes") == "shoe-placeholder.jpg"


def test_clothing_and_sportswear_map_to_shirt() -> None:
    assert placeholder_filename("Clothing") == "shirt-placeholder.jpg"
    assert placeholder_filename("Sportswear") == "shirt-placeholder.jpg"


def test_accessories_and_watches_map_to_watch() -> None:
    assert placeholder_filename("Accessories") == "watch-placeholder.jpg"
    assert placeholder_filename("Watches") == "watch-placeholder.jpg"


def test_dresses_and_bags() -> None:
    assert placeholder_filename("Dresses") == "dress-placeholder.jpg"
    assert placeholder_filename("Bags") == "bag-placeholder.jpg"


def test_lookup_is_case_and_whitespace_insensitive() -> None:
    assert placeholder_filename("  SHOES ") == "shoe-placeholder.jpg"


def test_unknown_category_uses_default() -> None:
    assert placeholder_filename("Spaceship") == "product-placeholder.jpg"


def test_none_category_uses_default() -> None:
    assert placeholder_filename(None) == "product-placeholder.jpg"


def test_asset_path_points_into_frontend_assets() -> None:
    path = placeholder_asset_path("Shoes")
    assert path.name == "shoe-placeholder.jpg"
    assert path.parent.name == "assets"


def test_every_mapping_value_is_a_jpg_filename() -> None:
    assert all(name.endswith("-placeholder.jpg") for name in CATEGORY_PLACEHOLDERS.values())
