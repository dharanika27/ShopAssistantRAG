"""Shared isolation fixtures for unit tests.

The E1-S2 config tests assert on the *code* defaults for the optional model and
index settings (e.g. ``EMBEDDING_MODEL == "text-embedding-004"``). Those tests
construct ``Settings(_env_file=None)`` to ignore any developer ``.env`` file —
but ``_env_file=None`` only disables pydantic's ``.env`` reading, not OS-level
environment variables. When a developer ``.env`` has been exported into the
process environment (as happens in this workspace), those exported values shadow
the code defaults and the "typed defaults" assertions fail spuriously.

This autouse fixture removes the optional, defaulted configuration keys from the
process environment for every unit test, completing the isolation the config
tests already intend. Required secrets are still supplied per-test via
``monkeypatch.setenv`` and are deliberately left untouched here.
"""

import sys
from pathlib import Path

import pytest

# The frontend is run via ``streamlit run app.py`` from inside ``frontend/``, so
# its modules import each other directory-relative (``from api_client import ...``,
# ``from components.product_card import ...``). The frontend unit tests, however,
# import them by package path (``frontend.components.catalog_grid``). Putting the
# ``frontend/`` directory on ``sys.path`` lets those directory-relative imports
# resolve during collection without rewriting the tests or the app imports.
_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if str(_FRONTEND_DIR) not in sys.path:
    sys.path.insert(0, str(_FRONTEND_DIR))

# Optional settings that have a code-level default in ``backend.core.config``.
# These must not be inherited from a developer ``.env`` during unit tests.
_OPTIONAL_CONFIG_KEYS: tuple[str, ...] = (
    "PINECONE_INDEX_NAME",
    "EMBEDDING_MODEL",
    "GENERATION_MODEL",
    "EMBEDDING_DIM",
    "LOG_LEVEL",
    "ALLOWED_ORIGINS",
    "LLM_PROVIDER",
    "GROQ_API_KEY",
    "GROQ_MODEL",
)


@pytest.fixture(autouse=True)
def _isolate_optional_config_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip optional, defaulted config env vars so code defaults are observable."""
    for key in _OPTIONAL_CONFIG_KEYS:
        monkeypatch.delenv(key, raising=False)
