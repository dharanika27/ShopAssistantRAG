"""Integration tests for E7-S3 — GET /api/products and GET /api/filters."""

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def test_products_returns_full_catalog(client: TestClient) -> None:
    response = client.get("/api/products")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 3
    ids = {product["product_id"] for product in body}
    assert ids == {"P1001", "P1002", "P2001"}


def test_product_shape_includes_canonical_fields(client: TestClient) -> None:
    product = client.get("/api/products").json()[0]

    for field in (
        "product_id", "name", "brand", "category",
        "price", "image_url", "stock", "in_stock",
    ):
        assert field in product


def test_filter_by_brand(client: TestClient) -> None:
    response = client.get("/api/products", params={"brand": "Nike"})

    body = response.json()
    assert len(body) == 1
    assert body[0]["brand"] == "Nike"


def test_filter_by_category_and_gender(client: TestClient) -> None:
    response = client.get(
        "/api/products", params={"category": "Bags", "gender": "Women"}
    )

    body = response.json()
    assert len(body) == 1
    assert body[0]["product_id"] == "P2001"


def test_filter_by_price_range(client: TestClient) -> None:
    response = client.get(
        "/api/products", params={"min_price": 3000, "max_price": 9000}
    )

    body = response.json()
    ids = {product["product_id"] for product in body}
    assert ids == {"P1002", "P2001"}


def test_no_matches_returns_empty_list_200(client: TestClient) -> None:
    response = client.get("/api/products", params={"brand": "Reebok"})

    assert response.status_code == 200
    assert response.json() == []


def test_invalid_category_enum_returns_422(client: TestClient) -> None:
    response = client.get("/api/products", params={"category": "Laptops"})

    assert response.status_code == 422


def test_out_of_stock_surfaced(client: TestClient) -> None:
    products = client.get("/api/products", params={"brand": "Adidas"}).json()

    assert products[0]["stock"] == 0
    assert products[0]["in_stock"] is False


def test_filters_endpoint_returns_distinct_options(client: TestClient) -> None:
    response = client.get("/api/filters")

    assert response.status_code == 200
    body = response.json()
    assert set(body["brands"]) == {"Nike", "Adidas", "Puma"}
    assert set(body["categories"]) == {"Shoes", "Bags"}
    assert set(body["genders"]) == {"Men", "Women"}
    assert set(body["colors"]) == {"Red", "Black"}
    assert body["price_range"]["min"] == 2799.0
    assert body["price_range"]["max"] == 8999.0
