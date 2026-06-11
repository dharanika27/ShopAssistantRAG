"""MySQL connection helpers and schema-init runner (E2-S1).

This module is the only place that talks to the MySQL driver. It exposes the
connection parameters derived from :class:`Settings`, a SQL-splitting helper,
and an idempotent ``init_schema`` runner that applies ``sql/schema.sql`` so a
fresh database can be bootstrapped for local dev and Docker (AC-3, AC-5).

Driver failures are caught and re-raised as :class:`RepositoryError` so no raw
``mysql.connector`` exception escapes this layer (error-handling-strategy.md §4).
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.core.config import Settings
from backend.core.errors import RepositoryError
from backend.core.logging import get_logger

logger = get_logger(__name__)

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "sql" / "schema.sql"

ConnectFn = Callable[..., Any]


def _default_connect(**kwargs: Any) -> Any:
    """Open a MySQL connection via mysql-connector-python.

    Imported lazily so importing this module never requires the driver to be
    installed (keeps unit tests that inject a fake ``connect`` dependency-free).
    """
    import mysql.connector

    return mysql.connector.connect(**kwargs)


def connection_params(settings: Settings) -> dict[str, Any]:
    """Build MySQL driver connection kwargs from settings (no password logging)."""
    return {
        "host": settings.MYSQL_HOST,
        "port": settings.MYSQL_PORT,
        "user": settings.MYSQL_USER,
        "password": settings.mysql_password_value(),
        "database": settings.MYSQL_DATABASE,
    }


def split_sql_statements(script: str) -> list[str]:
    """Split a SQL script into executable statements, dropping comments/blanks."""
    without_comments = "\n".join(
        line for line in script.splitlines() if not line.strip().startswith("--")
    )
    return [
        statement.strip()
        for statement in without_comments.split(";")
        if statement.strip()
    ]


def init_schema(settings: Settings, *, connect: ConnectFn = _default_connect) -> None:
    """Apply ``sql/schema.sql`` against the configured database (E2-S1 AC-3/AC-5).

    Idempotent because the schema uses ``CREATE TABLE IF NOT EXISTS`` with inline
    index declarations. Raises :class:`RepositoryError` on any driver failure.
    """
    statements = split_sql_statements(_SCHEMA_PATH.read_text(encoding="utf-8"))
    try:
        connection = connect(**connection_params(settings))
        try:
            with connection.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement)
            connection.commit()
        finally:
            connection.close()
    except RepositoryError:
        raise
    except Exception as exc:
        logger.error(
            "db.init_schema_failed",
            extra={"host": settings.MYSQL_HOST, "database": settings.MYSQL_DATABASE},
        )
        raise RepositoryError(
            f"Failed to initialize MySQL schema on {settings.MYSQL_HOST}: {exc}"
        ) from exc

    logger.info(
        "db.schema_initialized",
        extra={
            "host": settings.MYSQL_HOST,
            "database": settings.MYSQL_DATABASE,
            "statements_applied": len(statements),
        },
    )
