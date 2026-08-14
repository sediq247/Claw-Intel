#!/usr/bin/env python3
"""🚀 main.py — ClawIntel v4.0 Entry Point. Bootstraps DB → Server → Orchestrator → Nova."""

import asyncio
import signal
import sys

from utils.database import init_database, db
from runtime.server import ClawIntelServer
from agents.orchestrator import AgentOrchestrator
from agents.watcher import WatcherAgent


async def main():
    await init_database()
    server = ClawIntelServer(db=db)
    await server.start()

    orchestrator = AgentOrchestrator(server=server, db=db)
    orch_task = asyncio.create_task(orchestrator.start())

    nova = WatcherAgent(db=db, server=server)
    nova_task = asyncio.create_task(nova.start())

    def _check(task, name):
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[main] {name} crashed: {e}")

    nova_task.add_done_callback(lambda t: _check(t, "Nova"))
    orch_task.add_done_callback(lambda t: _check(t, "Orchestrator"))

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _shutdown():
        print("\n[main] Shutdown signal received...")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown)

    await stop_event.wait()

    for task, name, stop_fn in [
        (nova_task, "Nova", nova.stop),
        (orch_task, "Orchestrator", orchestrator.stop),
    ]:
        print(f"[main] Stopping {name}...")
        await stop_fn()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    await server.stop()
    await db.close()
    print("[main] ✅ Graceful shutdown complete.")
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
