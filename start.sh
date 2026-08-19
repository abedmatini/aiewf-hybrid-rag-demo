#!/usr/bin/env bash
# Start AIEWF Hybrid RAG Demo — FastAPI + React
# ───────────────────────────────────────────────
# Prerequisites:
#   - Docker running: docker compose up -d          (Postgres + pgvector on 5435)
#   - Ollama running with models pulled:
#       ollama pull bge-m3
#       ollama pull qwen2.5:7b-instruct
#       ollama pull medgemma:latest        (or any Ollama chat model — see README)
#   - Python venv: cd api && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
#   - Node deps:   cd ui && npm install
#   - api/.env and ui/.env created from their .env.example files
set -e

echo "Starting AIEWF Hybrid RAG Demo..."

(cd api && uvicorn main:app --host 0.0.0.0 --port 8003 --reload) &
(cd ui && npm run dev -- --port 5174) &

echo ""
echo "  API:  http://localhost:8003/docs"
echo "  UI:   http://localhost:5174"
echo ""
echo "Press Ctrl+C to stop."
wait
