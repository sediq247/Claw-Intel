#!/usr/bin/env python3
"""
🗄 utils/database.py
ClawIntel Database Layer.
Async MongoDB client for persisting tokens, investigations, creators, and chat history.
"""

import os
import asyncio
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from bson import ObjectId
from bson.errors import InvalidId

MONGO_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/clawintel")
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
        await self.client.admin.command('ping')
        print(f"[db] ✅ Connected to MongoDB: {DB_NAME}")

        # Create indexes for performance
        await self._create_indexes()
        self._initialized = True

    async def _create_indexes(self):
        """Create indexes for common queries."""
        try:
            await self.db.tokens.create_index("token_address", unique=True)
            await self.db.tokens.create_index("chain")
            await self.db.tokens.create_index([("timestamp", -1)])

            await self.db.creators.create_index("address", unique=True)
            await self.db.creators.create_index([("reputation_score", -1)])

            await self.db.investigations.create_index("token_address")
            await self.db.investigations.create_index([("timestamp", -1)])
            await self.db.investigations.create_index("verdict")

            await self.db.agent_messages.create_index([("timestamp", -1)])
            await self.db.agent_messages.create_index("investigation_id")

            await self.db.market_snapshots.create_index([("timestamp", -1)])

            print("[db] ✅ Indexes created")
        except Exception as e:
            print(f"[db] ⚠️ Index creation warning (may already exist): {e}")

    # ── TOKENS ──
    async def save_token(self, token_data: dict) -> str:
        """Save or update a discovered token."""
        token_data["updated_at"] = datetime.now(timezone.utc)
        token_data.setdefault("timestamp", datetime.now(timezone.utc).timestamp())

        result = await self.db.tokens.update_one(
            {"token_address": token_data["token_address"]},
            {"$set": token_data, "$setOnInsert": {"created_at": datetime.now(timezone.utc)}},
            upsert=True
        )
        return str(result.upserted_id or token_data["token_address"])

    async def get_token(self, token_address: str) -> Optional[dict]:
        return await self.db.tokens.find_one({"token_address": token_address})

    async def get_recent_tokens(self, limit: int = 50, chain: str = None) -> List[dict]:
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
        investigation["updated_at"] = datetime.now(timezone.utc)
        investigation.setdefault("timestamp", datetime.now(timezone.utc).timestamp())

        result = await self.db.investigations.insert_one(investigation)
        return str(result.inserted_id)

    async def get_investigation(self, investigation_id: str) -> Optional[dict]:
        try:
            return await self.db.investigations.find_one({"_id": ObjectId(investigation_id)})
        except InvalidId:
            return None

    async def get_investigations_by_token(self, token_address: str) -> List[dict]:
        cursor = self.db.investigations.find({"token_address": token_address}).sort("timestamp", -1)
        return await cursor.to_list(length=100)

    async def get_recent_investigations(self, limit: int = 50, verdict: str = None) -> List[dict]:
        query = {}
        if verdict:
            query["verdict"] = verdict
        cursor = self.db.investigations.find(query).sort("timestamp", -1).limit(limit)
        return await cursor.to_list(length=limit)

    # ── CREATORS ──
    async def save_creator(self, creator_data: dict) -> str:
        """Save or update a creator profile."""
        creator_data["updated_at"] = datetime.now(timezone.utc)

        result = await self.db.creators.update_one(
            {"address": creator_data["address"]},
            {"$set": creator_data, "$setOnInsert": {"created_at": datetime.now(timezone.utc)}},
            upsert=True
        )
        return str(result.upserted_id or creator_data["address"])

    async def get_creator(self, address: str) -> Optional[dict]:
        return await self.db.creators.find_one({"address": address})

    async def get_top_ruggers(self, limit: int = 20) -> List[dict]:
        cursor = self.db.creators.find({"tags": {"$in": ["repeat_rugger", "honeypot_dev"]}}).sort("scam_flags", -1).limit(limit)
        return await cursor.to_list(length=limit)

    # ── AGENT MESSAGES ──
    async def save_agent_message(self, msg: dict, investigation_id: str = None) -> str:
        """Save an agent chat message."""
        doc = {
            "agent": msg.get("agent"),
            "message": msg.get("message"),
            "type": msg.get("type", "chat"),
            "channel": msg.get("channel", "main"),
            "timestamp": msg.get("timestamp", datetime.now(timezone.utc).timestamp()),
            "investigation_id": investigation_id,
            "created_at": datetime.now(timezone.utc)
        }
        result = await self.db.agent_messages.insert_one(doc)
        return str(result.inserted_id)

    async def get_chat_history(self, limit: int = 100, investigation_id: str = None) -> List[dict]:
        query = {}
        if investigation_id:
            query["investigation_id"] = investigation_id
        cursor = self.db.agent_messages.find(query).sort("timestamp", 1).limit(limit)
        return await cursor.to_list(length=limit)

    # ── MARKET SNAPSHOTS ──
    async def save_market_snapshot(self, snapshot: dict) -> str:
        doc = {
            "trending": snapshot.get("trending", []),
            "gainers": snapshot.get("gainers", []),
            "losers": snapshot.get("losers", []),
            "ai_verified": snapshot.get("ai_verified", []),
            "timestamp": snapshot.get("timestamp", datetime.now(timezone.utc).timestamp()),
            "created_at": datetime.now(timezone.utc)
        }
        result = await self.db.market_snapshots.insert_one(doc)
        return str(result.inserted_id)

    async def get_latest_market_snapshot(self) -> Optional[dict]:
        return await self.db.market_snapshots.find_one(sort=[("timestamp", -1)])

    # ── STATS ──
    async def get_stats(self) -> dict:
        return {
            "total_tokens": await self.db.tokens.estimated_document_count(),
            "total_investigations": await self.db.investigations.estimated_document_count(),
            "total_creators": await self.db.creators.estimated_document_count(),
            "total_messages": await self.db.agent_messages.estimated_document_count(),
            "safe_count": await self.db.investigations.count_documents({"verdict": "SAFE"}),
            "warning_count": await self.db.investigations.count_documents({"verdict": "WARNING"}),
            "high_risk_count": await self.db.investigations.count_documents({"verdict": "HIGH_RISK"}),
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