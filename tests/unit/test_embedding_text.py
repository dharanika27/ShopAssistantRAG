"""Unit tests for E3-S1 — embedding text builder.

Pure function over a domain ``Product``; no external boundaries to mock.
Verifies the semantic fields are concatenated and that price/stock/image_url
are excluded (BRD embedding strategy; pinecone-index-design.md §3).
"""

from decimal import Decimal

from backend.domain.enums import Category, Gender
from backend.domain.models import Product
from backend.services.embedding_text import build_embedding_text


def _nike_running_shoe() -> Product:
    return Product(
        product_id="P1001",
        name="Nike Revolution 6",
        description="Lightweight everyday running shoes with soft foam cushioning.",
        brand="Nike",
        category=Category.SHOES,
        gender=Gender.MEN,
        color="Red",
        price=Decimal("2799.00"),
        image_url="https://cdn.example.com/p1001.jpg",
        stock=12,
        tags=["Running", "Sports"],
    )


class TestIncludedFields:
    def test_includes_all_semantic_fields(self) -> None:
        text = build_embedding_text(_nike_running_shoe())

        assert "Nike Revolution 6" in text
        assert "running shoes" in text
        assert "Nike" in text
        assert "Shoes" in text
        assert "Men" in text
        assert "Red" in text
        assert "Running" in text
        assert "Sports" in text

    def test_reads_as_coherent_description(self) -> None:
        text = build_embedding_text(_nike_running_shoe())

        # Sentence-style: name leads, attributes follow in a single string.
        assert text.startswith("Nike Revolution 6")
        assert "  " not in text
        assert text == text.strip()


class TestExcludedFields:
    def test_excludes_price_stock_and_image_url(self) -> None:
        text = build_embedding_text(_nike_running_shoe())

        assert "2799" not in text
        assert "12" not in text
        assert "cdn.example.com" not in text
        assert "https" not in text


class TestMissingOptionalFields:
    def test_omits_missing_color_and_tags_without_literal_none(self) -> None:
        product = Product(
            product_id="P2002",
            name="Classic Tote",
            description=None,
            brand=None,
            category=Category.BAGS,
            gender=None,
            color=None,
            price=Decimal("999.00"),
            stock=3,
            tags=[],
        )

        text = build_embedding_text(product)

        assert "None" not in text
        assert "Classic Tote" in text
        assert "Bags" in text

    def test_handles_product_with_only_required_fields(self) -> None:
        product = Product(
            product_id="P3003",
            name="Plain Cap",
            category=Category.ACCESSORIES,
            price=Decimal("499.00"),
        )

        text = build_embedding_text(product)

        assert "None" not in text
        assert "Plain Cap" in text
        assert "Accessories" in text
        assert text.strip() == text
