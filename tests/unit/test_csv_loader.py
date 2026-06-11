"""Unit tests for E2-S3 — CSV loader with row validation.

The file system is the external boundary; tests write a real temp CSV (file I/O
is an allowed boundary) and exercise parsing/validation business logic. No other
service is mocked.
"""

from pathlib import Path

from backend.domain.enums import Category, Gender
from backend.services.csv_loader import load_products_from_csv

_HEADER = (
    "product_id,name,description,brand,category,gender,color,"
    "price,image_url,stock,tags\n"
)


def _write_csv(tmp_path: Path, rows: str) -> Path:
    csv_path = tmp_path / "catalog.csv"
    csv_path.write_text(_HEADER + rows, encoding="utf-8")
    return csv_path


class TestValidRows:
    def test_valid_row_parses_into_product(self, tmp_path: Path) -> None:
        csv_path = _write_csv(
            tmp_path,
            "P1001,Nike Revolution 6,Running shoes,Nike,Shoes,Men,Red,"
            "2799.00,https://cdn.example.com/p1001.jpg,12,Running|Sports\n",
        )

        result = load_products_from_csv(csv_path)

        assert len(result.products) == 1
        product = result.products[0]
        assert product.product_id == "P1001"
        assert product.category is Category.SHOES
        assert product.gender is Gender.MEN
        assert result.failures == []

    def test_tags_parsed_into_trimmed_list(self, tmp_path: Path) -> None:
        csv_path = _write_csv(
            tmp_path,
            "P1002,Trail Tee,Tee,Adidas,Clothing,Women,Blue,"
            "999.00,,5, Trail | Running | Outdoor \n",
        )

        result = load_products_from_csv(csv_path)

        assert result.products[0].tags == ["Trail", "Running", "Outdoor"]

    def test_blank_tags_yield_empty_list(self, tmp_path: Path) -> None:
        csv_path = _write_csv(
            tmp_path,
            "P1003,Plain Cap,,Puma,Accessories,Unisex,Black,499.00,,7,\n",
        )

        result = load_products_from_csv(csv_path)

        assert result.products[0].tags == []


class TestSkippedRows:
    def test_missing_required_field_is_skipped_and_recorded(
        self, tmp_path: Path
    ) -> None:
        # Missing name and price.
        csv_path = _write_csv(
            tmp_path,
            "P2001,,Some desc,Nike,Shoes,Men,Red,,,3,Running\n",
        )

        result = load_products_from_csv(csv_path)

        assert result.products == []
        assert len(result.failures) == 1
        failure = result.failures[0]
        assert failure.row_id == "P2001"
        assert failure.reason

    def test_out_of_vocab_category_is_skipped(self, tmp_path: Path) -> None:
        csv_path = _write_csv(
            tmp_path,
            "P2002,Mystery Item,,Nike,Gadgets,Men,Red,1500.00,,3,Tech\n",
        )

        result = load_products_from_csv(csv_path)

        assert result.products == []
        assert len(result.failures) == 1
        assert "Gadgets" in result.failures[0].reason or result.failures[0].reason

    def test_out_of_vocab_gender_is_skipped(self, tmp_path: Path) -> None:
        csv_path = _write_csv(
            tmp_path,
            "P2003,Sock Pack,,Nike,Accessories,Robots,White,299.00,,3,Socks\n",
        )

        result = load_products_from_csv(csv_path)

        assert result.products == []
        assert len(result.failures) == 1

    def test_valid_and_invalid_rows_are_partitioned(self, tmp_path: Path) -> None:
        csv_path = _write_csv(
            tmp_path,
            "P3001,Good Shoe,,Nike,Shoes,Men,Red,2799.00,,12,Running\n"
            "P3002,,,Nike,Shoes,Men,Red,2799.00,,12,Running\n"
            "P3003,Good Bag,,Gucci,Bags,Women,Brown,4999.00,,4,Leather\n",
        )

        result = load_products_from_csv(csv_path)

        assert [p.product_id for p in result.products] == ["P3001", "P3003"]
        assert [f.row_id for f in result.failures] == ["P3002"]
