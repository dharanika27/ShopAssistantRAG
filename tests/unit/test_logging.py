"""Unit tests for E1-S3 — structured logging setup."""

import json
import logging
from pathlib import Path

import pytest

from backend.core.logging import StructuredFormatter, get_logger


class TestGetLogger:
    def test_returns_a_logger_instance(self) -> None:
        logger = get_logger("backend.services.example")

        assert isinstance(logger, logging.Logger)
        assert logger.name == "backend.services.example"

    def test_logger_has_a_structured_formatter_handler(self) -> None:
        logger = get_logger("backend.services.formatted")

        assert logger.handlers, "logger should configure at least one handler"
        assert any(
            isinstance(handler.formatter, StructuredFormatter)
            for handler in logger.handlers
        )

    def test_repeated_calls_do_not_duplicate_handlers(self) -> None:
        name = "backend.services.idempotent"
        first = get_logger(name)
        handler_count = len(first.handlers)

        second = get_logger(name)

        assert second is first
        assert len(second.handlers) == handler_count


class TestStructuredFormatter:
    def _format(self, record: logging.LogRecord) -> dict[str, object]:
        return json.loads(StructuredFormatter().format(record))

    def test_emits_timestamp_level_logger_and_message(self) -> None:
        record = logging.LogRecord(
            name="backend.services.retrieval",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="retrieval.query",
            args=(),
            exc_info=None,
        )

        payload = self._format(record)

        assert "ts" in payload
        assert payload["level"] == "INFO"
        assert payload["logger"] == "backend.services.retrieval"
        assert payload["msg"] == "retrieval.query"

    def test_includes_session_id_and_request_id_when_present(self) -> None:
        record = logging.LogRecord(
            name="backend.services.retrieval",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="retrieval.query",
            args=(),
            exc_info=None,
        )
        record.session_id = "s-13c"
        record.request_id = "r-8f2a"

        payload = self._format(record)

        assert payload["session_id"] == "s-13c"
        assert payload["request_id"] == "r-8f2a"

    def test_omits_correlation_fields_when_absent(self) -> None:
        record = logging.LogRecord(
            name="backend.services.retrieval",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="retrieval.query",
            args=(),
            exc_info=None,
        )

        payload = self._format(record)

        assert "session_id" not in payload
        assert "request_id" not in payload

    def test_includes_arbitrary_extra_context_fields(self) -> None:
        record = logging.LogRecord(
            name="backend.services.retrieval",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="retrieval.query",
            args=(),
            exc_info=None,
        )
        record.result_count = 5

        payload = self._format(record)

        assert payload["result_count"] == 5


class TestLogLevelConfiguration:
    def test_default_level_is_info(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LOG_LEVEL", raising=False)

        logger = get_logger("backend.services.default_level")

        assert logger.level == logging.INFO

    def test_level_configurable_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")

        logger = get_logger("backend.services.debug_level")

        assert logger.level == logging.DEBUG


class TestNoSecretsInLogCalls:
    def test_no_source_line_logs_a_raw_api_key(self) -> None:
        backend_root = Path(__file__).resolve().parents[2] / "backend"
        offenders: list[str] = []

        for source in backend_root.rglob("*.py"):
            for lineno, line in enumerate(
                source.read_text(encoding="utf-8").splitlines(), start=1
            ):
                stripped = line.strip()
                is_log_call = ".info(" in stripped or ".debug(" in stripped or (
                    ".warning(" in stripped or ".error(" in stripped
                )
                if is_log_call and (
                    "api_key_value()" in stripped or "password_value()" in stripped
                ):
                    offenders.append(f"{source.name}:{lineno}")

        assert not offenders, f"secret values passed to a log call: {offenders}"
