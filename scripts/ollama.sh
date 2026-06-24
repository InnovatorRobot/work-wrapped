#!/usr/bin/env bash
#
# Start the local Ollama LLM server for Work Wrapped.
#
# Everything runs on THIS machine — no work data is ever sent to a cloud service.
# Ollama uses your NVIDIA/AMD GPU automatically when present and falls back to CPU.
#
# Usage:
#   ./scripts/ollama.sh            # start server (foreground) and ensure the model is pulled
#   ./scripts/ollama.sh serve      # just start the server
#   ./scripts/ollama.sh pull       # just pull the model
#
# Configure which model via OPENAI_MODEL in .env (default: llama3.1:8b).

set -euo pipefail

# Find ollama (user-space install in ~/.local/bin, or on PATH)
export PATH="$HOME/.local/bin:$PATH"
if ! command -v ollama >/dev/null 2>&1; then
    echo "ollama not found. Install it (user-space, no sudo):" >&2
    echo "  curl -fL https://github.com/ollama/ollama/releases/latest/download/ollama-linux-amd64.tar.zst -o /tmp/ollama.tar.zst" >&2
    echo "  tar -I zstd -xf /tmp/ollama.tar.zst -C \"\$HOME/.local\"" >&2
    echo "Or system-wide: curl -fsSL https://ollama.com/install.sh | sh" >&2
    exit 1
fi

export OLLAMA_HOST="${OLLAMA_HOST:-127.0.0.1:11434}"

# Read OPENAI_MODEL from .env if present, else default.
MODEL="${OPENAI_MODEL:-}"
if [[ -z "$MODEL" ]]; then
    ENV_FILE="$(dirname "$0")/../.env"
    if [[ -f "$ENV_FILE" ]]; then
        MODEL="$(grep -E '^OPENAI_MODEL=' "$ENV_FILE" | tail -1 | cut -d= -f2- | tr -d '"' || true)"
    fi
fi
MODEL="${MODEL:-llama3.1:8b}"

start_server() {
    if curl -s -m 2 "http://${OLLAMA_HOST}/api/version" >/dev/null 2>&1; then
        echo "Ollama already running at http://${OLLAMA_HOST}"
    else
        echo "Starting Ollama at http://${OLLAMA_HOST} ..."
        nohup ollama serve >/tmp/ollama.log 2>&1 &
        for _ in $(seq 1 30); do
            curl -s -m 2 "http://${OLLAMA_HOST}/api/version" >/dev/null 2>&1 && break
            sleep 1
        done
        echo "Ollama started (logs: /tmp/ollama.log)"
    fi
}

pull_model() {
    if ollama list 2>/dev/null | awk '{print $1}' | grep -qx "$MODEL"; then
        echo "Model '$MODEL' already present."
    else
        echo "Pulling model '$MODEL' (one-time download)..."
        ollama pull "$MODEL"
    fi
}

case "${1:-all}" in
    serve) start_server ;;
    pull)  start_server; pull_model ;;
    all|"") start_server; pull_model; echo "Ready. Point the app at http://${OLLAMA_HOST}/v1 (already set in .env)." ;;
    *) echo "Usage: $0 [serve|pull|all]" >&2; exit 1 ;;
esac
