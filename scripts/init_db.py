"""CLI entrypoint to apply the MySQL product schema (E2-S1).

Usage::

    python -m scripts.init_db

Idempotent — safe to run repeatedly against a fresh or existing database. Exits
non-zero with a clear message if configuration or the database is unavailable.
"""

import sys

from backend.core.config import Settings
from backend.core.errors import AppError
from backend.core.logging import get_logger
from backend.repositories.db import init_schema

logger = get_logger(__name__)


def main() -> int:
    """Load settings, apply the schema, and return a process exit code."""
    try:
        settings = Settings()
        init_schema(settings)
    except AppError as exc:
        logger.error("init_db.failed", extra={"code": exc.code})
        print(f"Schema init failed [{exc.code}]: {exc}", file=sys.stderr)
        return 1
    print(f"Schema applied to '{settings.MYSQL_DATABASE}' on {settings.MYSQL_HOST}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
