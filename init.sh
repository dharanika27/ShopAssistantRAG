#!/usr/bin/env bash
# Bootstrap the ShopAssistantRAG environment from a clean checkout (E10-S2 AC-2).
#
#   ./init.sh
#
# 1. Copy .env.example -> .env if .env is absent, then stop so the operator can
#    fill in the real Google/Pinecone keys and MySQL credentials.
# 2. Once .env has real values, re-run to apply the MySQL schema and run the
#    product ingestion pipeline (CSV -> MySQL -> embeddings -> Pinecone).
#
# Secrets live only in .env (gitignored); none are written by this script.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

PYTHON_BIN="${PYTHON_BIN:-python}"

if [ ! -f .env ]; then
  if [ ! -f .env.example ]; then
    echo "Missing .env.example template; cannot bootstrap environment." >&2
    exit 1
  fi
  cp .env.example .env
  echo "Created .env from .env.example."
  echo "Edit .env to set GOOGLE_API_KEY, PINECONE_API_KEY, and the MySQL"
  echo "credentials, then re-run ./init.sh to initialize the database and"
  echo "ingest the catalog."
  exit 0
fi

echo "Applying MySQL schema (idempotent)..."
"${PYTHON_BIN}" -m scripts.init_db

echo "Running product ingestion (CSV -> MySQL -> embeddings -> Pinecone)..."
"${PYTHON_BIN}" -m scripts.ingest

echo "Bootstrap complete. Start the app with:"
echo "  Dev mode:    uvicorn backend.api.main:create_app --factory --reload  (and: streamlit run frontend/app.py)"
echo "  Docker mode: docker compose up --build"
