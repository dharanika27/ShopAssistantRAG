"""Unit tests for E3-S3 — ingestion pipeline orchestration & summary report.

The external boundaries (CSV file I/O, MySQL repository, Gemini embeddings,
Pinecone upsert) are injected as fakes. The orchestration business logic —
wiring the flow, counting failures non-fatally, building the summary, and
idempotent re-runs — is exercised directly. No live service is called.
"""

from decimal import Decimal
from pathlib import Path

from backend.core.errors import EmbeddingError
from backend.domain.enums import Category, Gender
from backend.domain.models import Product
from backend.services.csv_loader import CsvLoadResult, RowFailure
from backend.services.ingestion import IngestionPipeline, IngestionSummary

_HEADER = (
    "product_id,name,description,brand,category,gender,color,"
    "price,image_url,stock,tags\n"
)


def _write_csv(tmp_path: Path, rows: str) -> Path:
    csv_path = tmp_path / "catalog.csv"
    csv_path.write_text(_HEADER + rows, encoding="utf-8")
    return csv_path


def _product(product_id: str, *, price: str = "2799.00") -> Product:
    return Product(
        product_id=product_id,
        name=f"Product {product_id}",
        description="A great product.",
        brand="Nike",
        category=Category.SHOES,
        gender=Gender.MEN,
        color="Red",
        price=Decimal(price),
        image_url=None,
        stock=5,
        tags=["Running"],
    )


def _vector(seed: float = 0.1) -> list[float]:
    return [seed] * 768


class _FakeRepository:
    def __init__(self) -> None:
        self.upserted: list[Product] = []

    def upsert_product(self, product: Product) -> None:
        self.upserted.append(product)


class _FakeEmbeddingClient:
    """Fails when any ``fail_marker`` appears in the embedding text.

    The pipeline builds embedding text from a product's semantic fields (name,
    description, brand, etc.) — never the ``product_id`` — so failure markers
    must be chosen from those fields (e.g. the product name).
    """

    def __init__(self, *, fail_markers: set[str] | None = None) -> None:
        self._fail_markers = fail_markers or set()
        self.embedded_texts: list[str] = []

    def embed_text(self, text: str) -> list[float]:
        self.embedded_texts.append(text)
        for marker in self._fail_markers:
            if marker in text:
                raise EmbeddingError(f"Gemini failed for text containing {marker!r}")
        return _vector(0.1)


class _FakePineconeClient:
    def __init__(self) -> None:
        self.upsert_calls: list[tuple[list[Product], list[list[float]]]] = []
        self.vectors: dict[str, list[float]] = {}

    def upsert_products(
        self, products: list[Product], vectors: list[list[float]]
    ) -> None:
        self.upsert_calls.append((products, vectors))
        for product, vector in zip(products, vectors, strict=True):
            self.vectors[product.product_id] = vector


def _pipeline(
    repo: _FakeRepository,
    embedder: _FakeEmbeddingClient,
    pinecone: _FakePineconeClient,
) -> IngestionPipeline:
    return IngestionPipeline(
        repository=repo, embedding_client=embedder, pinecone_client=pinecone
    )


class TestHappyPath:
    def test_valid_rows_land_in_mysql_and_pinecone(self, tmp_path: Path) -> None:
        csv_path = _write_csv(
            tmp_path,
            "P1001,Nike Revolution 6,Running shoes,Nike,Shoes,Men,Red,"
            "2799.00,,12,Running|Sports\n"
            "P1002,Adidas Tee,Cotton tee,Adidas,Clothing,Women,Blue,"
            "999.00,,5,Casual\n",
        )
        repo, embedder, pinecone = (
            _FakeRepository(),
            _FakeEmbeddingClient(),
            _FakePineconeClient(),
        )

        summary = _pipeline(repo, embedder, pinecone).run(csv_path)

        assert {p.product_id for p in repo.upserted} == {"P1001", "P1002"}
        assert set(pinecone.vectors.keys()) == {"P1001", "P1002"}
        assert summary.total_rows == 2
        assert summary.successful == 2
        assert summary.failed == 0
        assert summary.failures == []


