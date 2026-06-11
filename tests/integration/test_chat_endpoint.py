"""Integration tests for E7-S2 — POST /api/chat."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from backend.core.errors import GenerationError
from backend.services.chat_orchestrator import ChatResult

from .conftest import FakeChatOrchestrator, build_product

pytestmark = pytest.mark.integration


def test_valid_query_returns_reply_and_products(client: TestClient) -> None:
    response = client.post(
        "/api/chat",
        json={"session_id": "sess-abc", "message": "red Nike shoes under 3000"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "Here are some matches."
    assert len(body["products"]) == 1
    assert body["products"][0]["product_id"] == "P1001"
    assert body["products"][0]["in_stock"] is True


def test_products_are_capped_at_five(
    client: TestClient, orchestrator: FakeChatOrchestrator
) -> None:
    many = [build_product(product_id=f"P{n}") for n in range(8)]
    orchestrator.set_result(ChatResult(reply="lots", products=many))

    response = client.post(
        "/api/chat", json={"session_id": "sess-abc", "message": "shoes"}
    )

    assert response.status_code == 200
    assert len(response.json()["products"]) == 5


def test_distinct_sessions_are_forwarded_independently(
    client: TestClient, orchestrator: FakeChatOrchestrator
) -> None:
    client.post("/api/chat", json={"session_id": "sess-1", "message": "shoes"})
    client.post("/api/chat", json={"session_id": "sess-2", "message": "bags"})

    assert ("sess-1", "shoes") in orchestrator.calls
    assert ("sess-2", "bags") in orchestrator.calls


def test_empty_message_returns_422(client: TestClient) -> None:
    response = client.post(
        "/api/chat", json={"session_id": "sess-abc", "message": "   "}
    )

    assert response.status_code == 422


def test_missing_message_returns_422(client: TestClient) -> None:
    response = client.post("/api/chat", json={"session_id": "sess-abc"})

    assert response.status_code == 422


def test_empty_session_id_returns_422(client: TestClient) -> None:
    response = client.post("/api/chat", json={"session_id": "", "message": "shoes"})

    assert response.status_code == 422


def test_no_match_returns_friendly_reply_with_empty_products(
    client: TestClient, orchestrator: FakeChatOrchestrator
) -> None:
    orchestrator.set_result(
        ChatResult(reply="I couldn't find any products matching that.", products=[])
    )

    response = client.post(
        "/api/chat", json={"session_id": "sess-abc", "message": "laptops"}
    )

    assert response.status_code == 200
    assert response.json()["products"] == []


def test_downstream_service_failure_maps_to_envelope(
    client: TestClient, orchestrator: FakeChatOrchestrator
) -> None:
    def boom(session_id: str, message: str) -> ChatResult:
        raise GenerationError("gemini down")

    orchestrator.handle_turn = boom  # type: ignore[method-assign]

    response = client.post(
        "/api/chat", json={"session_id": "sess-abc", "message": "shoes"}
    )

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "GEMINI_UNAVAILABLE"
    assert "Traceback" not in response.text


def test_price_serialized_as_number(client: TestClient, orchestrator: FakeChatOrchestrator) -> None:
    orchestrator.set_result(
        ChatResult(reply="x", products=[build_product(price=Decimal("2799.00"))])
    )

    response = client.post(
        "/api/chat", json={"session_id": "sess-abc", "message": "shoes"}
    )

    assert response.json()["products"][0]["price"] == 2799.0
