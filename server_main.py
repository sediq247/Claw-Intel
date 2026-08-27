import asyncio
import signal
import sys

from utils.database import init_database, db
from runtime.server import ClawIntelServer


async def main():
    await init_database()
    server = ClawIntelServer(db=db)
    await server.start()

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _shutdown():
        print("\n[server_main] Shutdown signal received...")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown)

    await stop_event.wait()

    await server.stop()
    await db.close()
    print("[server_main] ✅ Server shutdown complete.")
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
