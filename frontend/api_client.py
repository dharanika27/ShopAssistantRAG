"""Thin typed HTTP client to the FastAPI backend (E8-S1, E8-S2, E8-S3).

This is the single seam between the Streamlit UI and the backend. The UI never
imports backend Python modules (one-way import rule, folder-structure.md); it
only calls the methods here, which speak HTTP and return frontend-local view
models — the UI never sees raw JSON or ``requests`` objects.

Every backend failure (a non-2xx error envelope or a transport error) is
translated into a single typed :class:`ApiUnavailableError` carrying the
BRD-style friendly message, so the UI can show that message instead of a stack
trace (E8-S1 AC-4, error-handling-strategy.md §"Frontend").
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

import requests

DEFAULT_BASE_URL = "http://localhost:8000"
_DEFAULT_TIMEOUT_SECONDS = 10.0
_TRANSPORT_ERROR_MESSAGE = (
    "We are unable to reach the assistant right now. Please try again later."
)
_UNKNOWN_ERROR_MESSAGE = "An unexpected error occurred. Please try again later."


class ApiUnavailableError(Exception):
    """A backend call failed — surfaced to the UI as a friendly message.

    Carries the machine-readable ``code`` from the error envelope when present
    (e.g. ``MYSQL_UNAVAILABLE``) and a human-readable, stack-trace-free message
    suitable for direct display.
    """

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ProductView:
    """UI-local view of a catalog product (mirrors api-contracts.md §2/§3)."""

    product_id: str
    name: str
    description: str | None
    brand: str | None
    category: str
    gender: str | None
    color: str | None
    price: Decimal
    image_url: str | None
    stock: int
    in_stock: bool
    tags: list[str]


@dataclass(frozen=True)
class FilterOptionsView:
    """UI-local view of the available filter options (api-contracts.md §4)."""

    brands: list[str]
    categories: list[str]
    genders: list[str]
    colors: list[str]
    price_min: Decimal
    price_max: Decimal


@dataclass(frozen=True)
class ChatReply:
    """UI-local view of one chat turn's response (api-contracts.md §2)."""

    reply: str
    products: list[ProductView]


@dataclass(frozen=True)
class ProductQuery:
    """Selected catalog filters; ``None`` fields are omitted from the request."""

    brand: str | None = None
    category: str | None = None
    gender: str | None = None
    color: str | None = None
    min_price: Decimal | None = None
    max_price: Decimal | None = None

    def to_params(self) -> dict[str, str | float]:
        """Render the set filters as query params, dropping unset ones."""
        params: dict[str, str | float] = {}
        for name in ("brand", "category", "gender", "color"):
            value = getattr(self, name)
            if value:
                params[name] = value
        if self.min_price is not None:
            params["min_price"] = float(self.min_price)
        if self.max_price is not None:
            params["max_price"] = float(self.max_price)
        return params


class _HttpResponse(Protocol):
    """The subset of ``requests.Response`` the client reads."""

    status_code: int

    def json(self) -> Any: ...


class _HttpSession(Protocol):
    """The subset of ``requests.Session`` the client uses (the mock boundary)."""

    def get(
        self,
        url: str,
        params: Mapping[str, object] | None = ...,
        timeout: float | None = ...,
    ) -> _HttpResponse: ...

    def post(
        self,
        url: str,
        json: Mapping[str, object] | None = ...,
        timeout: float | None = ...,
    ) -> _HttpResponse: ...


