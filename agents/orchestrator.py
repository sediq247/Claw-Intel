#!/usr/bin/env python3
"""
🎛 agents/orchestrator.py
Explicitly waits for bridge to connect before starting agents.
"""

import asyncio
import os
import sys
import signal
from typing import List

from agents.bridge import make_publish_callable, NodeBridge

from agents.watcher import WatcherAgent
from agents.simulator import SimulatorAgent
from agents.analyzer import AnalyzerAgent
from agents.memory import MemoryAgent
from agents.decision import DecisionAgent


def _log(msg: str):
    print(f"[orch] {msg}", file=sys.stderr, flush=True)


class AgentOrchestrator:
    def __init__(self):
        self.publish = make_publish_callable()
        self.bridge = self.publish._bridge
        self.agents = {}
        self.running = False
        self._tasks: List[asyncio.Task] = []

    def _wire_subscriptions(self):
        _log("Wiring agent pipeline...")

        nova = WatcherAgent(self.publish)
        atlas = SimulatorAgent(self.publish)
        vega = AnalyzerAgent(self.publish)
        echo = MemoryAgent(self.publish)
        orion = DecisionAgent(self.publish)

        nova.on_new_token = lambda data: atlas.on_new_token(data)
        atlas.on_simulation_complete = lambda data: vega.on_simulation_complete(data)
        vega.on_analysis_complete = lambda data: echo.on_analysis_complete(data)
        echo.on_memory_intelligence = lambda data: orion.on_memory_intelligence(data)
        nova.on_new_token_echo = lambda data: echo.on_new_token(data)

        self.agents = {
            "nova": nova,
            "atlas": atlas,
            "vega": vega,
            "echo": echo,
            "orion": orion,
        }
        _log("✅ Agent pipeline wired: Nova → Atlas → Vega → Echo → Orion")

    async def start(self):
        self.running = True

        # 🔥 CRITICAL: Wait for bridge to connect to Node before starting agents
        _log("Waiting for Node bridge to be ready...")
        ready = await self.bridge.wait_for_node(max_wait=60)
        if not ready:
            _log("❌ Cannot connect to Node. Agents will not start.")
            return

        self._wire_subscriptions()

        _log("\n🚀 CLAW INTEL — Agent Swarm Orchestrator")
        _log("══════════════════════════════════════════")

        # Start Nova (the watcher)
        nova = self.agents["nova"]
        self._tasks.append(asyncio.create_task(nova.start()))
        _log("👁 Nova (Watcher) started")

        # Start market engine
        try:
            from utils.marketEngine import MarketEngine
            engine = MarketEngine(self.publish)
            self._tasks.append(asyncio.create_task(engine.start()))
            _log("💰 MarketEngine started")
        except Exception as e:
            _log(f"⚠️ MarketEngine not started: {e}")

        _log("✅ All agents running\n")

        # Announce system start
        self.publish("AGENT_MESSAGE", {
            "agent": "system",
            "message": "ClawIntel agent swarm is online. Nova is scanning for new tokens...",
            "type": "system",
            "channel": "main",
            "timestamp": asyncio.get_event_loop().time()
        })

        while self.running:
            await asyncio.sleep(1)

    async def stop(self):
        _log("\n🛑 Stopping agent swarm...")
        self.running = False

        for agent in self.agents.values():
            if hasattr(agent, "stop"):
                try:
                    agent.stop()
                except Exception as e:
                    _log(f"⚠️ Error stopping {agent.name}: {e}")

        for task in self._tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        await self.bridge.close()
        _log("✅ Agent swarm stopped")


async def main():
    orchestrator = AgentOrchestrator()

    def handle_signal(sig):
        _log(f"\n[signal] Received {sig.name}, shutting down...")
        asyncio.create_task(orchestrator.stop())

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: handle_signal(s))

    try:
        await orchestrator.start()
    except asyncio.CancelledError:
        pass
    finally:
        await orchestrator.stop()


if __name__ == "__main__":
    asyncio.run(main())