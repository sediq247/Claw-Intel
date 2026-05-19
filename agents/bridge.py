#!/usr/bin/env python3
"""
🌉 ClawIntel Node Bridge
Python → Node EventBus communication layer
"""

import os
import sys
import json
import asyncio
import aiohttp
from typing import Any, List

NODE_URL = os.getenv("CLAWINTEL_NODE_URL", "http://localhost:3000")


def log(msg: str):
    print(f"[bridge] {msg}", file=sys.stderr, flush=True)


class NodeBridge:
    def __init__(self, node_url: str = None):
        self.node_url = node_url or NODE_URL
        self.publish_url = f"{self.node_url}/api/publish"
        self.health_url = f"{self.node_url}/health"

        self.session: aiohttp.ClientSession | None = None
        self.ready = False
        self.closed = False

        # 🔥 BUFFER (prevents message loss)
        self.queue: List[dict] = []

        # 🔥 CIRCUIT BREAKER
        self.failures = 0
        self.max_failures = 5
        self.circuit_open = False

        log(f"Bridge initialized → {self.publish_url}")

    async def _session_get(self):
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15)
            )
        return self.session

    # ----------------------------
    # HEALTH CHECK
    # ----------------------------
    async def wait_for_node(self, max_wait: int = 90):
        log("Waiting for Node server...")

        for i in range(max_wait):
            try:
                session = await self._session_get()
                async with session.get(self.health_url, timeout=3) as r:
                    if r.status == 200:
                        self.ready = True
                        log(f"✅ Node ready after {i}s")
                        return True
            except:
                pass

            await asyncio.sleep(1)

        log("❌ Node never became ready")
        return False

    # ----------------------------
    # SEND EVENT
    # ----------------------------
    async def publish(self, event_type: str, payload: Any):
        if self.closed:
            return False

        body = {"eventType": event_type, "payload": payload}

        # 🔥 queue if circuit is open
        if self.circuit_open:
            self.queue.append(body)
            log(f"Queued event (circuit open): {event_type}")
            return True

        try:
            session = await self._session_get()

            async with session.post(
                self.publish_url,
                json=body,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:

                if resp.status == 200:
                    self.failures = 0
                    return True

                self.failures += 1
                log(f"HTTP {resp.status}")

        except Exception as e:
            self.failures += 1
            log(f"Publish error: {type(e).__name__}: {e}")

        # 🔥 OPEN CIRCUIT BREAKER
        if self.failures >= self.max_failures:
            self.circuit_open = True
            log("⚠️ Circuit breaker OPEN — buffering events")

        return False

    # ----------------------------
    # SYNC WRAPPER
    # ----------------------------
    def publish_sync(self, event_type: str, payload: Any):
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.publish(event_type, payload))
        except RuntimeError:
            self.queue.append({"eventType": event_type, "payload": payload})

    # ----------------------------
    # FLUSH BUFFER
    # ----------------------------
    async def flush(self):
        if not self.queue:
            return

        log(f"Flushing {len(self.queue)} queued events...")

        while self.queue:
            event = self.queue.pop(0)
            await self.publish(event["eventType"], event["payload"])

        self.circuit_open = False
        log("Buffer flushed")

    # ----------------------------
    # CLOSE
    # ----------------------------
    async def close(self):
        self.closed = True
        if self.session:
            await self.session.close()


def make_publish_callable(node_url: str = None):
    bridge = NodeBridge(node_url)

    def publish(event_type: str, payload: Any):
        bridge.publish_sync(event_type, payload)

    publish._bridge = bridge
    return publish