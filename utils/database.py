import os
import time
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, DESCENDING

MONGO_URI = os.getenv("MONGODB_URI") or os.getenv("MONGO_URI", "mongodb://localhost:27017/clawintel")


class Database:
    def __init__(self):
        self.client: Optional[AsyncIOMotorClient] = None
        self.db = None

    async def init(self):
        self.client = AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        self.db = self.client.clawintel
        await self.client.admin.command("ping")
        print("[db] ✅ Connected to MongoDB: clawintel")
        await self._create_indexes()

    async def _create_indexes(self):
        await self.db.chat_messages.create_index([("timestamp", DESCENDING)])
        await self.db.chat_messages.create_index([("agent", ASCENDING)])
        await self.db.discovered_tokens.create_index([("discovered_at", DESCENDING)])
        await self.db.discovered_tokens.create_index([("status", ASCENDING)])
        await self.db.discovered_tokens.create_index([("token_address", ASCENDING)])
        await self.db.tokens_queue.create_index([("timestamp", DESCENDING)])
        await self.db.tokens_queue.create_index([("status", ASCENDING)])
        await self.db.investigations.create_index([("timestamp", DESCENDING)])
        await self.db.investigations.create_index([("token_address", ASCENDING)])
        await self.db.creator_profiles.create_index([("address", ASCENDING)], unique=True)
        await self.db.events.create_index([("timestamp", ASCENDING)])
        await self.db.events.create_index(
            [("created_at", ASCENDING)], expireAfterSeconds=86400
        )
        await self.db.market_data.create_index([("updated_at", DESCENDING)])
        await self.db.signals.create_index([("timestamp", DESCENDING)])
        await self.db.discovered_tokens.create_index([("symbol", ASCENDING)])
        await self.db.discovered_tokens.create_index([("name", ASCENDING)])
        await self.db.discovered_tokens.create_index([("address", ASCENDING)])

        print("[db] ✅ Indexes created")

    async def save_chat_message(
        self,
        agent: str,
        message: str,
        msg_type: str = "chat",
        channel: str = "main",
    ) -> str:
        doc = {
            "agent": agent,
            "message": message,
            "type": msg_type,
            "channel": channel,
            "timestamp": time.time(),
            "created_at": datetime.now(timezone.utc),
        }
        result = await self.db.chat_messages.insert_one(doc)
        return str(result.inserted_id)

    async def get_chat_history(self, limit: int = 50) -> List[dict]:
        cursor = (
            self.db.chat_messages.find()
            .sort("timestamp", DESCENDING)
            .limit(limit)
        )
        msgs = await cursor.to_list(length=limit)
        for m in msgs:
            m["_id"] = str(m["_id"])
        return msgs

    async def save_discovered_token(self, token: dict) -> str:
        doc = {
            **token,
            "created_at": datetime.now(timezone.utc),
        }
        result = await self.db.discovered_tokens.insert_one(doc)
        return str(result.inserted_id)

    async def get_discovered_tokens(self, limit: int = 100) -> List[dict]:
        cursor = (
            self.db.discovered_tokens.find()
            .sort("discovered_at", DESCENDING)
            .limit(limit)
        )
        tokens = await cursor.to_list(length=limit)
        for t in tokens:
            t["_id"] = str(t["_id"])
        return tokens

    async def add_token_to_queue(self, token: dict) -> str:
        doc = {
            **token,
            "status": "pending",
            "timestamp": time.time(),
            "created_at": datetime.now(timezone.utc),
        }
        result = await self.db.tokens_queue.insert_one(doc)
        return str(result.inserted_id)

    async def get_token_queue(self, limit: int = 100) -> List[dict]:
        cursor = (
            self.db.tokens_queue.find({"status": "pending"})
            .sort("timestamp", ASCENDING)
            .limit(limit)
        )
        tokens = await cursor.to_list(length=limit)
        for t in tokens:
            t["_id"] = str(t["_id"])
        return tokens

    async def count_pending_tokens(self) -> int:
        return await self.db.tokens_queue.count_documents({"status": "pending"})

    async def update_token_status(self, token_address: str, status: str):
        await self.db.tokens_queue.update_one(
            {"address": token_address},
            {"$set": {"status": status, "updated_at": time.time()}},
        )
    async def save_investigation(self, investigation: dict) -> str:
        doc = {
            **investigation,
            "created_at": datetime.now(timezone.utc),
        }
        result = await self.db.investigations.insert_one(doc)
        return str(result.inserted_id)

    async def get_completed_investigations(self, limit: int = 100) -> List[dict]:
        cursor = (
            self.db.investigations.find()
            .sort("timestamp", DESCENDING)
            .limit(limit)
        )
        invs = await cursor.to_list(length=limit)
        for i in invs:
            i["_id"] = str(i["_id"])
        return invs

    async def save_creator_profile(self, profile: dict):
        address = profile.get("address")
        if not address:
            return
        await self.db.creator_profiles.update_one(
            {"address": address},
            {"$set": {**profile, "updated_at": time.time()}},
            upsert=True,
        )

    async def get_creator_profile(self, address: str) -> Optional[dict]:
        return await self.db.creator_profiles.find_one({"address": address})
    async def save_event(self, event_type: str, payload: dict) -> str:
        """Write an event to the events stream for the server to poll."""
        doc = {
            "event_type": event_type,
            "payload": payload,
            "timestamp": time.time(),
            "created_at": datetime.now(timezone.utc),
        }
        result = await self.db.events.insert_one(doc)
        return str(result.inserted_id)

    async def get_recent_events(self, since: float = 0, limit: int = 500) -> List[dict]:
        """Fetch events newer than `since` timestamp (ascending order)."""
        cursor = (
            self.db.events.find({"timestamp": {"$gt": since}})
            .sort("timestamp", ASCENDING)
            .limit(limit)
        )
        events = await cursor.to_list(length=limit)
        for e in events:
            e["_id"] = str(e["_id"])
        return events

    async def save_market_data(self, data: dict):
        """Upsert the latest market snapshot (single doc, always overwritten)."""
        doc = {
            **data,
            "updated_at": datetime.now(timezone.utc),
        }
        await self.db.market_data.update_one(
            {"_id": "latest"},
            {"$set": doc},
            upsert=True,
        )

    async def get_market_data(self) -> dict:
        """Retrieve the latest market snapshot."""
        doc = await self.db.market_data.find_one({"_id": "latest"})
        if doc:
            doc.pop("_id", None)
            return doc
        return {
            "trending": [],
            "gainers": [],
            "losers": [],
            "ai_verified": [],
            "timestamp": 0,
        }
    async def save_signal(self, signal: dict):
        await self.db.signals.insert_one({
            **signal,
            "created_at": datetime.now(timezone.utc),
        })

    async def get_signals(self, limit: int = 50) -> List[dict]:
        cursor = (
            self.db.signals.find()
            .sort("timestamp", DESCENDING)
            .limit(limit)
        )
        sigs = await cursor.to_list(length=limit)
        for s in sigs:
            s["_id"] = str(s["_id"])
        return sigs
    async def search_tokens(self, query: str, limit: int = 50) -> List[dict]:
        """Search discovered_tokens by symbol, name, or address (case-insensitive)."""
        regex = {"$regex": query, "$options": "i"}
        filter_doc = {
            "$or": [
                {"symbol": regex},
                {"name": regex},
                {"address": regex},
                {"token_address": regex},
            ]
        }
        cursor = (
            self.db.discovered_tokens.find(filter_doc)
            .sort("discovered_at", DESCENDING)
            .limit(limit)
        )
        results = await cursor.to_list(length=limit)
        for r in results:
            r["_id"] = str(r["_id"])
        return results

    async def get_stats(self) -> dict:
        total_tokens = await self.db.discovered_tokens.estimated_document_count()
        total_investigations = await self.db.investigations.estimated_document_count()
        total_creators = await self.db.creator_profiles.estimated_document_count()
        total_messages = await self.db.chat_messages.estimated_document_count()

        safe_count = await self.db.investigations.count_documents({"verdict": "SAFE"})
        warning_count = await self.db.investigations.count_documents({"verdict": "WARNING"})
        high_risk_count = await self.db.investigations.count_documents({"verdict": "HIGH_RISK"})

        return {
            "total_tokens": total_tokens,
            "total_investigations": total_investigations,
            "total_creators": total_creators,
            "total_messages": total_messages,
            "safe_count": safe_count,
            "warning_count": warning_count,
            "high_risk_count": high_risk_count,
        }

    async def close(self):
        if self.client:
            self.client.close()
            print("[db] ✅ Connection closed")
db = Database()


async def init_database():
    await db.init()
