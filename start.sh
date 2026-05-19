#!/bin/bash
# 🚀 ClawIntel Production Start Script (Railway/Koyeb safe)

set -e

log() {
    echo "[ClawIntel] $1"
}

log "🦅 Starting ClawIntel system..."

PORT=${PORT:-3000}

# -----------------------------
# Start Node.js server
# -----------------------------
log "[1/2] Starting Node runtime..."

node runtime/server.js &
NODE_PID=$!

log "Node PID: $NODE_PID"

# -----------------------------
# Wait for Node to be ready
# -----------------------------
log "⏳ Waiting for server health..."

TIMEOUT=90
ELAPSED=0

while [ $ELAPSED -lt $TIMEOUT ]; do
    STATUS=$(curl -s http://localhost:$PORT/health || echo "fail")

    if echo "$STATUS" | grep -q "ok"; then
        log "✅ Node is ready"
        break
    fi

    sleep 2
    ELAPSED=$((ELAPSED+2))
done

if [ $ELAPSED -ge $TIMEOUT ]; then
    log "❌ Node failed to start in time"
    kill $NODE_PID || true
    exit 1
fi

# -----------------------------
# Start Python agents
# -----------------------------
log "[2/2] Starting Python agent swarm..."

python3 -m agents.orchestrator &
PYTHON_PID=$!

log "Python PID: $PYTHON_PID"

# -----------------------------
# Shutdown handler
# -----------------------------
cleanup() {
    log "🛑 Shutting down ClawIntel..."

    kill -TERM $PYTHON_PID 2>/dev/null || true
    kill -TERM $NODE_PID 2>/dev/null || true

    wait $PYTHON_PID 2>/dev/null || true
    wait $NODE_PID 2>/dev/null || true

    log "✅ Shutdown complete"
    exit 0
}

trap cleanup SIGINT SIGTERM

# -----------------------------
# Supervision loop (safe)
# -----------------------------
while true; do

    if ! kill -0 $NODE_PID 2>/dev/null; then
        log "⚠️ Node crashed — restarting..."
        node runtime/server.js &
        NODE_PID=$!
    fi

    if ! kill -0 $PYTHON_PID 2>/dev/null; then
        log "⚠️ Python crashed — restarting..."
        python3 -m agents.orchestrator &
        PYTHON_PID=$!
    fi

    sleep 5
done