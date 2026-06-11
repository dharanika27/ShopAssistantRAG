# Deployment Architecture — ShopAssistantRAG

Source: BRD §6.6, stories E10-S1 / E10-S2. Demo-grade, single-deployment (BRD §12). Two run paths: **dev mode** (manual processes) and **Docker mode** (`docker-compose up`).

---

## 1. Environments

| Environment | Purpose | Topology |
|-------------|---------|----------|
| **dev (local)** | Day-to-day development | `uvicorn` + `streamlit` run directly; local or containerized MySQL; live Gemini/Pinecone. |
| **demo (Docker)** | Recruiter/reviewer one-command run | `docker-compose up` → `backend`, `frontend`, `mysql` containers; Gemini + Pinecone external. |
| **prod** | Out of scope (BRD §12 — single demo deployment). | Documented as future: same compose stack behind a reverse proxy + managed MySQL. |

No staging environment (demo project). MySQL and the two app processes are local/containerized; Gemini and Pinecone are always external managed cloud services.

---

## 2. Container Topology (Docker mode)

```
                docker network: shopassistant-net
   ┌──────────────────────────────────────────────────────────┐
   │  frontend (Streamlit)  :8501  ── HTTP ──▶ backend :8000     │
   │  backend  (FastAPI/uvicorn) :8000 ── TCP ──▶ mysql :3306    │
   │  mysql    (mysql:8)  :3306   volume: mysql_data (named)      │
   └──────────────────────────────────────────────────────────┘
        backend  ── HTTPS ──▶ Google Gemini API  (external)
        backend  ── HTTPS ──▶ Pinecone API        (external)
```

Exposed to host: `frontend` 8501, `backend` 8000. `mysql` reachable only on the internal network (optionally mapped to host 3306 for dev).

---

## 3. CI/CD Pipeline (proposed, GitHub Actions)

Demo project — lightweight pipeline. `.github/workflows/ci.yml`:

| Stage | Step | Tooling |
|-------|------|---------|
| 1. Lint | `ruff check` + `ruff format --check` | ruff |
| 2. Unit tests | `pytest tests/unit -m unit` (externals mocked, E9-S1) | pytest |
| 3. Build | `docker build` backend & frontend images | docker buildx |
| 4. Integration | `docker-compose up -d mysql backend`, run `pytest tests/integration` against seeded test catalog (E9-S2) | pytest + compose |
| 5. E2E (optional) | Core-journey test (E9-S2) | pytest/Playwright |
| 6. Publish | Tag + push images to registry (manual/demo) | docker push |

Secrets in CI are injected as GitHub Actions secrets (`GOOGLE_API_KEY`, `PINECONE_API_KEY`), never committed. Integration stage may mock Gemini/Pinecone to avoid live-key dependence.

---

## 4. Infrastructure-as-Code

| Concern | Approach |
|---------|----------|
| Local/demo orchestration | `docker-compose.yml` (declarative, the single IaC artifact for the MVP). |
| DB schema provisioning | `sql/schema.sql` mounted to `/docker-entrypoint-initdb.d/` (runs on first MySQL boot) **and** idempotent `scripts/init_db.py` for dev (E2-S1, E10-S2). |
| Image build | `docker/backend.Dockerfile`, `docker/frontend.Dockerfile`. |
| Bootstrap | `init.sh` — copies `.env.example`→`.env` if absent, runs ingestion (E10-S2). |
| Future cloud | Compose translates to a single VM (Docker) or a managed-container service; out of MVP scope. |

---

## 5. Secrets Management

- All secrets via `.env` (gitignored) injected as container `environment` / `env_file` (BRD §6.5, E10-S1 AC-5). **Never baked into images.**
- `.env.example` lists every key with placeholder values (E1-S2 AC-2).
- Required keys: `GOOGLE_API_KEY`, `PINECONE_API_KEY`, `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`. Defaults (non-secret): `PINECONE_INDEX_NAME`, `EMBEDDING_MODEL=text-embedding-004`, `GENERATION_MODEL=gemini-1.5-flash`, `EMBEDDING_DIM=768`, `LOG_LEVEL=INFO`, `BACKEND_URL`.
- Logs are secret-free (E1-S3 AC-4).

---

## 6. Startup / Bootstrap Sequence (Docker mode)

1. `mysql` starts; on first boot runs `sql/schema.sql` from init dir → `products` table created (E10-S2 AC-1).
2. `backend` `entrypoint-backend.sh` waits for MySQL TCP readiness, runs idempotent schema init (safety), then `uvicorn backend.api.main:app`.
3. `frontend` waits for backend health (`GET /api/health`), then `streamlit run frontend/app.py`.
4. Operator runs ingestion once: `docker compose exec backend python scripts/ingest.py` (or via `init.sh`) → CSV → MySQL → Pinecone.
5. App reachable at `http://localhost:8501` (E10-S2 AC-4).

---

## 7. Data Persistence & Rollback

- **Persistence:** MySQL data on named volume `mysql_data` — survives container restarts (E10-S1 AC-4). Pinecone index persists in the managed cloud.
- **Rollback (app):** `docker compose down && docker compose up -d` on a prior image tag; stateless app containers make rollback a re-tag + redeploy.
- **Rollback (data):** re-run `scripts/ingest.py` — idempotent upsert restores MySQL + Pinecone to the CSV state (E3-S3 AC-5). To wipe: `docker compose down -v` drops the volume, next boot re-inits schema.
- **Disaster recovery:** CSV (`data/products.csv`) is the canonical seed; the entire data plane is reproducible from it via ingestion.

---

## 8. Health & Observability

- `GET /api/health` is the readiness/liveness probe (compose `healthcheck`, E7-S1).
- Structured logs to stdout (12-factor) collected by `docker compose logs` (E1-S3, BRD NFR-4).
- No metrics/APM in MVP (low-concurrency demo).
