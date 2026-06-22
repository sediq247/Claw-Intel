#!/usr/bin/env python3
"""
agents/orchestrator.py
The Conductor — with Database Persistence, Investigation Pacing, and Forensic Lab.

v2.2-fix CHANGES:
- Fixed: bridge.subscribe() guarded with hasattr (was crashing on 'NodeBridge' object)
- Fixed: db.close() guarded — client may be None
- Fixed: await async agent.stop() methods (WatcherAgent.stop is async)
- MarketEngine AI_VERDICT forwarding works via in-process call (no bridge needed)
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
    """State machine for investigation pacing."""
    IDLE = "IDLE"
    INVESTIGATING = "INVESTIGATING"
    RESTING = "RESTING"


class AgentOrchestrator:
    """
    The Conductor.

    INVESTIGATION CYCLE:
    1. IDLE: Nova is scanning, tokens are being discovered
    2. INVESTIGATING: A token enters the pipeline. Nova pauses.
       Atlas → Vega → Echo → Orion run sequentially.
       Max duration: 4 minutes (INVESTIGATION_TIMEOUT)
    3. RESTING: After Orion delivers verdict, agents rest.
       Duration: 1 minute (REST_DURATION)
    4. Back to IDLE

    FORENSIC LAB:
    - Listens for MANUAL_INVESTIGATE events from Node.js
    - Immediately triggers Nova.search_token() for user-submitted addresses
    - Bypasses the normal queue for urgent user requests

    WIRING (your real memory.py):
    - MemoryAgent.on_new_token() → starts creator tracking
    - MemoryAgent.on_analysis_complete() → publishes MEMORY_INTELLIGENCE
    - We subscribe to MEMORY_INTELLIGENCE and forward to Orion
    """

    # Timing constants
    INVESTIGATION_TIMEOUT = 240   # 4 minutes max for full investigation
    REST_DURATION = 60            # 1 minute rest between investigations
    FORENSIC_TIMEOUT = 300        # 5 minutes max for forensic investigations

    def __init__(self):
        self.publish = make_publish_callable()
        self.bridge = self.publish._bridge
        self.agents = {}
        self.market_engine = None
        self.running = False
        self._tasks: List[asyncio.Task] = []
        self._pending_investigations = {}  # token_address -> investigation doc

        # State machine
        self._state = InvestigationState.IDLE
        self._current_investigation_token: Optional[str] = None
        self._investigation_start_time: float = 0
        self._investigation_timer: Optional[asyncio.Task] = None

        # Forensic lab queue
        self._forensic_queue: asyncio.Queue = asyncio.Queue()
        self._forensic_busy = False

    def _wire_subscriptions(self):
        _log("Wiring agent pipeline...")

        nova = WatcherAgent(self.publish)
        atlas = SimulatorAgent(self.publish)
        vega = AnalyzerAgent(self.publish)
        echo = MemoryAgent(self.publish)
        orion = DecisionAgent(self.publish)

        # CRITICAL FIX: Set attributes on agents so lambdas can be attached

        # Nova: We set on_new_token as a callable attribute
        # When Nova discovers a token, it calls self.publish("NEW_TOKEN", ...)
        # We subscribe to NEW_TOKEN and route through _on_nova_discovery
        nova.on_new_token = lambda data: self._on_nova_discovery(data, atlas, echo)

        # Atlas: When simulation completes, hand to Vega
        atlas.on_simulation_complete = lambda data: self._on_simulation(data, vega)

        # Vega: When analysis completes, hand to Echo
        vega.on_analysis_complete = lambda data: self._on_analysis(data, echo)

        orion.on_decision_complete = lambda data: self._on_decision(data)

        self.agents = {
            "nova": nova,
            "atlas": atlas,
            "vega": vega,
            "echo": echo,
            "orion": orion,
        }

        _log("Subscribing to MEMORY_INTELLIGENCE from Echo...")

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
        """Transition state machine and notify Nova."""
        old_state = self._state
        self._state = new_state
        _log(f"State: {old_state} → {new_state}")

        nova = self.agents.get("nova")
        if nova and hasattr(nova, 'set_busy'):
            nova.set_busy(new_state == InvestigationState.INVESTIGATING)

    def _on_nova_discovery(self, data: dict, atlas, echo):
        """Nova found a token — start investigation if idle."""
        token_address = data.get("token_address")

        # If we are already investigating, skip this token
        if self._state != InvestigationState.IDLE:
            _log(f"⏸️ Token {token_address[:12]}... skipped — system is {self._state}")
            return

        # Start investigation
        self._start_investigation(token_address, data, atlas, echo)

    def _start_investigation(self, token_address: str, data: dict, atlas, echo):
        """Begin a new investigation cycle."""
        self._set_state(InvestigationState.INVESTIGATING)
        self._current_investigation_token = token_address
        self._investigation_start_time = time.time()

        # Initialize investigation tracker
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

        # Persist token to DB (fire and forget)
        asyncio.create_task(db.save_token(data))

        # Hand off to next agents
        # Atlas starts simulation
        atlas.on_new_token(data)

        # Echo starts tracking creator
        echo.on_new_token(data)
        self._investigation_timer = asyncio.create_task(self._investigation_timeout_watch())

    async def _investigation_timeout_watch(self):
        """Watchdog: if investigation takes too long, force-complete it."""
        try:
            await asyncio.sleep(self.INVESTIGATION_TIMEOUT)

            if self._state == InvestigationState.INVESTIGATING:
                token = self._current_investigation_token
                _log(f"⏰ Investigation TIMEOUT for {token[:12]}... — forcing rest")

                # Force publish a timeout message
                self.publish("AGENT_MESSAGE", {
                    "agent": "system",
                    "message": f"Investigation timed out after {self.INVESTIGATION_TIMEOUT}s. Moving to rest.",
                    "type": "system",
                    "channel": "main",
                    "timestamp": time.time()
                })

                await self._start_rest()
        except asyncio.CancelledError:
            pass  # Normal cancellation when investigation completes

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


    def _handle_memory_intelligence(self, data: dict):
        """
        Handle MEMORY_INTELLIGENCE from Echo.
        Echo publishes this to eventBus. We catch it and forward to Orion.
        """
        token_address = data.get("token_address") or data.get("token")

        if token_address in self._pending_investigations:
            self._pending_investigations[token_address]["memory"] = data

        # Persist creator profile
        creator_data = data.get("profile")
        if creator_data:
            asyncio.create_task(db.save_creator(creator_data))

        # Forward to Orion
        orion = self.agents.get("orion")
        if orion:
            orion.on_memory_intelligence(data)

    def _on_decision(self, data: dict):
        """Orion finished — save complete investigation, publish AI_VERDICT, start rest period."""
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

        # Persist to DB
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

        self.publish("AI_VERDICT", ai_verdict_payload)
        _log(f"📡 AI_VERDICT published: {symbol} → {verdict} ({confidence:.0%})")

        # Also directly forward to MarketEngine (in-process, zero latency)
        if self.market_engine:
            self.market_engine.on_ai_verdict(ai_verdict_payload)
            _log(f"📊 MarketEngine notified: {symbol} added to AI-verified")

        # Cancel timeout timer
        if self._investigation_timer and not self._investigation_timer.done():
            self._investigation_timer.cancel()

        # Start rest period
        asyncio.create_task(self._start_rest())

    async def _start_rest(self):
        """Enter RESTING state for REST_DURATION seconds."""
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

        # Process any forensic queue items
        if not self._forensic_queue.empty() and not self._forensic_busy:
            asyncio.create_task(self._process_forensic_queue())

    # FORENSIC LAB — User-submitted token investigations

    async def _handle_manual_investigate(self, payload: dict):
        """
        Handle MANUAL_INVESTIGATE event from Node.js eventBus.
        User pasted a token address — trigger immediate investigation.
        """
        token_address = payload.get("token_address") or payload.get("tokenAddress")
        chain = payload.get("chain", "ethereum")
        triggered_by = payload.get("triggered_by", "user")

        if not token_address:
            _log("❌ MANUAL_INVESTIGATE missing token_address")
            return

        _log(f"🔍 FORENSIC LAB request: {token_address} on {chain} (by {triggered_by})")

        # Add to forensic queue
        await self._forensic_queue.put({
            "token_address": token_address,
            "chain": chain,
            "triggered_by": triggered_by,
            "timestamp": time.time()
        })

        # Process queue if not already processing
        if not self._forensic_busy:
            asyncio.create_task(self._process_forensic_queue())

    async def _process_forensic_queue(self):
        """Process forensic lab queue items one at a time."""
        if self._forensic_busy:
            return

        self._forensic_busy = True
        nova = self.agents.get("nova")

        try:
            while not self._forensic_queue.empty():
                item = await self._forensic_queue.get()

                _log(f"🔬 Processing forensic request: {item['token_address'][:12]}...")

                # Use Nova's search_token for forensic investigation
                if nova and hasattr(nova, 'search_token'):
                    try:
                        result = await asyncio.wait_for(
                            nova.search_token(item["token_address"], item["chain"]),
                            timeout=self.FORENSIC_TIMEOUT
                        )
                        if result:
                            _log(f"✅ Forensic investigation complete for {result.token_symbol}")

                            # Trigger the full pipeline for forensic results
                            # search_token() already publishes NEW_TOKEN, which triggers Atlas
                        else:
                            _log(f"⚠️ Forensic investigation returned no result")
                    except asyncio.TimeoutError:
                        _log(f"⏰ Forensic investigation timed out for {item['token_address'][:12]}...")
                    except Exception as e:
                        _log(f"❌ Forensic investigation error: {e}")
                else:
                    _log("❌ Nova agent not available for forensic lab")

                # Brief pause between forensic requests
                await asyncio.sleep(2)
        finally:
            self._forensic_busy = False

    # EVENTBUS BRIDGE LISTENER

    async def _eventbus_bridge_listener(self):
        """
        Listen for events coming FROM Node.js via the bridge.
        The bridge queues messages when Node is down.
        We need to process MANUAL_INVESTIGATE and MEMORY_INTELLIGENCE events.

        If the bridge supports polling for incoming events, use it.
        Otherwise we keep the task alive for future WebSocket/SSE implementation.
        """
        _log("EventBus bridge listener active")

        while self.running:
            try:
                # If bridge supports polling for incoming events, use it
                if hasattr(self.bridge, 'get_events') and callable(getattr(self.bridge, 'get_events', None)):
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
                    # Bridge doesn't support polling — keep alive for future implementation
                    await asyncio.sleep(10)
            except asyncio.CancelledError:
                break
            except Exception as e:
                _log(f"⚠️ Bridge listener error: {e}")
                await asyncio.sleep(5)

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

        # Initialize MarketEngine BEFORE wiring subscriptions
        try:
            from utils.marketEngine import MarketEngine
            # MarketEngine needs publish + optional subscribe access
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

        _log("\n🚀 CLAW INTEL — Agent Swarm Orchestrator")
        _log("══════════════════════════════════════════")
        _log(f"Investigation cycle: {self.INVESTIGATION_TIMEOUT}s max + {self.REST_DURATION}s rest")
        _log("Forensic Lab: ENABLED")
        _log("MarketEngine: " + ("ACTIVE" if self.market_engine else "OFFLINE"))
        _log("══════════════════════════════════════════\n")

        nova = self.agents["nova"]
        self._tasks.append(asyncio.create_task(nova.start()))
        _log("👁 Nova (Watcher) started")

        # Start bridge listener
        self._tasks.append(asyncio.create_task(self._eventbus_bridge_listener()))
        _log("🔗 Bridge listener started")

        if self.market_engine:
            self._tasks.append(asyncio.create_task(self.market_engine.start()))
            _log("📊 MarketEngine started")

        _log("All agents running\n")

        # Announce system start
        self.publish("AGENT_MESSAGE", {
            "agent": "system",
            "message": (
                f"ClawIntel v2.2-fix online. Investigation cycle: "
                f"{self.INVESTIGATION_TIMEOUT//60}min max + {self.REST_DURATION//60}min rest. "
                f"Forensic Lab ready. MarketEngine active. Nova scanning..."
            ),
            "type": "system",
            "channel": "main",
            "timestamp": time.time()
        })

        # Keep main loop alive
        while self.running:
            await asyncio.sleep(1)

    async def stop(self):
        _log("Stopping agent swarm...")
        self.running = False

        # FIX: Properly await async stop() methods
        for name, agent in self.agents.items():
            if hasattr(agent, "stop"):
                try:
                    stop_result = agent.stop()
                    if asyncio.iscoroutine(stop_result):
                        await stop_result
                    _log(f"🛑 {name} stopped")
                except Exception as e:
                    _log(f"⚠️ Error stopping {name}: {e}")

        # Gracefully stop MarketEngine
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

        # FIX: Guard db.close() — client may be None
        try:
            if db and hasattr(db, 'close'):
                close_result = db.close()
                if close_result is not None and asyncio.iscoroutine(close_result):
                    await close_result
                _log("Database closed")
        except Exception as e:
            _log(f"⚠️ Error closing database: {e}")

        _log("Agent swarm stopped")
# HTTP API for Forensic Lab (runs alongside the main orchestrator)

from aiohttp import web

async def init_forensic_api(orchestrator: AgentOrchestrator):
    """
    Start a small HTTP server that receives forensic lab requests
    directly from the frontend or from the Node.js backend.

    Endpoints:
    - POST /api/analyze → Queue forensic investigation
    - GET /health → Orchestrator status
    - POST /api/memory → Receive MEMORY_INTELLIGENCE from Echo (internal)
    """

    async def handle_analyze(request):
        try:
            data = await request.json()
            token_address = data.get("tokenAddress") or data.get("token_address")
            chain = data.get("chain", "ethereum")

            if not token_address:
                return web.json_response({"error": "tokenAddress required"}, status=400)

            # Queue the forensic investigation
            await orchestrator._forensic_queue.put({
                "token_address": token_address,
                "chain": chain.lower(),
                "triggered_by": "api",
                "timestamp": time.time()
            })

            # Trigger processing
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
        """Internal endpoint for Echo to deliver MEMORY_INTELLIGENCE."""
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

    # Start forensic API server
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
