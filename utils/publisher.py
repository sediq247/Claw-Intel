"""
EVENT PUBLISHER — v4.1
Decoupled broadcast + persistence layer.
Saves all events to MongoDB, optionally broadcasts via WebSocket.
Used by both agents and server event-polling loop.
"""

import time
from typing import Optional, Any


class EventPublisher:
    """
    v4.1: Decoupled publisher.
    - All events persisted to MongoDB via db.save_event()
    - Optional live broadcast via server.broadcast()
    - server can be None (agents_main.py runs without WS server)
    """

    def __init__(self, db: Optional[Any] = None, server: Optional[Any] = None):
        self.db = db
        self.server = server

    async def broadcast(self, event_type: str, payload: dict):
        """Persist to DB + optional live WS broadcast."""
        try:
            if self.db and hasattr(self.db, "save_event"):
                await self.db.save_event(event_type, payload)
        except Exception as e:
            print(f"⚠️ Publisher: DB save failed: {e}")

        if self.server and hasattr(self.server, "broadcast"):
            try:
                await self.server.broadcast(event_type, payload)
            except Exception as e:
                print(f"⚠️ Publisher: WS broadcast failed: {e}")

    async def agent_message(self, agent: str, message: str, msg_type: str = "response"):
        """Save chat message to DB + broadcast AGENT_MESSAGE."""
        payload = {
            "agent": agent,
            "message": message,
            "type": msg_type,
            "channel": "main",
            "timestamp": time.time(),
        }
        try:
            if self.db and hasattr(self.db, "save_chat_message"):
                await self.db.save_chat_message(agent, message, msg_type)
        except Exception as e:
            print(f"⚠️ Publisher: Chat save failed: {e}")
        await self.broadcast("AGENT_MESSAGE", payload)

    async def agent_working(self, agent: str, token: str, action: str, chain: str = ""):
        """Broadcast AGENT_WORKING spinner. Not persisted to chat history."""
        payload = {
            "agent": agent,
            "token": token,
            "action": action,
            "chain": chain,
            "timestamp": time.time(),
        }
        await self.broadcast("AGENT_WORKING", payload)

    async def system_message(self, message: str):
        """Broadcast a system message."""
        payload = {
            "message": message,
            "timestamp": time.time(),
        }
        await self.broadcast("SYSTEM", payload)

    async def new_token(self, token_data: dict):
        """Save discovered token to DB."""
        try:
            if self.db and hasattr(self.db, "save_discovered_token"):
                discovered_doc = {
                    "token_address": token_data.get("address") or token_data.get("token_address"),
                    "address": token_data.get("address") or token_data.get("token_address"),
                    "chain": token_data.get("chain", "unknown"),
                    "symbol": token_data.get("symbol", "???"),
                    "name": token_data.get("name", "Unknown"),
                    "creator": token_data.get("creator", "unknown"),
                    "liquidity_usd": token_data.get("liquidity_usd"),
                    "market_cap": token_data.get("market_cap"),
                    "volume_24h": token_data.get("volume_24h"),
                    "attention_score": token_data.get("attention_score", 0),
                    "status": "pending",
                    "discovered_at": time.time(),
                    "origin_source": token_data.get("origin_source", "unknown"),
                    "raw_data": token_data.get("raw_data"),
                }
                await self.db.save_discovered_token(discovered_doc)
        except Exception as e:
            print(f"⚠️ Publisher: Token save failed: {e}")

    async def signal(self, token: str, chain: str, symbol: str, verdict: str, score: float, confidence: float):
        """Save AI signal to DB + broadcast + save as event for market engine polling."""
        signal_doc = {
            "token": token,
            "chain": chain,
            "symbol": symbol,
            "verdict": verdict,
            "score": score,
            "confidence": confidence,
            "timestamp": time.time(),
        }
        try:
            if self.db and hasattr(self.db, "save_signal"):
                await self.db.save_signal(signal_doc)
        except Exception as e:
            print(f"⚠️ Publisher: Signal save failed: {e}")

        # FIX: Also save to events collection so market engine can poll it
        try:
            if self.db and hasattr(self.db, "save_event"):
                await self.db.save_event("SIGNAL", signal_doc)
        except Exception as e:
            print(f"⚠️ Publisher: Signal event save failed: {e}")

        await self.broadcast("SIGNAL", signal_doc)

    async def investigation_complete(self, investigation: dict):
        """Broadcast investigation completion."""
        await self.broadcast("INVESTIGATION_COMPLETE", investigation)

    async def market_update(self, market_data: dict):
        """Save market snapshot to DB + broadcast MARKET_UPDATE."""
        try:
            if self.db and hasattr(self.db, "save_market_data"):
                await self.db.save_market_data(market_data)
        except Exception as e:
            print(f"⚠️ Publisher: Market data save failed: {e}")
        await self.broadcast("MARKET_UPDATE", market_data)
