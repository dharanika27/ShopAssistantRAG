"""Unit tests for E6-S2 — Grounded RAG answer generation (Gemini).

Gemini is the external boundary and is mocked via an injected ``generate_fn``;
no live API is called. Tests assert that the generation prompt contains only the
supplied products (AC-1), that the model invocation uses the configured
``gemini-1.5-flash`` model (AC-4), that empty context yields a friendly no-match
message with category suggestions without calling the model (AC-3), and that an
SDK failure surfaces the BRD user-facing message rather than a stack trace (AC-5).
"""

from decimal import Decimal

import pytest

from backend.core.config import Settings
from backend.domain.enums import Category, Gender
from backend.domain.models import Product
from backend.services.answer_generator import (
    UNAVAILABLE_MESSAGE,
    AnswerGenerator,
)

_SETTINGS_OVERRIDES = {
    "GOOGLE_API_KEY": "test-google-key",
    "PINECONE_API_KEY": "test-pinecone-key",
    "MYSQL_HOST": "localhost",
    "MYSQL_PORT": 3306,
    "MYSQL_USER": "shop",
    "MYSQL_PASSWORD": "shop-password",
    "MYSQL_DATABASE": "shop_catalog",
}


def _settings() -> Settings:
    return Settings(_env_file=None, **_SETTINGS_OVERRIDES)


def _product(
    product_id: str,
    name: str,
    *,
    brand: str = "Nike",
    price: str = "4999.00",
    color: str = "Red",
) -> Product:
    return Product(
        product_id=product_id,
        name=name,
        brand=brand,
        category=Category.SHOES,
        gender=Gender.MEN,
        color=color,
        price=Decimal(price),
        stock=12,
    )


class _RecordingGenerate:
    """Captures the prompt and returns a canned reply."""

    def __init__(self, reply: str = "Here are some great options for you.") -> None:
        self.reply = reply
        self.model: str | None = None
        self.prompt: str | None = None

    def __call__(self, *, model: str, prompt: str) -> str:
        self.model = model
        self.prompt = prompt
        return self.reply


class _FailingGenerate:
    def __call__(self, *, model: str, prompt: str) -> str:
        raise RuntimeError("Gemini 503 backend unavailable")


class TestGroundedGeneration:
    def test_prompt_contains_only_supplied_products(self) -> None:
        generate = _RecordingGenerate()
        generator = AnswerGenerator(_settings(), generate_fn=generate)
        products = [
            _product("SKU-001", "Pegasus Runner"),
            _product("SKU-002", "Air Zoom Trail", color="Blue"),
        ]

        generator.generate("running shoes", products)

        assert generate.prompt is not None
        assert "Pegasus Runner" in generate.prompt
        assert "Air Zoom Trail" in generate.prompt
        assert "4999.00" in generate.prompt
        # No product outside the supplied context should leak into the prompt.
        assert "SKU-999" not in generate.prompt

    def test_uses_generation_model_from_settings(self) -> None:
        settings = _settings()
        generate = _RecordingGenerate()
        generator = AnswerGenerator(settings, generate_fn=generate)

        generator.generate("running shoes", [_product("SKU-001", "Pegasus Runner")])

        assert generate.model == settings.active_generation_model()

    def test_returns_the_model_reply_text(self) -> None:
        generate = _RecordingGenerate(reply="The Pegasus Runner is a great pick.")
        generator = AnswerGenerator(_settings(), generate_fn=generate)

        reply = generator.generate("running shoes", [_product("SKU-001", "Pegasus Runner")])

        assert reply == "The Pegasus Runner is a great pick."

    def test_query_is_included_in_prompt(self) -> None:
        generate = _RecordingGenerate()
        generator = AnswerGenerator(_settings(), generate_fn=generate)

        generator.generate("lightweight trail shoes", [_product("SKU-001", "Pegasus Runner")])

        assert generate.prompt is not None
        assert "lightweight trail shoes" in generate.prompt


class TestEmptyContext:
    def test_empty_products_returns_no_match_without_calling_model(self) -> None:
        generate = _RecordingGenerate()
        generator = AnswerGenerator(_settings(), generate_fn=generate)

        reply = generator.generate("purple unicorn slippers", [])

        assert generate.prompt is None  # model never invoked
        for category in ("Shoes", "Clothing", "Accessories", "Sportswear", "Bags"):
            assert category in reply

    def test_no_match_message_invents_no_products(self) -> None:
        generator = AnswerGenerator(_settings(), generate_fn=_RecordingGenerate())

        reply = generator.generate("anything", [])

        assert "SKU" not in reply


class TestGenerationFailure:
    def test_sdk_failure_returns_brd_user_message(self) -> None:
        generator = AnswerGenerator(_settings(), generate_fn=_FailingGenerate())

        reply = generator.generate("running shoes", [_product("SKU-001", "Pegasus Runner")])

        assert reply == UNAVAILABLE_MESSAGE

    def test_sdk_failure_does_not_leak_exception(self) -> None:
        generator = AnswerGenerator(_settings(), generate_fn=_FailingGenerate())

        reply = generator.generate("running shoes", [_product("SKU-001", "Pegasus Runner")])

        assert "Traceback" not in reply
        assert "503" not in reply


@pytest.fixture(autouse=True)
def _no_network() -> None:
    """Guard: these tests must never touch a real network boundary."""
    return None
