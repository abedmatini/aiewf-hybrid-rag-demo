#!/usr/bin/env bash
# .devcontainer/setup.sh — runs once when the Codespace is first created.
# Installs dependencies, pulls small Ollama models (sized for Codespace
# resource limits), and writes .env files with the correct Codespace URLs.
set -e

BOLD='\033[1m'
GREEN='\033[0;32m'
RESET='\033[0m'
step() { echo -e "\n${BOLD}=== $1 ===${RESET}"; }

# ── 1. PostgreSQL ────────────────────────────────────────────────────────────
step "[1/5] Starting PostgreSQL + pgvector"
if docker compose up db -d 2>/dev/null; then
  echo "Waiting for DB to be healthy..."
  until docker compose exec -T db pg_isready -U chainlit -d chainlit_db &>/dev/null; do
    sleep 2
  done
  echo "PostgreSQL ready."
else
  echo "Docker not yet available — DB will start via postStartCommand. Skipping."
fi

# ── 2. Python dependencies ───────────────────────────────────────────────────
step "[2/5] Installing Python dependencies"
pip install --quiet -r api/requirements.txt

# ── 3. Node.js dependencies ──────────────────────────────────────────────────
step "[3/5] Installing Node.js dependencies"
if ! command -v npm &>/dev/null && [ -s "/usr/local/share/nvm/nvm.sh" ]; then
  source "/usr/local/share/nvm/nvm.sh"
fi
cd ui && npm install --silent && cd -

# ── 4. Ollama + models ───────────────────────────────────────────────────────
step "[4/5] Installing Ollama and pulling models"
curl -fsSL https://ollama.com/install.sh | sh
nohup ollama serve > /tmp/ollama.log 2>&1 &
echo "Waiting for Ollama to start..."
until curl -sf http://localhost:11434/api/tags &>/dev/null; do
  sleep 2
done
# Small models chosen for Codespace CPU-only resource limits.
# Swap for bge-m3 / qwen2.5:7b-instruct / medgemma:latest on a real GPU box.
echo "Pulling nomic-embed-text (270 MB)..."
ollama pull nomic-embed-text
echo "Pulling qwen2.5:0.5b (400 MB, chat + agent tool calling)..."
ollama pull qwen2.5:0.5b

# ── 5. Environment files ─────────────────────────────────────────────────────
step "[5/5] Writing .env files"
DOMAIN="${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}"
NAME="${CODESPACE_NAME:-localhost}"
API_URL="https://${NAME}-8003.${DOMAIN}"
UI_URL="https://${NAME}-5174.${DOMAIN}"

cat > api/.env << EOF
DATABASE_URL=postgresql://chainlit:chainlit@localhost:5435/chainlit_db
OLLAMA_URL=http://localhost:11434
EMBED_MODEL=nomic-embed-text
EMBED_DIM=768
CHAT_MODEL=qwen2.5:0.5b
CLASSIFIER_MODEL=none
AGENT_MODEL=qwen2.5:0.5b
OLLAMA_NUM_CTX=2048
CHITCHAT_DISTANCE_THRESHOLD=0.70
MAX_HISTORY=20
CORS_ORIGINS=${UI_URL},http://localhost:5174
KB_USER_ID=demo_kb
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=
EOF

cat > ui/.env << EOF
VITE_API_URL=${API_URL}
VITE_PRIVACY_POLICY_URL=https://example.com/privacy
VITE_GA4_ID=
EOF

echo -e "\n${GREEN}${BOLD}Setup complete!${RESET}"
echo "  API → ${API_URL}"
echo "  UI  → ${UI_URL}"
echo ""
echo "Start both with: bash start.sh"
