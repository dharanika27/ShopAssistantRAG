# Folder Structure — ShopAssistantRAG

Proposed implementation directory tree. One-line annotation per directory. Aligns with BRD §6.7 modular separation (Frontend · API · Services · Retrieval · Database · Embedding).

```
ShopAssistantRAG/
├── backend/                         # FastAPI backend application (one runnable process)
│   ├── __init__.py
│   ├── core/                        # Cross-cutting infrastructure: config, logging, errors
│   │   ├── __init__.py
│   │   ├── config.py                # Typed Settings — loads .env secrets & defaults (E1-S2)
│   │   ├── logging.py               # get_logger() structured logger w/ correlation (E1-S3)
│   │   └── errors.py                # Typed error hierarchy + BRD user-message mapping
│   ├── domain/                      # Pure domain model — no I/O, imported everywhere
│   │   ├── __init__.py
│   │   ├── models.py                # Product, QueryFilters (E1-S1)
│   │   └── enums.py                 # Category, Gender enums (E1-S1)
│   ├── repositories/                # Data-access layer: MySQL + Pinecone
│   │   ├── __init__.py
│   │   ├── db.py                    # MySQL connection/pool + schema init runner (E2-S1)
│   │   ├── product_repository.py    # CRUD, list/filter, bulk hydrate by IDs (E2-S2)
│   │   └── pinecone_client.py       # Index provisioning, upsert, query (E4-S1, E4-S2)
│   ├── services/                    # Business logic / RAG pipeline orchestration
│   │   ├── __init__.py
│   │   ├── embedding_text.py        # build_embedding_text(product) (E3-S1)
│   │   ├── embedding_client.py      # Gemini text-embedding-004 client (E3-S2)
│   │   ├── csv_loader.py            # CSV parse + row validation (E2-S3)
│   │   ├── ingestion.py             # Ingestion orchestration + summary (E3-S3)
│   │   ├── filter_extractor.py      # Gemini JSON → normalized QueryFilters (E5-S1)
│   │   ├── hybrid_retriever.py      # Metadata pre-filter + semantic search (E5-S2)
│   │   ├── hydrator.py              # Pinecone IDs → MySQL Product records (E5-S3)
│   │   ├── query_state.py           # QueryStateManager: session filters + history (E6-S1)
│   │   ├── answer_generator.py      # Grounded gemini-1.5-flash generation (E6-S2)
│   │   └── chat_orchestrator.py     # End-to-end chat turn + reset/no-match rules (E6-S3)
│   ├── api/                         # HTTP boundary: FastAPI app, routes, schemas
│   │   ├── __init__.py
│   │   ├── main.py                  # App factory, CORS, middleware, router wiring (E7-S1)
│   │   ├── middleware.py            # Request logging + global exception → JSON (E7-S1)
│   │   ├── dependencies.py          # DI providers (repos, services, settings)
│   │   ├── schemas.py               # Pydantic request/response DTOs for endpoints
│   │   └── routes/                  # One module per resource group
│   │       ├── __init__.py
│   │       ├── health.py            # GET /api/health (E7-S1)
│   │       ├── chat.py              # POST /api/chat (E7-S2)
│   │       └── catalog.py           # GET /api/products, GET /api/filters (E7-S3)
│   └── prompts/                     # Prompt templates for Gemini calls
│       ├── filter_extraction.txt    # Structured-JSON filter-extraction prompt (E5-S1)
│       └── answer_generation.txt    # Grounded RAG answer prompt (E6-S2)
├── frontend/                        # Streamlit frontend application (one runnable process)
│   ├── __init__.py
│   ├── app.py                       # Streamlit entrypoint; tabs + session_id (E8-S1/2/3)
│   ├── api_client.py                # Thin HTTP client to FastAPI backend
│   └── components/                  # Reusable UI render helpers
│       ├── __init__.py
│       ├── product_card.py          # Single product card renderer (E8-S1)
│       ├── catalog_grid.py          # Grid of cards + fetch (E8-S1)
│       ├── filters.py               # Brand/category/gender/color/price controls (E8-S2)
│       └── chat.py                  # Chat transcript + input + inline cards (E8-S3)
├── scripts/                         # Operational / bootstrap scripts
│   ├── ingest.py                    # CLI entrypoint → services/ingestion.py (E3-S3)
│   └── init_db.py                   # Apply MySQL schema (E2-S1, E10-S2)
├── sql/                             # SQL DDL — mounted into MySQL container init
│   └── schema.sql                   # products table DDL, idempotent (E2-S1)
├── data/                            # Seed data
│   └── products.csv                 # Product catalog CSV (500–1000 rows)
├── tests/                           # Test suite
│   ├── __init__.py
│   ├── conftest.py                  # Fixtures: mock Gemini/Pinecone/MySQL, seed catalog
│   ├── unit/                        # Critical-path unit tests, externals mocked (E9-S1)
│   │   ├── test_filter_extractor.py
│   │   ├── test_hybrid_retriever.py
│   │   ├── test_hydrator.py
│   │   ├── test_query_state.py
│   │   └── test_chat_orchestrator.py
│   ├── integration/                 # API integration tests vs seeded catalog (E9-S2)
│   │   ├── test_chat_endpoint.py
│   │   └── test_catalog_endpoints.py
│   └── e2e/                         # Core-journey end-to-end test (E9-S2)
│       └── test_core_journey.py
├── docker/                          # Container build context
│   ├── backend.Dockerfile           # FastAPI image (E10-S1)
│   ├── frontend.Dockerfile          # Streamlit image (E10-S1)
│   └── entrypoint-backend.sh        # Waits for MySQL, runs schema init, starts uvicorn
├── docs/                            # Project documentation
│   └── BRD.md                       # Business Requirements Document (existing)
├── specs/                           # SDLC pipeline artifacts (existing)
│   ├── features.json
│   ├── stories/
│   └── design/                      # THIS phase's outputs
├── docker-compose.yml               # backend + frontend + mysql stack (E10-S1)
├── .env.example                     # All required keys w/ placeholder values (E1-S2)
├── .env                             # Real secrets — gitignored (E1-S2)
├── .gitignore                       # Ignores .env, __pycache__, etc.
├── init.sh                          # Bootstrap: copy .env, run ingestion (E10-S2)
├── requirements.txt                 # Python deps (backend + ingestion)
├── frontend-requirements.txt        # Streamlit + httpx deps (optional split)
├── pytest.ini                       # Pytest config (markers: unit/integration/e2e)
└── README.md                        # Dev-mode + Docker-mode run instructions (E10-S2)
```

## Import direction (one-way, enforced by `architecture` rules)

```
domain  ←  core  ←  repositories  ←  services  ←  api  ←  frontend
```

- `domain` imports nothing from the project (pure types).
- `core` may import `domain`.
- `repositories` may import `core`, `domain`.
- `services` may import `repositories`, `core`, `domain`.
- `api` may import `services`, `core`, `domain` (not repositories directly).
- `frontend` talks to `api` only over HTTP — no Python imports of backend.
- `scripts/` and `tests/` may import anything.
