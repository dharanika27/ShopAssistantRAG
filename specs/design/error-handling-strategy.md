# Error Handling Strategy — ShopAssistantRAG

Graceful failure for Gemini, Pinecone, and MySQL — never leak stack traces (BRD NFR-3, §9). Source: stories E2-S2, E3-S2, E4-S1, E6-S2, E6-S3, E7-S1.

---

## 1. Principles

1. **Typed errors at boundaries.** Repository/service layers catch raw driver/SDK exceptions and raise a typed domain error (`backend/core/errors.py`). No raw `pymysql`, `pinecone`, or `google.generativeai` exception escapes its layer.
2. **Map once, at the edge.** The FastAPI error middleware (E7-S1) is the single place that maps typed errors → HTTP status + BRD user message envelope.
3. **No stack traces in responses.** Internals are logged (with correlation id), never returned (NFR-3).
4. **Non-fatal where the BRD says so.** Ingestion embedding failures and CSV-row failures are recorded and skipped, not raised (E2-S3, E3-S3). Missing-in-MySQL hydration IDs are skipped, not fatal (E5-S3 AC-3).

---

## 2. Typed Error Hierarchy (`backend/core/errors.py`)

```
AppError (base)
├── RepositoryError      # MySQL/connection/query failures (E2-S2 AC-5)
├── RetrievalError       # Pinecone connect/query/provision failures (E4-S1 AC-4)
├── EmbeddingError       # Gemini embedding SDK failures (E3-S2 AC-3)
├── GenerationError      # Gemini generation SDK failures (E6-S2 AC-5)
└── ConfigError          # missing/invalid settings (E1-S2 AC-4); index dim mismatch (E4-S1 AC-3)
```

`ValidationError` is handled by FastAPI/Pydantic natively (422), not in this hierarchy.

---

## 3. Error → HTTP → User Message Map (BRD §9.1, api-contracts.md)

| Typed error | HTTP | `code` | User message |
|-------------|------|--------|--------------|
| `EmbeddingError`, `GenerationError` | 503 | `GEMINI_UNAVAILABLE` | The AI assistant is temporarily unavailable. Please try again in a few moments. |
| `RetrievalError` | 503 | `PINECONE_UNAVAILABLE` | Product search is temporarily unavailable. Please try again later. |
| `RepositoryError` | 503 | `MYSQL_UNAVAILABLE` | We are unable to load product details right now. Please try again later. |
| Pydantic/request validation | 422 | `VALIDATION_ERROR` | FastAPI field-level detail body. |
| Any unhandled `Exception` | 500 | `INTERNAL_ERROR` | An unexpected error occurred. Please try again later. |

Envelope (all non-2xx except 422):

```json
{ "error": { "code": "PINECONE_UNAVAILABLE", "message": "Product search is temporarily unavailable. Please try again later." } }
```

---

## 4. Layer Responsibilities

| Layer | On failure |
|-------|-----------|
| Repository (MySQL) | Catch driver exception → raise `RepositoryError` (E2-S2 AC-5). |
| Pinecone client | Catch SDK/connection error → raise `RetrievalError` (E4-S1 AC-4). |
| Embedding client | Catch Gemini error → raise `EmbeddingError` (E3-S2 AC-3). |
| Answer generator | Catch Gemini error → raise `GenerationError`; orchestrator returns BRD message (E6-S2 AC-5). |
| ChatOrchestrator | Lets typed errors propagate to middleware; handles **business** edge cases itself (no-match, small talk, invalid query) without raising — these are valid 200 responses (E6-S3 AC-4/AC-5). |
| API middleware | Maps typed error → envelope; logs full detail with `request_id`/`session_id`; returns no trace (E7-S1 AC-3/AC-4). |
| Frontend (Streamlit) | On non-200, shows the friendly message from the envelope, not a trace (E8-S1 AC-4). |

---

## 5. Business Edge Cases (200 OK, not errors) — BRD §9.2

| Case | Handling |
|------|----------|
| Empty result set | Friendly no-match `reply` + `products: []`, suggest categories (E6-S3 AC-4). |
| Out-of-catalog category ("laptops") | Filters drop unknown → no match → category suggestions. |
| Invalid query ("asdfgh") | Clarification `reply`, no retrieval (E6-S3 AC-5). |
| Greetings / small talk | Scoped conversational `reply`, no retrieval. |
| Price-only ("under ₹500") | Valid — price filter + semantic retrieval. |

These never produce a 4xx/5xx; they are normal grounded responses.

---

## 6. Ingestion Failure Handling (non-fatal) — BRD §9.3

| Case | Handling |
|------|----------|
| Missing required field (name/price/category) | Skip row, record `{row_id, reason}`, continue (E2-S3 AC-2). |
| Enum out of range (category/gender) | Skip row, record failure (E2-S3 AC-3). |
| Duplicate product_id | Upsert (update existing) — not an error (E3-S3 AC-5). |
| Embedding failure for a row | Log, skip Pinecone upsert for it, include in summary (E3-S3 AC-3). |
| End of run | Print summary: total / successful / failed / reasons (E3-S3 AC-4). |

---

## 7. Retry & Timeout Posture (demo scale)

- Single-attempt external calls in MVP (low concurrency); on failure → typed error → user message. No aggressive retry loops (avoids breaching the <5s budget).
- Optional single bounded retry on transient Gemini/Pinecone errors is a documented future hook (NFR-6), not required for MVP.
- MySQL connectivity is verified at startup (entrypoint wait-for-mysql) so request-time `RepositoryError` is rare.
