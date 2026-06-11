"""Unit tests for the Groq chat-completion client (LLM generation provider).

The Groq SDK is the external boundary and is mocked via an injected
``sdk_factory``; no live API call is made. Tests assert the request shape (model,
single user message), content extraction, and that every SDK failure mode is
translated into a typed :class:`GenerationError` rather than leaking an SDK type.
"""

import pytest

from backend.core.config import Settings
from backend.core.errors import ConfigError, GenerationError
from backend.services.groq_client import GroqClient

_OVERRIDES = {
    "GOOGLE_API_KEY": "test-google-key",
    "PINECONE_API_KEY": "test-pinecone-key",
    "MYSQL_HOST": "localhost",
    "MYSQL_PORT": 3306,
    "MYSQL_USER": "shop",
    "MYSQL_PASSWORD": "shop-password",
    "MYSQL_DATABASE": "shop_catalog",
}


def _settings(**extra: object) -> Settings:
    return Settings(_env_file=None, **{**_OVERRIDES, **extra})


class _Message:
    def __init__(self, content: str | None) -> None:
        self.content = content


class _Choice:
    def __init__(self, content: str | None) -> None:
        self.message = _Message(content)


class _Completion:
    def __init__(self, content: str | None) -> None:
        self.choices = [_Choice(content)]


class _FakeCompletions:
    def __init__(self, reply: str | None) -> None:
        self.reply = reply
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> _Completion:
        self.calls.append(kwargs)
        return _Completion(self.reply)


class _FakeChat:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.completions = completions


class _FakeGroqSdk:
    def __init__(self, reply: str | None) -> None:
        self.chat = _FakeChat(_FakeCompletions(reply))


def _factory_returning(reply: str | None):
    def factory(api_key: str, timeout: float, max_retries: int):
        return _FakeGroqSdk(reply)

    return factory


def test_complete_returns_message_content() -> None:
    client = GroqClient(
        _settings(GROQ_API_KEY="gsk-test"), sdk_factory=_factory_returning("Here are 3 options.")
    )
    assert client.complete(model="llama-3.3-70b-versatile", prompt="hi") == "Here are 3 options."


def test_request_uses_model_and_single_user_message() -> None:
    sdk = _FakeGroqSdk("ok")
    client = GroqClient(_settings(GROQ_API_KEY="gsk-test"), sdk_factory=lambda *_: sdk)
    client.complete(model="llama-3.3-70b-versatile", prompt="red shoes")
    call = sdk.chat.completions.calls[0]
    assert call["model"] == "llama-3.3-70b-versatile"
    assert call["messages"] == [{"role": "user", "content": "red shoes"}]
    assert call["temperature"] == 0


def test_none_content_becomes_empty_string() -> None:
    client = GroqClient(_settings(GROQ_API_KEY="gsk-test"), sdk_factory=_factory_returning(None))
    assert client.complete(model="m", prompt="x") == ""


def test_sdk_failure_is_translated_to_generation_error() -> None:
    class _Boom:
        class chat:  # noqa: N801
            class completions:  # noqa: N801
                @staticmethod
                def create(**_: object):
                    raise RuntimeError("429 rate limit exceeded")

    client = GroqClient(_settings(GROQ_API_KEY="gsk-test"), sdk_factory=lambda *_: _Boom())
    with pytest.raises(GenerationError):
        client.complete(model="m", prompt="x")


def test_connect_failure_is_translated_to_generation_error() -> None:
    def failing_factory(*_: object):
        raise RuntimeError("connection refused")

    with pytest.raises(GenerationError):
        GroqClient(_settings(GROQ_API_KEY="gsk-test"), sdk_factory=failing_factory)


def test_missing_key_raises_config_error_not_generation_error() -> None:
    # No GROQ_API_KEY -> fail fast as ConfigError (misconfiguration), not a
    # transient GenerationError.
    with pytest.raises(ConfigError):
        GroqClient(_settings(), sdk_factory=_factory_returning("ok"))


def test_as_completion_fn_matches_provider_signature() -> None:
    client = GroqClient(_settings(GROQ_API_KEY="gsk-test"), sdk_factory=_factory_returning("ok"))
    fn = client.as_completion_fn()
    assert fn(model="m", prompt="p") == "ok"
