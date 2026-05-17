#!/usr/bin/env python3
"""
🎛 agents/orchestrator.py
The Conductor.
Launches all 5 agents in one async process, wires their subscriptions,
and bridges every event to the Node.js eventBus via HTTP.

Run:  python3 -m agents.orchestrator
"""

import asyncio
import os
import signal
import sys
from typing import List

from agents.bridge import make_publish_callable

# Agent imports
from agents.watcher import WatcherAgent
from agents.simulator import SimulatorAgent
from agents.analyzer import AnalyzerAgent
from agents.memory import MemoryAgent
from agents.decision import DecisionAgent


class AgentOrchestrator:
    """
    Single-process conductor for the entire agent swarm.
    """

    def __init__(self):
        self.publish = make_publish_callable()
        self.bridge = self.publish._bridge
        self.agents = {}
        self.running = False
        self._tasks: List[asyncio.Task] = []

    def _wire_subscriptions(self):
        """
        Wire the agent pipeline:
        Nova (watcher) -> Atlas (simulator) -> Vega (analyzer) -> Echo (memory) -> Orion (decision)
        """
        nova = WatcherAgent(self.publish)
        atlas = SimulatorAgent(self.publish)
        vega = AnalyzerAgent(self.publish)
        echo = MemoryAgent(self.publish)
        orion = DecisionAgent(self.publish)

        # Nova discovers → Atlas simulates
        nova.on_new_token = lambda data: atlas.on_new_token(data)

        # Atlas simulates → Vega analyzes
        atlas.on_simulation_complete = lambda data: vega.on_simulation_complete(data)

        # Vega analyzes → Echo updates memory
        vega.on_analysis_complete = lambda data: echo.on_analysis_complete(data)

        # Echo memory + Vega analysis → Orion decides
        echo.on_memory_intelligence = lambda data: orion.on_memory_intelligence(data)

        # Also wire Echo to hear Nova directly for new tokens
        nova.on_new_token_echo = lambda data: echo.on_new_token(data)

        self.agents = {
            "nova": nova,
            "atlas": atlas,
            "vega": vega,
            "echo": echo,
            "orion": orion,
        }

    async def start(self):
        self.running = True
        self._wire_subscriptions()

        print("\n🚀 CLAW INTEL — Agent Swarm Orchestrator")
        print("══════════════════════════════════════════")

        # Start Nova (the watcher) — she drives the pipeline
        nova = self.agents["nova"]
        self._tasks.append(asyncio.create_task(nova.start()))

        # Start market engine if available
        try:
            from utils.marketEngine import MarketEngine
            engine = MarketEngine(self.publish)
            self._tasks.append(asyncio.create_task(engine.start()))
            print("💰 MarketEngine started")
        except Exception as e:
            print(f"⚠️ MarketEngine not started: {e}")

        print("✅ All agents wired and running\n")

        # Keep alive
        while self.running:
            await asyncio.sleep(1)

    async def stop(self):
        print("\n🛑 Stopping agent swarm...")
        self.running = False

        for agent in self.agents.values():
            if hasattr(agent, "stop"):
                try:
                    agent.stop()
                except Exception as e:
                    print(f"⚠️ Error stopping {agent.name}: {e}")

        for task in self._tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        await self.bridge.close()
        print("✅ Agent swarm stopped")


async def main():
    orchestrator = AgentOrchestrator()

    def handle_signal(sig):
        print(f"\n[signal] Received {sig.name}, shutting down...")
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
