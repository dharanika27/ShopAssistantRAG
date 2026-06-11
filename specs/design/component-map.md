# Component Map — ShopAssistantRAG

Maps every story ID to the implementation files created or modified. Routing instructions for the build phase.

| Story | Title | Files (create unless noted) |
|-------|-------|------------------------------|
| **E1-S1** | Domain types & enums | `backend/domain/models.py`, `backend/domain/enums.py` |
| **E1-S2** | Config & secrets | `backend/core/config.py`, `.env.example`, `.gitignore` (mod) |
| **E1-S3** | Structured logging | `backend/core/logging.py` |
| **E2-S1** | MySQL schema & migrations | `sql/schema.sql`, `scripts/init_db.py`, `backend/repositories/db.py` |
| **E2-S2** | Product repository | `backend/repositories/product_repository.py`, `backend/core/errors.py` (mod) |
| **E2-S3** | CSV loader + validation | `backend/services/csv_loader.py` |
| **E3-S1** | Embedding text builder | `backend/services/embedding_text.py` |
| **E3-S2** | Gemini embedding client | `backend/services/embedding_client.py`, `backend/core/errors.py` (mod) |
| **E3-S3** | Ingestion orchestration | `backend/services/ingestion.py`, `scripts/ingest.py` |
| **E4-S1** | Pinecone index & client | `backend/repositories/pinecone_client.py`, `backend/core/errors.py` (mod) |
| **E4-S2** | Pinecone upsert + metadata | `backend/repositories/pinecone_client.py` (mod) |
| **E5-S1** | Filter extraction + normalize | `backend/services/filter_extractor.py`, `backend/prompts/filter_extraction.txt` |
| **E5-S2** | Hybrid retriever | `backend/services/hybrid_retriever.py` |
| **E5-S3** | MySQL hydration | `backend/services/hydrator.py` |
| **E6-S1** | Session memory & filter state | `backend/services/query_state.py` |
| **E6-S2** | Grounded RAG generation | `backend/services/answer_generator.py`, `backend/prompts/answer_generation.txt` |
| **E6-S3** | Multi-turn / reset / no-match | `backend/services/chat_orchestrator.py` |
| **E7-S1** | FastAPI app + middleware | `backend/api/main.py`, `backend/api/middleware.py`, `backend/api/routes/health.py`, `backend/api/dependencies.py`, `backend/core/errors.py` (mod) |
| **E7-S2** | Chat endpoint | `backend/api/routes/chat.py`, `backend/api/schemas.py` (mod) |
| **E7-S3** | Catalog & filter endpoints | `backend/api/routes/catalog.py`, `backend/api/schemas.py` (mod) |
| **E8-S1** | Catalog grid | `frontend/app.py` (mod), `frontend/components/catalog_grid.py`, `frontend/components/product_card.py`, `frontend/api_client.py` (mod) |
| **E8-S2** | Traditional filters | `frontend/components/filters.py`, `frontend/api_client.py` (mod) |
| **E8-S3** | Chat interface | `frontend/components/chat.py`, `frontend/app.py` (mod), `frontend/api_client.py` (mod) |
| **E9-S1** | Critical-path unit tests | `tests/conftest.py`, `tests/unit/test_filter_extractor.py`, `tests/unit/test_hybrid_retriever.py`, `tests/unit/test_hydrator.py`, `tests/unit/test_query_state.py`, `tests/unit/test_chat_orchestrator.py`, `pytest.ini` |
| **E9-S2** | Integration & E2E tests | `tests/integration/test_chat_endpoint.py`, `tests/integration/test_catalog_endpoints.py`, `tests/e2e/test_core_journey.py` |
| **E10-S1** | Dockerfiles & compose | `docker/backend.Dockerfile`, `docker/frontend.Dockerfile`, `docker/entrypoint-backend.sh`, `docker-compose.yml`, `requirements.txt`, `frontend-requirements.txt` |
| **E10-S2** | Env config, init, docs | `init.sh`, `README.md`, `.env.example` (mod), `docker-compose.yml` (mod for schema init mount) |

## Shared / foundational files touched by multiple stories
| File | Stories |
|------|---------|
| `backend/core/errors.py` | E2-S2, E3-S2, E4-S1, E7-S1 |
| `backend/api/schemas.py` | E7-S2, E7-S3 |
| `frontend/app.py` | E8-S1, E8-S2, E8-S3 |
| `frontend/api_client.py` | E8-S1, E8-S2, E8-S3 |
| `docker-compose.yml` | E10-S1, E10-S2 |
| `.env.example` | E1-S2, E10-S2 |
