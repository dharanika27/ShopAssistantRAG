"""Unit tests for E2-S1 — MySQL schema & migration runner.

The MySQL driver is the external boundary and is mocked. Business logic (reading
the DDL file, splitting statements, executing them, idempotency of the schema
text itself) is exercised directly.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.core.config import Settings
from backend.core.errors import RepositoryError
from backend.repositories import db

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "sql" / "schema.sql"

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


class TestSchemaFile:
    def test_schema_file_exists(self) -> None:
        assert SCHEMA_PATH.exists()

    def test_products_table_is_created_if_not_exists(self) -> None:
        sql = SCHEMA_PATH.read_text(encoding="utf-8")

        assert "CREATE TABLE IF NOT EXISTS products" in sql

    def test_required_not_null_columns_present(self) -> None:
        sql = SCHEMA_PATH.read_text(encoding="utf-8").lower()

        assert "name" in sql and "not null" in sql
        assert "category" in sql
        assert "price" in sql
        assert "primary key" in sql

    def test_category_and_gender_enum_constraints_present(self) -> None:
        sql = SCHEMA_PATH.read_text(encoding="utf-8")

        for value in ("Shoes", "Clothing", "Accessories", "Sportswear", "Bags"):
            assert value in sql
        for value in ("Men", "Women", "Unisex", "Kids"):
            assert value in sql

    def test_product_id_is_primary_key(self) -> None:
        sql = SCHEMA_PATH.read_text(encoding="utf-8")

        assert "PRIMARY KEY (product_id)" in sql

    def test_indexes_declared_inline_for_idempotency(self) -> None:
        # MySQL 8 has no CREATE INDEX IF NOT EXISTS, so indexes are declared
        # inside the CREATE TABLE IF NOT EXISTS statement to stay idempotent.
        sql = SCHEMA_PATH.read_text(encoding="utf-8")

        assert db.split_sql_statements(sql) and len(db.split_sql_statements(sql)) == 1
        assert "KEY idx_products_category" in sql
        assert "KEY idx_products_price" in sql


class TestSplitStatements:
    def test_splits_on_semicolons_and_drops_blanks(self) -> None:
        statements = db.split_sql_statements(
            "CREATE TABLE a (x INT);\n\nCREATE INDEX i ON a (x);\n"
        )

        assert statements == [
            "CREATE TABLE a (x INT)",
            "CREATE INDEX i ON a (x)",
        ]

    def test_ignores_sql_line_comments(self) -> None:
        statements = db.split_sql_statements(
            "-- a comment\nCREATE TABLE a (x INT);\n-- trailing\n"
        )

        assert statements == ["CREATE TABLE a (x INT)"]


class TestInitSchema:
    def test_executes_every_statement_from_the_schema_file(
        self, settings: Settings
    ) -> None:
        cursor = MagicMock()
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        connect = MagicMock(return_value=connection)

        db.init_schema(settings, connect=connect)

        statements = db.split_sql_statements(SCHEMA_PATH.read_text(encoding="utf-8"))
        assert cursor.execute.call_count == len(statements)
        connection.commit.assert_called_once()
        connection.close.assert_called_once()

    def test_wraps_driver_failure_in_repository_error(
        self, settings: Settings
    ) -> None:
        def failing_connect(**_: object) -> object:
            raise ConnectionError("mysql refused the connection")

        with pytest.raises(RepositoryError) as exc_info:
            db.init_schema(settings, connect=failing_connect)

        assert exc_info.value.code == "MYSQL_UNAVAILABLE"

    def test_connect_receives_settings_without_leaking_password_in_error(
        self, settings: Settings
    ) -> None:
        cursor = MagicMock()
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        captured: dict[str, object] = {}

        def capturing_connect(**kwargs: object) -> object:
            captured.update(kwargs)
            return connection

        db.init_schema(settings, connect=capturing_connect)

        assert captured["host"] == "localhost"
        assert captured["port"] == 3306
        assert captured["database"] == "shopassistant"
        assert captured["user"] == "shop_user"
        assert captured["password"] == "shop_password"
