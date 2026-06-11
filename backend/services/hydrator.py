"""MySQL hydration of retrieved product IDs (E5-S3).

Pinecone returns only IDs and metadata; the full display record (description,
image URL, stock, etc.) lives in MySQL. This step turns the retriever's ranked
ID list into complete :class:`Product` objects, preserving the retrieval rank
order (AC-1, AC-2).

An ID present in Pinecone but absent from MySQL (e.g. deleted after indexing) is
skipped and logged rather than failing the whole request (AC-3); an empty ID
list short-circuits with no database query at all (AC-4).

The repository is injected as a narrow :class:`Protocol` so this orchestration
logic is unit-testable without a live database.
"""

from typing import Protocol

from backend.core.logging import get_logger
from backend.domain.models import Product

logger = get_logger(__name__)


class SupportsBulkProductLookup(Protocol):
    """The repository capability the hydrator needs (E2-S2)."""

    def get_products_by_ids(self, product_ids: list[str]) -> list[Product]: ...


class ProductHydrator:
    """Hydrates ranked product IDs into full :class:`Product` records (E5-S3)."""

    def __init__(self, *, repository: SupportsBulkProductLookup) -> None:
        self._repository = repository

    def hydrate(self, product_ids: list[str]) -> list[Product]:
        """Return full products for ``product_ids`` in rank order (AC-1..AC-4)."""
        if not product_ids:
            return []
        products = self._repository.get_products_by_ids(product_ids)
        ordered = _order_by_rank(products, product_ids)
        _log_missing(product_ids, ordered)
        return ordered


def _order_by_rank(products: list[Product], ranked_ids: list[str]) -> list[Product]:
    """Reorder ``products`` to match ``ranked_ids``; drop unranked ones (AC-2)."""
    by_id = {product.product_id: product for product in products}
    return [by_id[pid] for pid in ranked_ids if pid in by_id]


def _log_missing(requested_ids: list[str], hydrated: list[Product]) -> None:
    """Log any requested ID that MySQL did not return (E5-S3 AC-3)."""
    hydrated_ids = {product.product_id for product in hydrated}
    missing = [pid for pid in requested_ids if pid not in hydrated_ids]
    if missing:
        logger.warning(
            "hydrator.missing_products",
            extra={"missing_ids": missing, "missing_count": len(missing)},
        )
