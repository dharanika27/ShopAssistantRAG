# Logging Strategy — ShopAssistantRAG

Structured logging for retrieval operations, API requests, and embedding generation — secret-free, correlatable (BRD NFR-4, §9.1). Source: stories E1-S3, E7-S1.

---

## 1. Principles

1. **Structured records** — every log carries `timestamp`, `level`, `logger` name, `message`, plus optional context (E1-S3 AC-1).
2. **Correlation** — a `request_id` (per HTTP request) and `session_id` (per chat session) are attached so a single user journey can be traced across layers (E1-S3 AC-2).
3. **Secret-free** — no log statement ever emits `GOOGLE_API_KEY` or `PINECONE_API_KEY` values (E1-S3 AC-4). Verified by inspection/test.
4. **stdout, 12-factor** — logs to stdout; collected via `docker compose logs` (deployment.md §8). No file rotation logic in app.
5. **Configurable level** — `LOG_LEVEL` env var, default `INFO` (E1-S3 AC-3).

---

## 2. Logger Helper (`backend/core/logging.py`)

```python
get_logger(name) -> Logger          # configured; structured formatter; level from LOG_LEVEL
# usage:
log = get_logger(__name__)
log.info("retrieval.query", extra={"session_id": sid, "request_id": rid,
                                   "filters": filters_summary, "result_count": n})
```

Context fields (`session_id`, `request_id`) are injected via a context filter / `extra` so they appear on every record within a request scope. Record format (JSON-ish):

```
{"ts":"2026-06-02T10:15:30Z","level":"INFO","logger":"backend.services.hybrid_retriever",
 "msg":"retrieval.query","request_id":"r-8f2a","session_id":"s-13c","result_count":5}
```

---

## 3. What Gets Logged (BRD NFR-4)

| Area | Event | Fields (no secrets) |
|------|-------|---------------------|
| API request | `http.request` / `http.response` | method, path, status, latency_ms, request_id (E7-S1 AC-5) |
| Chat turn | `chat.turn` | session_id, message length (not raw PII concern here), reset/merge decision, result_count |
| Filter extraction | `extract.filters` | session_id, normalized filter keys (not the model key), dropped_out_of_vocab count |
| Retrieval | `retrieval.query` | applied filter fields, top_k, result_count, pinecone_ms |
| Hydration | `hydrate.products` | requested_ids count, hydrated count, missing_ids count (E5-S3 AC-3) |
| Generation | `generate.answer` | session_id, context_size (#products), model name, gemini_ms |
| Embedding | `embed.batch` | batch_size, dim=768, gemini_ms |
| Ingestion | `ingest.summary` | total_processed, successful, failed, failure reasons (E3-S3 AC-4) |
| Errors | `error.<type>` | error code, layer, request_id — **message only, no stack trace in user response** (trace may be logged server-side) |

---

## 4. Redaction Rules

| Item | Rule |
|------|------|
| `GOOGLE_API_KEY`, `PINECONE_API_KEY` | Never logged in any form (E1-S3 AC-4). Settings repr must mask them. |
| MySQL password | Never logged; connection logs show host/db only. |
| Full user message | Logged at DEBUG only (optional); INFO logs message length / hash to keep logs lean. |
| Embedding vectors | Never logged (768 floats) — log only dimension and count. |

A unit/inspection test asserts no source line passes a secret value into a log call (E1-S3 AC-4).

---

## 5. Log Levels

| Level | Use |
|-------|-----|
| `DEBUG` | Prompt text, raw model JSON, full filter objects (dev only). |
| `INFO` (default) | Request/response, retrieval/generation summaries, ingestion summary. |
| `WARNING` | Out-of-vocab filter dropped, ID missing in MySQL during hydration, embedding skipped for a row. |
| `ERROR` | Typed service failures (Gemini/Pinecone/MySQL) with code + request_id (server-side trace allowed; response stays clean). |

---

## 6. Correlation Flow

```
Streamlit -> POST /api/chat (session_id)
  middleware assigns request_id  -> logs http.request {request_id, session_id, path}
  orchestrator logs chat.turn / extract.filters / retrieval.query / hydrate.products / generate.answer
     all carrying {request_id, session_id}
  middleware logs http.response {request_id, status, latency_ms}
```

Searching logs by `request_id` reconstructs one turn end-to-end; by `session_id` reconstructs a whole conversation — the key diagnostic for the multi-turn risk area (R-1).
