import asyncio
import json
import os
import time
from pathlib import Path
from typing import Set, Optional

import aiohttp
from aiohttp import web

PORT = int(os.getenv("PORT", "3000"))


class ClawIntelServer:
    """
    Standalone Python server.
    - Static file serving from repo root
    - WebSocket at /ws with 30s heartbeat
    - REST API for health, analyze, chat history, stats, tokens, investigations, markets
    - broadcast() method for agent -> frontend communication
    - Event polling loop for decoupled engine->server communication
    """

    def __init__(self, db=None):
        self.db = db
        self.app = web.Application()
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None
        self.ws_clients: Set[web.WebSocketResponse] = set()
        self.running = False
        self._start_time = time.time()
        self._poll_task: Optional[asyncio.Task] = None
        self._last_event_ts = 0.0
        self._setup_routes()

    def _setup_routes(self):
        
        self.app.router.add_get("/", self._index)
        self.app.router.add_get("/index.html", self._index)
        self.app.router.add_get("/ws", self._ws_handler)
        self.app.router.add_get("/health", self._health)
        self.app.router.add_post("/api/analyze", self._api_analyze)
        self.app.router.add_get("/api/chat/history", self._api_chat_history)
        self.app.router.add_get("/api/stats", self._api_stats)
        self.app.router.add_get("/api/tokens", self._api_tokens)
        self.app.router.add_get("/api/investigations", self._api_investigations)
        self.app.router.add_get("/api/markets", self._api_markets)

        frontend_path = Path(__file__).parent.parent / "frontend"
        if frontend_path.exists():
            self.app.router.add_static("/frontend", path=frontend_path, name="frontend")

    async def _index(self, request: web.Request) -> web.Response:
        index_path = Path(__file__).parent.parent / "index.html"
        if index_path.exists():
            return web.FileResponse(index_path)
        return web.Response(
            text="ClawIntel  index.html not found", status=404
        )

    async def _ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30.0)
        await ws.prepare(request)

        try:
            await ws.send_json(
                {
                    "type": "SYSTEM",
                    "payload": {
                        "message": "Connected to Intel Claw ",
                        "timestamp": time.time(),
                    },
                }
            )
        except Exception:
            pass

        if self.db is not None:
            try:
                history = await self.db.get_chat_history(limit=50)
                history.reverse()
                for msg in history:
                    await ws.send_json(
                        {
                            "type": "AGENT_MESSAGE",
                            "payload": {
                                "agent": msg.get("agent", "system"),
                                "message": msg.get("message", ""),
                                "type": msg.get("type", "chat"),
                                "channel": msg.get("channel", "main"),
                                "timestamp": msg.get("timestamp", time.time()),
                            },
                        }
                    )
                if history:
                    await ws.send_json(
                        {
                            "type": "SYSTEM",
                            "payload": {
                                "message": f"--- Loaded {len(history)} past messages ---",
                                "timestamp": time.time(),
                            },
                        }
                    )
            except Exception as e:
                print(f"[server] History push failed: {e}")

        self.ws_clients.add(ws)
        print(f"[server] WS client connected. Total: {len(self.ws_clients)}")

        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        if data.get("type") == "ping":
                            await ws.send_json(
                                {"type": "pong", "payload": {"time": time.time()}}
                            )
                    except json.JSONDecodeError:
                        pass
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    print(f"[server] WS error: {ws.exception()}")
        finally:
            self.ws_clients.discard(ws)
            print(
                f"[server] WS client disconnected. Total: {len(self.ws_clients)}"
            )
        return ws

    async def broadcast(self, event_type: str, payload: dict):
        """Send JSON event to all connected WebSocket clients. Prune dead connections."""
        if not self.ws_clients:
            return
        message = json.dumps(
            {"type": event_type, "payload": payload}, default=str
        )
        dead = set()
        for ws in list(self.ws_clients):
            if ws.closed:
                dead.add(ws)
                continue
            try:
                await ws.send_str(message)
            except Exception:
                dead.add(ws)
        self.ws_clients -= dead

    async def _poll_events_loop(self):
        """
        Poll MongoDB events collection every second and broadcast
        new events to all connected WebSocket clients.
        This is the bridge between the engine (separate process) and the frontend.
        """
        self._last_event_ts = time.time() - 5

        while self.running:
            try:
                if self.db is not None and hasattr(self.db, "get_recent_events"):
                    events = await self.db.get_recent_events(
                        since=self._last_event_ts, limit=100
                    )
                    for event in events:
                        event_type = event.get("event_type", "AGENT_MESSAGE")
                        payload = event.get("payload", {})
                        await self.broadcast(event_type, payload)

                        ts = event.get("timestamp", 0)
                        if ts > self._last_event_ts:
                            self._last_event_ts = ts

                await asyncio.sleep(1)
            except Exception as e:
                print(f"[server] Event poll error: {e}")
                await asyncio.sleep(2)

    async def _health(self, request: web.Request) -> web.Response:
        uptime = int(time.time() - self._start_time)
        pending = 0
        if self.db:
            try:
                pending = await self.db.count_pending_tokens()
            except Exception:
                pass
        return web.json_response(
            {
                "status": "ok",
                "uptime_seconds": uptime,
                "ws_clients": len(self.ws_clients),
                "queue_size": pending,
                "version": "4.1",
            }
        )

    async def _api_analyze(self, request: web.Request) -> web.Response:
        """Accept {tokenAddress, chain} and queue as USER_QUERY with attention=100."""
        try:
            data = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        token_address = data.get("tokenAddress") or data.get("token_address")
        chain = data.get("chain", "ethereum")
        if not token_address:
            return web.json_response(
                {"error": "tokenAddress required"}, status=400
            )
        if self.db:
            try:
                await self.db.save_discovered_token(
                    {
                        "token_address": str(token_address).strip(),
                        "chain": chain.lower().strip(),
                        "symbol": data.get("symbol", "UNKNOWN"),
                        "name": data.get("name", "User Query"),
                        "creator": data.get("creator", "unknown"),
                        "attention_score": 100,
                        "status": "pending",
                        "origin_source": "USER_QUERY",
                        "discovered_at": time.time(),
                    }
                )
            except Exception as e:
                print(f"[server] DB save error: {e}")

        try:
            await self.broadcast(
                "AGENT_MESSAGE",
                {
                    "agent": "system",
                    "message": (
                        f"Forensic Lab: User requested analysis of {str(token_address)[:12]}... "
                        f"on {chain.upper()}. Queued for immediate investigation."
                    ),
                    "type": "system",
                    "channel": "main",
                    "timestamp": time.time(),
                },
            )
        except Exception:
            pass

        return web.json_response(
            {"status": "queued", "tokenAddress": token_address, "chain": chain}
        )

    async def _api_chat_history(self, request: web.Request) -> web.Response:
        """Return chat history. Key is 'history' (matches frontend app.js expectation)."""
        limit = int(request.query.get("limit", "50"))
        if self.db:
            try:
                history = await self.db.get_chat_history(limit=limit)
                history.reverse()
                return web.json_response({"history": history})
            except Exception as e:
                return web.json_response({"error": str(e)}, status=500)
        return web.json_response({"history": []})

    async def _api_stats(self, request: web.Request) -> web.Response:
        if self.db:
            try:
                stats = await self.db.get_stats()
                stats["agents_online"] = 5
                return web.json_response(stats)
            except Exception as e:
                return web.json_response({"error": str(e)}, status=500)
        return web.json_response(
            {
                "total_tokens": 0,
                "total_investigations": 0,
                "total_creators": 0,
                "total_messages": 0,
                "safe_count": 0,
                "warning_count": 0,
                "high_risk_count": 0,
                "agents_online": 5,
            }
        )

    async def _api_tokens(self, request: web.Request) -> web.Response:
        limit = int(request.query.get("limit", "100"))
        if self.db:
            try:
                tokens = await self.db.get_discovered_tokens(limit=limit)
                return web.json_response({"tokens": tokens})
            except Exception as e:
                return web.json_response({"error": str(e)}, status=500)
        return web.json_response({"tokens": []})

    async def _api_investigations(self, request: web.Request) -> web.Response:
        limit = int(request.query.get("limit", "100"))
        if self.db:
            try:
                investigations = await self.db.get_completed_investigations(
                    limit=limit
                )
                return web.json_response({"investigations": investigations})
            except Exception as e:
                return web.json_response({"error": str(e)}, status=500)
        return web.json_response({"investigations": []})

    async def _api_markets(self, request: web.Request) -> web.Response:
        """
        Markets tab:
          - trending / gainers / losers  → always LIVE from DexScreener (no DB)
          - ai_verified                 → only from DB (Orion completed investigations)
        """
        import time as _time
        data = {
            "trending": [],
            "gainers": [],
            "losers": [],
            "ai_verified": [],
            "timestamp": _time.time(),
            "source": "live",
        }
        try:
            live = await self._live_fetch_markets()
            if live:
                data["trending"] = live.get("trending") or []
                data["gainers"] = live.get("gainers") or []
                data["losers"] = live.get("losers") or []
                data["timestamp"] = live.get("timestamp") or data["timestamp"]
                data["source"] = live.get("source") or "live"
        except Exception as e:
            print(f"[server] live markets fetch failed: {e}")

        # AI-verified only from DB
        if self.db and hasattr(self.db, "get_ai_verified_tokens"):
            try:
                data["ai_verified"] = await self.db.get_ai_verified_tokens(limit=30)
            except Exception as e:
                print(f"[server] ai_verified load failed: {e}")

        return web.json_response(data)

    async def _live_fetch_markets(self) -> dict:
        """Minimal DexScreener pull so Markets tab works even without agents process."""
        import time as _time
        trending, gainers, losers = [], [], []
        timeout = aiohttp.ClientTimeout(total=12)
        headers = {"User-Agent": "ClawIntel/5.1"}

        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            # Boosted / trending
            try:
                async with session.get("https://api.dexscreener.com/token-boosts/top/v1") as resp:
                    if resp.status == 200:
                        items = await resp.json()
                        if isinstance(items, list):
                            for item in items[:15]:
                                tok = self._ds_item_to_market_row(item, source="boosted")
                                if tok:
                                    trending.append(tok)
            except Exception as e:
                print(f"[server] boosted fetch: {e}")

            # Search-based gainers proxy
            for q in ("SOL", "ETH", "PEPE", "BONK"):
                try:
                    async with session.get(
                        f"https://api.dexscreener.com/latest/dex/search?q={q}"
                    ) as resp:
                        if resp.status != 200:
                            continue
                        body = await resp.json()
                        pairs = body.get("pairs") or []
                        for p in pairs[:8]:
                            row = self._ds_pair_to_market_row(p)
                            if not row:
                                continue
                            ch = (row.get("price_change_24h") or 0)
                            if ch >= 0:
                                gainers.append(row)
                            else:
                                losers.append(row)
                except Exception:
                    continue

        # de-dupe by id
        def dedupe(rows):
            seen, out = set(), []
            for r in rows:
                i = r.get("id")
                if i and i not in seen:
                    seen.add(i)
                    out.append(r)
            return out

        gainers = sorted(dedupe(gainers), key=lambda x: x.get("_change_num") or 0, reverse=True)[:20]
        losers = sorted(dedupe(losers), key=lambda x: x.get("_change_num") or 0)[:20]
        trending = dedupe(trending)[:20]

        return {
            "trending": trending,
            "gainers": gainers,
            "losers": losers,
            "ai_verified": [],
            "timestamp": _time.time(),
            "source": "live_fallback",
        }

    def _ds_item_to_market_row(self, item: dict, source: str = "") -> dict:
        if not isinstance(item, dict):
            return None
        token_addr = item.get("tokenAddress") or item.get("address")
        chain = (item.get("chainId") or item.get("chain") or "unknown")
        if isinstance(chain, str) and chain.startswith("0x"):
            chain = "ethereum"
        symbol = item.get("symbol") or "???"
        name = item.get("name") or symbol
        # boosted payload is thin — id only
        tid = f"{chain}:{token_addr}" if token_addr else None
        if not tid:
            return None
        return {
            "id": tid,
            "symbol": symbol,
            "name": name,
            "chain": str(chain),
            "price": 0,
            "price_change_24h": 0,
            "volume_24h": 0,
            "liquidity": 0,
            "market_cap": 0,
            "address": token_addr,
            "source": source or "dexscreener",
        }

    def _ds_pair_to_market_row(self, pair: dict) -> dict:
        if not isinstance(pair, dict):
            return None
        bt = pair.get("baseToken") or {}
        chain = pair.get("chainId") or "unknown"
        addr = bt.get("address") or pair.get("pairAddress")
        if not addr:
            return None
        try:
            price = float(pair.get("priceUsd") or 0)
        except (TypeError, ValueError):
            price = 0.0
        ch = (pair.get("priceChange") or {}).get("h24")
        try:
            ch = float(ch) if ch is not None else 0.0
        except (TypeError, ValueError):
            ch = 0.0
        vol = (pair.get("volume") or {}).get("h24") or 0
        liq = (pair.get("liquidity") or {}).get("usd") or 0
        def _fmt_price(p):
            try:
                p = float(p)
            except Exception:
                return "$0.00"
            if p >= 1:
                return f"${p:,.4f}"
            if p >= 0.0001:
                return f"${p:.6f}"
            return f"${p:.8f}"
        def _fmt_pct(c):
            try:
                c = float(c)
            except Exception:
                return "0.00%"
            return f"{c:+.2f}%"
        def _fmt_usd(n):
            try:
                n = float(n)
            except Exception:
                return "$0"
            if n >= 1e9:
                return f"${n/1e9:.2f}B"
            if n >= 1e6:
                return f"${n/1e6:.2f}M"
            if n >= 1e3:
                return f"${n/1e3:.2f}K"
            return f"${n:.2f}"
        mcap = pair.get("marketCap") or 0
        return {
            "id": f"{chain}:{addr}",
            "symbol": bt.get("symbol") or "???",
            "name": bt.get("name") or bt.get("symbol") or "Unknown",
            "chain": str(chain),
            "price": _fmt_price(price),
            "price_change_24h": _fmt_pct(ch),
            "volume_24h": _fmt_usd(vol),
            "liquidity": _fmt_usd(liq),
            "market_cap": _fmt_usd(mcap),
            "address": addr,
            "pair_address": pair.get("pairAddress"),
            "source": "dexscreener",
            "_change_num": ch,
        }

    async def start(self):
        self.running = True
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "0.0.0.0", PORT)
        await self.site.start()
        print(f"[server] ✅ ClawIntel server running on http://0.0.0.0:{PORT}")
        print(f"[server] 📡 WebSocket endpoint: ws://0.0.0.0:{PORT}/ws")

        self._poll_task = asyncio.create_task(self._poll_events_loop())
        print("[server] 🔄 Event polling started (DB-driven broadcasts)")

    async def stop(self):
        self.running = False

        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

        for ws in list(self.ws_clients):
            if not ws.closed:
                try:
                    await ws.close()
                except Exception:
                    pass
        self.ws_clients.clear()

        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()
        print("[server] ✅ Server stopped")
