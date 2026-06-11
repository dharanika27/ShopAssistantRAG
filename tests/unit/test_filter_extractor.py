"""Unit tests for E5-S1 — Gemini filter extraction with enum normalization.

Gemini is the external boundary and is mocked via an injected extraction
function returning the raw model text. The normalization/validation business
logic (synonym mapping, out-of-vocab dropping, graceful malformed handling) is
exercised directly. No live API call is made.
"""

from decimal import Decimal

import pytest

from backend.core.config import Settings
from backend.domain.enums import Category, Gender
from backend.domain.models import QueryFilters
from backend.services.filter_extractor import ExtractFn, FilterExtractor

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


def _extractor_returning(raw: str) -> ExtractFn:
    def extract(*, model: str, prompt: str) -> str:
        return raw

    return extract


def _build(settings: Settings, raw: str) -> FilterExtractor:
    return FilterExtractor(settings, extract_fn=_extractor_returning(raw))


class TestStructuredExtraction:
    def test_full_query_maps_all_fields(self, settings: Settings) -> None:
        raw = (
            '{"brand": "Nike", "color": "Red", "category": "Shoes", '
            '"gender": null, "min_price": null, "max_price": 3000}'
        )
        extractor = _build(settings, raw)

        result = extractor.extract("Show me red Nike shoes under 3000")

        assert result == QueryFilters(
            brand="Nike",
            color="Red",
            category=Category.SHOES,
            gender=None,
            min_price=None,
            max_price=Decimal("3000"),
        )

    def test_price_only_query_leaves_other_fields_none(self, settings: Settings) -> None:
        raw = (
            '{"brand": null, "color": null, "category": null, '
            '"gender": null, "min_price": null, "max_price": 500}'
        )
        extractor = _build(settings, raw)

        result = extractor.extract("under 500")

        assert result.max_price == Decimal("500")
        assert result.brand is None
        assert result.color is None
        assert result.category is None
        assert result.gender is None
        assert result.min_price is None

    def test_uses_generation_model_from_settings(self, settings: Settings) -> None:
        captured: dict[str, str] = {}

        def extract(*, model: str, prompt: str) -> str:
            captured["model"] = model
            return '{"category": "Shoes"}'

        extractor = FilterExtractor(settings, extract_fn=extract)

        extractor.extract("running shoes")

        assert captured["model"] == settings.active_generation_model()

    def test_query_is_injected_into_prompt(self, settings: Settings) -> None:
        captured: dict[str, str] = {}

        def extract(*, model: str, prompt: str) -> str:
            captured["prompt"] = prompt
            return "{}"

        extractor = FilterExtractor(settings, extract_fn=extract)

        extractor.extract("blue running shoes for women")

        assert "blue running shoes for women" in captured["prompt"]


class TestSynonymNormalization:
    def test_color_synonym_normalizes_to_canonical(self, settings: Settings) -> None:
        extractor = _build(settings, '{"color": "Crimson"}')

        result = extractor.extract("crimson dress")

        assert result.color == "Red"

    def test_category_synonym_normalizes_to_enum(self, settings: Settings) -> None:
        extractor = _build(settings, '{"category": "Trainers"}')

        result = extractor.extract("trainers")

        assert result.category == Category.SHOES

    def test_category_matches_enum_case_insensitively(self, settings: Settings) -> None:
        extractor = _build(settings, '{"category": "shoes"}')

        result = extractor.extract("shoes")

        assert result.category == Category.SHOES

    def test_gender_matches_enum_case_insensitively(self, settings: Settings) -> None:
        extractor = _build(settings, '{"gender": "women"}')

        result = extractor.extract("dresses for women")

        assert result.gender == Gender.WOMEN


class TestOutOfVocabularyDropping:
    def test_unknown_category_is_dropped(self, settings: Settings) -> None:
        extractor = _build(settings, '{"category": "Electronics"}')

        result = extractor.extract("a laptop")

        assert result.category is None

    def test_unknown_gender_is_dropped(self, settings: Settings) -> None:
        extractor = _build(settings, '{"gender": "Robot", "category": "Shoes"}')

        result = extractor.extract("robot shoes")

        assert result.gender is None
        assert result.category == Category.SHOES


class TestGracefulMalformedHandling:
    def test_non_json_output_yields_empty_filters(self, settings: Settings) -> None:
        extractor = _build(settings, "I am sorry, I cannot help with that.")

        result = extractor.extract("something")

        assert result == QueryFilters()

    def test_partial_garbage_yields_empty_filters(self, settings: Settings) -> None:
        extractor = _build(settings, '{"brand": "Nike", ')

        result = extractor.extract("nike")

        assert result == QueryFilters()

    def test_json_array_instead_of_object_yields_empty_filters(
        self, settings: Settings
    ) -> None:
        extractor = _build(settings, "[1, 2, 3]")

        result = extractor.extract("numbers")

        assert result == QueryFilters()

    def test_negative_price_is_dropped(self, settings: Settings) -> None:
        extractor = _build(settings, '{"max_price": -50, "category": "Bags"}')

        result = extractor.extract("cheap bag")

        assert result.max_price is None
        assert result.category == Category.BAGS

    def test_json_embedded_in_markdown_fence_is_parsed(
        self, settings: Settings
    ) -> None:
        raw = '```json\n{"category": "Bags", "color": "Black"}\n```'
        extractor = _build(settings, raw)

        result = extractor.extract("black bag")

        assert result.category == Category.BAGS
        assert result.color == "Black"
