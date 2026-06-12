# System Design — ShopAssistantRAG

> Conversational AI shopping assistant. Hybrid RAG over a 500–1000 product catalog. Stack: Streamlit · FastAPI · MySQL · Pinecone · Google Gemini · LangChain. Source: `docs/BRD.md` v1.0 (Approved).

---

## 1. System Architecture

### 1.1 Architectural Style
Layered, modular monolith with two runnable processes (FastAPI backend, Streamlit frontend) plus one standalone batch process (ingestion CLI). External managed services: Google Gemini (embeddings + generation) and Pinecone (vector store). MySQL is the **system of record**; Pinecone is a **derived retrieval index**.

This satisfies BRD NFR-1 (modular architecture) and NFR-6 (scalable but not over-engineered) for a low-concurrency demo workload.

### 1.2 Layer Topology

```
┌──────────────────────────────────────────────────────────────────────┐
│  FRONTEND (Streamlit)  — frontend/                                     │
│  Catalog grid · Traditional filters · Chat interface (session_id)      │
└───────────────┬────────────────────────────────────────────────────────┘
                │ HTTP (JSON, CORS)
┌───────────────▼────────────────────────────────────────────────────────┐
│  API LAYER (FastAPI)  — backend/api/                                    │
│  /api/health · /api/chat · /api/products · /api/filters                 │
│  Error middleware (typed error → BRD user message) · request logging    │
└───────────────┬────────────────────────────────────────────────────────┘
                │ in-process calls
┌───────────────▼────────────────────────────────────────────────────────┐
│  SERVICE LAYER  — backend/services/                                     │
│  ChatOrchestrator · QueryStateManager · FilterExtractor                 │
│  HybridRetriever · Hydrator · AnswerGenerator · IngestionPipeline       │
│  (LangChain wires retrieval → context → generation)                     │
└──────┬───────────────────────┬──────────────────────┬───────────────────┘
       │                       │                      │
┌──────▼──────┐        ┌───────▼────────┐     ┌───────▼─────────┐
│ REPOSITORY  │        │  EMBEDDING     │     │  GENERATION     │
│ MySQL repo  │        │  Gemini embed  │     │  Gemini flash   │
│ Pinecone    │        │  text-embed-004│     │  gemini-1.5-    │
│ repo/client │        │  (768-dim)     │     │  flash          │
└──────┬──────┘        └───────┬────────┘     └───────┬─────────┘
       │                       │                      │
┌──────▼──────┐        ┌───────▼──────────────────────▼─────────┐
│  MySQL 8    │        │   Google Gemini API   ·   Pinecone API  │
│ (container) │        │        (external cloud services)        │
└─────────────┘        └─────────────────────────────────────────┘
```

### 1.3 Components & Responsibilities

| Component | Module | Responsibility |
|-----------|--------|----------------|
| Streamlit app | `frontend/app.py` | Tabs: Catalog grid, Filters, Chat. Holds `session_id` in `st.session_state`. |
| FastAPI app | `backend/api/main.py` | App bootstrap, CORS, middleware, router registration. |
| Chat router | `backend/api/routes/chat.py` | `POST /api/chat` → ChatOrchestrator. |
| Catalog router | `backend/api/routes/catalog.py` | `GET /api/products`, `GET /api/filters`. |
| ChatOrchestrator | `backend/services/chat_orchestrator.py` | End-to-end turn: extract → state merge/reset → retrieve → hydrate → generate. |
| QueryStateManager | `backend/services/query_state.py` | In-memory accumulating `QueryFilters` + bounded turn history per session. |
| FilterExtractor | `backend/services/filter_extractor.py` | Gemini structured JSON → normalized `QueryFilters`. |
| HybridRetriever | `backend/services/hybrid_retriever.py` | Pinecone metadata pre-filter + semantic search → top-5 IDs. |
| Hydrator | `backend/services/hydrator.py` | Pinecone IDs → full `Product` records from MySQL, rank-preserving. |
| AnswerGenerator | `backend/services/answer_generator.py` | Grounded LLM NL reply (Groq `llama-3.3-70b-versatile` default, `LLM_PROVIDER`-selectable) from product context. |
| IngestionPipeline | `backend/services/ingestion.py` | CSV → validate → MySQL upsert → embed → Pinecone upsert + summary. |
| ProductRepository | `backend/repositories/product_repository.py` | MySQL CRUD, bulk hydrate, list/filter. |
| PineconeClient | `backend/repositories/pinecone_client.py` | Index provisioning, upsert, query. |
| GeminiEmbeddingClient | `backend/services/embedding_client.py` | `embed_text` / `embed_batch` (768-dim). |
| Settings | `backend/core/config.py` | Typed env/secret loader. |
| Logger | `backend/core/logging.py` | Structured logger with session/request correlation. |
| Domain types | `backend/domain/models.py` | `Product`, `QueryFilters`, `Category`, `Gender`. |

