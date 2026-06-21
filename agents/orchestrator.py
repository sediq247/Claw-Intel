#!/usr/bin/env python3
"""
agents/orchestrator.py
The Conductor — with Database Persistence, Investigation Pacing, and Forensic Lab.

v2.2 CHANGES:
- MarketEngine is stored as self.market_engine and wired to receive AI_VERDICT
- Orion publishes AI_VERDICT event after decision (frontend + MarketEngine both receive it)
- _on_decision forwards verdict to MarketEngine.add_ai_verified()
- MarketEngine.stop() is awaited properly in orchestrator.stop()
- EventBus bridge listener subscribes to AI_VERDICT from Node.js
"""

import asyncio
import os
import sys
import signal
import time
from typing import List, Optional

from agents.bridge import make_publish_callable
from utils.database import init_database, db

from agents.watcher import WatcherAgent
from agents.simulator import SimulatorAgent
from agents.analyzer import AnalyzerAgent
from agents.memory import MemoryAgent
from agents.decision import DecisionAgent


def _log(msg: str):
    print(f"[orch] {msg}", file=sys.stderr, flush=True)


class InvestigationState:
    IDLE = "IDLE"
    INVESTIGATING = "INVESTIGATING"
    RESTING = "RESTING"


class AgentOrchestrator:
    INVESTIGATION_TIMEOUT = 240
    REST_DURATION = 60
    FORENSIC_TIMEOUT = 300

    def __init__(self):
        self.publish = make_publish_callable()
        self.bridge = self.publish._bridge
        self.agents = {}
        self.market_engine = None
        self.running = False
        self._tasks: List[asyncio.Task] = []
        self._pending_investigations = {}
        self._state = InvestigationState.IDLE
        self._current_investigation_token: Optional[str] = None
        self._investigation_start_time: float = 0
        self._investigation_timer: Optional[asyncio.Task] = None
        self._forensic_queue: asyncio.Queue = asyncio.Queue()
        self._forensic_busy = False

    def _wire_subscriptions(self):
        _log("Wiring agent pipeline...")
        nova = WatcherAgent(self.publish)
        atlas = SimulatorAgent(self.publish)
        vega = AnalyzerAgent(self.publish)
        echo = MemoryAgent(self.publish)
        orion = DecisionAgent(self.publish)

        nova.on_new_token = lambda data: self._on_nova_discovery(data, atlas, echo)
        atlas.on_simulation_complete = lambda data: self._on_simulation(data, vega)
        vega.on_analysis_complete = lambda data: self._on_analysis(data, echo)
        orion.on_decision_complete = lambda data: self._on_decision(data)

        self.agents = {
            "nova": nova,
            "atlas": atlas,
            "vega": vega,
            "echo": echo,
            "orion": orion,
        }
        _log("Agent pipeline wired: Nova → Atlas → Vega → Echo → Orion")

        # Wire MarketEngine to receive AI_VERDICT events
        if self.market_engine:
            self.bridge.subscribe("AI_VERDICT", self.market_engine.on_ai_verdict)
            _log("MarketEngine subscribed to AI_VERDICT events")

    def _set_state(self, new_state: str):
        old_state = self._state
        self._state = new_state
        _log(f"State: {old_state} → {new_state}")
        nova = self.agents.get("nova")
        if nova and hasattr(nova, 'set_busy'):
            nova.set_busy(new_state == InvestigationState.INVESTIGATING)

    def _on_nova_discovery(self, data: dict, atlas, echo):
        token_address = data.get("token_address")
        if self._state != InvestigationState.IDLE:
            _log(f"⏸️ Token {token_address[:12]}... skipped — system is {self._state}")
            return
        self._start_investigation(token_address, data, atlas, echo)

    def _start_investigation(self, token_address: str, data: dict, atlas, echo):
        self._set_state(InvestigationState.INVESTIGATING)
        self._current_investigation_token = token_address
        self._investigation_start_time = time.time()
        self._pending_investigations[token_address] = {
            "token_address": token_address,
            "chain": data.get("chain"),
            "symbol": data.get("token_symbol"),
            "name": data.get("token_name"),
            "creator": data.get("creator"),
            "discovery_source": data.get("origin_source"),
            "nova_data": data,
            "timestamp": time.time(),
            "status": "in_progress"
        }
        _log(f"🔬 Investigation STARTED: {data.get('token_symbol', '???')} on {data.get('chain', '???')}")
        asyncio.create_task(db.save_token(data))
        atlas.on_new_token(data)
        echo.on_new_token(data)
        self._investigation_timer = asyncio.create_task(self._investigation_timeout_watch())

    async def _investigation_timeout_watch(self):
        try:
            await asyncio.sleep(self.INVESTIGATION_TIMEOUT)
            if self._state == InvestigationState.INVESTIGATING:
                token = self._current_investigation_token
                _log(f"⏰ Investigation TIMEOUT for {token[:12]}... — forcing rest")
                self.publish("AGENT_MESSAGE", {
                    "agent": "system",
                    "message": f"Investigation timed out after {self.INVESTIGATION_TIMEOUT}s. Moving to rest.",
                    "type": "system",
                    "channel": "main",
                    "timestamp": time.time()
                })
                await self._start_rest()
        except asyncio.CancelledError:
            pass

    def _on_simulation(self, data: dict, vega):
        token_address = data.get("token_address")
        if token_address in self._pending_investigations:
            self._pending_investigations[token_address]["simulation"] = data
        vega.on_simulation_complete(data)

    def _on_analysis(self, data: dict, echo):
        token_address = data.get("token_address")
        if token_address in self._pending_investigations:
            self._pending_investigations[token_address]["analysis"] = data
        echo.on_analysis_complete(data)

    def _handle_memory_intelligence(self, data: dict):
        token_address = data.get("token_address") or data.get("token")
        if token_address in self._pending_investigations:
            self._pending_investigations[token_address]["memory"] = data
        creator_data = data.get("profile")
        if creator_data:
            asyncio.create_task(db.save_creator(creator_data))
        orion = self.agents.get("orion")
        if orion:
            orion.on_memory_intelligence(data)

    def _on_decision(self, data: dict):
        """Orion finished — save investigation, publish AI_VERDICT, forward to MarketEngine."""
        token_address = data.get("token_address")
        inv = self._pending_investigations.pop(token_address, {})

        verdict = data.get("verdict", "UNKNOWN")
        confidence = data.get("confidence", 0)
        symbol = data.get("symbol", inv.get("symbol", "???"))
        chain = data.get("chain", inv.get("chain", "unknown"))

        investigation = {
            "token_address": token_address,
            "chain": chain,
            "symbol": symbol,
            "verdict": verdict,
            "confidence": confidence,
            "reasoning": data.get("reasoning"),
            "factors": data.get("factors", {}),
            "simulation": inv.get("simulation", {}),
            "analysis": inv.get("analysis", {}),
            "memory": inv.get("memory", {}),
            "nova_discovery": inv.get("nova_data", {}),
            "timestamp": data.get("timestamp", time.time()),
            "status": "completed"
        }

        asyncio.create_task(db.save_investigation(investigation))
        _log(f"✅ Investigation COMPLETE: {token_address} → {verdict}")

        # ───────────────────────────────────────────────
        #  CRITICAL: Publish AI_VERDICT to eventBus
        #  This hits BOTH the frontend (via WebSocket) AND MarketEngine
        # ───────────────────────────────────────────────
        ai_verdict_payload = {
            "token": token_address,
            "token_address": token_address,
            "symbol": symbol,
            "chain": chain,
            "verdict": verdict,
            "confidence": confidence,
            "reasoning": data.get("reasoning", ""),
            "timestamp": time.time()
        }

        self.publish("AI_VERDICT", ai_verdict_payload)
        _log(f"📡 AI_VERDICT published: {symbol} → {verdict} ({confidence:.0%})")

        # Also directly forward to MarketEngine (in-process, zero latency)
        if self.market_engine:
            self.market_engine.on_ai_verdict(ai_verdict_payload)
            _log(f"📊 MarketEngine notified: {symbol} added to AI-verified")

        if self._investigation_timer and not self._investigation_timer.done():
            self._investigation_timer.cancel()
        asyncio.create_task(self._start_rest())

    async def _start_rest(self):
        self._set_state(InvestigationState.RESTING)
        self._current_investigation_token = None
        _log(f"😴 RESTING for {self.REST_DURATION}s...")
        self.publish("AGENT_MESSAGE", {
            "agent": "system",
            "message": f"Agents resting for {self.REST_DURATION} seconds before next investigation.",
            "type": "system",
            "channel": "main",
            "timestamp": time.time()
        })
        await asyncio.sleep(self.REST_DURATION)
        self._set_state(InvestigationState.IDLE)
        _log("👁 Nova resuming surveillance...")
        if not self._forensic_queue.empty() and not self._forensic_busy:
            asyncio.create_task(self._process_forensic_queue())

    async def _handle_manual_investigate(self, payload: dict):
        token_address = payload.get("token_address") or payload.get("tokenAddress")
        chain = payload.get("chain", "ethereum")
        triggered_by = payload.get("triggered_by", "user")
        if not token_address:
            _log("❌ MANUAL_INVESTIGATE missing token_address")
            return
        _log(f"🔍 FORENSIC LAB request: {token_address} on {chain} (by {triggered_by})")
        await self._forensic_queue.put({
            "token_address": token_address,
            "chain": chain,
            "triggered_by": triggered_by,
            "timestamp": time.time()
        })
        if not self._forensic_busy:
            asyncio.create_task(self._process_forensic_queue())

    async def _process_forensic_queue(self):
        if self._forensic_busy:
            return
        self._forensic_busy = True
        nova = self.agents.get("nova")
        try:
            while not self._forensic_queue.empty():
                item = await self._forensic_queue.get()
                _log(f"🔬 Processing forensic request: {item['token_address'][:12]}...")
                if nova and hasattr(nova, 'search_token'):
                    try:
                        result = await asyncio.wait_for(
                            nova.search_token(item["token_address"], item["chain"]),
                            timeout=self.FORENSIC_TIMEOUT
                        )
                        if result:
                            _log(f"✅ Forensic investigation complete for {result.token_symbol}")
                        else:
                            _log(f"⚠️ Forensic investigation returned no result")
                    except asyncio.TimeoutError:
                        _log(f"⏰ Forensic investigation timed out for {item['token_address'][:12]}...")
                    except Exception as e:
                        _log(f"❌ Forensic investigation error: {e}")
                else:
                    _log("❌ Nova agent not available for forensic lab")
                await asyncio.sleep(2)
        finally:
            self._forensic_busy = False

    async def _eventbus_bridge_listener(self):
        """
        Listen for events coming FROM Node.js via the bridge.
        Processes AI_VERDICT events forwarded from Node backend.
        """
        _log("EventBus bridge listener active")
        while self.running:
            try:
                # Poll the bridge for incoming events from Node.js
                # bridge.get_events() should return a list of {type, payload} dicts
                if hasattr(self.bridge, 'get_events'):
                    events = await self.bridge.get_events(timeout=5)
                    for event in events:
                        event_type = event.get("type")
                        payload = event.get("payload", {})

                        if event_type == "AI_VERDICT":
                            _log(f"📥 Bridge received AI_VERDICT from Node: {payload.get('symbol', '???')}")
                            if self.market_engine:
                                self.market_engine.on_ai_verdict(payload)
                        elif event_type == "MANUAL_INVESTIGATE":
                            await self._handle_manual_investigate(payload)
                        elif event_type == "REQUEST_MARKET_DATA":
                            if self.market_engine:
                                self.publish("MARKET_DATA_RESPONSE", self.market_engine.get_all())
                else:
                    # Fallback: just keep alive if bridge doesn't support polling
                    await asyncio.sleep(5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                _log(f"⚠️ Bridge listener error: {e}")
                await asyncio.sleep(5)

    async def start(self):
        self.running = True
        _log("Initializing database...")
        await init_database()
        _log("Waiting for Node bridge...")
        ready = await self.bridge.wait_for_node(max_wait=60)
        if not ready:
            _log("Cannot connect to Node. Agents will not start.")
            return

        # Initialize MarketEngine BEFORE wiring subscriptions
        try:
            from utils.marketEngine import MarketEngine
            # MarketEngine needs publish + subscribe access
            self.market_engine = MarketEngine(
                event_bus_publish=self.publish,
                event_bus_subscribe=self.bridge.subscribe if hasattr(self.bridge, 'subscribe') else None
            )
            _log("📊 MarketEngine initialized")
        except Exception as e:
            _log(f"⚠️ MarketEngine not available: {e}")
            self.market_engine = None

        self._wire_subscriptions()

        _log("\n🚀 CLAW INTEL — Agent Swarm Orchestrator v2.2")
        _log("══════════════════════════════════════════")
        _log(f"Investigation cycle: {self.INVESTIGATION_TIMEOUT}s max + {self.REST_DURATION}s rest")
        _log("Forensic Lab: ENABLED")
        _log("MarketEngine: " + ("ACTIVE" if self.market_engine else "OFFLINE"))
        _log("══════════════════════════════════════════\n")

        nova = self.agents["nova"]
        self._tasks.append(asyncio.create_task(nova.start()))
        _log("👁 Nova (Watcher) started")

        if self.market_engine:
            self._tasks.append(asyncio.create_task(self.market_engine.start()))
            _log("📊 MarketEngine started")

        self._tasks.append(asyncio.create_task(self._eventbus_bridge_listener()))
        _log("🔗 Bridge listener started")

        _log("All agents running\n")
        self.publish("AGENT_MESSAGE", {
            "agent": "system",
            "message": (
                f"ClawIntel v2.2 online. Investigation cycle: "
                f"{self.INVESTIGATION_TIMEOUT//60}min max + {self.REST_DURATION//60}min rest. "
                f"Forensic Lab ready. MarketEngine active. Nova scanning..."
            ),
            "type": "system",
            "channel": "main",
            "timestamp": time.time()
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

        # Gracefully stop MarketEngine
        if self.market_engine and hasattr(self.market_engine, 'stop'):
            try:
                await self.market_engine.stop()
                _log("📊 MarketEngine stopped")
            except Exception as e:
                _log(f"⚠️ Error stopping MarketEngine: {e}")

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


async def init_forensic_api(orchestrator: AgentOrchestrator):
    from aiohttp import web

    async def handle_analyze(request):
        try:
            data = await request.json()
            token_address = data.get("tokenAddress") or data.get("token_address")
            chain = data.get("chain", "ethereum")
            if not token_address:
                return web.json_response({"error": "tokenAddress required"}, status=400)
            await orchestrator._forensic_queue.put({
                "token_address": token_address,
                "chain": chain.lower(),
                "triggered_by": "api",
                "timestamp": time.time()
            })
            if not orchestrator._forensic_busy:
                asyncio.create_task(orchestrator._process_forensic_queue())
            return web.json_response({
                "status": "investigation_queued",
                "tokenAddress": token_address,
                "chain": chain,
                "message": "Agents will investigate. Watch the live feed."
            })
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_memory(request):
        try:
            data = await request.json()
            await orchestrator._handle_memory_intelligence(data)
            return web.json_response({"status": "received"})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_health(request):
        return web.json_response({
            "status": "ok",
            "state": orchestrator._state,
            "current_token": orchestrator._current_investigation_token,
            "forensic_queue_size": orchestrator._forensic_queue.qsize(),
            "agents": list(orchestrator.agents.keys()) if orchestrator.agents else [],
            "market_engine": orchestrator.market_engine is not None,
            "ai_verified_count": len(orchestrator.market_engine.ai_verified_tokens) if orchestrator.market_engine else 0
        })

    app = web.Application()
    app.router.add_post("/api/analyze", handle_analyze)
    app.router.add_post("/api/memory", handle_memory)
    app.router.add_get("/health", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8081)
    await site.start()
    _log("🔬 Forensic API listening on :8081")
    return runner


async def main():
    orchestrator = AgentOrchestrator()
    forensic_runner = None
    try:
        forensic_runner = await init_forensic_api(orchestrator)
    except Exception as e:
        _log(f"⚠️ Forensic API not started: {e}")

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
        if forensic_runner:
            await forensic_runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
