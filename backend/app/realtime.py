import asyncio
from collections import defaultdict
from fastapi import WebSocket


class RealtimeHub:
    def __init__(self):
        self._clients: dict[tuple[str, str], set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def add(self, websocket: WebSocket, department: str, session_id: str):
        async with self._lock:
            self._clients[(department, session_id)].add(websocket)

    async def remove(self, websocket: WebSocket, department: str, session_id: str):
        async with self._lock:
            self._clients[(department, session_id)].discard(websocket)

    async def publish(self, event: dict):
        department = event["department"]
        session_id = str(event.get("session_id") or "")
        async with self._lock:
            targets = set(self._clients.get((department, session_id), set()))
            if department == "autonomous":
                targets |= set(self._clients.get((department, ""), set()))
        for client in targets:
            try:
                await client.send_json(event)
            except Exception:
                await self.remove(client, department, session_id)

    async def close_private_session(self, session_id: str):
        async with self._lock:
            targets = set(self._clients.get(("trading", session_id), set()))
        for client in targets:
            try:
                await client.close(code=1008, reason="Demo wallet disconnected")
            except Exception:
                pass


hub = RealtimeHub()
