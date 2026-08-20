#!/usr/bin/env python3
"""🤖 agents_main.py — ClawIntel Agent Swarm Service (Railway)"""

import asyncio
import signal
import sys

from utils.database import init_database, db
from agents.orchestrator import AgentOrchestrator


async def main():
    await init_database()

    # server=None → EventPublisher writes ONLY to MongoDB.
    # The web-server service polls the same DB and broadcasts to clients.
    orchestrator = AgentOrchestrator(server=None, db=db)
    orch_task = asyncio.create_task(orchestrator.start())

    def _check(task, name):
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[agents_main] {name} crashed: {e}")

    orch_task.add_done_callback(lambda t: _check(t, "Orchestrator"))

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _shutdown():
        print("\n[agents_main] Shutdown signal received...")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown)

    await stop_event.wait()

    print("[agents_main] Stopping Orchestrator...")
    await orchestrator.stop()
    orch_task.cancel()
    try:
        await orch_task
    except asyncio.CancelledError:
        pass

    await db.close()
    print("[agents_main] ✅ Graceful shutdown complete.")
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
