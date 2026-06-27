#!/usr/bin/env python3
"""
🌉 agents/bridge.py
Python ↔ Node EventBus Bridge.

BIDIRECTIONAL:
- Outbound: HTTP POST /api/publish → Node.js
- Inbound:  WebSocket → local dispatch to Python subscribers
"""

import os
import sys
import json
import asyncio
from typing import Any, Optional, Callable, Dict, List
from collections import defaultdict, deque

import aiohttp
from aiohttp import WSMsgType

NODE_URL = os.getenv("CLAWINTEL_NODE_URL", "https://clawintel.up.railway.app")
WS_PATH = os.getenv("CLAWINTEL_WS_PATH", "/")
PUBLISH_ENDPOINT = f"{NODE_URL}/api/publish"
HEALTH_ENDPOINT = f"{NODE_URL}/health"


def _log(msg: str):
    print(f"[bridge] {msg}", file=sys.stderr, flush=True)


class NodeBridge:
    """Async bridge to Node.js event bus. HTTP out + WebSocket in."""

    def __init__(self, node_url: str = None, ws_path: str = None):
        self.node_url = node_url or NODE_URL
        self.publish_endpoint = f"{self.node_url}/api/publish"
        self.health_endpoint = f"{self.node_url}/health"

        base_ws = self.node_url.replace("https://", "wss://").replace("http://", "ws://")
        self.ws_url = f"{base_ws}{ws_path or WS_PATH}"

        self._session: Optional[aiohttp.ClientSession] = None
        self._closed = False
        self._ready = False
        self._pending_queue: deque = deque(maxlen=500)
        self._flush_task: Optional[asyncio.Task] = None
        self._ws_task: Optional[asyncio.Task] = None

        # Local subscribers for events coming FROM Node.js
        self._local_subscribers: Dict[str, List[Callable[[Any], None]]] = defaultdict(list)

        _log(f"Initialized. Publish: {self.publish_endpoint} | WS: {self.ws_url}")

    # ─────────────────────────────────────────────────────────
    # Local Subscribe — NEW: receive events from Node.js
    # ─────────────────────────────────────────────────────────

    def subscribe(self, event_type: str, callback: Callable[[Any], None]) -> Callable[[], None]:
        """Subscribe to events arriving from Node.js via WebSocket."""
        self._local_subscribers[event_type].append(callback)
        _log(f"Subscribed to '{event_type}' ({len(self._local_subscribers[event_type])} handlers)")

        def unsubscribe():
            try:
                self._local_subscribers[event_type].remove(callback)
            except ValueError:
                pass
        return unsubscribe

    def _dispatch_local(self, event_type: str, payload: Any):
        """Dispatch an incoming Node.js event to local Python subscribers."""
        for cb in list(self._local_subscribers.get(event_type, [])):
            try:
                cb(payload)
            except Exception as e:
                _log(f"Error in local subscriber for {event_type}: {e}")

    # ─────────────────────────────────────────────────────────
    # WebSocket Listener — NEW: receive events from Node.js
    # ─────────────────────────────────────────────────────────

    async def _ws_listener(self):
        """Background task: maintain WebSocket connection to Node.js."""
        while not self._closed:
            try:
                session = await self._get_session()
                _log(f"Connecting to WebSocket: {self.ws_url}")
                async with session.ws_connect(
                    self.ws_url,
                    heartbeat=30.0,
                    autoping=True,
                ) as ws:
                    _log("✅ WebSocket connected")
                    # Register as backend client
                    await ws.send_json({
                        "type": "REGISTER_BACKEND",
                        "events": ["MANUAL_INVESTIGATE", "REQUEST_MARKET_DATA", "USER_COMMAND"]
                    })
                    async for msg in ws:
                        if msg.type == WSMsgType.TEXT:
                            try:
                                data = msg.json()
                                event_type = data.get("type") or data.get("eventType")
                                payload = data.get("payload")
                                if event_type:
                                    self._dispatch_local(event_type, payload)
                            except Exception as e:
                                _log(f"WS message parse error: {e}")
                        elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSED):
                            break
            except Exception as e:
                _log(f"WebSocket error: {type(e).__name__}: {e}")
            if self._closed:
                break
            _log("WebSocket reconnecting in 5s...")
            await asyncio.sleep(5)

    # ─────────────────────────────────────────────────────────
    # HTTP Publish — existing outbound logic
    # ─────────────────────────────────────────────────────────

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=10)
            )
        return self._session

    async def wait_for_node(self, max_wait: int = 60) -> bool:
        _log(f"Waiting for Node at {self.health_endpoint} (max {max_wait}s)...")
        for attempt in range(max_wait):
            try:
                session = await self._get_session()
                async with session.get(self.health_endpoint, timeout=2) as resp:
                    if resp.status == 200:
                        self._ready = True
                        _log(f"✅ Node is ready! (took {attempt + 1}s)")
                        self._flush_task = asyncio.create_task(self._flush_loop())
                        if not self._ws_task or self._ws_task.done():
                            self._ws_task = asyncio.create_task(self._ws_listener())
                        return True
            except Exception as e:
                if attempt % 5 == 0:
                    _log(f"  ... still waiting ({attempt + 1}s) — {type(e).__name__}")
            await asyncio.sleep(1)
        _log(f"❌ Node failed after {max_wait}s")
        return False

    async def publish(self, event_type: str, payload: Any, retries: int = 5) -> bool:
        if self._closed:
            _log(f"Dropping {event_type} — bridge closed")
            return False
        if not self._ready:
            self._pending_queue.append({"eventType": event_type, "payload": payload})
            _log(f"📦 Queued {event_type} — Node not ready ({len(self._pending_queue)} queued)")
            await self.wait_for_node(max_wait=5)
            return False

        body = {"eventType": event_type, "payload": payload}
        for attempt in range(retries + 1):
            try:
                session = await self._get_session()
                async with session.post(self.publish_endpoint, json=body, timeout=5) as resp:
                    if resp.status == 200:
                        return True
                    text = await resp.text()
                    _log(f"Node HTTP {resp.status}: {text[:200]}")
                    if resp.status == 404:
                        return False
                    if attempt < retries:
                        await asyncio.sleep(min(2 ** attempt, 30))
            except Exception as e:
                _log(f"Publish error (attempt {attempt + 1}): {e}")
                if attempt < retries:
                    await asyncio.sleep(min(2 ** attempt, 30))
                else:
                    self._pending_queue.append(body)
                    return False
        return False

    def publish_sync(self, event_type: str, payload: Any) -> None:
        if self._closed:
            return
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self.publish(event_type, payload))
            task.add_done_callback(lambda t: self._on_publish_done(t, event_type))
        except RuntimeError:
            _log(f"No event loop — cannot publish {event_type}")

    @staticmethod
    def _on_publish_done(task: asyncio.Task, event_type: str):
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            _log(f"⚠️ Background publish ({event_type}) failed: {e}")

    async def _flush_loop(self):
        while not self._closed:
            try:
                if self._pending_queue and self._ready:
                    batch = []
                    while self._pending_queue and len(batch) < 10:
                        batch.append(self._pending_queue.popleft())
                    for msg in batch:
                        try:
                            success = await self.publish(msg["eventType"], msg["payload"], retries=2)
                            if not success:
                                self._pending_queue.appendleft(msg)
                                break
                        except Exception as e:
                            _log(f"⚠️ Flush error: {e}")
                            self._pending_queue.appendleft(msg)
                            break
            except Exception as e:
                _log(f"⚠️ Flush loop error: {e}")
            await asyncio.sleep(5)

    async def close(self):
        self._closed = True
        _log("Closing bridge...")
        for task in (self._flush_task, self._ws_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        if self._pending_queue:
            _log(f"Flushing {len(self._pending_queue)} remaining messages...")
            for msg in list(self._pending_queue):
                try:
                    await self.publish(msg["eventType"], msg["payload"], retries=1)
                except Exception:
                    pass
        if self._session and not self._session.closed:
            await self._session.close()
            _log("✅ Session closed")


def make_publish_callable(node_url: str = None):
    bridge = NodeBridge(node_url)
    def publish(event_type: str, payload: Any):
        bridge.publish_sync(event_type, payload)
    publish._bridge = bridge
    return publish
