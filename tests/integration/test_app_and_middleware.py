"""Integration tests for E7-S1 — app bootstrap, health, CORS, error middleware."""

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from backend.api.main import create_app
from backend.core.errors import (
    EmbeddingError,
    GenerationError,
    RepositoryError,
    RetrievalError,
)

pytestmark = pytest.mark.integration


def test_health_returns_200_with_status_body(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "shopassistant-backend"


def test_cors_allows_streamlit_origin(client: TestClient) -> None:
    response = client.get(
        "/api/health", headers={"Origin": "http://localhost:8501"}
    )

    assert response.headers["access-control-allow-origin"] == "http://localhost:8501"


def test_each_response_carries_a_request_id_header(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.headers["X-Request-ID"]


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (EmbeddingError("gemini down"), 503, "GEMINI_UNAVAILABLE"),
        (GenerationError("gemini down"), 503, "GEMINI_UNAVAILABLE"),
        (RetrievalError("pinecone down"), 503, "PINECONE_UNAVAILABLE"),
        (RepositoryError("mysql down"), 503, "MYSQL_UNAVAILABLE"),
    ],
)
def test_typed_service_errors_map_to_brd_envelope(
    error: Exception, status: int, code: str
) -> None:
    app = create_app()
    router = APIRouter()

    @router.get("/api/_boom")
    def boom() -> None:
        raise error

    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/_boom")

    assert response.status_code == status
    body = response.json()
    assert body["error"]["code"] == code
    assert body["error"]["message"]
    assert "Traceback" not in response.text


def test_unhandled_exception_returns_500_envelope_without_trace() -> None:
    app = create_app()
    router = APIRouter()

    @router.get("/api/_explode")
    def explode() -> None:
        raise ValueError("secret internal detail xyz")

    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/_explode")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "secret internal detail xyz" not in response.text
    assert "Traceback" not in response.text
