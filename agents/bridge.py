#!/usr/bin/env python3
"""
🌉 agents/bridge.py
Python → Node EventBus Bridge.

"""

import os
import sys
import json
import asyncio
from typing import Any, Optional
from collections import deque

import aiohttp

NODE_URL = os.getenv("CLAWINTEL_NODE_URL", "https://clawintel.up.railway.app")
PUBLISH_ENDPOINT = f"{NODE_URL}/api/publish"
HEALTH_ENDPOINT = f"{NODE_URL}/health"


def _log(msg: str):
    """Log to stderr — always visible in Render/Fly/Railway logs."""
    print(f"[bridge] {msg}", file=sys.stderr, flush=True)


class NodeBridge:
    """
    Async bridge to the Node.js event bus.
    Handles reconnection, backoff, and message queuing.
    """

    def __init__(self, node_url: str = None):
        self.node_url = node_url or NODE_URL
        self.publish_endpoint = f"{self.node_url}/api/publish"
        self.health_endpoint = f"{self.node_url}/health"
        self._session: Optional[aiohttp.ClientSession] = None
        self._closed = False
        self._ready = False
        self._pending_queue: deque = deque(maxlen=500)  # Buffer when Node is down
        self._flush_task: Optional[asyncio.Task] = None
        _log(f"Initialized. Publish endpoint: {self.publish_endpoint}")

    # ─────────────────────────────────────────────────────────

    async def _get_session(self) -> aiohttp.ClientSession:
        """Lazy session creation with auto-reconnect."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=10)
            )
        return self._session

    # ─────────────────────────────────────────────────────────

    async def wait_for_node(self, max_wait: int = 60) -> bool:
        """Block until Node /health returns 200. Critical for container startup."""
        _log(f"Waiting for Node at {self.health_endpoint} (max {max_wait}s)...")
        for attempt in range(max_wait):
            try:
                session = await self._get_session()
                async with session.get(self.health_endpoint, timeout=2) as resp:
                    if resp.status == 200:
                        self._ready = True
                        _log(f"✅ Node is ready! (took {attempt + 1}s)")
                        # Start background flush of queued messages
                        self._flush_task = asyncio.create_task(self._flush_loop())
                        return True
            except asyncio.TimeoutError:
                if attempt % 5 == 0:
                    _log(f"  ... health check timed out ({attempt + 1}s)")
            except Exception as e:
                if attempt % 5 == 0:
                    _log(f"  ... still waiting ({attempt + 1}s) — {type(e).__name__}")
            await asyncio.sleep(1)
        _log(f"❌ Node failed to become ready after {max_wait}s")
        return False

    # ─────────────────────────────────────────────────────────

    async def publish(self, event_type: str, payload: Any, retries: int = 5) -> bool:
        """
        Publish an event to the Node bridge.
        If Node is down, queue it for later delivery.
        """
        if self._closed:
            _log(f"Dropping {event_type} — bridge is closed")
            return False

        if not self._ready:
            # Queue the message and try to wake up Node
            self._pending_queue.append({"eventType": event_type, "payload": payload})
            _log(f"📦 Queued {event_type} — Node not ready ({len(self._pending_queue)} queued)")
            # Attempt quick wake-up
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
                    _log(f"Node returned HTTP {resp.status}: {text[:200]}")
                    if resp.status == 404:
                        _log("CRITICAL: /api/publish endpoint not found! Check server.js")
                        return False
                    # For 5xx or other errors, retry
                    if attempt < retries:
                        wait = min(2 ** attempt, 30)
                        _log(f"  Retrying in {wait}s...")
                        await asyncio.sleep(wait)
                    else:
                        return False
            except aiohttp.ClientConnectorError as e:
                _log(f"Connection refused (attempt {attempt + 1}/{retries + 1}): {e}")
                if attempt < retries:
                    wait = min(2 ** attempt, 30)
                    _log(f"  Retrying in {wait}s...")
                    await asyncio.sleep(wait)
                else:
                    # Queue for later flush
                    self._pending_queue.append(body)
                    _log(f"📦 Queued {event_type} for later flush ({len(self._pending_queue)} total)")
                    return False
            except Exception as e:
                _log(f"Unexpected error (attempt {attempt + 1}): {type(e).__name__}: {e}")
                if attempt < retries:
                    await asyncio.sleep(2)
                else:
                    self._pending_queue.append(body)
                    return False

        return False

    # ─────────────────────────────────────────────────────────

    def publish_sync(self, event_type: str, payload: Any) -> None:
        """
        Fire-and-forget publish from sync context.
        Creates an asyncio task that runs in the background.
        """
        if self._closed:
            return

        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self.publish(event_type, payload))
            # Add done callback to catch unhandled exceptions
            task.add_done_callback(
                lambda t: self._on_publish_done(t, event_type)
            )
        except RuntimeError:
            # No event loop running — cannot publish
            _log(f"No event loop — cannot publish {event_type}")

    @staticmethod
    def _on_publish_done(task: asyncio.Task, event_type: str):
        """Log any unhandled exception from a background publish."""
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            _log(f"⚠️ Background publish ({event_type}) failed: {e}")

    # ─────────────────────────────────────────────────────────

    async def _flush_loop(self):
        """Background task that periodically tries to deliver queued messages."""
        while not self._closed:
            try:
                if self._pending_queue and self._ready:
                    # Flush up to 10 messages at a time
                    batch = []
                    while self._pending_queue and len(batch) < 10:
                        batch.append(self._pending_queue.popleft())

                    for msg in batch:
                        try:
                            success = await self.publish(
                                msg["eventType"],
                                msg["payload"],
                                retries=2
                            )
                            if not success:
                                # Re-queue if failed
                                self._pending_queue.appendleft(msg)
                                break  # Stop flushing, Node is struggling
                        except Exception as e:
                            _log(f"⚠️ Flush error: {e}")
                            self._pending_queue.appendleft(msg)
                            break
            except Exception as e:
                _log(f"⚠️ Flush loop error: {e}")

            await asyncio.sleep(5)

    # ─────────────────────────────────────────────────────────

    async def close(self):
        """Graceful shutdown: flush remaining messages, close session."""
        self._closed = True
        _log("Closing bridge...")

        # Cancel flush loop
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        # Final flush attempt
        if self._pending_queue:
            _log(f"Flushing {len(self._pending_queue)} remaining messages...")
            for msg in list(self._pending_queue):
                try:
                    await self.publish(msg["eventType"], msg["payload"], retries=1)
                    self._pending_queue.remove(msg)
                except Exception:
                    pass

        if self._pending_queue:
            _log(f"⚠️ {len(self._pending_queue)} messages dropped — Node never came back")

        # Close session
        if self._session and not self._session.closed:
            await self._session.close()
            _log("✅ Session closed")


# ─────────────────────────────────────────────────────────────
# Callable Factory
# ─────────────────────────────────────────────────────────────

def make_publish_callable(node_url: str = None):
    """
    Create a sync callable that agents can use to fire-and-forget publish.
    The returned function exposes `_bridge` for orchestrator access.
    """
    bridge = NodeBridge(node_url)

    def publish(event_type: str, payload: Any):
        bridge.publish_sync(event_type, payload)

    publish._bridge = bridge
    return publish
