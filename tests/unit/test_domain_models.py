"""Unit tests for E1-S1 — product domain types and enums."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from backend.domain.enums import Category, Gender
from backend.domain.models import Product, QueryFilters


class TestCategoryEnum:
    def test_category_has_exactly_five_members(self) -> None:
        assert {member.value for member in Category} == {
            "Shoes",
            "Clothing",
            "Accessories",
            "Sportswear",
            "Bags",
        }

    def test_unknown_category_value_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            Category("Laptops")


class TestGenderEnum:
    def test_gender_has_exactly_four_members(self) -> None:
        assert {member.value for member in Gender} == {
            "Men",
            "Women",
            "Unisex",
            "Kids",
        }

    def test_unknown_gender_value_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            Gender("Robots")


class TestProductModel:
    def test_builds_a_valid_product_with_all_fields(self) -> None:
        product = Product(
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

        assert product.product_id == "P1001"
        assert product.category is Category.SHOES
        assert product.gender is Gender.MEN
        assert product.price == Decimal("2799.00")
        assert product.tags == ["Running", "Sports"]

    def test_price_is_a_decimal(self) -> None:
        product = Product(
            product_id="P1002",
            name="Adidas Ultraboost",
            category=Category.SHOES,
            price=Decimal("8999.50"),
        )

        assert isinstance(product.price, Decimal)

    def test_missing_name_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            Product(  # type: ignore[call-arg]
                product_id="P1003",
                category=Category.CLOTHING,
                price=Decimal("499.00"),
            )

    def test_missing_price_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            Product(  # type: ignore[call-arg]
                product_id="P1004",
                name="Levi's 511 Slim Jeans",
                category=Category.CLOTHING,
            )

    def test_missing_category_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            Product(  # type: ignore[call-arg]
                product_id="P1005",
                name="Levi's 511 Slim Jeans",
                price=Decimal("2499.00"),
            )

    def test_stock_zero_is_valid_and_yields_in_stock_false(self) -> None:
        product = Product(
            product_id="P1006",
            name="Puma Suede Classic",
            category=Category.SHOES,
            price=Decimal("4499.00"),
            stock=0,
        )

        assert product.stock == 0
        assert product.in_stock is False

    def test_positive_stock_yields_in_stock_true(self) -> None:
        product = Product(
            product_id="P1007",
            name="Puma Suede Classic",
            category=Category.SHOES,
            price=Decimal("4499.00"),
            stock=5,
        )

        assert product.in_stock is True

    def test_stock_defaults_to_zero(self) -> None:
        product = Product(
            product_id="P1008",
            name="Wildcraft Backpack",
            category=Category.BAGS,
            price=Decimal("1999.00"),
        )

        assert product.stock == 0
        assert product.in_stock is False

    def test_optional_fields_default_to_none_or_empty(self) -> None:
        product = Product(
            product_id="P1009",
            name="Generic Tee",
            category=Category.CLOTHING,
            price=Decimal("299.00"),
        )

        assert product.description is None
        assert product.brand is None
        assert product.gender is None
        assert product.color is None
        assert product.image_url is None
        assert product.tags == []

    def test_invalid_category_string_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Product(
                product_id="P1010",
                name="Mystery Item",
                category="Laptops",  # type: ignore[arg-type]
                price=Decimal("100.00"),
            )

    def test_negative_price_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Product(
                product_id="P1011",
                name="Discount Shoe",
                category=Category.SHOES,
                price=Decimal("-1.00"),
            )

    def test_negative_stock_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Product(
                product_id="P1012",
                name="Discount Shoe",
                category=Category.SHOES,
                price=Decimal("1.00"),
                stock=-5,
            )


class TestQueryFilters:
    def test_all_fields_default_to_none(self) -> None:
        filters = QueryFilters()

        assert filters.brand is None
        assert filters.color is None
        assert filters.category is None
        assert filters.gender is None
        assert filters.min_price is None
        assert filters.max_price is None

    def test_accepts_partial_filters(self) -> None:
        filters = QueryFilters(
            brand="Nike",
            color="Red",
            category=Category.SHOES,
            max_price=Decimal("3000.00"),
        )

        assert filters.brand == "Nike"
        assert filters.category is Category.SHOES
        assert filters.gender is None
        assert filters.max_price == Decimal("3000.00")
