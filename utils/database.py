#!/usr/bin/env python3
"""
Async MongoDB client — the single source of truth for tokens, investigations,
creators, and chat history. Singleton pattern, connection pooling.
"""

import os
import asyncio
import time
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ReturnDocument
from bson import ObjectId
from bson.errors import InvalidId

MONGO_URI = os.getenv("MONGO_URI") or os.getenv("MONGODB_URI", "mongodb://localhost:27017/clawintel")
DB_NAME = os.getenv("MONGODB_DB_NAME", "clawintel")


class Database:
    """
    Async MongoDB interface for ClawIntel.
    Singleton pattern — one connection per process.
    """

    _instance = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
            cls._instance.client = None
        return cls._instance

    async def init(self):
        if self._initialized:
            return

        print(f"[db] Connecting to MongoDB...")
        self.client = AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        self.db: AsyncIOMotorDatabase = self.client[DB_NAME]

        # Verify connection
        await self.client.admin.command("ping")
        print(f"[db] ✅ Connected to MongoDB: {DB_NAME}")

        # Create indexes for performance
        await self._create_indexes()
        self._initialized = True

    async def _create_indexes(self):
        """Create indexes for common queries."""
        try:
            # Tokens collection (upsert by compound key)
            await self.db.tokens.create_index(
                [("token_address", 1), ("chain", 1)], unique=True
            )
            await self.db.tokens.create_index("status")
            await self.db.tokens.create_index(
                [("attention_score", -1), ("discovered_at", 1)]
            )
            await self.db.tokens.create_index([("discovered_at", -1)])

            # Creators collection
            await self.db.creators.create_index("address", unique=True)
            await self.db.creators.create_index([("reputation_score", -1)])

            # Investigations collection
            await self.db.investigations.create_index("token_address")
            await self.db.investigations.create_index([("timestamp", -1)])
            await self.db.investigations.create_index("verdict")

            # Agent messages (chat history)
            await self.db.agent_messages.create_index([("timestamp", -1)])
            await self.db.agent_messages.create_index("investigation_id")

            # Market snapshots
            await self.db.market_snapshots.create_index([("timestamp", -1)])

            # Cursors for Nova block tracking
            await self.db.cursors.create_index("chain", unique=True)

            print("[db] ✅ Indexes created")
        except Exception as e:
            print(f"[db] ⚠️ Index creation warning (may already exist): {e}")

    # ── DISCOVERED TOKENS (Nova's queue) ──

    async def save_discovered_token(self, doc: dict) -> str:
        """Save or update a discovered token. Upsert by {token_address, chain}."""
        doc.setdefault("discovered_at", datetime.now(timezone.utc))
        doc.setdefault("timestamp", time.time())
        doc.setdefault("status", "pending")
        doc.setdefault("attention_score", 0)

        token_address = doc["token_address"]
        chain = doc["chain"]

        result = await self.db.tokens.update_one(
            {"token_address": token_address, "chain": chain},
            {
                "$set": doc,
                "$setOnInsert": {"created_at": datetime.now(timezone.utc)},
            },
            upsert=True,
        )
        return str(result.upserted_id or f"{chain}:{token_address}")

    async def get_next_pending_token(self) -> Optional[dict]:
        """
        Atomically pick the highest-attention pending token,
        set status to 'investigating', and return it.
        """
        token = await self.db.tokens.find_one_and_update(
            {"status": "pending"},
            {"$set": {"status": "investigating", "investigated_at": time.time()}},
            sort=[("attention_score", -1), ("discovered_at", 1)],
            return_document=ReturnDocument.AFTER,
        )
        return token

    async def mark_token_completed(self, token_address: str, chain: str, verdict: str):
        """Mark a token as completed with a verdict."""
        await self.db.tokens.update_one(
            {"token_address": token_address, "chain": chain},
            {
                "$set": {
                    "status": "completed",
                    "verdict": verdict,
                    "completed_at": time.time(),
                }
            },
        )

    async def count_pending_tokens(self) -> int:
        return await self.db.tokens.count_documents({"status": "pending"})

    async def get_lowest_attention_in_queue(self) -> Optional[float]:
        """Get the minimum attention_score among pending tokens."""
        doc = await self.db.tokens.find_one(
            {"status": "pending"}, sort=[("attention_score", 1)]
        )
        return doc.get("attention_score") if doc else None

    async def get_discovered_tokens(self, limit: int = 100) -> List[dict]:
        cursor = self.db.tokens.find().sort("discovered_at", -1).limit(limit)
        return await cursor.to_list(length=limit)

    async def get_completed_investigations(self, limit: int = 100) -> List[dict]:
        """Return full investigation records from the investigations collection."""
        cursor = self.db.investigations.find().sort("timestamp", -1).limit(limit)
        return await cursor.to_list(length=limit)

    # ── TOKEN (legacy compat) ──
    async def save_token(self, token_data: dict) -> str:
        """Legacy compat — forwards to save_discovered_token."""
        return await self.save_discovered_token(token_data)

    async def get_token(
        self, token_address: str, chain: Optional[str] = None
    ) -> Optional[dict]:
        query = {"token_address": token_address}
        if chain:
            query["chain"] = chain
        return await self.db.tokens.find_one(query)

    async def get_recent_tokens(
        self, limit: int = 50, chain: str = None
    ) -> List[dict]:
        query = {}
        if chain:
            query["chain"] = chain
        cursor = self.db.tokens.find(query).sort("timestamp", -1).limit(limit)
        return await cursor.to_list(length=limit)

    async def get_token_count(self) -> int:
        return await self.db.tokens.estimated_document_count()

    # ── INVESTIGATIONS ──
    async def save_investigation(self, investigation: dict) -> str:
        """Save a complete investigation pipeline result."""
        investigation.setdefault("timestamp", time.time())
        investigation.setdefault("created_at", datetime.now(timezone.utc))
        result = await self.db.investigations.insert_one(investigation)
        return str(result.inserted_id)

    async def get_investigation(self, investigation_id: str) -> Optional[dict]:
        try:
            return await self.db.investigations.find_one(
                {"_id": ObjectId(investigation_id)}
            )
        except InvalidId:
            return None

    async def get_investigations_by_token(self, token_address: str) -> List[dict]:
        cursor = (
            self.db.investigations.find({"token_address": token_address})
            .sort("timestamp", -1)
        )
        return await cursor.to_list(length=100)

    async def get_recent_investigations(
        self, limit: int = 50, verdict: str = None
    ) -> List[dict]:
        query = {}
        if verdict:
            query["verdict"] = verdict
        cursor = self.db.investigations.find(query).sort("timestamp", -1).limit(limit)
        return await cursor.to_list(length=limit)

    # ── CREATORS ──
    async def save_creator_profile(self, profile: dict) -> str:
        """Save or update a creator profile. Upsert by address."""
        address = profile.get("address")
        if not address:
            raise ValueError("Creator profile missing 'address'")
        profile.setdefault("updated_at", datetime.now(timezone.utc))
        result = await self.db.creators.update_one(
            {"address": address.lower()},
            {
                "$set": profile,
                "$setOnInsert": {"created_at": datetime.now(timezone.utc)},
            },
            upsert=True,
        )
        return str(result.upserted_id or address)

    async def get_creator_profile(self, address: str) -> Optional[dict]:
        return await self.db.creators.find_one({"address": address.lower()})

    async def get_top_ruggers(self, limit: int = 20) -> List[dict]:
        cursor = (
            self.db.creators.find(
                {"tags": {"$in": ["repeat_rugger", "honeypot_dev"]}}
            )
            .sort("scam_flags", -1)
            .limit(limit)
        )
        return await cursor.to_list(length=limit)

    # ── CHAT / AGENT MESSAGES ──
    async def save_chat_message(
        self,
        agent: str,
        message: str,
        msg_type: str = "chat",
        investigation_id: str = None,
    ) -> str:
        """Save an agent chat message."""
        doc = {
            "agent": agent,
            "message": message,
            "type": msg_type,
            "channel": "main",
            "timestamp": time.time(),
            "investigation_id": investigation_id,
            "created_at": datetime.now(timezone.utc),
        }
        result = await self.db.agent_messages.insert_one(doc)
        return str(result.inserted_id)

    async def get_chat_history(
        self, limit: int = 50, investigation_id: str = None
    ) -> List[dict]:
        query = {}
        if investigation_id:
            query["investigation_id"] = investigation_id
        cursor = (
            self.db.agent_messages.find(query).sort("timestamp", -1).limit(limit)
        )
        return await cursor.to_list(length=limit)

    # Legacy compat
    async def save_agent_message(
        self, msg: dict, investigation_id: str = None
    ) -> str:
        return await self.save_chat_message(
            msg.get("agent", "system"),
            msg.get("message", ""),
            msg.get("type", "chat"),
            investigation_id,
        )

    # ── MARKET SNAPSHOTS ──
    async def save_market_snapshot(self, snapshot: dict) -> str:
        doc = {
            "trending": snapshot.get("trending", []),
            "gainers": snapshot.get("gainers", []),
            "losers": snapshot.get("losers", []),
            "ai_verified": snapshot.get("ai_verified", []),
            "timestamp": snapshot.get("timestamp", time.time()),
            "created_at": datetime.now(timezone.utc),
        }
        result = await self.db.market_snapshots.insert_one(doc)
        return str(result.inserted_id)

    async def get_latest_market_snapshot(self) -> Optional[dict]:
        return await self.db.market_snapshots.find_one(sort=[("timestamp", -1)])

    # ── CURSORS (Nova block tracking) ──
    async def get_cursor(self, chain: str) -> Optional[int]:
        doc = await self.db.cursors.find_one({"chain": chain})
        return doc.get("last_block") if doc else None

    async def save_cursor(self, chain: str, last_block: int):
        await self.db.cursors.update_one(
            {"chain": chain},
            {"$set": {"last_block": last_block, "updated_at": time.time()}},
            upsert=True,
        )

    # ── STATS ──
    async def get_stats(self) -> dict:
        return {
            "total_tokens": await self.db.tokens.estimated_document_count(),
            "total_investigations": await self.db.investigations.estimated_document_count(),
            "total_creators": await self.db.creators.estimated_document_count(),
            "total_messages": await self.db.agent_messages.estimated_document_count(),
            "safe_count": await self.db.investigations.count_documents(
                {"verdict": "SAFE"}
            ),
            "warning_count": await self.db.investigations.count_documents(
                {"verdict": "WARNING"}
            ),
            "high_risk_count": await self.db.investigations.count_documents(
                {"verdict": "HIGH_RISK"}
            ),
            "pending_count": await self.db.tokens.count_documents(
                {"status": "pending"}
            ),
            "investigating_count": await self.db.tokens.count_documents(
                {"status": "investigating"}
            ),
        }

    async def close(self):
        if self.client:
            await self.client.close()
            print("[db] ✅ Connection closed")


# Global instance
db = Database()


async def init_database():
    """Initialize database connection. Call once at startup."""
    await db.init()
