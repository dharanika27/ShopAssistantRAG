"""Embedding text builder (E3-S1).

Composes the single text string embedded per product from its *semantic* fields
only: Name, Description, Brand, Category, Gender, Color, Tags. Price, stock, and
image URL are deliberately excluded — they live as Pinecone metadata, not in the
vector text (pinecone-index-design.md §3; E3-S1 AC-2).

Missing optional fields are omitted rather than rendered as the literal string
``None`` (AC-3), so the output always reads as a coherent sentence-style
description (AC-4).
"""

from backend.domain.models import Product


def build_embedding_text(product: Product) -> str:
    """Build the semantic embedding text for ``product`` (E3-S1 AC-1).

    Returns a single space-joined string of the present semantic fields. The
    product name leads; absent optional fields are skipped entirely.
    """
    segments = [
        product.name,
        product.description,
        _brand_segment(product.brand),
        _category_segment(product.category.value),
        _gender_segment(product.gender.value if product.gender else None),
        _color_segment(product.color),
        _tags_segment(product.tags),
    ]
    return " ".join(segment for segment in segments if segment)


def _brand_segment(brand: str | None) -> str | None:
    return f"Brand {brand}." if brand else None


def _category_segment(category: str) -> str:
    return f"Category {category}."


def _gender_segment(gender: str | None) -> str | None:
    return f"For {gender}." if gender else None


def _color_segment(color: str | None) -> str | None:
    return f"Color {color}." if color else None


def _tags_segment(tags: list[str]) -> str | None:
    cleaned = [tag.strip() for tag in tags if tag.strip()]
    return "Tags " + ", ".join(cleaned) + "." if cleaned else None
