"""Hybrid retriever — metadata filter + semantic search (E5-S2).

Executes the BRD hybrid retrieval strategy:

1. translate the structured :class:`QueryFilters` into a Pinecone metadata
   pre-filter (equality on brand/color/category/gender; numeric ``$gte``/``$lte``
   range on price; AC-1, AC-2);
2. embed the natural-language query intent into a 768-dim vector (AC-3);
3. run a single Pinecone vector query restricted by that filter and return at
   most the top-5 product IDs in similarity order (AC-3, AC-4).

When the metadata filter excludes every vector Pinecone returns no matches, and
the retriever yields an empty list — enabling the downstream no-match path
without error (AC-5).

Dependencies (the Pinecone client and embedding client) are injected as narrow
:class:`Protocol`s so the orchestration logic is unit-testable without live
services; this module never imports an external SDK.
"""

from decimal import Decimal
from typing import Any, Protocol

from backend.core.logging import get_logger
from backend.domain.models import QueryFilters

logger = get_logger(__name__)

TOP_K = 5


class SupportsVectorQuery(Protocol):
    """The Pinecone index capability the retriever needs (E4-S1/E4-S2)."""

    def query(self, **kwargs: Any) -> Any: ...


class SupportsIndexHandle(Protocol):
    """The Pinecone client capability the retriever needs (E4-S1)."""

    def index(self) -> SupportsVectorQuery: ...


class SupportsTextEmbedding(Protocol):
    """The embedding capability the retriever needs (E3-S2)."""

    def embed_text(self, text: str) -> list[float]: ...


class HybridRetriever:
    """Metadata pre-filter + semantic vector search over Pinecone (E5-S2)."""

    def __init__(
        self,
        *,
        pinecone_client: SupportsIndexHandle,
        embedding_client: SupportsTextEmbedding,
    ) -> None:
        self._pinecone_client = pinecone_client
        self._embedding_client = embedding_client

    def retrieve(self, query: str, filters: QueryFilters) -> list[str]:
        """Return up to top-5 product IDs for ``query`` under ``filters`` (AC-1..5)."""
        vector = self._embedding_client.embed_text(query)
        metadata_filter = _build_metadata_filter(filters)
        response = self._run_query(vector, metadata_filter)
        ids = _extract_ids(response)
        logger.info(
            "hybrid_retriever.retrieved",
            extra={"result_count": len(ids), "has_filter": bool(metadata_filter)},
        )
        return ids

    def _run_query(
        self, vector: list[float], metadata_filter: dict[str, Any]
    ) -> Any:
        index = self._pinecone_client.index()
        kwargs: dict[str, Any] = {
            "vector": vector,
            "top_k": TOP_K,
            "include_metadata": False,
        }
        if metadata_filter:
            kwargs["filter"] = metadata_filter
        return index.query(**kwargs)


def _build_metadata_filter(filters: QueryFilters) -> dict[str, Any]:
    """Build a Pinecone metadata filter from ``filters`` (E5-S2 AC-1, AC-2)."""
    clauses: dict[str, Any] = {}
    _add_equality(clauses, "brand", filters.brand)
    _add_equality(clauses, "color", filters.color)
    _add_equality(clauses, "category", filters.category.value if filters.category else None)
    _add_equality(clauses, "gender", filters.gender.value if filters.gender else None)
    price = _build_price_range(filters.min_price, filters.max_price)
    if price:
        clauses["price"] = price
    return clauses


def _add_equality(clauses: dict[str, Any], field: str, value: str | None) -> None:
    if value is not None:
        clauses[field] = {"$eq": value}


def _build_price_range(
    min_price: Decimal | None, max_price: Decimal | None
) -> dict[str, float]:
    bounds: dict[str, float] = {}
    if min_price is not None:
        bounds["$gte"] = float(min_price)
    if max_price is not None:
        bounds["$lte"] = float(max_price)
    return bounds


def _extract_ids(response: Any) -> list[str]:
    """Pull ranked match IDs from a Pinecone query response (E5-S2 AC-3, AC-5).

    Pinecone returns matches already ordered by descending similarity, so input
    order is preserved. A response with no matches yields an empty list.
    """
    matches = _matches_of(response)
    return [str(match_id) for match_id in (_id_of(match) for match in matches) if match_id]


def _matches_of(response: Any) -> list[Any]:
    if isinstance(response, dict):
        return list(response.get("matches") or [])
    return list(getattr(response, "matches", None) or [])


def _id_of(match: Any) -> str | None:
    if isinstance(match, dict):
        return match.get("id")
    return getattr(match, "id", None)
