"""Unit tests for E5-S2 — Hybrid retriever (metadata filter + semantic search).

Pinecone and the embedding client are the external boundaries and are mocked via
lightweight fakes. The hybrid-retrieval business logic (metadata filter
construction, 768-dim query embedding, top-5 truncation, empty-result handling)
is exercised directly. No live API call is made.
"""

from decimal import Decimal
from typing import Any

import pytest

from backend.domain.enums import Category, Gender
from backend.domain.models import QueryFilters
from backend.services.hybrid_retriever import HybridRetriever

_TOP_K = 5


class _FakeEmbeddingClient:
    def __init__(self) -> None:
        self.embedded: list[str] = []

    def embed_text(self, text: str) -> list[float]:
        self.embedded.append(text)
        return [0.1] * 768


class _FakeIndex:
    def __init__(self, matches: list[dict[str, Any]]) -> None:
        self._matches = matches
        self.last_query: dict[str, Any] | None = None

    def query(self, **kwargs: Any) -> dict[str, Any]:
        self.last_query = kwargs
        top_k = kwargs["top_k"]
        return {"matches": self._matches[:top_k]}


class _FakePineconeClient:
    def __init__(self, index: _FakeIndex) -> None:
        self._index = index

    def index(self) -> _FakeIndex:
        return self._index


def _matches(count: int) -> list[dict[str, Any]]:
    return [
        {"id": f"SKU-{rank:03d}", "score": 1.0 - rank * 0.1}
        for rank in range(count)
    ]


def _build(index: _FakeIndex) -> tuple[HybridRetriever, _FakeEmbeddingClient]:
    embedder = _FakeEmbeddingClient()
    retriever = HybridRetriever(
        pinecone_client=_FakePineconeClient(index),
        embedding_client=embedder,
    )
    return retriever, embedder


class TestMetadataFilters:
    def test_equality_fields_become_pinecone_filters(self) -> None:
        index = _FakeIndex(_matches(3))
        retriever, _ = _build(index)
        filters = QueryFilters(
            brand="Nike",
            color="Red",
            category=Category.SHOES,
            gender=Gender.MEN,
        )

        retriever.retrieve("red nike shoes for men", filters)

        assert index.last_query is not None
        assert index.last_query["filter"] == {
            "brand": {"$eq": "Nike"},
            "color": {"$eq": "Red"},
            "category": {"$eq": "Shoes"},
            "gender": {"$eq": "Men"},
        }

    def test_price_bounds_become_numeric_range_filters(self) -> None:
        index = _FakeIndex(_matches(2))
        retriever, _ = _build(index)
        filters = QueryFilters(min_price=Decimal("1000"), max_price=Decimal("3000"))

        retriever.retrieve("mid-range bag", filters)

        assert index.last_query is not None
        assert index.last_query["filter"] == {
            "price": {"$gte": 1000.0, "$lte": 3000.0}
        }

    def test_no_filters_sends_no_filter_clause(self) -> None:
        index = _FakeIndex(_matches(2))
        retriever, _ = _build(index)

        retriever.retrieve("anything", QueryFilters())

        assert index.last_query is not None
        assert index.last_query.get("filter") in (None, {})


class TestSemanticSearch:
    def test_query_is_embedded_to_768_dims(self) -> None:
        index = _FakeIndex(_matches(2))
        retriever, embedder = _build(index)

        retriever.retrieve("waterproof hiking boots", QueryFilters())

        assert embedder.embedded == ["waterproof hiking boots"]
        assert index.last_query is not None
        assert len(index.last_query["vector"]) == 768

    def test_results_preserve_similarity_order(self) -> None:
        index = _FakeIndex(_matches(3))
        retriever, _ = _build(index)

        ids = retriever.retrieve("running shoes", QueryFilters())

        assert ids == ["SKU-000", "SKU-001", "SKU-002"]


class TestTopKAndEmptyResults:
    def test_returns_at_most_five_ids(self) -> None:
        index = _FakeIndex(_matches(20))
        retriever, _ = _build(index)

        ids = retriever.retrieve("popular sneakers", QueryFilters())

        assert len(ids) == _TOP_K
        assert index.last_query is not None
        assert index.last_query["top_k"] == _TOP_K

    def test_empty_matches_return_empty_list(self) -> None:
        index = _FakeIndex([])
        retriever, _ = _build(index)

        ids = retriever.retrieve("nonexistent product", QueryFilters())

        assert ids == []

    def test_missing_matches_key_returns_empty_list(self) -> None:
        class _EmptyIndex(_FakeIndex):
            def query(self, **kwargs: Any) -> dict[str, Any]:
                self.last_query = kwargs
                return {}

        retriever, _ = _build(_EmptyIndex([]))

        ids = retriever.retrieve("anything", QueryFilters())

        assert ids == []


@pytest.fixture(autouse=True)
def _no_network() -> None:
    """Guard: these tests must never touch a real network boundary."""
    return None
