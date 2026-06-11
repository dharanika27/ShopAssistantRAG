"""Product domain enumerations (E1-S1).

Single source of truth for the category and gender vocabularies used across
ingestion, retrieval, filter extraction, and the API. Centralizing them here
prevents enum drift between layers.
"""

from enum import StrEnum


class Category(StrEnum):
    """Product category — restricted to exactly five values (E1-S1 AC-2)."""

    SHOES = "Shoes"
    CLOTHING = "Clothing"
    ACCESSORIES = "Accessories"
    SPORTSWEAR = "Sportswear"
    BAGS = "Bags"


class Gender(StrEnum):
    """Target gender — restricted to exactly four values (E1-S1 AC-3)."""

    MEN = "Men"
    WOMEN = "Women"
    UNISEX = "Unisex"
    KIDS = "Kids"
