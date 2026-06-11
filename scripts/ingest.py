"""CLI entrypoint to run the product ingestion pipeline (E3-S3).

Usage::

    python -m scripts.ingest [CSV_PATH]

Loads the catalog CSV, persists valid rows to MySQL, embeds them with Gemini,
and upserts the resulting vectors into Pinecone. Row-level and embedding
failures are non-fatal: they are skipped, counted, and listed in the summary
report printed at the end (AC-4). Re-running on the same CSV updates records in
place rather than duplicating them (AC-5). Exits non-zero only on a fatal setup
failure (bad config, unreachable service), never on skipped rows.
"""

import sys
from pathlib import Path

from backend.core.config import Settings
from backend.core.errors import AppError
from backend.core.logging import get_logger
from backend.repositories.pinecone_client import PineconeClient
from backend.repositories.product_repository import ProductRepository
from backend.services.embedding_client import EmbeddingClient
from backend.services.ingestion import IngestionPipeline

logger = get_logger(__name__)

_DEFAULT_CSV_PATH = Path("data/products.csv")


def _resolve_csv_path(argv: list[str]) -> Path:
    return Path(argv[1]) if len(argv) > 1 else _DEFAULT_CSV_PATH


def _build_pipeline(settings: Settings) -> IngestionPipeline:
    pinecone_client = PineconeClient(settings)
    pinecone_client.ensure_index()
    return IngestionPipeline(
        repository=ProductRepository(settings),
        embedding_client=EmbeddingClient(settings),
        pinecone_client=pinecone_client,
    )


def main(argv: list[str] | None = None) -> int:
    """Load settings, run the pipeline, print the summary, return an exit code."""
    args = list(argv if argv is not None else sys.argv)
    csv_path = _resolve_csv_path(args)
    try:
        settings = Settings()
        pipeline = _build_pipeline(settings)
        summary = pipeline.run(csv_path)
    except AppError as exc:
        logger.error("ingest.failed", extra={"code": exc.code})
        print(f"Ingestion failed [{exc.code}]: {exc}", file=sys.stderr)
        return 1
    print(summary.render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
