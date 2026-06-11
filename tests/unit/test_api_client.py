"""Unit tests for the frontend HTTP client (E8-S1, E8-S2, E8-S3).

The client is the single seam between the Streamlit UI and the FastAPI backend.
Tests mock ``requests`` (the external HTTP boundary) only — the parsing,
parameter construction, and error-translation logic under test is never mocked.
"""

from collections.abc import Mapping
from decimal import Decimal

import pytest
import requests
from api_client import (
    ApiClient,
    ApiUnavailableError,
    ChatReply,
    FilterOptionsView,
    ProductQuery,
    ProductView,
)

BASE_URL = "http://localhost:8000"

PRODUCT_JSON = {
    "product_id": "P1001",
    "name": "Nike Revolution 6",
    "description": "Lightweight everyday running shoes.",
    "brand": "Nike",
    "category": "Shoes",
    "gender": "Men",
    "color": "Red",
    "price": 2799.00,
    "image_url": "https://cdn.example.com/p1001.jpg",
    "stock": 12,
    "in_stock": True,
    "tags": ["Running", "Sports"],
}

OUT_OF_STOCK_JSON = {
    "product_id": "P1003",
    "name": "Puma Essentials Tee",
    "description": "Soft cotton crew-neck t-shirt.",
    "brand": "Puma",
    "category": "Clothing",
    "gender": "Unisex",
    "color": "Black",
    "price": 799.00,
    "image_url": None,
    "stock": 0,
    "in_stock": False,
    "tags": ["Casual"],
}

FILTERS_JSON = {
    "brands": ["Adidas", "Nike", "Puma"],
    "categories": ["Accessories", "Bags", "Clothing", "Shoes", "Sportswear"],
    "genders": ["Kids", "Men", "Unisex", "Women"],
    "colors": ["Black", "Blue", "Red", "White"],
    "price_range": {"min": 199.00, "max": 14999.00},
}

CHAT_JSON = {
    "reply": "Here are some red Nike shoes you might like.",
    "products": [PRODUCT_JSON],
}


class _FakeResponse:
    """Minimal stand-in for ``requests.Response`` used by the session mock."""

    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        return self._payload


class _FakeSession:
    """Records the last request and returns a queued response (HTTP boundary mock)."""

    def __init__(self, response: _FakeResponse | Exception) -> None:
        self._response = response
        self.last_url: str | None = None
        self.last_params: Mapping[str, object] | None = None
        self.last_json: Mapping[str, object] | None = None
        self.last_timeout: float | None = None

    def get(
        self,
        url: str,
        params: Mapping[str, object] | None = None,
        timeout: float | None = None,
    ) -> _FakeResponse:
        self.last_url = url
        self.last_params = params
        self.last_timeout = timeout
        if isinstance(self._response, Exception):
            raise self._response
        return self._response

    def post(
        self,
        url: str,
        json: Mapping[str, object] | None = None,
        timeout: float | None = None,
    ) -> _FakeResponse:
        self.last_url = url
        self.last_json = json
        self.last_timeout = timeout
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def _client(response: _FakeResponse | Exception) -> tuple[ApiClient, _FakeSession]:
    session = _FakeSession(response)
    return ApiClient(base_url=BASE_URL, session=session), session


def test_get_products_parses_product_objects() -> None:
    # Arrange
    client, _ = _client(_FakeResponse(200, [PRODUCT_JSON, OUT_OF_STOCK_JSON]))
    # Act
    products = client.get_products(ProductQuery())
    # Assert
    assert [type(p) for p in products] == [ProductView, ProductView]
    assert products[0].product_id == "P1001"
    assert products[0].price == Decimal("2799.00")
    assert products[1].in_stock is False


def test_get_products_omits_unset_filter_params() -> None:
    # Arrange
    client, session = _client(_FakeResponse(200, []))
    # Act
    client.get_products(ProductQuery(brand="Nike", category="Shoes"))
    # Assert — only the set params are forwarded; None values are dropped
    assert session.last_params == {"brand": "Nike", "category": "Shoes"}
    assert session.last_url == f"{BASE_URL}/api/products"


def test_get_products_forwards_price_bounds_as_numbers() -> None:
    # Arrange
    client, session = _client(_FakeResponse(200, []))
    # Act
    client.get_products(ProductQuery(min_price=Decimal("500"), max_price=Decimal("3000")))
    # Assert
    assert session.last_params == {"min_price": 500.0, "max_price": 3000.0}


def test_get_products_empty_result_is_empty_list_not_error() -> None:
    # Arrange
    client, _ = _client(_FakeResponse(200, []))
    # Act
    products = client.get_products(ProductQuery(brand="Puma", category="Bags"))
    # Assert — no-match is a normal empty list (E7-S3 AC-4 / E8-S2)
    assert products == []


def test_get_filters_parses_options_and_price_range() -> None:
    # Arrange
    client, _ = _client(_FakeResponse(200, FILTERS_JSON))
    # Act
    options = client.get_filters()
    # Assert
    assert isinstance(options, FilterOptionsView)
    assert options.brands == ["Adidas", "Nike", "Puma"]
    assert options.price_min == Decimal("199.00")
    assert options.price_max == Decimal("14999.00")


def test_post_chat_sends_session_and_message_and_parses_reply() -> None:
    # Arrange
    client, session = _client(_FakeResponse(200, CHAT_JSON))
    # Act
    reply = client.post_chat(session_id="sess-7a3f", message="Show me red Nike shoes")
    # Assert
    assert session.last_url == f"{BASE_URL}/api/chat"
    assert session.last_json == {"session_id": "sess-7a3f", "message": "Show me red Nike shoes"}
    assert isinstance(reply, ChatReply)
    assert reply.reply == "Here are some red Nike shoes you might like."
    assert len(reply.products) == 1
    assert reply.products[0].product_id == "P1001"


def test_post_chat_no_match_yields_message_and_zero_products() -> None:
    # Arrange
    no_match = {
        "reply": "I couldn't find anything matching that. We carry Shoes, Clothing, "
        "Accessories, Sportswear and Bags — want to browse one of those?",
        "products": [],
    }
    client, _ = _client(_FakeResponse(200, no_match))
    # Act
    reply = client.post_chat(session_id="sess-7a3f", message="show me laptops")
    # Assert
    assert reply.products == []
    assert "couldn't find" in reply.reply


def test_server_error_envelope_becomes_friendly_message() -> None:
    # Arrange — backend 503 with the BRD error envelope
    envelope = {
        "error": {
            "code": "MYSQL_UNAVAILABLE",
            "message": "We are unable to load product details right now. Please try again later.",
        }
    }
    client, _ = _client(_FakeResponse(503, envelope))
    # Act / Assert
    with pytest.raises(ApiUnavailableError) as exc:
        client.get_products(ProductQuery())
    assert exc.value.code == "MYSQL_UNAVAILABLE"
    assert "unable to load product details" in str(exc.value)


def test_connection_failure_becomes_friendly_message_not_traceback() -> None:
    # Arrange — backend unreachable (E8-S1 AC-4: no stack trace)
    client, _ = _client(requests.ConnectionError("refused"))
    # Act / Assert
    with pytest.raises(ApiUnavailableError) as exc:
        client.get_products(ProductQuery())
    assert "try again" in str(exc.value).lower()


def test_chat_connection_failure_raises_friendly_error() -> None:
    # Arrange
    client, _ = _client(requests.Timeout("slow"))
    # Act / Assert
    with pytest.raises(ApiUnavailableError):
        client.post_chat(session_id="sess-1", message="hi")
