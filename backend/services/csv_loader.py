"""CSV loader with row validation (E2-S3).

Reads the product catalog CSV, validates each row against the :class:`Product`
domain model, and partitions the rows into clean products and skipped-row
failures. Invalid rows are non-fatal: they are recorded with a row identifier
and reason for the ingestion summary (E3-S3), never raised.

Tags are parsed from a pipe-delimited string into a list of trimmed strings
(AC-4). Rows missing a required field, or carrying an out-of-vocabulary
category/gender, are skipped and recorded (AC-2, AC-3).
"""

import csv
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pydantic import ValidationError

from backend.core.logging import get_logger
from backend.domain.enums import Category, Gender
from backend.domain.models import Product

logger = get_logger(__name__)

_TAG_DELIMITER = "|"


@dataclass(frozen=True)
class RowFailure:
    """A skipped CSV row: which row, and why (E2-S3 AC-2/AC-5)."""

    row_id: str
    reason: str


@dataclass
class CsvLoadResult:
    """Outcome of loading a CSV: valid products plus skipped rows (AC-5)."""

    products: list[Product] = field(default_factory=list)
    failures: list[RowFailure] = field(default_factory=list)


def load_products_from_csv(csv_path: Path) -> CsvLoadResult:
    """Load and validate products from ``csv_path`` (E2-S3 AC-1/AC-5).

    Returns both the valid :class:`Product` objects and the list of skipped-row
    failures. Never raises on row-level validation problems.
    """
    result = CsvLoadResult()
    with csv_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            _ingest_row(row, result)
    logger.info(
        "csv_loader.completed",
        extra={
            "path": str(csv_path),
            "valid": len(result.products),
            "skipped": len(result.failures),
        },
    )
    return result


def _ingest_row(row: dict[str, str], result: CsvLoadResult) -> None:
    row_id = (row.get("product_id") or "").strip() or "<unknown>"
    try:
        result.products.append(_build_product(row))
    except (ValidationError, ValueError, InvalidOperation) as exc:
        result.failures.append(RowFailure(row_id=row_id, reason=_summarize(exc)))
        logger.warning(
            "csv_loader.row_skipped", extra={"row_id": row_id, "reason": _summarize(exc)}
        )


def _build_product(row: dict[str, str]) -> Product:
    return Product(
        product_id=_required(row, "product_id"),
        name=_required(row, "name"),
        description=_optional(row, "description"),
        brand=_optional(row, "brand"),
        category=_parse_category(_required(row, "category")),
        gender=_parse_gender(_optional(row, "gender")),
        color=_optional(row, "color"),
        price=_parse_price(_required(row, "price")),
        image_url=_optional(row, "image_url"),
        stock=_parse_stock(row.get("stock")),
        tags=_parse_tags(row.get("tags")),
    )


def _required(row: dict[str, str], key: str) -> str:
    value = (row.get(key) or "").strip()
    if not value:
        raise ValueError(f"missing required field '{key}'")
    return value


def _optional(row: dict[str, str], key: str) -> str | None:
    value = (row.get(key) or "").strip()
    return value or None


def _parse_category(raw: str) -> Category:
    try:
        return Category(raw)
    except ValueError as exc:
        raise ValueError(f"category: '{raw}' is not a valid category") from exc


def _parse_gender(raw: str | None) -> Gender | None:
    if raw is None:
        return None
    try:
        return Gender(raw)
    except ValueError as exc:
        raise ValueError(f"gender: '{raw}' is not a valid gender") from exc


def _parse_price(raw: str) -> Decimal:
    return Decimal(raw)


def _parse_stock(raw: str | None) -> int:
    value = (raw or "").strip()
    return int(value) if value else 0


def _parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [tag.strip() for tag in raw.split(_TAG_DELIMITER) if tag.strip()]


def _summarize(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first.get("loc", ()))
        return f"{location}: {first.get('msg', 'invalid value')}".strip(": ")
    return str(exc)
