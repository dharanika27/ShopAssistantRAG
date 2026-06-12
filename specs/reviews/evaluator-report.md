# Evaluator Report — Sprint Contract Group B

- **Project:** ShopAssistantRAG
- **Contract:** `sprint-contracts/B.json`
- **Stories:** E2-S2, E2-S3, E3-S1, E3-S2, E4-S1
- **Features:** F017–F033
- **Verification mode:** docker (backend :8000, frontend :8501, mysql :3307)
- **Evaluated:** 2026-06-12T17:40:00Z

## Overall Verdict: PASS

All three verification layers pass for every Group B feature. The application stack is healthy, the
Group B unit suite is green, mypy is clean on all contract modules, layering is one-way, and the
running backend exercises the data/RAG plumbing (repository, embeddings, Pinecone retrieval) correctly
end-to-end.

---

## Layer 1 — Architecture Checks

| Check | Required | Result | Evidence |
|-------|----------|--------|----------|
| files_must_exist (6 files) | yes | PASS | All 6 present: `product_repository.py`, `core/errors.py`, `csv_loader.py`, `embedding_text.py`, `embedding_client.py`, `pinecone_client.py` |
| layering (one-way imports) | yes | PASS | No reverse imports found. domain/core import nothing upward; repositories import no services/api; services import no api. |
| typing (mypy clean) | yes | PASS | `mypy 1.14.1 --ignore-missing-imports` on all 6 modules: "Success: no issues found in 6 source files". No unannotated `def` found. |
| folder_structure | yes | PASS | File locations match `specs/design/component-map.md` for E2-S2…E4-S1. |
| env_vars (no hardcoded secrets) | no | PASS | Secret regex scan over `backend/**` found no hardcoded keys; config flows via Settings/.env. |
| migrations (idempotent schema) | no | PASS | `sql/schema.sql` uses `CREATE TABLE IF NOT EXISTS products` (idempotent). |

Note: `mypy` and `pytest` are intentionally absent from the runtime backend container image (lean
production image). Both checks were executed on the host toolchain (anaconda python 3, mypy 1.14.1,
pytest 8.3.4) against the same source tree. This is expected and not a defect.

## Layer 1 — Unit Tests (Group B critical path)

`pytest` over the 5 Group B modules + errors: **56 passed in 0.42s**. Per-feature mapping:

| Feature | Acceptance criterion | Backing test | Result |
|---------|----------------------|--------------|--------|
| F017 | upsert inserts new / updates existing by id | `test_upsert_executes_insert_on_duplicate_key_update` | PASS |
| F018 | get_products_by_ids preserves input order | `test_preserves_input_ordering` | PASS |
| F019 | list_products filters / all-when-empty | `test_filters_build_where_clause_with_bound_params`, `test_no_filters_selects_all` | PASS |
| F020 | empty id list returns empty without querying DB | `test_empty_id_list_returns_empty_without_querying` | PASS |
| F021 | connection failure → typed RepositoryError | `test_connection_failure_raises_repository_error` | PASS |
| F022 | valid CSV row → Product | `test_valid_row_parses_into_product` | PASS |
| F023 | missing required field skipped + recorded | `test_missing_required_field_is_skipped_and_recorded` | PASS |
| F024 | out-of-enum category/gender skipped | `test_out_of_vocab_category_is_skipped`, `test_out_of_vocab_gender_is_skipped` | PASS |
| F025 | tags parsed to trimmed list; valid+failures returned | `test_tags_parsed_into_trimmed_list`, `test_valid_and_invalid_rows_are_partitioned` | PASS |
| F026 | embedding text includes semantic fields, excludes price/stock/image | `test_includes_all_semantic_fields`, `test_excludes_price_stock_and_image_url` | PASS |
| F027 | missing optionals omitted without literal "None"; coherent | `test_omits_missing_color_and_tags_without_literal_none`, `test_reads_as_coherent_description` | PASS |
| F028 | embed_text → 768-dim, model text-embedding-004 | `test_returns_768_dim_vector`, `test_uses_model_from_settings` | PASS |
| F029 | embed_batch → one ordered 768-dim vector per text | `test_returns_one_vector_per_input_in_order` | PASS |
| F030 | SDK error → typed EmbeddingError; settings-driven | `test_sdk_failure_is_reraised_as_embedding_error`, `test_wrong_dimension_raises_embedding_error` | PASS |
| F031 | Pinecone connects via settings, reuses existing index | `test_reuses_existing_index_without_creating`, `test_passes_api_key_from_settings_to_sdk` | PASS |
| F032 | missing index created dim=768 cosine; wrong dim flagged | `test_creates_index_when_absent_with_768_cosine`, `test_rejects_non_768_configured_dimension` | PASS |
| F033 | connection failure → typed retrieval error | `test_connection_failure_raises_retrieval_error` | PASS |

## Layer 2 — Running Backend (end-to-end exercise)

Group B features are data/RAG-plumbing and are not directly HTTP-exposed, but the running stack
exercises them through the live endpoints:

| Check | Result | Evidence |
|-------|--------|----------|
| Health | PASS | `GET /api/health` → 200 `{"status":"ok",...}` after retry loop |
| Catalog (repository → MySQL) | PASS | `GET /api/products` → 200, 30 products, full display fields incl. derived `in_stock` |
| Chat product search (embeddings → Pinecone → hydrate → generate) | PASS | "running shoes" → 5 grounded products; "Nike shoes" → 2; "bags" → 4 |
| Hybrid equality filter correctness | PASS | "red Nike shoes" → 0 products — confirmed correct: catalog has no red Nike shoes (Nike shoes are Black/Pink; only red shoe is Adidas) |
| Out-of-catalog short-circuit | PASS | "gaming laptop RTX 4090" → clean no-match naming the 5 categories, zero products |
| Chat validation | PASS | empty message → 422; missing message → 422 |
| Grounding cap | PASS | chat products ≤ 5, full product schema |
| CORS | PASS | OPTIONS preflight from `http://localhost:8501` → `access-control-allow-origin: http://localhost:8501` |
| Request logging (secret-free) | PASS | structured logs carry request_id/method/path/status; no secret values |

## Layer 3 — Frontend liveness (Playwright-level)

| Check | Result | Evidence |
|-------|--------|----------|
| Streamlit reachable | PASS | `GET /` → 200; `/_stcore/health` → 200 |

Full browser-driven Playwright UI assertions belong to Group G (F074–F081) and are out of scope for the
Group B contract. Frontend liveness plus the verified backend chat round-trip is sufficient evidence the
Group B pipeline serves the UI.

---

## Findings

No BLOCK findings.

- **INFO** — `mypy` and `pytest` are not installed in the runtime backend container image
  (`shopassistantrag-backend-1`). Appropriate for a lean production image; checks were run via the host
  toolchain. If CI should run them in-container, add a dev/test image stage.
- **INFO** — Layer 1 unit tests use mocked Gemini/Pinecone (per design); the live Pinecone/Groq
  integration was independently confirmed working through the running `/api/chat` round-trips.

## features.json updates

F017–F033 set to `passes: true`, `last_evaluated: 2026-06-12T17:40:00Z`, `failure_reason: null`,
`failure_layer: null`. No other features modified. No regressions detected in previously passing
Group A features (catalog/health endpoints exercised remain green).
