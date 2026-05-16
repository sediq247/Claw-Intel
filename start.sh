#!/bin/bash
# 🚀 ClawIntel Combined Start Script for Render
# Runs Node server AND Python agent swarm in the same service
# This ensures they can communicate via localhost


echo "🦅 Starting ClawIntel..."
echo "═══════════════════════════════════════"

# Start Node server in background
echo "[1/2] Starting Node server..."
node runtime/server.js &
NODE_PID=$!
echo "✅ Node server started (PID: $NODE_PID)"

# Wait for Node to be ready
echo "⏳ Waiting for Node server to be ready..."
for i in {1..30}; do
    if curl -s http://localhost:3000/health > /dev/null 2>&1; then
        echo "✅ Node server is ready!"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "❌ Node server failed to start within 30s"
        kill $NODE_PID 2>/dev/null
        exit 1
    fi
    sleep 1
done

# Start Python agent swarm
echo "[2/2] Starting Python agent swarm..."
python3 -m agents.orchestrator &
PYTHON_PID=$!
echo "✅ Python agents started (PID: $PYTHON_PID)"

echo "═══════════════════════════════════════"
echo "🦅 ClawIntel is LIVE!"
echo "   HTTP:  http://localhost:$PORT"
echo "   WS:    ws://localhost:$PORT"
echo "═══════════════════════════════════════"

# Handle shutdown gracefully
cleanup() {
    echo "\n🛑 Shutting down ClawIntel..."
    kill $PYTHON_PID 2>/dev/null
    kill $NODE_PID 2>/dev/null
    wait $PYTHON_PID 2>/dev/null
    wait $NODE_PID 2>/dev/null
    echo "✅ Shutdown complete"
    exit 0
}

trap cleanup SIGTERM SIGINT

# Keep script running
wait $NODE_PID