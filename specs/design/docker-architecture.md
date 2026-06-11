# Docker Architecture — ShopAssistantRAG

Containerization and `docker-compose` deployment. Complements `deployment.md`. Source: BRD §6.6, stories E10-S1, E10-S2.

---

## 1. Services

| Service | Image base | Port (host:container) | Depends on | Purpose |
|---------|-----------|------------------------|------------|---------|
| `mysql` | `mysql:8` | `3306:3306` (optional host map) | — | System of record. Named volume + schema init. |
| `backend` | `python:3.11-slim` (FastAPI/uvicorn) | `8000:8000` | `mysql` (healthy) | API + services + retrieval. |
| `frontend` | `python:3.11-slim` (Streamlit) | `8501:8501` | `backend` (healthy) | Streamlit UI. |

Gemini and Pinecone are **external cloud services** — never containerized (BRD §6.6, E10-S1).

```
        host
   :8501 ─► frontend (Streamlit) ──HTTP──► backend :8000
                                   backend ──TCP──► mysql :3306
                                   backend ──HTTPS─► Gemini API   (external)
                                   backend ──HTTPS─► Pinecone API (external)
   network: shopassistant-net   ·   volume: mysql_data
```

---

## 2. docker-compose.yml (shape — E10-S1)

```yaml
services:
  mysql:
    image: mysql:8
    environment:
      MYSQL_DATABASE: ${MYSQL_DATABASE}
      MYSQL_USER: ${MYSQL_USER}
      MYSQL_PASSWORD: ${MYSQL_PASSWORD}
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD}
    volumes:
      - mysql_data:/var/lib/mysql                       # persistence (AC-4)
      - ./sql/schema.sql:/docker-entrypoint-initdb.d/schema.sql:ro   # first-boot schema (E10-S2 AC-1)
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost", "-p${MYSQL_PASSWORD}"]
      interval: 10s
      timeout: 5s
      retries: 10
    networks: [shopassistant-net]

  backend:
    build:
      context: .
      dockerfile: docker/backend.Dockerfile
    env_file: .env                                       # secrets injected, never baked in (AC-5)
    environment:
      MYSQL_HOST: mysql                                  # service name on the network
    depends_on:
      mysql:
        condition: service_healthy
    ports: ["8000:8000"]
    entrypoint: ["/app/docker/entrypoint-backend.sh"]    # wait-for-mysql + idempotent schema init + uvicorn
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/health').status==200 else 1)"]
      interval: 10s
      timeout: 5s
      retries: 10
    networks: [shopassistant-net]

  frontend:
    build:
      context: .
      dockerfile: docker/frontend.Dockerfile
    environment:
      BACKEND_URL: http://backend:8000                   # internal DNS
    depends_on:
      backend:
        condition: service_healthy
    ports: ["8501:8501"]
    networks: [shopassistant-net]

volumes:
  mysql_data:
networks:
  shopassistant-net:
```

---

## 3. Dockerfiles

### `docker/backend.Dockerfile` (E10-S1 AC-1)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends default-mysql-client && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./backend/
COPY sql/ ./sql/
COPY scripts/ ./scripts/
COPY docker/entrypoint-backend.sh ./docker/entrypoint-backend.sh
RUN chmod +x ./docker/entrypoint-backend.sh
EXPOSE 8000
ENTRYPOINT ["/app/docker/entrypoint-backend.sh"]
CMD ["uvicorn", "backend.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### `docker/frontend.Dockerfile`

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY frontend-requirements.txt .
RUN pip install --no-cache-dir -r frontend-requirements.txt
COPY frontend/ ./frontend/
EXPOSE 8501
CMD ["streamlit", "run", "frontend/app.py", "--server.address=0.0.0.0", "--server.port=8501"]
```

### `docker/entrypoint-backend.sh`

```sh
#!/bin/sh
set -e
# Wait for MySQL TCP readiness (belt-and-braces alongside compose healthcheck)
until mysqladmin ping -h "$MYSQL_HOST" --silent; do
  echo "waiting for mysql..."; sleep 2
done
# Idempotent schema init (safety; first-boot init also mounts schema.sql)
python scripts/init_db.py || true
exec "$@"
```

---

## 4. Build & Image Hygiene

| Concern | Approach |
|---------|----------|
| Layer caching | Copy `requirements.txt` and `pip install` **before** copying source so dependency layers cache. |
| Image size | `python:3.11-slim`; `--no-cache-dir`; only `default-mysql-client` extra on backend. |
| Secrets | Only via `env_file`/`environment` at runtime — **never** `COPY .env` or `ARG` secrets (E10-S1 AC-5). |
| `.dockerignore` | Exclude `.env`, `.git`, `tests/`, `__pycache__`, `specs/`, mockups, venvs. |
| Separate requirement files | `requirements.txt` (backend: fastapi, uvicorn, langchain, pinecone, google-generativeai, mysql driver) and `frontend-requirements.txt` (streamlit, requests). |

---

## 5. Startup Order (E10-S1 AC-3, E10-S2)

1. `mysql` boots → first-boot runs `sql/schema.sql` from init dir → `products` table.
2. `backend` waits for `mysql` healthy → entrypoint runs idempotent `init_db.py` → starts uvicorn → `/api/health` goes 200.
3. `frontend` waits for `backend` healthy → starts Streamlit → reachable at `http://localhost:8501`.
4. Operator runs ingestion once: `docker compose exec backend python scripts/ingest.py` (or via `init.sh`).

`docker-compose up` brings the whole stack online end-to-end (BRD DoD item 11, E10-S1 AC-3).

---

## 6. Persistence, Reset & Rollback

- **Persist:** `mysql_data` named volume survives restarts (E10-S1 AC-4).
- **Reset data:** `docker compose down -v` drops the volume → next boot re-inits schema → re-run ingestion.
- **App rollback:** redeploy a prior image tag (`down && up -d`); app containers are stateless.
