#!/usr/bin/env bash
# Backend container entrypoint (E10-S1, E10-S2 AC-1).
#
# 1. Wait for MySQL to accept connections (compose starts containers in
#    parallel, so the DB may not be ready when this image boots).
# 2. Apply the product schema idempotently (first-boot initialization).
# 3. Launch the FastAPI app under uvicorn.
#
# All connection parameters come from the environment / .env (AC-5); nothing is
# hardcoded here.
set -euo pipefail

MYSQL_HOST="${MYSQL_HOST:-mysql}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
WAIT_TIMEOUT_SECONDS="${DB_WAIT_TIMEOUT_SECONDS:-60}"

echo "Waiting for MySQL at ${MYSQL_HOST}:${MYSQL_PORT} (timeout ${WAIT_TIMEOUT_SECONDS}s)..."
elapsed=0
until python -c "import socket,sys; s=socket.socket(); s.settimeout(2); s.connect(('${MYSQL_HOST}', ${MYSQL_PORT})); s.close()" 2>/dev/null; do
  if [ "${elapsed}" -ge "${WAIT_TIMEOUT_SECONDS}" ]; then
    echo "MySQL did not become reachable within ${WAIT_TIMEOUT_SECONDS}s." >&2
    exit 1
  fi
  sleep 2
  elapsed=$((elapsed + 2))
done
echo "MySQL is reachable."

echo "Applying product schema (idempotent)..."
python -m scripts.init_db

echo "Starting FastAPI on 0.0.0.0:8000..."
exec uvicorn backend.api.main:create_app --factory --host 0.0.0.0 --port 8000
