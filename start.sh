set -e

_log() {
    echo "[start] $1" >&2
}

PORT=${PORT:-3000}

_log "🦅 Starting ClawIntel..."
_log "═══════════════════════════════════════"
_log "PORT=$PORT"
_log "NODE_ENV=${NODE_ENV:-production}"
_log "PWD=$(pwd)"

# Check dependencies
command -v node >/dev/null 2>&1 || { _log "node not found"; exit 1; }
command -v python3 >/dev/null 2>&1 || { _log "python3 not found"; exit 1; }

# =========================
# 1. START NODE (SERVER)
# =========================
_log "[1/2] Starting Node server..."

node runtime/server.js &
NODE_PID=$!

_log "Node PID: $NODE_PID"

# Wait for port to open
_log "⏳ Waiting for Node to bind port $PORT..."

for i in $(seq 1 60); do
    if nc -z localhost "$PORT" 2>/dev/null; then
        _log "Node is listening on port $PORT"
        break
    fi

    if [ $i -eq 60 ]; then
        _log "Node failed to bind port in time"
        kill $NODE_PID 2>/dev/null || true
        exit 1
    fi

    sleep 1
done

# Small stabilization delay (important for eventBus + DB + stream init)
sleep 2

# =========================
# 2. START PYTHON AGENTS
# =========================
_log "[2/2] Starting Python agent swarm..."

python3 -m agents.orchestrator &
PYTHON_PID=$!

_log "Python PID: $PYTHON_PID"

_log "═══════════════════════════════════════"
_log "🦅 ClawIntel LIVE"
_log "   HTTP: http://localhost:$PORT"
_log "   WS:   ws://localhost:$PORT"
_log "═══════════════════════════════════════"

# =========================
# SAFE RESTART HANDLERS
# =========================
restart_node() {
    _log "Node crashed → restarting..."
    sleep 3
    node runtime/server.js &
    NODE_PID=$!
}

restart_python() {
    _log "Python crashed → restarting..."
    sleep 3
    python3 -m agents.orchestrator &
    PYTHON_PID=$!
}

# =========================
# SUPERVISOR LOOP
# =========================
while true; do

    if ! kill -0 $NODE_PID 2>/dev/null; then
        restart_node
    fi

    if ! kill -0 $PYTHON_PID 2>/dev/null; then
        restart_python
    fi

    sleep 5
done