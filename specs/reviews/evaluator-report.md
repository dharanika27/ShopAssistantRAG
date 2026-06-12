# Evaluator Report — Sprint Contract Group A

- Project: ShopAssistantRAG
- Contract: `sprint-contracts/A.json`
- Stories: E1-S1, E1-S2, E1-S3, E2-S1
- Features: F001–F016
- Verification mode: FULL (Docker stack live: backend, frontend, mysql:8.0 healthy)
- Date: 2026-06-12

## Overall Verdict: PASS

All architecture checks pass, all 16 in-scope feature acceptance criteria are verified
(unit tests + live MySQL behavior + live API), and the full test suite (unit + integration + e2e)
is green. One non-blocking advisory is recorded below.

---

## Environment / Infrastructure

- Health check `GET http://localhost:8000/api/health` -> `200` `{"status":"ok",...}` (reachable).
- Docker containers up: `shopassistantrag-backend-1`, `shopassistantrag-frontend-1`,
  `shopassistantrag-mysql-1` (healthy).
- Backend container is a production image (Python 3.11.15, no test deps, tests not mounted).
- Test suite executed with local `py -3` (Python 3.13.2, pytest 9.0.3, mypy 2.1.0, pydantic 2.x present).
- Live `GET /api/products` returns a JSON list of 30 seeded products with the derived `in_stock`
  field — confirms schema + API + catalog are functional end to end.

---

## Architecture Checks (from A.json)

| Check | Result | Evidence |
|-------|--------|----------|
| layering (one-way imports) | PASS | `backend/domain/*` imports only `domain`; `backend/core/config.py` imports only `core.errors`. No upward imports (domain->core/services/api/repos = NONE; core->services/api/repos = NONE). `repositories/db.py` imports core+domain (downward, correct). |
| typing (mypy clean) | PASS | `mypy backend/domain/models.py enums.py core/config.py core/logging.py repositories/db.py scripts/init_db.py` -> "Success: no issues found in 6 source files". |
| folder_structure | PASS | All files for E1-S1/E1-S2/E1-S3/E2-S1 present at the paths in `specs/design/component-map.md`. |
| env_vars (no hardcoded secrets) | PASS | Secret/password/api-key literal scan over Group A source -> none. Secrets loaded via `Settings` (pydantic-settings, `.env`) as `SecretStr`. `.env` is gitignored and NOT tracked by git. |
| migrations (idempotent) | PASS | `sql/schema.sql` re-applied twice against live MySQL -> exit 0 both times; `information_schema` shows exactly one `products` table. |
| files_must_exist (9 files) | PASS | All 9 listed files exist (models.py, enums.py, config.py, logging.py, schema.sql, init_db.py, db.py, .env.example, .gitignore). |

---

## Feature Acceptance Criteria (F001–F016)

Verified via the mapped unit tests (46 passed) plus live MySQL/API checks.

| Feature | Story | Result | Evidence |
|---------|-------|--------|----------|
| F001 Product model exposes all BRD fields, correct types | E1-S1 | PASS | `test_builds_a_valid_product_with_all_fields`, `test_price_is_a_decimal`; model has product_id/name/description/brand/category/gender/color/price(Decimal)/image_url/stock(int)/tags(list). |
| F002 Category enum = 5 allowed values | E1-S1 | PASS | `test_category_has_exactly_five_members`, `test_unknown_category_value_is_rejected`. |
| F003 Gender enum = 4 allowed values | E1-S1 | PASS | `test_gender_has_exactly_four_members`, `test_unknown_gender_value_is_rejected`. |
| F004 QueryFilters 6 optional fields default None | E1-S1 | PASS | `test_all_fields_default_to_none`. |
| F005 Missing name/price/category raises validation error | E1-S1 | PASS | `test_missing_name/price/category_raises_validation_error`. |
| F006 stock=0 -> in_stock False | E1-S1 | PASS | `test_stock_zero_is_valid_and_yields_in_stock_false`. |
| F007 Settings load required secrets + MySQL params from env | E1-S2 | PASS | `test_loads_all_required_keys_from_environment`. |
| F008 .env.example lists all required keys; .env gitignored | E1-S2 | PASS | All 7 required keys present in `.env.example`; `.gitignore` line 3 = `.env`; `.env` untracked. |
| F009 Missing required setting raises error naming the key | E1-S2 | PASS | `test_missing_required_key_raises_config_error_naming_the_key`, `test_missing_multiple_keys_names_each_one`; `ConfigError` lists missing keys. |
| F010 Typed model/index defaults (index, embed model, gen model, dim 768) | E1-S2 | PASS | `test_exposes_typed_defaults`; code defaults EMBEDDING_MODEL=text-embedding-004, GENERATION_MODEL=gemini-1.5-flash, EMBEDDING_DIM=768, PINECONE_INDEX_NAME=shop-products. See Advisory A-1. |
| F011 get_logger structured (ts, level, name, msg) | E1-S3 | PASS | `test_emits_timestamp_level_logger_and_message`. |
| F012 session_id/request_id correlation + configurable level | E1-S3 | PASS | `test_includes_session_id_and_request_id_when_present`, `test_level_configurable_via_env`. |
| F013 No log emits raw API key values | E1-S3 (security) | PASS | `test_no_source_line_logs_a_raw_api_key`; independent grep for secret-logging -> none. |
| F014 products table: required cols + NOT NULL | E2-S1 | PASS | Live `DESCRIBE products`: product_id/name/category/price NOT NULL; all BRD columns present. |
| F015 category/gender constrained to enum sets | E2-S1 | PASS | Live insert category='Laptops' rejected (exit 1); gender='Robot' rejected (exit 1). CHECK constraints present in DDL. |
| F016 schema idempotent + product_id PK | E2-S1 | PASS | Schema re-applied twice OK; duplicate product_id insert rejected (exit 1); product_id is PRIMARY KEY. |

---

## Test Suite Results

- `pytest tests/unit` -> 223 passed.
- Group A subset (`test_domain_models`, `test_config`, `test_logging`, `test_db`) -> 46 passed.
- `pytest tests/integration tests/e2e` -> 28 passed (1 deprecation warning, non-blocking).
- mypy on Group A modules -> clean.

---

## Advisory (non-blocking)

- A-1: `.env.example` line 45 sets `EMBEDDING_MODEL=gemini-embedding-2`, which contradicts the
  code default (`backend/core/config.py:52` = `text-embedding-004`), the project manifest
  (`text-embedding-004`), and F010's expected value. This does NOT fail F010 (which verifies the
  code default, and the unit test isolates env so it passes) and does not affect Group A acceptance
  criteria. It is a config/documentation inconsistency that should be reconciled — a deployed `.env`
  copied from the template would request an embedding model name that differs from the documented
  contract. Recommend aligning `.env.example` to `text-embedding-004` (or updating the contract if
  the provider migration to a Gemini embedding model is intentional).

## Checks Not Run / Limitations

- None for Group A. All architecture checks and F001–F016 criteria were executed directly against
  source, the test suite, and the live MySQL container / API. The backend production container lacks
  test dependencies, so the test suite was run via the local Python 3.13 interpreter rather than
  inside the container; results are consistent with the live containerized behavior verified
  separately (schema, constraints, API responses).