class TestNonFatalFailures:
    def test_invalid_csv_row_is_skipped_and_counted(self, tmp_path: Path) -> None:
        csv_path = _write_csv(
            tmp_path,
            "P1001,Good Shoe,,Nike,Shoes,Men,Red,2799.00,,12,Running\n"
            "P2001,,,Nike,Shoes,Men,Red,2799.00,,12,Running\n",
        )
        repo, embedder, pinecone = (
            _FakeRepository(),
            _FakeEmbeddingClient(),
            _FakePineconeClient(),
        )

        summary = _pipeline(repo, embedder, pinecone).run(csv_path)

        assert [p.product_id for p in repo.upserted] == ["P1001"]
        assert list(pinecone.vectors.keys()) == ["P1001"]
        assert summary.total_rows == 2
        assert summary.successful == 1
        assert summary.failed == 1
        assert any(f.row_id == "P2001" for f in summary.failures)

    def test_embedding_failure_skips_pinecone_but_keeps_mysql(
        self, tmp_path: Path
    ) -> None:
        csv_path = _write_csv(
            tmp_path,
            "P1001,Good Shoe,,Nike,Shoes,Men,Red,2799.00,,12,Running\n"
            "P9999,Bad Embed,,Nike,Shoes,Men,Red,2799.00,,12,Running\n",
        )
        repo = _FakeRepository()
        embedder = _FakeEmbeddingClient(fail_markers={"Bad Embed"})
        pinecone = _FakePineconeClient()

        summary = _pipeline(repo, embedder, pinecone).run(csv_path)

        # MySQL is the system of record — both valid rows persist there.
        assert {p.product_id for p in repo.upserted} == {"P1001", "P9999"}
        # Only the successfully embedded product reaches Pinecone.
        assert list(pinecone.vectors.keys()) == ["P1001"]
        assert summary.successful == 1
        assert summary.failed == 1
        failure = next(f for f in summary.failures if f.row_id == "P9999")
        assert "embedding failed" in failure.reason

    def test_embedding_failure_does_not_abort_remaining_products(
        self, tmp_path: Path
    ) -> None:
        csv_path = _write_csv(
            tmp_path,
            "P9999,Bad Embed,,Nike,Shoes,Men,Red,2799.00,,12,Running\n"
            "P1002,Good Shoe,,Nike,Shoes,Men,Red,2799.00,,12,Running\n",
        )
        repo = _FakeRepository()
        embedder = _FakeEmbeddingClient(fail_markers={"Bad Embed"})
        pinecone = _FakePineconeClient()

        summary = _pipeline(repo, embedder, pinecone).run(csv_path)

        assert list(pinecone.vectors.keys()) == ["P1002"]
        assert summary.successful == 1
        assert summary.failed == 1


class TestSummaryReport:
    def test_summary_renders_counts_and_reasons(self, tmp_path: Path) -> None:
        csv_path = _write_csv(
            tmp_path,
            "P1001,Good Shoe,,Nike,Shoes,Men,Red,2799.00,,12,Running\n"
            "P2001,,,Nike,Shoes,Men,Red,2799.00,,12,Running\n",
        )
        summary = _pipeline(
            _FakeRepository(), _FakeEmbeddingClient(), _FakePineconeClient()
        ).run(csv_path)

        report = summary.render()

        assert "2" in report  # total processed
        assert "P2001" in report  # failure reason listed
        assert "successful" in report.lower()
        assert "failed" in report.lower()

    def test_summary_from_components_counts_correctly(self) -> None:
        summary = IngestionSummary(
            total_rows=3,
            successful=2,
            failures=[RowFailure(row_id="P2001", reason="name: missing")],
        )

        assert summary.failed == 1


class TestIdempotentReRun:
    def test_rerun_upserts_without_duplicates(self, tmp_path: Path) -> None:
        csv_path = _write_csv(
            tmp_path,
            "P1001,Good Shoe,,Nike,Shoes,Men,Red,2799.00,,12,Running\n",
        )
        repo, embedder, pinecone = (
            _FakeRepository(),
            _FakeEmbeddingClient(),
            _FakePineconeClient(),
        )
        pipeline = _pipeline(repo, embedder, pinecone)

        pipeline.run(csv_path)
        pipeline.run(csv_path)

        # Pinecone keys are product_id, so a re-run overwrites in place.
        assert list(pinecone.vectors.keys()) == ["P1001"]
        # MySQL upsert is called each run (idempotent ON DUPLICATE KEY UPDATE).
        assert [p.product_id for p in repo.upserted] == ["P1001", "P1001"]


class TestLoaderInjection:
    def test_uses_injected_loader_result(self, tmp_path: Path) -> None:
        # The loader is injectable so the pipeline can be tested without a CSV.
        prebuilt = CsvLoadResult(
            products=[_product("P5001")],
            failures=[RowFailure(row_id="P5002", reason="price: invalid")],
        )
        repo, embedder, pinecone = (
            _FakeRepository(),
            _FakeEmbeddingClient(),
            _FakePineconeClient(),
        )
        pipeline = IngestionPipeline(
            repository=repo,
            embedding_client=embedder,
            pinecone_client=pinecone,
            loader=lambda _path: prebuilt,
        )

        summary = pipeline.run(tmp_path / "ignored.csv")

        assert summary.total_rows == 2
        assert summary.successful == 1
        assert summary.failed == 1
