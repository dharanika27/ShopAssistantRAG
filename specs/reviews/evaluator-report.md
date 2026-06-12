# Evaluator Report — Sprint Contract Group E (Chat Service)

- **Project:** ShopAssistantRAG
- **Contract:** `sprint-contracts/E.json`
- **Stories:** E6-S1 (session memory & filter state), E6-S2 (grounded RAG generation), E6-S3 (multi-turn / reset / no-match)
- **Features:** F049–F061
- **Verification mode:** docker (Full) — used the already-running stack
- **Evaluated:** 2026-06-12
- **Backend:** http://localhost:8000 — `GET /api/health` -> 200 (1st attempt)
- **Frontend:** http://localhost:8501 — 200
- **MySQL:** healthy; catalog seeded with 30 products (shoes ₹2299–₹6999)

## Overall Verdict: PASS

All three verification layers pass for every feature F049–F061 and all three
required architecture checks (layering, typing, folder_structure). All four
required files exist.

The single remaining blocker from the prior review cycle (F054 / AC-4 naming
`gemini-1.5-flash`) is now **resolved by a ratified contract amendment**: the
E6-S2 story file carries a "Contract Amendment — 2026-06-12" making AC-4
provider-agnostic, and `specs/features.json` F054 was updated to the
provider-agnostic wording ("default Groq llama-3.3-70b-versatile", asserting on
`Settings.active_generation_model()`). The running system satisfies that current
criterion: `active_generation_model()` resolves to Groq `llama-3.3-70b-versatile`.

| Severity | Count |
|----------|-------|
| BLOCK    | 0 |
| WARN     | 1 |
| INFO     | 1 |

## Required files (all present)

| File | Status |
|------|--------|
| `backend/services/query_state.py` | present |
| `backend/services/answer_generator.py` | present |
| `backend/prompts/answer_generation.txt` | present |
| `backend/services/chat_orchestrator.py` | present |

## Architecture checks

| Check | Required | Result | Evidence |
|-------|----------|--------|----------|
| **layering** | yes | PASS | The three E6 service files import only from `backend.core`, `backend.domain`, and sibling `backend.services`. No `backend.api` import anywhere under `backend/services/` (one-way API->Service->Repository per system-design.md). `chat_orchestrator` takes collaborators via `Protocol`s, not concrete repository imports. |
| **typing** | yes | PASS | `mypy 2.1.0` (config `disallow_untyped_defs`, `no_implicit_optional`, `check_untyped_defs`) on the three files: "Success: no issues found in 3 source files". |
| **folder_structure** | yes | PASS | Files exactly match `specs/design/component-map.md` rows E6-S1/E6-S2/E6-S3. |
| env_vars | no | skipped | not required for group E |
| migrations | no | skipped | not required for group E |

## Per-feature results

