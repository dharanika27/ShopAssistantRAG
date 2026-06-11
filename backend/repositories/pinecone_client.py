"""Pinecone index provisioning & client (E4-S1).

Single integration point for the Pinecone vector store. This is the only module
that talks to the Pinecone SDK; business logic depends on this typed wrapper,
never on the SDK (code-gen wrapper pattern). The client:

* connects using ``PINECONE_API_KEY`` from centralized :class:`Settings`
  (AC-1);
* idempotently ensures the configured index exists with dimension 768 and
  cosine metric — creating it if absent, reusing it otherwise (AC-2);
* rejects a configured dimension other than 768 as a :class:`ConfigError`
  (AC-3);
* catches raw SDK exceptions and re-raises :class:`RetrievalError` so no SDK
  type leaks to callers (AC-4);
* accepts an injected ``sdk_factory`` so tests substitute the SDK without a live
  connection.

Upsert (E4-S2) writes one vector per product keyed by ``product_id`` with the
retrieval metadata (brand, color, category, gender, numeric price) needed for
hybrid search; query (E5-S2) is added later against the same index handle.
"""

from collections.abc import Callable
from typing import Any

from backend.core.config import Settings
from backend.core.errors import ConfigError, RetrievalError
from backend.core.logging import get_logger
from backend.domain.models import Product

logger = get_logger(__name__)

EMBEDDING_DIM = 768
UPSERT_BATCH_SIZE = 100
_METRIC = "cosine"
_CLOUD = "aws"
_REGION = "us-east-1"

SdkFactory = Callable[[str], Any]


def _default_sdk_factory(api_key: str) -> Any:
    """Construct the live Pinecone SDK client (lazy import).

    Imported lazily so importing this module never requires the SDK to be
    installed — unit tests inject a fake ``sdk_factory`` instead.
    """
    from pinecone import Pinecone

    return Pinecone(api_key=api_key)


class PineconeClient:
    """Typed wrapper that provisions and hands out the product index (E4-S1)."""

    def __init__(
        self, settings: Settings, *, sdk_factory: SdkFactory = _default_sdk_factory
    ) -> None:
        self._index_name = settings.PINECONE_INDEX_NAME
        self._dimension = _require_supported_dimension(settings.EMBEDDING_DIM)
        self._sdk = self._connect(settings, sdk_factory)

    def _connect(self, settings: Settings, sdk_factory: SdkFactory) -> Any:
        try:
            return sdk_factory(settings.pinecone_api_key_value())
        except Exception as exc:
            logger.error("pinecone.connect_failed", extra={"index": self._index_name})
            raise RetrievalError(f"Failed to connect to Pinecone: {exc}") from exc

    def ensure_index(self) -> None:
        """Create the index if absent, otherwise reuse it (E4-S1 AC-2).

        Idempotent: a second call with the index already present is a no-op.
        Raises :class:`RetrievalError` on any SDK failure (AC-4).
        """
        try:
            if self._index_exists():
                logger.info("pinecone.index_reused", extra={"index": self._index_name})
                return
            self._create_index()
            logger.info("pinecone.index_created", extra={"index": self._index_name})
        except RetrievalError:
            raise
        except Exception as exc:
            logger.error(
                "pinecone.provisioning_failed", extra={"index": self._index_name}
            )
            raise RetrievalError(
                f"Failed to provision Pinecone index {self._index_name!r}: {exc}"
            ) from exc

    def index(self) -> Any:
        """Return the SDK index handle for upsert/query (E4-S2, E5-S2)."""
        try:
            return self._sdk.Index(self._index_name)
        except Exception as exc:
            raise RetrievalError(
                f"Failed to open Pinecone index {self._index_name!r}: {exc}"
            ) from exc

    def upsert_products(
        self, products: list[Product], vectors: list[list[float]]
    ) -> None:
        """Upsert one vector per product, keyed by ``product_id`` (E4-S2 AC-1).

        Each vector carries the retrieval metadata (brand, color, category,
        gender, numeric price; AC-2/AC-4). Re-upserting an existing
        ``product_id`` overwrites the prior vector and metadata (AC-3). Writes
        are batched at :data:`UPSERT_BATCH_SIZE` so 500–1000 products load in a
        single run without exceeding request limits (AC-5). Raises
        :class:`RetrievalError` on length mismatch or any SDK failure.
        """
        _require_matching_lengths(products, vectors)
        if not products:
            return
        records = [
            _to_pinecone_record(product, vector)
            for product, vector in zip(products, vectors, strict=True)
        ]
        self._upsert_in_batches(records)
        logger.info(
            "pinecone.products_upserted",
            extra={"index": self._index_name, "count": len(records)},
        )

    def _upsert_in_batches(self, records: list[dict[str, Any]]) -> None:
        handle = self.index()
        try:
            for start in range(0, len(records), UPSERT_BATCH_SIZE):
                batch = records[start : start + UPSERT_BATCH_SIZE]
                handle.upsert(vectors=batch)
        except Exception as exc:
            logger.error(
                "pinecone.upsert_failed", extra={"index": self._index_name}
            )
            raise RetrievalError(
                f"Failed to upsert vectors into {self._index_name!r}: {exc}"
            ) from exc

    def _index_exists(self) -> bool:
        names = {entry["name"] for entry in self._sdk.list_indexes()}
        return self._index_name in names

    def _create_index(self) -> None:
        self._sdk.create_index(
            name=self._index_name,
            dimension=self._dimension,
            metric=_METRIC,
            **_serverless_spec(),
        )


def _require_matching_lengths(
    products: list[Product], vectors: list[list[float]]
) -> None:
    if len(products) != len(vectors):
        raise RetrievalError(
            f"Cannot upsert: {len(products)} product(s) but "
            f"{len(vectors)} vector(s)"
        )


def _to_pinecone_record(product: Product, vector: list[float]) -> dict[str, Any]:
    return {
        "id": product.product_id,
        "values": vector,
        "metadata": _build_metadata(product),
    }


def _build_metadata(product: Product) -> dict[str, Any]:
    """Build retrieval metadata; ``None`` optional fields are omitted (E4-S2 AC-2).

    ``price`` is stored as ``float`` so Pinecone range filters (``$gte`` /
    ``$lte``) work (AC-4); ``category``/``gender`` use their enum string values.
    """
    metadata: dict[str, Any] = {
        "category": product.category.value,
        "price": float(product.price),
    }
    if product.brand:
        metadata["brand"] = product.brand
    if product.color:
        metadata["color"] = product.color
    if product.gender:
        metadata["gender"] = product.gender.value
    return metadata


def _require_supported_dimension(dimension: int) -> int:
    """Reject any configured dimension other than 768 (E4-S1 AC-3)."""
    if dimension != EMBEDDING_DIM:
        raise ConfigError(
            f"Pinecone index dimension must be {EMBEDDING_DIM} to match "
            f"text-embedding-004; got {dimension}"
        )
    return dimension


def _serverless_spec() -> dict[str, Any]:
    """Build the serverless ``spec`` kwarg for ``create_index`` (pinecone v3+ API).

    ``ServerlessSpec`` is a top-level export of the ``pinecone`` package, not an
    attribute of the client instance, so it must be imported directly. Imported
    lazily to keep the module importable without the SDK (unit tests inject a
    fake ``sdk_factory`` and never create a real index).
    """
    try:
        from pinecone import ServerlessSpec
    except ImportError:
        return {}
    return {"spec": ServerlessSpec(cloud=_CLOUD, region=_REGION)}
