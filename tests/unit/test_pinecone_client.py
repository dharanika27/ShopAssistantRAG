"""Unit tests for E4-S1 — Pinecone index provisioning & client.

The Pinecone SDK is the external boundary and is mocked via an injected fake
client. Business logic (idempotent provisioning, dimension/metric contract,
typed error translation) is exercised directly. No live API call is made.
"""

from decimal import Decimal

import pytest

from backend.core.config import Settings
from backend.core.errors import ConfigError, RetrievalError
from backend.domain.enums import Category, Gender
from backend.domain.models import Product
from backend.repositories.pinecone_client import (
    EMBEDDING_DIM,
    UPSERT_BATCH_SIZE,
    PineconeClient,
)

REQUIRED_ENV = {
    "GOOGLE_API_KEY": "test-google-key",
    "PINECONE_API_KEY": "test-pinecone-key",
    "MYSQL_HOST": "localhost",
    "MYSQL_PORT": "3306",
    "MYSQL_USER": "shop_user",
    "MYSQL_PASSWORD": "shop_password",
    "MYSQL_DATABASE": "shopassistant",
}


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


class _FakeIndexHandle:
    """Records upsert calls; later upserts overwrite by vector id (like Pinecone)."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.upsert_calls: list[list[dict[str, object]]] = []
        self.vectors: dict[str, dict[str, object]] = {}

    def upsert(self, *, vectors: list[dict[str, object]]) -> None:
        self.upsert_calls.append(vectors)
        for vector in vectors:
            self.vectors[str(vector["id"])] = vector


class _FakePinecone:
    """Minimal stand-in for the Pinecone SDK client."""

    def __init__(self, *, api_key: str, existing: list[str] | None = None) -> None:
        self.api_key = api_key
        self._existing = list(existing or [])
        self.created: list[dict[str, object]] = []
        self._handles: dict[str, _FakeIndexHandle] = {}

    def list_indexes(self) -> list[dict[str, str]]:
        return [{"name": name} for name in self._existing]

    def create_index(self, **kwargs: object) -> None:
        self.created.append(kwargs)
        self._existing.append(str(kwargs["name"]))

    def Index(self, name: str) -> _FakeIndexHandle:  # noqa: N802 (SDK casing)
        return self._handles.setdefault(name, _FakeIndexHandle(name))


class TestProvisioning:
    def test_creates_index_when_absent_with_768_cosine(
        self, settings: Settings
    ) -> None:
        sdk = _FakePinecone(api_key="x", existing=[])
        client = PineconeClient(settings, sdk_factory=lambda api_key: sdk)

        client.ensure_index()

        assert len(sdk.created) == 1
        created = sdk.created[0]
        assert created["name"] == settings.PINECONE_INDEX_NAME
        assert created["dimension"] == EMBEDDING_DIM == 768
        assert created["metric"] == "cosine"

    def test_reuses_existing_index_without_creating(self, settings: Settings) -> None:
        sdk = _FakePinecone(api_key="x", existing=[settings.PINECONE_INDEX_NAME])
        client = PineconeClient(settings, sdk_factory=lambda api_key: sdk)

        client.ensure_index()

        assert sdk.created == []

    def test_passes_api_key_from_settings_to_sdk(self, settings: Settings) -> None:
        captured: dict[str, str] = {}

        def factory(api_key: str) -> _FakePinecone:
            captured["api_key"] = api_key
            return _FakePinecone(api_key=api_key)

        PineconeClient(settings, sdk_factory=factory)

        assert captured["api_key"] == "test-pinecone-key"


class TestDimensionMismatch:
    def test_rejects_non_768_configured_dimension(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EMBEDDING_DIM", "512")
        bad_settings = Settings(_env_file=None)
        sdk = _FakePinecone(api_key="x")

        with pytest.raises(ConfigError):
            PineconeClient(bad_settings, sdk_factory=lambda api_key: sdk)


class TestIndexHandle:
    def test_index_returns_handle_after_provisioning(self, settings: Settings) -> None:
        sdk = _FakePinecone(api_key="x", existing=[settings.PINECONE_INDEX_NAME])
        client = PineconeClient(settings, sdk_factory=lambda api_key: sdk)
        client.ensure_index()

        handle = client.index()

        assert handle.name == settings.PINECONE_INDEX_NAME


class TestErrorTranslation:
    def test_connection_failure_raises_retrieval_error(
        self, settings: Settings
    ) -> None:
        def failing_factory(api_key: str) -> _FakePinecone:
            raise ConnectionError("pinecone refused the connection")

        with pytest.raises(RetrievalError) as exc_info:
            PineconeClient(settings, sdk_factory=failing_factory)

        assert exc_info.value.code == "PINECONE_UNAVAILABLE"

    def test_provisioning_failure_raises_retrieval_error(
        self, settings: Settings
    ) -> None:
        class _ExplodingPinecone(_FakePinecone):
            def list_indexes(self) -> list[dict[str, str]]:
                raise RuntimeError("pinecone 503 during list")

        sdk = _ExplodingPinecone(api_key="x")
        client = PineconeClient(settings, sdk_factory=lambda api_key: sdk)

        with pytest.raises(RetrievalError):
            client.ensure_index()


def _product(
    product_id: str,
    *,
    brand: str | None = "Nike",
    color: str | None = "Red",
    category: Category = Category.SHOES,
    gender: Gender | None = Gender.MEN,
    price: str = "2799.00",
) -> Product:
    return Product(
        product_id=product_id,
        name=f"Product {product_id}",
        description="A great product.",
        brand=brand,
        category=category,
        gender=gender,
        color=color,
        price=Decimal(price),
        image_url=None,
        stock=5,
        tags=["Running"],
    )


def _vector(seed: float = 0.1) -> list[float]:
    return [seed] * EMBEDDING_DIM


def _ready_client(settings: Settings) -> tuple[PineconeClient, _FakePinecone]:
    sdk = _FakePinecone(api_key="x", existing=[settings.PINECONE_INDEX_NAME])
    client = PineconeClient(settings, sdk_factory=lambda api_key: sdk)
    return client, sdk


class TestUpsertProducts:
    def test_writes_one_vector_per_product_keyed_by_product_id(
        self, settings: Settings
    ) -> None:
        client, sdk = _ready_client(settings)
        products = [_product("P1001"), _product("P1002")]
        vectors = [_vector(0.1), _vector(0.2)]

        client.upsert_products(products, vectors)

        handle = sdk.Index(settings.PINECONE_INDEX_NAME)
        assert set(handle.vectors.keys()) == {"P1001", "P1002"}
        assert handle.vectors["P1001"]["values"] == vectors[0]

    def test_each_vector_carries_required_metadata_fields(
        self, settings: Settings
    ) -> None:
        client, sdk = _ready_client(settings)

        client.upsert_products([_product("P1001")], [_vector()])

        metadata = sdk.Index(settings.PINECONE_INDEX_NAME).vectors["P1001"]["metadata"]
        assert metadata == {
            "brand": "Nike",
            "color": "Red",
            "category": "Shoes",
            "gender": "Men",
            "price": 2799.00,
        }

    def test_price_metadata_is_numeric_for_range_filters(
        self, settings: Settings
    ) -> None:
        client, sdk = _ready_client(settings)

        client.upsert_products([_product("P1001", price="1499.50")], [_vector()])

        price = sdk.Index(settings.PINECONE_INDEX_NAME).vectors["P1001"]["metadata"][
            "price"
        ]
        assert isinstance(price, float)
        assert price == 1499.50

    def test_optional_none_metadata_fields_are_omitted(
        self, settings: Settings
    ) -> None:
        client, sdk = _ready_client(settings)
        product = _product("P1001", brand=None, color=None, gender=None)

        client.upsert_products([product], [_vector()])

        metadata = sdk.Index(settings.PINECONE_INDEX_NAME).vectors["P1001"]["metadata"]
        assert metadata == {"category": "Shoes", "price": 2799.00}

    def test_reupserting_same_id_overwrites_without_duplicates(
        self, settings: Settings
    ) -> None:
        client, sdk = _ready_client(settings)

        client.upsert_products([_product("P1001", price="2799.00")], [_vector(0.1)])
        client.upsert_products([_product("P1001", price="1999.00")], [_vector(0.9)])

        handle = sdk.Index(settings.PINECONE_INDEX_NAME)
        assert list(handle.vectors.keys()) == ["P1001"]
        assert handle.vectors["P1001"]["values"] == _vector(0.9)
        assert handle.vectors["P1001"]["metadata"]["price"] == 1999.00

    def test_upsert_is_batched_under_the_batch_size(self, settings: Settings) -> None:
        client, sdk = _ready_client(settings)
        count = UPSERT_BATCH_SIZE * 2 + 5
        products = [_product(f"P{index:04d}") for index in range(count)]
        vectors = [_vector(0.1)] * count

        client.upsert_products(products, vectors)

        handle = sdk.Index(settings.PINECONE_INDEX_NAME)
        assert len(handle.upsert_calls) == 3
        assert all(len(call) <= UPSERT_BATCH_SIZE for call in handle.upsert_calls)
        assert len(handle.vectors) == count

    def test_empty_products_does_not_call_upsert(self, settings: Settings) -> None:
        client, sdk = _ready_client(settings)

        client.upsert_products([], [])

        assert sdk.Index(settings.PINECONE_INDEX_NAME).upsert_calls == []

    def test_mismatched_products_and_vectors_raises_retrieval_error(
        self, settings: Settings
    ) -> None:
        client, _ = _ready_client(settings)

        with pytest.raises(RetrievalError):
            client.upsert_products([_product("P1001")], [_vector(), _vector()])

    def test_sdk_upsert_failure_raises_retrieval_error(
        self, settings: Settings
    ) -> None:
        class _ExplodingIndex(_FakeIndexHandle):
            def upsert(self, *, vectors: list[dict[str, object]]) -> None:
                raise RuntimeError("pinecone 503 during upsert")

        class _ExplodingPinecone(_FakePinecone):
            def Index(self, name: str) -> _FakeIndexHandle:  # noqa: N802
                return self._handles.setdefault(name, _ExplodingIndex(name))

        sdk = _ExplodingPinecone(
            api_key="x", existing=[settings.PINECONE_INDEX_NAME]
        )
        client = PineconeClient(settings, sdk_factory=lambda api_key: sdk)

        with pytest.raises(RetrievalError) as exc_info:
            client.upsert_products([_product("P1001")], [_vector()])

        assert exc_info.value.code == "PINECONE_UNAVAILABLE"
