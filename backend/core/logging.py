"""Structured logging setup (E1-S3).

Provides ``get_logger(name)`` returning a logger that emits one JSON record per
line to stdout (12-factor; logging-strategy.md §1). Records always carry a
timestamp, level, logger name, and message, and optionally a ``session_id`` /
``request_id`` for correlating a single request or chat session across layers.

Secrets are never emitted by this module: it only serializes the fields callers
attach via ``extra=`` — callers are responsible for never passing secret values,
and a test (E1-S3 AC-4) verifies no source line does.
"""

import json
import logging
import os
import sys
from datetime import UTC, datetime

_RESERVED_RECORD_KEYS = frozenset(logging.LogRecord(
    name="", level=logging.INFO, pathname="", lineno=0, msg="", args=(), exc_info=None
).__dict__.keys()) | {"message", "asctime", "taskName"}

_DEFAULT_LEVEL = "INFO"


class StructuredFormatter(logging.Formatter):
    """Render a log record as a single-line JSON object.

    Base fields (``ts``, ``level``, ``logger``, ``msg``) are always present.
    Any extra context attached via ``extra={...}`` (e.g. ``session_id``,
    ``request_id``, ``result_count``) is merged into the same object.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": _format_timestamp(record.created),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload.update(_extract_context(record))
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def get_logger(name: str) -> logging.Logger:
    """Return a configured structured logger for ``name`` (E1-S3 AC-1).

    The level is read from ``LOG_LEVEL`` (default ``INFO``; AC-3). Handlers are
    configured once per logger so repeated calls do not duplicate output.
    """
    logger = logging.getLogger(name)
    logger.setLevel(_resolve_level())
    if not any(isinstance(handler.formatter, StructuredFormatter) for handler in logger.handlers):
        handler = logging.StreamHandler(stream=sys.stdout)
        handler.setFormatter(StructuredFormatter())
        logger.addHandler(handler)
        logger.propagate = False
    return logger


def _resolve_level() -> int:
    level_name = os.environ.get("LOG_LEVEL", _DEFAULT_LEVEL).upper()
    return logging.getLevelNamesMapping().get(level_name, logging.INFO)


def _format_timestamp(created: float) -> str:
    return datetime.fromtimestamp(created, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _extract_context(record: logging.LogRecord) -> dict[str, object]:
    return {
        key: value
        for key, value in record.__dict__.items()
        if key not in _RESERVED_RECORD_KEYS and not key.startswith("_")
    }
