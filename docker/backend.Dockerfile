# Backend image: FastAPI served by uvicorn (E10-S1 AC-1).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install dependencies first so the layer caches across code changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code, SQL schema, ingestion scripts, and entrypoint.
COPY backend ./backend
COPY scripts ./scripts
COPY sql ./sql
COPY docker/entrypoint-backend.sh /usr/local/bin/entrypoint-backend.sh
RUN chmod +x /usr/local/bin/entrypoint-backend.sh

EXPOSE 8000

# The entrypoint waits for MySQL, applies the schema on first boot (E10-S2 AC-1),
# then launches the API. Secrets arrive via environment, never baked in (AC-5).
ENTRYPOINT ["/usr/local/bin/entrypoint-backend.sh"]