### 1.4 Key Design Decisions & Rationale

| # | Decision | Rationale |
|---|----------|-----------|
| D-1 | MySQL = source of truth; Pinecone = derived index storing IDs + retrieval metadata only | BRD §4.3. Avoids dual source-of-truth; display fields (description, image, stock) hydrated from MySQL. |
| D-2 | In-memory session store (process-local dict) for Query State Manager | BRD §6.3/§8 — active session only, no cross-session persistence; low concurrency (NFR-6). Redis = over-engineering. |
| D-3 | Single Pinecone query with `filter=` metadata pre-filter (not two-stage) | BRD §6.4 hybrid strategy; one network round-trip → helps <5s target. |
| D-4 | Rebuild fresh retrieval each turn from accumulated `QueryFilters` (not re-filter prior result list) | BRD §8.1 / risk R-1. |
| D-5 | Enum normalization layer between Gemini and retrieval | BRD risk R-2 (Crimson→Red, Trainers→Shoes); drops out-of-vocab values. |
| D-6 | Typed errors at repository/service boundaries mapped to BRD user messages in API middleware | BRD NFR-3 / §9.1 — never leak stack traces. |
| D-7 | Ingestion is a standalone CLI, not an API | BRD §4.3 — no ingestion API; embedding failures non-fatal. |
| D-8 | LLM generation via `LLM_PROVIDER` (Groq `llama-3.3-70b-versatile` default, Gemini legacy) | BRD §6.2 — low latency/cost, <5s target. |

### 1.5 Data Flows

**Ingestion (batch):** `CSV → CSVLoader (validate) → ProductRepository.upsert_product → build_embedding_text → GeminiEmbeddingClient.embed_batch → PineconeClient.upsert_products(metadata) → summary report`.

**Retrieval/Chat (request):** `POST /api/chat → ChatOrchestrator → FilterExtractor (Gemini JSON + normalize) → QueryStateManager.merge_or_reset → HybridRetriever.retrieve (Pinecone filter + vector search → ≤5 IDs) → Hydrator.hydrate (MySQL get_products_by_ids, rank-preserving) → AnswerGenerator.generate (grounded Gemini) → { reply, products[≤5] }`.

**Catalog (request):** `GET /api/products?filters → ProductRepository.list_products → product list`. `GET /api/filters → distinct brand/category/gender/color`.

### 1.6 Cross-Cutting Concerns
- **Config/secrets:** `backend/core/config.py`, `.env` only (BRD §6.5).
- **Logging:** structured, session/request correlation, secret-free (BRD NFR-4).
- **Error handling:** typed errors → user messages (BRD §9.1).
- **Testing:** critical path unit-tested with mocks; integration/E2E for core journey (BRD NFR-5, DoD 12–14).

### 1.7 Non-Goals
No cart/checkout/payment/orders, auth, reviews, pagination, real-time inventory, multi-language, admin UI, ingestion API (BRD §3.3).