@dataclass
class ApiClient:
    """Typed HTTP client for the ShopAssistant backend."""

    base_url: str = DEFAULT_BASE_URL
    session: _HttpSession = field(default_factory=requests.Session)
    timeout: float = _DEFAULT_TIMEOUT_SECONDS

    def get_products(self, query: ProductQuery) -> list[ProductView]:
        """Fetch catalog products matching ``query`` (api-contracts.md §3)."""
        payload = self._get("/api/products", params=query.to_params())
        return [_parse_product(item) for item in _as_list(payload)]

    def get_filters(self) -> FilterOptionsView:
        """Fetch the distinct filter option values (api-contracts.md §4)."""
        payload = self._get("/api/filters", params={})
        return _parse_filters(_as_dict(payload))

    def post_chat(self, session_id: str, message: str) -> ChatReply:
        """Run one conversational turn (api-contracts.md §2)."""
        payload = self._post(
            "/api/chat", body={"session_id": session_id, "message": message}
        )
        return _parse_chat_reply(_as_dict(payload))

    def _get(self, path: str, params: Mapping[str, object]) -> object:
        try:
            response = self.session.get(
                f"{self.base_url}{path}", params=params, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise _transport_error(exc) from exc
        return _read_payload(response)

    def _post(self, path: str, body: Mapping[str, object]) -> object:
        try:
            response = self.session.post(
                f"{self.base_url}{path}", json=body, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise _transport_error(exc) from exc
        return _read_payload(response)


def _read_payload(response: _HttpResponse) -> object:
    """Return the JSON body for a 2xx response or raise a friendly error."""
    body = response.json()
    if 200 <= response.status_code < 300:
        return body
    raise _envelope_error(body)


def _envelope_error(body: object) -> ApiUnavailableError:
    """Translate a non-2xx error envelope into a typed friendly error."""
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            message = str(error.get("message", _UNKNOWN_ERROR_MESSAGE))
            code = str(error.get("code", "INTERNAL_ERROR"))
            return ApiUnavailableError(message, code=code)
    return ApiUnavailableError(_UNKNOWN_ERROR_MESSAGE, code="INTERNAL_ERROR")


def _transport_error(exc: requests.RequestException) -> ApiUnavailableError:
    """Translate a transport failure into a friendly, trace-free error."""
    return ApiUnavailableError(_TRANSPORT_ERROR_MESSAGE, code="BACKEND_UNREACHABLE")


def _as_list(payload: object) -> list[object]:
    if not isinstance(payload, list):
        raise ApiUnavailableError(_UNKNOWN_ERROR_MESSAGE, code="INVALID_RESPONSE")
    return payload


def _as_dict(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ApiUnavailableError(_UNKNOWN_ERROR_MESSAGE, code="INVALID_RESPONSE")
    return payload


def _parse_product(item: object) -> ProductView:
    """Build a :class:`ProductView` from one product JSON object."""
    data = _as_dict(item)
    return ProductView(
        product_id=str(data["product_id"]),
        name=str(data["name"]),
        description=_optional_str(data.get("description")),
        brand=_optional_str(data.get("brand")),
        category=str(data["category"]),
        gender=_optional_str(data.get("gender")),
        color=_optional_str(data.get("color")),
        price=Decimal(str(data["price"])),
        image_url=_optional_str(data.get("image_url")),
        stock=int(str(data["stock"])),
        in_stock=bool(data["in_stock"]),
        tags=[str(tag) for tag in _as_list(data.get("tags", []))],
    )


def _parse_filters(data: dict[str, object]) -> FilterOptionsView:
    """Build a :class:`FilterOptionsView` from the filters JSON object."""
    price_range = _as_dict(data["price_range"])
    return FilterOptionsView(
        brands=[str(value) for value in _as_list(data["brands"])],
        categories=[str(value) for value in _as_list(data["categories"])],
        genders=[str(value) for value in _as_list(data["genders"])],
        colors=[str(value) for value in _as_list(data["colors"])],
        price_min=Decimal(str(price_range["min"])),
        price_max=Decimal(str(price_range["max"])),
    )


def _parse_chat_reply(data: dict[str, object]) -> ChatReply:
    """Build a :class:`ChatReply` from the chat JSON object."""
    return ChatReply(
        reply=str(data["reply"]),
        products=[_parse_product(item) for item in _as_list(data.get("products", []))],
    )


def _optional_str(value: object) -> str | None:
    """Return the value as a string, preserving ``None``."""
    return None if value is None else str(value)
