# Dependency Graph — ShopAssistantRAG

Decomposition of the approved BRD (v1.0) into parallel-executable story groups, ordered along the foundation → deployment pipeline.

**Pipeline ordering:** Foundation → Database → Embeddings → Pinecone → Retrieval → Chat Service → API → Frontend → Testing → Deployment

**Validation:** No circular dependencies. Each `depends_on` edge points only to a story in an earlier group. Stories within a group are independently executable in parallel.

---

## Group A — Foundation (no dependencies)

Foundation layer: shared types, enums, configuration, and the relational schema. These can all start in parallel on day one.

| Story ID | Title | Layer | Dependencies |
|----------|-------|-------|--------------|
| E1-S1 | Define product domain types and enums | Types | — |
| E1-S2 | Centralized configuration & secret loading | Config | — |
| E1-S3 | Structured logging setup | Config | — |
| E2-S1 | MySQL product schema & migrations | Repository | — |

---

## Group B — Database & Embedding Foundations (depend only on Group A)

| Story ID | Title | Layer | Dependencies |
|----------|-------|-------|--------------|
| E2-S2 | Product repository (CRUD + bulk hydrate by IDs) | Repository | E1-S1, E1-S2, E2-S1 |
| E2-S3 | CSV loader with row validation | Repository | E1-S1, E1-S2, E2-S1 |
| E3-S1 | Embedding text builder | Service | E1-S1 |
| E3-S2 | Gemini embedding client | Service | E1-S2, E1-S3 |
| E4-S1 | Pinecone index provisioning & client | Repository | E1-S2, E1-S3 |

---

## Group C — Pinecone Upsert & Ingestion (depend on Group B)

| Story ID | Title | Layer | Dependencies |
|----------|-------|-------|--------------|
| E4-S2 | Pinecone upsert with metadata | Repository | E3-S2, E4-S1 |
| E3-S3 | Ingestion pipeline orchestration & summary report | Service | E2-S2, E2-S3, E3-S1, E3-S2, E4-S2 |

---

## Group D — Retrieval & Filter Extraction (depend on Group C)

| Story ID | Title | Layer | Dependencies |
|----------|-------|-------|--------------|
| E5-S1 | Gemini filter extraction with enum normalization | Service | E1-S1, E3-S2 |
| E5-S2 | Hybrid retriever (metadata filter + semantic search) | Service | E4-S2, E5-S1 |
| E5-S3 | MySQL hydration of retrieved product IDs | Service | E2-S2, E5-S2 |

---

## Group E — Chat Service & Session Memory (depend on Group D)

| Story ID | Title | Layer | Dependencies |
|----------|-------|-------|--------------|
| E6-S1 | Session-scoped conversational memory & filter state | Service | E1-S1 |
| E6-S2 | Grounded RAG answer generation (Gemini) | Service | E5-S3 |
| E6-S3 | Multi-turn refinement, reset & no-match handling | Service | E5-S1, E5-S2, E5-S3, E6-S1, E6-S2 |

---

## Group F — API Layer (depend on Group E)

| Story ID | Title | Layer | Dependencies |
|----------|-------|-------|--------------|
| E7-S1 | FastAPI app, health check & error middleware | API | E1-S2, E1-S3 |
| E7-S2 | Chat endpoint (POST /api/chat) | API | E6-S3, E7-S1 |
| E7-S3 | Catalog & filter-options endpoints | API | E2-S2, E7-S1 |

---

## Group G — Frontend (depend on Group F)

| Story ID | Title | Layer | Dependencies |
|----------|-------|-------|--------------|
| E8-S1 | Product catalog grid with cards | UI | E7-S3 |
| E8-S2 | Traditional filter controls | UI | E7-S3 |
| E8-S3 | Conversational chat interface with session | UI | E7-S2 |

---

## Group H — Testing & Deployment (depend on Group G)

| Story ID | Title | Layer | Dependencies |
|----------|-------|-------|--------------|
| E9-S1 | Critical-path unit tests (mocked external services) | Service | E3-S3, E5-S2, E5-S3, E6-S3 |
| E9-S2 | Integration & E2E tests for core journey | API | E7-S2, E7-S3, E8-S3 |
| E10-S1 | Dockerfiles & docker-compose stack | Config | E7-S1, E8-S3 |
| E10-S2 | Environment config, init script & deployment docs | Config | E10-S1 |

---

## Sprint Breakdown

Stories are scheduled by group so each sprint delivers a runnable vertical increment.

| Sprint | Theme | Groups | Stories |
|--------|-------|--------|---------|
| Sprint 1 | Foundation & Data | A, B | E1-S1, E1-S2, E1-S3, E2-S1, E2-S2, E2-S3, E3-S1, E3-S2, E4-S1 |
| Sprint 2 | Embeddings → Pinecone → Retrieval | C, D | E4-S2, E3-S3, E5-S1, E5-S2, E5-S3 |
| Sprint 3 | Chat Service & API | E, F | E6-S1, E6-S2, E6-S3, E7-S1, E7-S2, E7-S3 |
| Sprint 4 | Frontend, Testing & Deployment | G, H | E8-S1, E8-S2, E8-S3, E9-S1, E9-S2, E10-S1, E10-S2 |

---

## Story Clusters

Cross-cutting clusters that share design concerns and should be reviewed together.

| Cluster | Stories | Shared Concern |
|---------|---------|----------------|
| Ingestion Pipeline | E2-S3, E3-S1, E3-S2, E4-S2, E3-S3 | CSV → MySQL → Embeddings → Pinecone data flow |
| Hybrid Retrieval | E5-S1, E5-S2, E5-S3 | Filter extraction + metadata pre-filter + semantic search + hydration |
| Conversational Core | E6-S1, E6-S2, E6-S3 | Session memory, grounded generation, multi-turn refinement |
| Service Resilience | E1-S3, E7-S1, E6-S3 | Logging + graceful failure messages for Gemini/Pinecone/MySQL |
| Catalog UX | E7-S3, E8-S1, E8-S2 | Grid rendering + traditional filters |
| Quality Gate | E9-S1, E9-S2 | Unit + integration coverage of critical path |

---

## Priorities

| Priority | Definition | Stories |
|----------|------------|---------|
| P0 (Critical) | Core RAG journey; MVP blocked without these | E1-S1, E1-S2, E2-S1, E2-S2, E3-S1, E3-S2, E4-S1, E4-S2, E3-S3, E5-S1, E5-S2, E5-S3, E6-S2, E6-S3, E7-S1, E7-S2, E8-S3 |
| P1 (High) | Required for full Definition of Done | E1-S3, E2-S3, E6-S1, E7-S3, E8-S1, E8-S2, E9-S1, E9-S2, E10-S1 |
| P2 (Medium) | Supports demo/deploy polish | E10-S2 |
