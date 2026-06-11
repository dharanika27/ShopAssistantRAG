# ShopAssistantRAG

A conversational shopping assistant. Browse a product catalog, filter it with
traditional controls, or chat with a Retrieval-Augmented-Generation assistant
that understands natural-language queries ("red Nike shoes under 3000"),
refines results across turns, and grounds every answer in the real catalog.

**Stack:** FastAPI backend, Streamlit frontend, MySQL (product catalog),
Pinecone (vector search), **Google Gemini** (embeddings), and **Groq**
(chat generation + filter extraction). Gemini, Groq, and Pinecone are external
cloud services; MySQL runs locally or in a container.

| Concern | Technology |
|---------|------------|
| Product catalog storage | MySQL |
| Vector storage / semantic search | Pinecone (768-dim, cosine) |
| Text embeddings | Google Gemini (`gemini-embedding-2`, 768-dim) |
| Chat answer generation + filter extraction | Groq (`llama-3.3-70b-versatile`) |
| Backend API | FastAPI |
| Frontend UI | Streamlit |

> **Note on the LLM:** embeddings run on **Gemini**; chat generation and
> natural-language filter extraction run on **Groq**. The generation provider is
> selectable via `LLM_PROVIDER` (`groq` default, `gemini` legacy fallback) — see
> Configuration below. Embeddings always use Gemini regardless of that setting.

---

## Architecture — request flow

A single `POST /api/chat` turn runs the full RAG pipeline:

```
User Query
  → Groq Filter Extraction      (structured brand/color/category/gender/price JSON)
  → Gemini Embedding Generation (query → 768-dim vector)
  → Pinecone Retrieval          (metadata pre-filter + semantic vector search)
  → MySQL Hydration             (fetch full product rows by returned IDs)
  → Groq Answer Generation      (grounded NL reply over the hydrated products)
```

The catalog/browse path is simpler: `GET /api/products` and `GET /api/filters`
read directly from MySQL (no LLM/vector calls). Ingestion is the write path:
`CSV → MySQL → Gemini embeddings → Pinecone upsert`.

---

## Prerequisites

- Python 3.11+
- A running MySQL 8 instance (or Docker, see below)
- A **Google Gemini** API key (embeddings), a **Groq** API key (chat
  generation), and a **Pinecone** API key (vector index)
- A catalog CSV at `data/products.csv` (used by the ingestion pipeline)

---

## Configuration

All configuration is read from a `.env` file (never committed). Start from the
template:

```bash
cp .env.example .env
```

Then edit `.env` and set the required values:

| Variable | Required | Purpose |
|----------|----------|---------|
| `GOOGLE_API_KEY` | ✅ | Gemini **embeddings** ([get a key](https://aistudio.google.com/app/apikey)) |
| `GROQ_API_KEY` | ✅ | Groq **chat generation + filter extraction** ([get a key](https://console.groq.com/keys)) |
| `PINECONE_API_KEY` | ✅ | Pinecone vector index ([get a key](https://app.pinecone.io)) |
| `MYSQL_HOST` / `MYSQL_PORT` | ✅ | MySQL connection (`localhost` / `3306` for dev) |
| `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DATABASE` | ✅ | MySQL credentials |
| `LLM_PROVIDER` | — | Generation provider: `groq` (default) or `gemini` (legacy) |
| `GROQ_MODEL` | — | Groq chat model (default `llama-3.3-70b-versatile`) |
| `GENERATION_MODEL` | — | Gemini generation model, used **only** when `LLM_PROVIDER=gemini` |
| `EMBEDDING_MODEL` | — | Gemini embedding model (default `gemini-embedding-2`, 768-dim) |
| `EMBEDDING_DIM` | — | Embedding/index dimension (default `768`; must match the Pinecone index) |
| `PINECONE_INDEX_NAME` | — | Vector index name (default `shop-products`) |
| `ALLOWED_ORIGINS` | — | CORS origins (default `http://localhost:8501`) |
| `LOG_LEVEL` | — | Log verbosity (default `INFO`) |

> **Required keys for a fresh clone:** `GOOGLE_API_KEY`, `GROQ_API_KEY`,
> `PINECONE_API_KEY`, and the five `MYSQL_*` values. With the defaults,
> generation uses Groq — so `GROQ_API_KEY` must be set or the backend will fail
> fast at startup with a clear `ConfigError`.

---

## Run path 1 — Dev mode (local processes)

Use this for development with a local MySQL and live reload.

```bash
# 1. Install dependencies
pip install -r requirements.txt
pip install -r frontend-requirements.txt

# 2. Bootstrap: copies .env.example -> .env (first run), then on a second run
#    applies the schema and ingests the catalog. Edit .env between the two runs.
./init.sh        # first run: creates .env, then stops
#   ... edit .env with real keys + MySQL creds ...
./init.sh        # second run: applies schema and ingests data/products.csv

# 3. Start the backend (terminal 1)
uvicorn backend.api.main:create_app --factory --reload --port 8000

# 4. Start the frontend (terminal 2)
streamlit run frontend/app.py
```

Open the Streamlit UI at <http://localhost:8501>. It calls the backend at
`http://localhost:8000` by default (override with the `BACKEND_URL` env var).

You can also run the schema and ingestion steps directly instead of `init.sh`:

```bash
python -m scripts.init_db          # apply sql/schema.sql (idempotent)
python -m scripts.ingest           # CSV -> MySQL -> embeddings -> Pinecone
python -m scripts.ingest path/to/other.csv   # optional: custom CSV path
```

---

## Run path 2 — Docker mode (full stack)

Runs the backend, frontend, and MySQL as containers on a shared network. Gemini,
Groq, and Pinecone are still reached as external services.

```bash
cp .env.example .env   # then edit .env with real keys + MySQL creds
docker compose up --build
```

This brings up:

- **mysql** — schema initialized automatically on first boot (the backend
  entrypoint applies `sql/schema.sql`, and the compose `initdb` mount applies it
  on an empty volume). Data persists in the named `mysql_data` volume across
  restarts.
- **backend** — FastAPI at <http://localhost:8000>
- **frontend** — Streamlit at <http://localhost:8501> (reaches the backend at
  `http://backend:8000` over the shared network)

After the stack is up, ingest the catalog into MySQL and Pinecone:

```bash
docker compose exec backend python -m scripts.ingest
```

Open <http://localhost:8501> in your browser.

Secrets are injected from the host `.env` at runtime and are never baked into
the images.

---

## Testing

The full suite mocks every external service (Gemini, Groq, Pinecone, MySQL), so
it runs offline:

```bash
pytest                 # all tests
pytest -m unit         # critical-path unit tests (E9-S1)
pytest -m integration  # API integration tests (E9-S2)
pytest -m e2e          # core-journey end-to-end test (E9-S2)
```

Lint and type-check:

```bash
ruff check .
mypy backend
```

---

## Project layout

```
backend/        FastAPI app, domain models, services, repositories
frontend/       Streamlit UI and the typed HTTP client to the backend
scripts/        init_db.py (schema) and ingest.py (ingestion pipeline)
sql/            schema.sql (MySQL product schema)
docker/         backend / frontend Dockerfiles and the backend entrypoint
tests/          unit, integration, and e2e suites
specs/          BRD, stories, design docs, dependency graph
```
