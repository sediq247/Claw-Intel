import time
from typing import Optional, Any


class EventPublisher:
    """
    Centralized publisher that writes every event to MongoDB
    before (or instead of) pushing it over WebSocket.

    In split-deployment mode (web server vs agents as separate services),
    the web server polls the MongoDB `events` collection and broadcasts
    to WebSocket clients. The agents service writes here; the web service
    reads here. No direct coupling between the two.
    """

    def __init__(self, db: Any, server: Optional[Any] = None):
        self.db = db
        self.server = server

    async def broadcast(self, event_type: str, payload: dict) -> None:
        """
        Generic broadcast entry-point. Routes to the correct persist
        method based on event_type, then optionally pushes to WS.
        """
        et = event_type.upper()

        if et == "AGENT_MESSAGE":
            agent = payload.get("agent", "system")
            msg = payload.get("message", "")
            msg_type = payload.get("type", "chat")
            channel = payload.get("channel", "main")
            await self.agent_message(agent, msg, msg_type, channel)
            return

        if et == "NEW_TOKEN":
            token_data = {
                "address": payload.get("token"),
                "chain": payload.get("chain"),
                "symbol": payload.get("symbol"),
                "timestamp": payload.get("timestamp", time.time()),
            }
            await self.new_token(token_data)
            return

        if et == "MARKET_UPDATE":
            await self.market_update(payload)
            return

        if et == "INVESTIGATION_COMPLETE":
            await self.investigation_complete(payload)
            return

        if et == "SIGNAL":
            await self.signal(
                token=payload.get("token", ""),
                chain=payload.get("chain", ""),
                symbol=payload.get("symbol", ""),
                verdict=payload.get("verdict", "UNKNOWN"),
                score=payload.get("score", 0.0),
                confidence=payload.get("confidence", 0.0),
            )
            return

        if et == "AGENT_WORKING":
            await self.agent_working(
                agent=payload.get("agent", ""),
                token=payload.get("token", ""),
                action=payload.get("action", "working..."),
                chain=payload.get("chain", ""),
            )
            return

        # Fallback for any unhandled event types
        if self.db is not None and hasattr(self.db, "save_event"):
            try:
                await self.db.save_event(event_type, payload)
            except Exception as e:
                print(f"[publisher] DB save_event failed: {e}")

        if self.server is not None and hasattr(self.server, "broadcast"):
            try:
                await self.server.broadcast(event_type, payload)
            except Exception as e:
                print(f"[publisher] Live broadcast failed: {e}")

    # ── AGENT MESSAGE ──

    async def agent_message(
        self,
        agent: str,
        message: str,
        msg_type: str = "chat",
        channel: str = "main",
    ) -> None:
        """
        Persist an agent chat message to MongoDB, then broadcast
        it to all currently-connected WebSocket clients.
        """
        payload = {
            "agent": agent,
            "message": message,
            "type": msg_type,
            "channel": channel,
            "timestamp": time.time(),
        }

        if self.db is not None and hasattr(self.db, "save_chat_message"):
            try:
                await self.db.save_chat_message(agent, message, msg_type, channel)
            except Exception as e:
                print(f"[publisher] DB save_chat_message failed: {e}")

        if self.db is not None and hasattr(self.db, "save_event"):
            try:
                await self.db.save_event("AGENT_MESSAGE", payload)
            except Exception as e:
                print(f"[publisher] DB save_event failed: {e}")

        if self.server is not None and hasattr(self.server, "broadcast"):
            try:
                await self.server.broadcast("AGENT_MESSAGE", payload)
            except Exception as e:
                print(f"[publisher] Live broadcast failed: {e}")

    async def system_message(self, message: str) -> None:
        """Persist a system-level message as the 'system' agent."""
        await self.agent_message("system", message, "system")

    # ── NEW TOKEN ──

    async def new_token(self, token_data: dict) -> None:
        """
        Persist a newly-discovered token to the processing queue,
        also mirror it to discovered_tokens for the REST API / history page,
        then broadcast a lightweight NEW_TOKEN event.
        """
        if self.db is not None and hasattr(self.db, "add_token_to_queue"):
            try:
                await self.db.add_token_to_queue(token_data)
            except Exception as e:
                print(f"[publisher] DB add_token_to_queue failed: {e}")

        if self.db is not None and hasattr(self.db, "save_discovered_token"):
            try:
                discovered_doc = {
                    "token_address": token_data.get("address")
                    or token_data.get("token_address"),
                    "address": token_data.get("address")
                    or token_data.get("token_address"),
                    "chain": token_data.get("chain", "unknown"),
                    "symbol": token_data.get("symbol", "???"),
                    "name": token_data.get("name", "Unknown"),
                    "creator": token_data.get("creator", "unknown"),
                    "liquidity": token_data.get("liquidity", 0),
                    "volume_24h": token_data.get("volume_24h", 0),
                    "price": token_data.get("price", 0),
                    "attention_score": token_data.get("attention_score", 50),
                    "status": token_data.get("status", "pending"),
                    "origin_source": token_data.get("source", "auto"),
                    "discovered_at": token_data.get("timestamp")
                    or token_data.get("discovered_at")
                    or time.time(),
                    "timestamp": token_data.get("timestamp")
                    or token_data.get("discovered_at")
                    or time.time(),
                }
                await self.db.save_discovered_token(discovered_doc)
            except Exception as e:
                print(f"[publisher] DB save_discovered_token failed: {e}")

        if self.server is not None and hasattr(self.server, "broadcast"):
            try:
                await self.server.broadcast("NEW_TOKEN", {
                    "token": token_data.get("address")
                    or token_data.get("token_address"),
                    "chain": token_data.get("chain"),
                    "symbol": token_data.get("symbol"),
                    "timestamp": time.time(),
                })
            except Exception as e:
                print(f"[publisher] NEW_TOKEN broadcast failed: {e}")

    # ── MARKET UPDATE ──

    async def market_update(self, data: dict) -> None:
        """
        Persist a full market snapshot and broadcast it live.
        """
        if self.db is not None and hasattr(self.db, "save_market_data"):
            try:
                await self.db.save_market_data(data)
            except Exception as e:
                print(f"[publisher] DB save_market_data failed: {e}")

        if self.server is not None and hasattr(self.server, "broadcast"):
            try:
                await self.server.broadcast("MARKET_UPDATE", data)
            except Exception as e:
                print(f"[publisher] MARKET_UPDATE broadcast failed: {e}")

    # ── INVESTIGATION COMPLETE ──

    async def investigation_complete(self, investigation: dict) -> None:
        """
        Persist a completed investigation and broadcast it.
        """
        if self.db is not None and hasattr(self.db, "save_investigation"):
            try:
                await self.db.save_investigation(investigation)
            except Exception as e:
                print(f"[publisher] DB save_investigation failed: {e}")

        if self.server is not None and hasattr(self.server, "broadcast"):
            try:
                await self.server.broadcast("INVESTIGATION_COMPLETE", investigation)
            except Exception as e:
                print(f"[publisher] INVESTIGATION_COMPLETE broadcast failed: {e}")

    # ── SIGNAL ──

    async def signal(
        self,
        token: str,
        chain: str,
        symbol: str,
        verdict: str,
        score: float,
        confidence: float,
    ) -> None:
        """
        Persist and broadcast a trading signal / verdict.
        """
        payload = {
            "token": token,
            "chain": chain,
            "symbol": symbol,
            "verdict": verdict,
            "score": score,
            "confidence": confidence,
            "timestamp": time.time(),
        }

        if self.db is not None and hasattr(self.db, "save_signal"):
            try:
                await self.db.save_signal(payload)
            except Exception as e:
                print(f"[publisher] DB save_signal failed: {e}")

        if self.server is not None and hasattr(self.server, "broadcast"):
            try:
                await self.server.broadcast("SIGNAL", payload)
            except Exception as e:
                print(f"[publisher] SIGNAL broadcast failed: {e}")

    # ── AGENT WORKING (SPINNER) ──

    async def agent_working(
        self,
        agent: str,
        token: str,
        action: str = "working...",
        chain: str = "",
    ) -> None:
        """
        Persist an AGENT_WORKING spinner event to MongoDB so the web-server
        service can poll it, then optionally live-broadcast if co-located.
        """
        payload = {
            "agent": agent,
            "token": token,
            "action": action,
            "chain": chain,
            "timestamp": time.time(),
        }

        # CRITICAL FIX: Persist to DB so split web-server can poll it
        if self.db is not None and hasattr(self.db, "save_event"):
            try:
                await self.db.save_event("AGENT_WORKING", payload)
            except Exception as e:
                print(f"[publisher] DB save_event failed for AGENT_WORKING: {e}")

        # Live broadcast only if server is co-located (monolith mode)
        if self.server is not None and hasattr(self.server, "broadcast"):
            try:
                await self.server.broadcast("AGENT_WORKING", payload)
            except Exception as e:
                print(f"[publisher] AGENT_WORKING broadcast failed: {e}")
