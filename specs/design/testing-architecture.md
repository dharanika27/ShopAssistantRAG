# Testing Architecture — ShopAssistantRAG

Critical-path unit tests (externals mocked) + integration/E2E for the core journey (BRD NFR-5, DoD 12–14). Source: stories E9-S1, E9-S2.

---

## 1. Test Pyramid

```
        ┌────────────────────────┐
        │  E2E (1 journey)        │  browse → query → refine → no-match   (E9-S2)
        ├────────────────────────┤
        │  Integration (API)      │  FastAPI TestClient vs seeded catalog (E9-S2)
        ├────────────────────────┤
        │  Unit (critical path)   │  Gemini/Pinecone/MySQL mocked         (E9-S1)
        └────────────────────────┘
```

All external services (Gemini, Pinecone, MySQL) are **mocked** in unit tests; the suite runs green with **no live connections** (E9-S1 AC-5).

---

## 2. Layout (`tests/`)

```
tests/
├── conftest.py                       # shared fixtures: mock embedding client, mock pinecone, fake repo, seeded catalog
├── unit/
│   ├── test_filter_extractor.py      # enum normalization, price-only, malformed JSON (E9-S1 AC-1)
│   ├── test_hybrid_retriever.py      # filter dict + range + k=5 vs mocked Pinecone (AC-2)
│   ├── test_hydrator.py              # rank-order preserved, missing IDs skipped (AC-3)
│   ├── test_query_state.py           # merge/reset/cheaper/isolation (AC-4)
│   └── test_chat_orchestrator.py     # turn wiring, no-match, small talk
├── integration/
│   ├── test_chat_endpoint.py         # POST /api/chat 200 + ≤5 products (E9-S2 AC-1)
│   └── test_catalog_endpoints.py     # GET /api/products filters, GET /api/filters (AC-2)
└── e2e/
    └── test_core_journey.py          # browse→query→refine→no-match (AC-3..AC-5)
```

`pytest.ini` registers markers (`unit`, `integration`, `e2e`) so CI can run layers independently (deployment.md §3).

---

## 3. Critical-Path Unit Tests (E9-S1)

| Target | Assertions | Mocks |
|--------|------------|-------|
| FilterExtractor | "red Nike shoes under ₹3000" → `{brand:Nike,color:Red,category:Shoes,max_price:3000}`; Crimson→Red, Trainers→Shoes; out-of-vocab→None; price-only; malformed JSON→empty filters | Gemini (canned JSON) |
| HybridRetriever | `$eq` filters for brand/color/category/gender; `$gte`/`$lte` for price; `k=5`; empty result on over-restrictive filter | Pinecone client, embedding client |
| Hydrator | rank order preserved (rank 1 first); ID present in Pinecone but absent in MySQL is skipped + logged; empty list → no query | MySQL repo |
| QueryStateManager | merge accumulates ("only red ones"); category change resets; "cheaper" lowers `max_price`; two sessions isolated | none (pure) |
| ChatOrchestrator | full turn returns `{reply, products[≤5]}`; no-match → empty products + suggestions; small talk/invalid → scoped reply, no retrieval | all services mocked |

---

## 4. Integration Tests (E9-S2)

- FastAPI `TestClient`; service layer wired to a **seeded test catalog** (in-memory or test MySQL) with mocked Gemini/Pinecone (or a deterministic fake retriever).
- `POST /api/chat` → 200, `reply` present, `products` ≤ 5 (AC-1).
- `GET /api/products?brand=Nike&category=Shoes` → only matching products (AC-2); no-match filter → `[]` + 200.
- `GET /api/filters` → distinct option lists + price_range.
- Multi-turn within one `session_id`: "Show Nike shoes" then "only red ones" narrows results (AC-3).
- No-match query → graceful reply + zero products (AC-4).
- 422 on empty/missing `message`.

---

## 5. E2E Core Journey (E9-S2 AC-5 / BRD DoD 14)

Sequence (against the running stack or TestClient + Streamlit-equivalent calls):

```
1. GET /api/products            -> catalog renders (browse)
2. GET /api/filters             -> filter options available
3. POST /api/chat "Show me red Nike shoes under ₹3000"  -> reply + ≤5 cards
4. POST /api/chat "cheaper options" (same session)       -> refined cheaper results
5. POST /api/chat "show me laptops"                      -> graceful no-match, 0 products
=> completes with no blocking errors (DoD 14)
```

Playwright may drive the Streamlit UI for a true browser E2E (optional in CI, deployment.md §3 stage 5).

---

## 6. Fixtures & Mock Boundaries (`conftest.py`)

| Fixture | Provides |
|---------|----------|
| `mock_embedding_client` | returns deterministic 768-dim vectors; never calls Gemini |
| `mock_pinecone` | returns canned ranked IDs + metadata for given filters; honors `k`, empty on over-restriction |
| `mock_generation` | returns a deterministic grounded reply; asserts only supplied products appear |
| `seeded_catalog` | ~10–20 `Product` rows covering each enum/brand/color for filter assertions |
| `fake_repo` | in-memory `ProductRepository` backed by `seeded_catalog` |

Mock boundary rule: mock at the **client/repository edge** (Gemini SDK, Pinecone SDK, MySQL driver) — never mock the services under test. This keeps tests honest about orchestration logic (the R-1 risk area).

---

## 7. Coverage Targets & Gate

- 100% of critical-path branches: filter normalization, retrieval filter construction, hydration ordering, merge/reset rules, no-match path.
- CI gate (deployment.md §3): lint → unit (mocked) → build → integration (seeded) → optional E2E. Unit suite must pass with no network (E9-S1 AC-5). DoD items 12–14 satisfied when unit + integration green and the core journey runs clean.