| Feature | Story | Verdict | Layer(s) | Evidence |
|---------|-------|---------|----------|----------|
| **F049** Isolated per-session filters & history | E6-S1 | PASS | unit | `test_query_state.py` (29 passed): A/B isolation; each `SessionState` owns its own `QueryFilters`. |
| **F050** Reset to empty filters | E6-S1 | PASS | unit + API | `QueryStateManager.reset()` clears filters/last_category/last_result_min_price; live "forget previous search" -> fresh reply. |
| **F051** In-memory only, bounded history | E6-S1 | PASS | unit | `history = deque(maxlen=history_limit)`; process-local dict, no persistence. |
| **F052** Prompt includes only retrieved products | E6-S2 | PASS | unit | `test_prompt_contains_only_supplied_products`; `_format_products` renders only supplied products. |
| **F053** Answer references only context products | E6-S2 | PASS | API | Live "Show me Nike shoes" -> reply references only the 2 returned products; scanning all 30 catalog names found NONE leaked. |
| **F054** Empty context -> no-match + configured provider | E6-S2 | PASS | unit + live | Empty context short-circuits to `_NO_MATCH_MESSAGE` listing all 5 categories, no model call; `active_generation_model()` = Groq `llama-3.3-70b-versatile` in the running container, matching the amended provider-agnostic AC-4 and the current F054 description. |
| **F055** Generation failure -> BRD message, no stack trace | E6-S2 | PASS | unit | `test_sdk_failure_returns_brd_user_message`, `test_sdk_failure_does_not_leak_exception`; `_invoke` catches, logs ERROR, returns `UNAVAILABLE_MESSAGE`. |
| **F056** Refinement merges & rebuilds fresh retrieval | E6-S3 | PASS | API | Live: "Show me Nike shoes" (2 cards) -> "only black ones" narrowed to the single Black Nike (Revolution 6) — color merged onto brand+category; fresh retrieval, not a re-filter of the prior list. |
| **F057** "Cheaper options" lowers ceiling & re-runs | E6-S3 | PASS | API | Live: shoes<6000, cheapest shown = ₹2799; "cheaper options" -> Adidas Tensaur Kids @ ₹2299 (strictly < ₹2799). `_lower_price_ceiling` sets exclusive ceiling = min_shown − ₹1. |
| **F058** Category change / reset clears state | E6-S3 | PASS | API | Live: after Nike-shoes, "Now show me bags" -> only Bags (4 cards); "forget previous search" -> reset reply. |
| **F059** Empty result -> no-match + zero cards | E6-S3 | PASS | API | Live: "Show me laptops under 50000" -> friendly out-of-catalog reply listing categories, 0 products. |
| **F060** Greetings/invalid -> scoped reply, no retrieval | E6-S3 | PASS | API | Live: "hi" -> capability reply, 0 products; "asdfgh" -> clarification, 0 products. |
| **F061** Each turn: NL message + <=5 grounded cards | E6-S3 | PASS | API + schema | Live "Show me Nike shoes": string reply + 2 products (<=5); validates against `ChatResponse` schema (reply:string, products:array maxItems 5). |

## Layer evidence summary

**Layer 1 — API (running backend, :8000):**
- `/api/chat` exercised: greeting, invalid, normal query, refine (merge), cheaper (x re-retrieval), category-change, reset, out-of-catalog no-match. All 200 with correct product/reply behavior.
- Empty `message` -> 422 validation error (matches contract).

**Layer 2 — Playwright (running frontend, :8501):**
- Streamlit UI renders, exposes a chat input; "Show me Nike shoes" produced a reply mentioning Nike — confirms the E6 chat service is wired end-to-end through the UI. (UI-correctness features are owned by group G; this was a wiring smoke check.)

**Layer 3 — Schema validation:**
- Live `ChatResponse` has required `reply` (string) + `products` (array, len<=5); each product carries the full `Product` property set from `api-contracts.schema.json`. Empty-message -> 422.

## Test execution summary

- `mypy` on the three E6 files: 0 issues.
- `test_query_state.py` + `test_chat_orchestrator.py`: 29 passed.
- `test_answer_generator.py`: 8 passed (F052, F054, F055).
- E6 + `test_llm_provider.py` + `test_config.py`: 49 passed total.

## Findings by severity

### BLOCK
None.

### WARN
- **WARN-1 — Stale "Gemini" wording in answer-generator docstrings/comments.**
  `backend/services/answer_generator.py` (module docstring lines 1–25, class docstring line 57, `_invoke` comment around line 90) and `tests/unit/test_answer_generator.py` still describe "Gemini" while the active provider is Groq. Documentation-only; non-blocking. Aligning these comments with the actual provider removes the ambiguity that drove the prior F054 BLOCK.

### INFO
- **INFO-1 — features.json F054 flag corrected.** `specs/features.json` carried `F054.passes = false` before this run. The implementation, unit tests, and live model resolution confirm F054 passes under the ratified provider-agnostic AC-4. Flag updated to `true` with this evaluation. No code change required.
