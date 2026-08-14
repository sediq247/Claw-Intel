#!/usr/bin/env python3
"""
🖥 runtime/server.py
ClawIntel Server v4.0 — Python aiohttp replaces Node.js completely.
Serves static files, WebSocket at /ws, REST API, and broadcasts to frontend.
"""

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
    Single-runtime Python server.
    - Static file serving from repo root
    - WebSocket at /ws with 30s heartbeat
    - REST API for health, analyze, chat history, stats, tokens, investigations
    - broadcast() method for agent → frontend communication
    """

    def __init__(self, db=None):
        self.db = db
        self.app = web.Application()
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None
        self.ws_clients: Set[web.WebSocketResponse] = set()
        self.running = False
        self._start_time = time.time()
        self._setup_routes()

    def _setup_routes(self):
        # Explicit routes first (static routes registered last)
        self.app.router.add_get("/", self._index)
        self.app.router.add_get("/ws", self._ws_handler)
        self.app.router.add_get("/health", self._health)
        self.app.router.add_post("/api/analyze", self._api_analyze)
        self.app.router.add_get("/api/chat/history", self._api_chat_history)
        self.app.router.add_get("/api/stats", self._api_stats)
        self.app.router.add_get("/api/tokens", self._api_tokens)
        self.app.router.add_get("/api/investigations", self._api_investigations)

        # Static assets
        frontend_path = Path(__file__).parent.parent / "frontend"
        if frontend_path.exists():
            self.app.router.add_static("/frontend", path=frontend_path, name="frontend")

    # ── STATIC FILES ──
    async def _index(self, request: web.Request) -> web.Response:
        index_path = Path(__file__).parent.parent / "index.html"
        if index_path.exists():
            return web.FileResponse(index_path)
        return web.Response(
            text="ClawIntel v4.0 — index.html not found", status=404
        )

    # ── WEBSOCKET ──
    async def _ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30.0)
        await ws.prepare(request)
        self.ws_clients.add(ws)
        print(f"[server] WS client connected. Total: {len(self.ws_clients)}")

        try:
            await ws.send_json(
                {
                    "type": "SYSTEM",
                    "payload": {
                        "message": "Connected to ClawIntel v4.0",
                        "timestamp": time.time(),
                    },
                }
            )
        except Exception:
            pass

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

    # ── BROADCAST ──
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

    # ── REST ENDPOINTS ──
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
                "version": "4.0",
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

        # Save to DB as high-priority pending token
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

        # Broadcast to frontend
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
        limit = int(request.query.get("limit", "50"))
        if self.db:
            try:
                history = await self.db.get_chat_history(limit=limit)
                history.reverse()
                return web.json_response({"messages": history})
            except Exception as e:
                return web.json_response({"error": str(e)}, status=500)
        return web.json_response({"messages": []})

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

    # ── LIFECYCLE ──
    async def start(self):
        self.running = True
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "0.0.0.0", PORT)
        await self.site.start()
        print(f"[server] ✅ ClawIntel server running on http://0.0.0.0:{PORT}")
        print(f"[server] 📡 WebSocket endpoint: ws://0.0.0.0:{PORT}/ws")

    async def stop(self):
        self.running = False
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
