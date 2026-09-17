import asyncio
import signal
import sys

from utils.database import init_database, db
from runtime.server import ClawIntelServer
from utils.marketEngine import MarketEngine
from utils.publisher import EventPublisher


async def main():
    await init_database()
    server = ClawIntelServer(db=db)
    await server.start()

    # Market data engine (DexScreener → DB → /api/markets + WS)
    publisher = EventPublisher(db=db, server=server)
    market_engine = MarketEngine(publisher=publisher, db=db)
    market_task = asyncio.create_task(market_engine.start())
    print("[server_main] MarketEngine started")

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _shutdown():
        print("\n[server_main] Shutdown signal received...")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown)

    await stop_event.wait()

    if hasattr(market_engine, "stop"):
        try:
            r = market_engine.stop()
            if asyncio.iscoroutine(r):
                await r
        except Exception:
            pass
    if not market_task.done():
        market_task.cancel()
        try:
            await market_task
        except asyncio.CancelledError:
            pass

    await server.stop()
    await db.close()
    print("[server_main] ✅ Server shutdown complete.")
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
