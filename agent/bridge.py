#!/usr/bin/env python3
"""
🌉 agents/bridge.py
Python → Node EventBus Bridge.
Every agent calls this instead of a local print stub.
POSTs events to the Node /api/publish endpoint.
"""

import os
import json
import asyncio
import aiohttp
from typing import Any

NODE_URL = os.getenv("CLAWINTEL_NODE_URL", "http://localhost:3000")
PUBLISH_ENDPOINT = f"{NODE_URL}/api/publish"


class NodeBridge:
    """
    Async HTTP bridge to Node eventBus.
    Fire-and-forget with small retry logic.
    """

    def __init__(self, node_url: str = None):
        self.node_url = node_url or NODE_URL
        self.endpoint = f"{self.node_url}/api/publish"
        self._session: aiohttp.ClientSession | None = None
        self._closed = False

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=5)
            )
        return self._session

    async def publish(self, event_type: str, payload: Any, retries: int = 2):
        """
        Publish an event to the Node eventBus.
        Non-blocking. Retries on transient failures.
        """
        if self._closed:
            return

        body = {"eventType": event_type, "payload": payload}

        for attempt in range(retries + 1):
            try:
                session = await self._get_session()
                async with session.post(self.endpoint, json=body) as resp:
                    if resp.status == 200:
                        return
                    # Log non-2xx but don't raise — fire and forget
                    text = await resp.text()
                    print(f"[bridge] Node returned {resp.status}: {text[:100]}")
                    return
            except Exception as e:
                if attempt < retries:
                    await asyncio.sleep(0.1 * (attempt + 1))
                else:
                    print(f"[bridge] Failed to publish {event_type}: {e}")

    def publish_sync(self, event_type: str, payload: Any):
        """
        Synchronous wrapper for fire-and-forget publishing.
        Creates a new task in the running loop.
        """
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.publish(event_type, payload))
        except RuntimeError:
            # No running loop — use asyncio.run in a thread or just print
            print(f"[bridge] No event loop — dropping {event_type}")

    async def close(self):
        self._closed = True
        if self._session and not self._session.closed:
            await self._session.close()


def make_publish_callable(node_url: str = None):
    """
    Returns a synchronous callable (event_type, payload) -> None
    that the agents can use exactly like their old test_publish.
    """
    bridge = NodeBridge(node_url)

    def publish(event_type: str, payload: Any):
        bridge.publish_sync(event_type, payload)

    # Attach bridge so orchestrator can close it on shutdown
    publish._bridge = bridge
    return publish
