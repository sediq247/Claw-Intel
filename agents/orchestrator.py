#!/usr/bin/env python3
"""
🎛 agents/orchestrator.py
The Conductor — with Database Persistence.
Launches all 5 agents, wires subscriptions, persists to MongoDB.
"""

import asyncio
import os
import sys
import signal
from typing import List

from agents.bridge import make_publish_callable
from utils.database import init_database, db

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
        self._pending_investigations = {}  # token_address -> investigation doc

    def _wire_subscriptions(self):
        _log("Wiring agent pipeline...")

        nova = WatcherAgent(self.publish)
        atlas = SimulatorAgent(self.publish)
        vega = AnalyzerAgent(self.publish)
        echo = MemoryAgent(self.publish)
        orion = DecisionAgent(self.publish)

        # Pipeline: Nova → Atlas → Vega → Echo → Orion
        nova.on_new_token = lambda data: self._on_nova_discovery(data, atlas, echo)
        atlas.on_simulation_complete = lambda data: self._on_simulation(data, vega)
        vega.on_analysis_complete = lambda data: self._on_analysis(data, echo)
        echo.on_memory_intelligence = lambda data: self._on_memory(data, orion)
        orion.on_decision_complete = lambda data: self._on_decision(data)

        self.agents = {
            "nova": nova,
            "atlas": atlas,
            "vega": vega,
            "echo": echo,
            "orion": orion,
        }
        _log(" Agent pipeline wired: Nova → Atlas → Vega → Echo → Orion")

    def _on_nova_discovery(self, data: dict, atlas, echo):
        """Nova found a token — start investigation, persist token, hand to Atlas + Echo."""
        token_address = data.get("token_address")

        # Initialize investigation tracker
        self._pending_investigations[token_address] = {
            "token_address": token_address,
            "chain": data.get("chain"),
            "symbol": data.get("token_symbol"),
            "name": data.get("token_name"),
            "creator": data.get("creator"),
            "discovery_source": data.get("origin_source"),
            "nova_data": data,
            "timestamp": asyncio.get_event_loop().time(),
        }

        # Persist token to DB (fire and forget)
        asyncio.create_task(db.save_token(data))

        # Hand off to next agents
        atlas.on_new_token(data)
        echo.on_new_token(data)

    def _on_simulation(self, data: dict, vega):
        """Atlas finished — add sim data, hand to Vega."""
        token_address = data.get("token_address")
        if token_address in self._pending_investigations:
            self._pending_investigations[token_address]["simulation"] = data
        vega.on_simulation_complete(data)

    def _on_analysis(self, data: dict, echo):
        """Vega finished — add analysis data, hand to Echo."""
        token_address = data.get("token_address")
        if token_address in self._pending_investigations:
            self._pending_investigations[token_address]["analysis"] = data
        echo.on_analysis_complete(data)

    def _on_memory(self, data: dict, orion):
        """Echo finished — add memory data, hand to Orion."""
        token_address = data.get("token")
        if token_address in self._pending_investigations:
            self._pending_investigations[token_address]["memory"] = data

        # Persist creator profile
        creator_data = data.get("profile")
        if creator_data:
            asyncio.create_task(db.save_creator(creator_data))

        orion.on_memory_intelligence(data)

    def _on_decision(self, data: dict):
        """Orion finished — save complete investigation to DB."""
        token_address = data.get("token_address")
        inv = self._pending_investigations.pop(token_address, {})

        investigation = {
            "token_address": token_address,
            "chain": data.get("chain", inv.get("chain")),
            "symbol": data.get("symbol", inv.get("symbol")),
            "verdict": data.get("verdict"),
            "confidence": data.get("confidence"),
            "reasoning": data.get("reasoning"),
            "factors": data.get("factors", {}),
            "simulation": inv.get("simulation", {}),
            "analysis": inv.get("analysis", {}),
            "memory": inv.get("memory", {}),
            "nova_discovery": inv.get("nova_data", {}),
            "timestamp": data.get("timestamp", asyncio.get_event_loop().time()),
        }

        # Persist to DB
        asyncio.create_task(db.save_investigation(investigation))
        _log(f"Investigation saved: {token_address} → {data.get('verdict')}")

    async def start(self):
        self.running = True

        # Initialize database
        _log("Initializing database...")
        await init_database()

        # Wait for Node bridge
        _log("Waiting for Node bridge...")
        ready = await self.bridge.wait_for_node(max_wait=60)
        if not ready:
            _log("Cannot connect to Node. Agents will not start.")
            return

        self._wire_subscriptions()

        _log("\n🚀 CLAW INTEL — Agent Swarm Orchestrator")
        _log("══════════════════════════════════════════")

        nova = self.agents["nova"]
        self._tasks.append(asyncio.create_task(nova.start()))
        _log("👁 Nova (Watcher) started")

        try:
            from utils.marketEngine import MarketEngine
            engine = MarketEngine(self.publish)
            self._tasks.append(asyncio.create_task(engine.start()))
            _log("MarketEngine started")
        except Exception as e:
            _log(f"MarketEngine not started: {e}")

        _log("All agents running\n")

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
        _log("Stopping agent swarm...")
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
        await db.close()
        _log("Agent swarm stopped")


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