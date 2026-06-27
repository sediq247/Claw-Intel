#!/usr/bin/env python3
"""
agents/orchestrator.py
The Conductor — with Database Persistence, Investigation Pacing, and Forensic Lab.

v3.0-fix CHANGES:
- Added PyEventBus for local agent coordination (fixes agents never running)
- Pipeline events (NEW_TOKEN, SIMULATION_COMPLETE, etc.) routed to local bus
- Only AGENT_MESSAGE, AI_VERDICT, DECISION_COMPLETE go to bridge → frontend
- Removed broken agent.on_* lambda wiring (never executed)
- Forensic lab bypasses state machine (always processes user queries)
"""

import asyncio
import os
import sys
import signal
import time
from typing import List, Optional

from agents.bridge import make_publish_callable
from utils.database import init_database, db
from runtime.py_event_bus import PyEventBus

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
        self.local_bus = PyEventBus()
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

    def _make_publish(self, agent_name: str):
        """
        Create a publish callable that routes pipeline events to local bus
        and chat/system events to the bridge (frontend).
        """
        pipeline_events = {
            "NEW_TOKEN", "SIMULATION_COMPLETE", "ANALYSIS_COMPLETE",
            "CREATOR_INTELLIGENCE", "MEMORY_INTELLIGENCE", "DECISION_COMPLETE"
        }

        def publish(event_type: str, payload: dict):
            if event_type in pipeline_events:
                self.local_bus.publish(event_type, payload)
            else:
                self.publish(event_type, payload)
        return publish

    def _wire_subscriptions(self):
        _log("Wiring agent pipeline via local event bus...")

        # Create agents with the routing wrapper
        nova = WatcherAgent(self._make_publish("Nova"))
        atlas = SimulatorAgent(self._make_publish("Atlas"))
        vega = AnalyzerAgent(self._make_publish("Vega"))
        echo = MemoryAgent(self._make_publish("Echo"))
        orion = DecisionAgent(self._make_publish("Orion"))

        self.agents = {
            "nova": nova,
            "atlas": atlas,
            "vega": vega,
            "echo": echo,
            "orion": orion,
        }

        # Subscribe orchestrator to local bus events to drive the pipeline
        self.local_bus.subscribe("NEW_TOKEN", self._on_nova_discovery)
        self.local_bus.subscribe("SIMULATION_COMPLETE", self._on_simulation)
        self.local_bus.subscribe("ANALYSIS_COMPLETE", self._on_analysis)
        self.local_bus.subscribe("MEMORY_INTELLIGENCE", self._handle_memory_intelligence)
        self.local_bus.subscribe("DECISION_COMPLETE", self._on_decision)

        # Bridge subscriptions for MarketEngine (if bridge supports it)
        if self.market_engine:
            if hasattr(self.bridge, 'subscribe') and callable(getattr(self.bridge, 'subscribe', None)):
                try:
                    self.bridge.subscribe("AI_VERDICT", self.market_engine.on_ai_verdict)
                    _log("MarketEngine subscribed to AI_VERDICT via bridge")
                except Exception as e:
                    _log(f"⚠️ Could not subscribe MarketEngine to AI_VERDICT: {e}")
            else:
                _log("Bridge has no subscribe() — MarketEngine will receive verdicts via in-process forward only")

        _log("Agent pipeline wired: Nova → Atlas → Vega → Echo → Orion")

    def _set_state(self, new_state: str):
        old_state = self._state
        self._state = new_state
        _log(f"State: {old_state} → {new_state}")
        nova = self.agents.get("nova")
        if nova and hasattr(nova, 'set_busy'):
            nova.set_busy(new_state == InvestigationState.INVESTIGATING)

    def _on_nova_discovery(self, data: dict):
        """Nova found a token — start investigation if idle (or if forensic/user query)."""
        token_address = data.get("token_address")
        if not token_address:
            return

        # Forensic/user queries ALWAYS process (bypass state machine)
        if data.get("origin_source") == "user_query":
            _log(f"🔬 Forensic token {token_address[:12]}... — bypassing state machine")
            self._start_investigation(token_address, data)
            return

        # Auto-discovered tokens only process if IDLE
        if self._state != InvestigationState.IDLE:
            _log(f"⏸️ Token {token_address[:12]}... skipped — system is {self._state}")
            return

        self._start_investigation(token_address, data)

    def _start_investigation(self, token_address: str, data: dict):
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

        atlas = self.agents.get("atlas")
        echo = self.agents.get("echo")
        if atlas and hasattr(atlas, 'on_new_token'):
            atlas.on_new_token(data)
        if echo and hasattr(echo, 'on_new_token'):
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

    def _on_simulation(self, data: dict):
        token_address = data.get("token_address")
        if token_address in self._pending_investigations:
            self._pending_investigations[token_address]["simulation"] = data
        vega = self.agents.get("vega")
        if vega and hasattr(vega, 'on_simulation_complete'):
            vega.on_simulation_complete(data)

    def _on_analysis(self, data: dict):
        token_address = data.get("token_address")
        if token_address in self._pending_investigations:
            self._pending_investigations[token_address]["analysis"] = data
        echo = self.agents.get("echo")
        if echo and hasattr(echo, 'on_analysis_complete'):
            echo.on_analysis_complete(data)

    def _handle_memory_intelligence(self, data: dict):
        token_address = data.get("token_address") or data.get("token")
        if token_address in self._pending_investigations:
            self._pending_investigations[token_address]["memory"] = data
        creator_data = data.get("profile")
        if creator_data:
            asyncio.create_task(db.save_creator(creator_data))
        orion = self.agents.get("orion")
        if orion and hasattr(orion, 'on_memory_intelligence'):
            orion.on_memory_intelligence(data)

    def _on_decision(self, data: dict):
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

        # Publish to bridge for frontend dashboard
        self.publish("AI_VERDICT", ai_verdict_payload)
        _log(f"📡 AI_VERDICT published: {symbol} → {verdict} ({confidence:.0%})")

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
        _log("EventBus bridge listener active")
        while self.running:
            try:
                if hasattr(self.bridge, 'get_events') and callable(getattr(self.bridge, 'get_events', None)):
                    events = await self.bridge.get_events(timeout=5)
                    for event in events:
                        event_type = event.get("type")
                        payload = event.get("payload", {})
                        if event_type == "AI_VERDICT":
                            if self.market_engine:
                                self.market_engine.on_ai_verdict(payload)
                        elif event_type == "MANUAL_INVESTIGATE":
                            await self._handle_manual_investigate(payload)
                        elif event_type == "REQUEST_MARKET_DATA":
                            if self.market_engine:
                                self.publish("MARKET_DATA_RESPONSE", self.market_engine.get_all())
                else:
                    await asyncio.sleep(10)
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

        try:
            from utils.marketEngine import MarketEngine
            subscribe_fn = None
            if hasattr(self.bridge, 'subscribe') and callable(getattr(self.bridge, 'subscribe', None)):
                subscribe_fn = self.bridge.subscribe
            self.market_engine = MarketEngine(
                event_bus_publish=self.publish,
                event_bus_subscribe=subscribe_fn
            )
            _log("📊 MarketEngine initialized")
        except Exception as e:
            _log(f"⚠️ MarketEngine not available: {e}")
            self.market_engine = None

        self._wire_subscriptions()

        _log("\n🚀 CLAW INTEL — Agent Swarm Orchestrator v3.0")
        _log("══════════════════════════════════════════")
        _log(f"Investigation cycle: {self.INVESTIGATION_TIMEOUT}s max + {self.REST_DURATION}s rest")
        _log("Forensic Lab: ENABLED")
        _log("MarketEngine: " + ("ACTIVE" if self.market_engine else "OFFLINE"))
        _log("══════════════════════════════════════════\n")

        nova = self.agents["nova"]
        self._tasks.append(asyncio.create_task(nova.start()))
        _log("👁 Nova (Watcher) started")

        self._tasks.append(asyncio.create_task(self._eventbus_bridge_listener()))
        _log("🔗 Bridge listener started")

        if self.market_engine:
            self._tasks.append(asyncio.create_task(self.market_engine.start()))
            _log("📊 MarketEngine started")

        _log("All agents running\n")

        self.publish("AGENT_MESSAGE", {
            "agent": "system",
            "message": (
                f"ClawIntel v3.0 online. Investigation cycle: "
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
        for name, agent in self.agents.items():
            if hasattr(agent, "stop"):
                try:
                    stop_result = agent.stop()
                    if asyncio.iscoroutine(stop_result):
                        await stop_result
                    _log(f"🛑 {name} stopped")
                except Exception as e:
                    _log(f"⚠️ Error stopping {name}: {e}")
        if self.market_engine and hasattr(self.market_engine, 'stop'):
            try:
                stop_result = self.market_engine.stop()
                if asyncio.iscoroutine(stop_result):
                    await stop_result
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
        try:
            if db and hasattr(db, 'close'):
                close_result = db.close()
                if close_result is not None and asyncio.iscoroutine(close_result):
                    await close_result
                _log("Database closed")
        except Exception as e:
            _log(f"⚠️ Error closing database: {e}")
        _log("Agent swarm stopped")


# HTTP API for Forensic Lab
from aiohttp import web

async def init_forensic_api(orchestrator: AgentOrchestrator):
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
