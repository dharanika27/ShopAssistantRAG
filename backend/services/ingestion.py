"""Ingestion pipeline orchestration & summary report (E3-S3).

Wires the full data flow for the standalone ingestion run:

    CSV → validate → MySQL upsert → embedding text → Gemini embeddings →
    Pinecone upsert

Per the BRD, the pipeline is resilient: a CSV row that fails validation, or a
product whose embedding generation fails, is skipped and counted — it never
aborts the run (AC-2, AC-3). MySQL is the system of record, so every valid row
is persisted there even if its embedding later fails; only successfully embedded
products reach Pinecone. Every run produces an :class:`IngestionSummary` with
total / successful / failed counts and failure reasons (AC-4). Because both the
MySQL upsert and the Pinecone upsert are keyed by ``product_id``, re-running on
the same CSV updates records in place rather than duplicating them (AC-5).

Dependencies (repository, embedding client, Pinecone client, CSV loader) are
injected so the orchestration logic is unit-testable without live services.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from backend.core.errors import EmbeddingError
from backend.core.logging import get_logger
from backend.domain.models import Product
from backend.services.csv_loader import CsvLoadResult, RowFailure, load_products_from_csv
from backend.services.embedding_text import build_embedding_text

logger = get_logger(__name__)

CsvLoader = Callable[[Path], CsvLoadResult]


class SupportsProductUpsert(Protocol):
    """The repository capability the pipeline needs (E2-S2)."""

    def upsert_product(self, product: Product) -> None: ...


class SupportsTextEmbedding(Protocol):
    """The embedding capability the pipeline needs (E3-S2)."""

    def embed_text(self, text: str) -> list[float]: ...


class SupportsVectorUpsert(Protocol):
    """The Pinecone capability the pipeline needs (E4-S2)."""

    def upsert_products(
        self, products: list[Product], vectors: list[list[float]]
    ) -> None: ...


@dataclass
class IngestionSummary:
    """Outcome of an ingestion run: counts and per-row failure reasons (AC-4)."""

    total_rows: int
    successful: int
    failures: list[RowFailure] = field(default_factory=list)

    @property
    def failed(self) -> int:
        """Number of rows skipped (CSV-invalid or embedding-failed)."""
        return len(self.failures)

    def render(self) -> str:
        """Render a human-readable summary report for the CLI (AC-4)."""
        lines = [
            "Ingestion summary",
            f"  Total processed: {self.total_rows}",
            f"  Successful:      {self.successful}",
            f"  Failed:          {self.failed}",
        ]
        if self.failures:
            lines.append("  Failure reasons:")
            lines.extend(
                f"    - {failure.row_id}: {failure.reason}"
                for failure in self.failures
            )
        return "\n".join(lines)


class IngestionPipeline:
    """Orchestrates CSV → MySQL → embeddings → Pinecone for one run (E3-S3)."""

    def __init__(
        self,
        *,
        repository: SupportsProductUpsert,
        embedding_client: SupportsTextEmbedding,
        pinecone_client: SupportsVectorUpsert,
        loader: CsvLoader = load_products_from_csv,
    ) -> None:
        self._repository = repository
        self._embedding_client = embedding_client
        self._pinecone_client = pinecone_client
        self._loader = loader

    def run(self, csv_path: Path) -> IngestionSummary:
        """Ingest ``csv_path`` end-to-end and return the run summary (AC-1)."""
        load_result = self._loader(csv_path)
        failures = list(load_result.failures)
        embedded = self._persist_and_embed(load_result.products, failures)
        self._upsert_vectors(embedded)
        summary = IngestionSummary(
            total_rows=len(load_result.products) + len(load_result.failures),
            successful=len(embedded),
            failures=failures,
        )
        logger.info(
            "ingestion.completed",
            extra={
                "total": summary.total_rows,
                "successful": summary.successful,
                "failed": summary.failed,
            },
        )
        return summary

    def _persist_and_embed(
        self, products: list[Product], failures: list[RowFailure]
    ) -> list[tuple[Product, list[float]]]:
        """Persist each product to MySQL and embed it; collect failures (AC-3)."""
        embedded: list[tuple[Product, list[float]]] = []
        for product in products:
            self._repository.upsert_product(product)
            vector = self._embed_product(product, failures)
            if vector is not None:
                embedded.append((product, vector))
        return embedded

    def _embed_product(
        self, product: Product, failures: list[RowFailure]
    ) -> list[float] | None:
        """Embed one product; on failure record it and return ``None`` (AC-3)."""
        try:
            return self._embedding_client.embed_text(build_embedding_text(product))
        except EmbeddingError as exc:
            logger.warning(
                "ingestion.embedding_failed",
                extra={"product_id": product.product_id, "reason": str(exc)},
            )
            failures.append(
                RowFailure(
                    row_id=product.product_id,
                    reason=f"embedding failed: {exc}",
                )
            )
            return None

    def _upsert_vectors(
        self, embedded: list[tuple[Product, list[float]]]
    ) -> None:
        """Batch-upsert the successfully embedded products into Pinecone (AC-1)."""
        if not embedded:
            return
        products = [product for product, _ in embedded]
        vectors = [vector for _, vector in embedded]
        self._pinecone_client.upsert_products(products, vectors)
