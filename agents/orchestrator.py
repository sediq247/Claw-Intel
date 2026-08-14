#!/usr/bin/env python3
"""
🎭 ORCHESTRATOR — Conductor v4.0
Theatrical multi-agent investigation conductor.
Polls MongoDB for pending tokens, runs 5-stage theatrical pipeline,
broadcasts AGENT_WORKING spinners, enforces minimum stage duration.

v4.0 CHANGES:
- Constructor accepts server + db
- Deleted PyEventBus, local_bus, event-driven pipeline
- Deleted INVESTIGATION_TIMEOUT, REST_DURATION
- STAGE_MIN_SECONDS = 15, REST_SECONDS = 45, MAX_QUEUE_SIZE = 100
- Reads from DB (get_next_pending_token), not from Nova events
- 5-stage theatrical _run_investigation with AGENT_WORKING broadcasts
- Saves full investigation to DB
- USER_QUERY gets attention_score = 100 (handled in server.py)
- No HTTP API — server handles REST/WebSocket
"""

import asyncio
import time
from typing import Optional, Any, Dict

from agents.watcher import WatcherAgent
from agents.simulator import SimulatorAgent
from agents.analyzer import AnalyzerAgent
from agents.memory import MemoryAgent
from agents.decision import DecisionAgent


class AgentOrchestrator:
    """
    The Conductor.
    Reads pending tokens from DB, runs theatrical 5-stage investigations,
    broadcasts progress to frontend, saves results to DB.
    """

    STAGE_MIN_SECONDS = 15
    REST_SECONDS = 45
    MAX_QUEUE_SIZE = 100

    def __init__(self, server: Any, db: Any):
        self.server = server
        self.db = db
        self.name = "Orchestrator"
        self.running = False
        self.state = "IDLE"  # IDLE, INVESTIGATING, RESTING
        self.rest_until = 0.0
        self._tasks: list[asyncio.Task] = []
        self.agents: Dict[str, Any] = {}
        self.nova: Optional[WatcherAgent] = None

    async def start(self):
        """Initialize agents and start the main loop."""
        self.running = True
        print(f"🎭 {self.name}: Conductor v4.0 starting...")

        # Initialize agents with server (and db for Echo)
        self.agents = {
            "atlas": SimulatorAgent(server=self.server),
            "vega": AnalyzerAgent(server=self.server),
            "echo": MemoryAgent(server=self.server, db=self.db),
            "orion": DecisionAgent(server=self.server),
        }
        print(f"✅ {self.name}: Agents initialized — Atlas, Vega, Echo, Orion")

        # Start Nova as independent background scraper
        self.nova = WatcherAgent(server=self.server, db=self.db)
        self._tasks.append(asyncio.create_task(self.nova.start()))
        print(f"✅ {self.name}: Nova (Watcher) started as background task")

        # Start main investigation loop
        self._tasks.append(asyncio.create_task(self._main_loop()))
        print(f"✅ {self.name}: Main loop started")

        # Broadcast system startup
        await self.server.broadcast("AGENT_MESSAGE", {
            "agent": "system",
            "message": (
                f"ClawIntel v4.0 online. Investigation cycle: ~2-3min per token, "
                f"{self.REST_SECONDS}s rest between cases. Nova scanning 4 chains..."
            ),
            "type": "system",
            "channel": "main",
            "timestamp": time.time()
        })

        # Keep orchestrator alive
        while self.running:
            await asyncio.sleep(1)

    async def stop(self):
        """Graceful shutdown."""
        print(f"🎭 {self.name}: Stopping conductor...")
        self.running = False

        # Stop Nova
        if self.nova and hasattr(self.nova, "stop"):
            try:
                stop_result = self.nova.stop()
                if asyncio.iscoroutine(stop_result):
                    await stop_result
                print(f"🛑 {self.name}: Nova stopped")
            except Exception as e:
                print(f"⚠️ {self.name}: Error stopping Nova: {e}")

        # Stop agents
        for name, agent in self.agents.items():
            if hasattr(agent, "stop"):
                try:
                    stop_result = agent.stop()
                    if asyncio.iscoroutine(stop_result):
                        await stop_result
                    print(f"🛑 {self.name}: {name} stopped")
                except Exception as e:
                    print(f"⚠️ {self.name}: Error stopping {name}: {e}")

        # Cancel tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        print(f"✅ {self.name}: Conductor stopped")

    # ═══════════════════════════════════════════════════════════
    # MAIN LOOP
    # ═══════════════════════════════════════════════════════════

    async def _main_loop(self):
        """Poll DB for pending tokens and run investigations."""
        while self.running:
            try:
                if self.state == "RESTING":
                    if time.time() < self.rest_until:
                        await asyncio.sleep(1)
                        continue
                    self.state = "IDLE"
                    print(f"🎭 {self.name}: Rest period over. Resuming surveillance.")

                if self.state == "IDLE":
                    token = await self._get_next_token()
                    if not token:
                        await asyncio.sleep(3)
                        continue
                    await self._run_investigation(token)

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"❌ {self.name}: Main loop error: {e}")
                await asyncio.sleep(5)

    async def _get_next_token(self) -> Optional[dict]:
        """Fetch the highest-attention pending token from DB."""
        try:
            if self.db and hasattr(self.db, "get_next_pending_token"):
                return await self.db.get_next_pending_token()
            return None
        except Exception as e:
            print(f"⚠️ {self.name}: Failed to get next token: {e}")
            return None

    # ═══════════════════════════════════════════════════════════
    # 5-STAGE THEATRICAL INVESTIGATION
    # ═══════════════════════════════════════════════════════════

    async def _run_investigation(self, token: dict):
        """Run the full 5-stage investigation with theatrical pacing."""
        token_address = token.get("token_address", "unknown")
        chain = token.get("chain", "unknown")
        symbol = token.get("symbol", "???")
        name = token.get("name", "Unknown")
        creator = token.get("creator", "unknown")
        nova_message = token.get("nova_message", f"New token discovered: {symbol}")

        print(f"🎭 {self.name}: Starting investigation on {symbol} ({chain})")
        self.state = "INVESTIGATING"

        # ── Stage 0: Nova's discovery message (read from DB) ──
        await self.server.broadcast("AGENT_MESSAGE", {
            "agent": "Nova",
            "message": nova_message,
            "type": "discovery",
            "channel": "main",
            "timestamp": time.time()
        })

        # ── Stage 1: Atlas (Simulation) ──
        sim_data = await self._run_stage(
            agent_name="Atlas",
            token=token,
            action="simulating trade paths",
            completion_event="SIMULATION_COMPLETE",
            work_fn=self.agents["atlas"].simulate,
            work_args=(token,)
        )

        # ── Stage 2: Vega (Analysis) ──
        analysis_data = await self._run_stage(
            agent_name="Vega",
            token=token,
            action="analyzing contract risks",
            completion_event="ANALYSIS_COMPLETE",
            work_fn=self.agents["vega"].analyze,
            work_args=(sim_data,)
        )

        # ── Stage 3: Echo (Memory) ──
        memory_data = await self._run_stage(
            agent_name="Echo",
            token=token,
            action="searching creator archives",
            completion_event="MEMORY_INTELLIGENCE",
            work_fn=self.agents["echo"].analyze,
            work_args=(token,)
        )

        # ── Stage 4: Orion (Decision) ──
        decision_data = await self._run_stage(
            agent_name="Orion",
            token=token,
            action="weighing evidence",
            completion_event="DECISION_COMPLETE",
            work_fn=self.agents["orion"].decide,
            work_args=(sim_data, analysis_data, memory_data)
        )

        # ── Save full investigation to DB ──
        investigation = {
            "token_address": token_address,
            "chain": chain,
            "symbol": symbol,
            "name": name,
            "creator": creator,
            "verdict": decision_data.get("verdict", "UNKNOWN"),
            "confidence": decision_data.get("confidence", 0),
            "reasoning": decision_data.get("reasoning", ""),
            "action": decision_data.get("action", "UNKNOWN"),
            "simulation": sim_data,
            "analysis": analysis_data,
            "memory": memory_data,
            "decision": decision_data,
            "timestamp": time.time(),
            "status": "completed",
        }
        try:
            if self.db and hasattr(self.db, "save_investigation"):
                await self.db.save_investigation(investigation)
                print(f"💾 {self.name}: Investigation saved for {symbol}")
        except Exception as e:
            print(f"⚠️ {self.name}: Failed to save investigation: {e}")

        # ── Mark token completed ──
        try:
            if self.db and hasattr(self.db, "mark_token_completed"):
                verdict = decision_data.get("verdict", "UNKNOWN")
                await self.db.mark_token_completed(token_address, chain, verdict)
                print(f"✅ {self.name}: Token {symbol} marked completed — verdict: {verdict}")
        except Exception as e:
            print(f"⚠️ {self.name}: Failed to mark token completed: {e}")

        # ── Transition to RESTING ──
        self.state = "RESTING"
        self.rest_until = time.time() + self.REST_SECONDS
        await self.server.broadcast("AGENT_MESSAGE", {
            "agent": "system",
            "message": f"Investigation complete on {symbol}. Verdict: {decision_data.get('verdict', 'UNKNOWN')}. Agents resting for {self.REST_SECONDS}s.",
            "type": "system",
            "channel": "main",
            "timestamp": time.time()
        })
        print(f"😴 {self.name}: Investigation complete. Resting for {self.REST_SECONDS}s.")

    async def _run_stage(
        self,
        agent_name: str,
        token: dict,
        action: str,
        completion_event: str,
        work_fn,
        work_args: tuple
    ) -> dict:
        """
        Run a single investigation stage with theatrical timing.
        1. Broadcast AGENT_WORKING spinner
        2. Run the agent's actual work
        3. Wait until work is done AND at least STAGE_MIN_SECONDS have passed
        4. Broadcast completion event
        5. Broadcast AGENT_MESSAGE if agent returned a message
        """
        symbol = token.get("symbol", "???")
        chain = token.get("chain", "unknown")
        stage_start = time.time()

        # 1. Broadcast AGENT_WORKING spinner
        await self.server.broadcast("AGENT_WORKING", {
            "agent": agent_name,
            "token": symbol,
            "action": action,
            "chain": chain,
            "timestamp": time.time()
        })
        print(f"🎭 {self.name}: Stage {agent_name} started — {action} on {symbol}")

        # 2. Run actual work
        try:
            result = await work_fn(*work_args)
            if result is None:
                result = {}
        except Exception as e:
            print(f"❌ {self.name}: Stage {agent_name} failed: {e}")
            result = {
                "error": str(e),
                "token_address": token.get("token_address"),
                "chain": chain,
                "token_symbol": symbol,
                "message": f"{agent_name} encountered an error analyzing {symbol}: {e}",
            }

        # 3. Enforce minimum stage duration
        elapsed = time.time() - stage_start
        if elapsed < self.STAGE_MIN_SECONDS:
            remaining = self.STAGE_MIN_SECONDS - elapsed
            print(f"⏱️ {self.name}: Stage {agent_name} done in {elapsed:.1f}s — waiting {remaining:.1f}s for theatrical minimum")
            await asyncio.sleep(remaining)

        # 4. Broadcast completion event
        await self.server.broadcast(completion_event, result)
        print(f"✅ {self.name}: Stage {agent_name} complete — {completion_event}")

        # 5. Broadcast AGENT_MESSAGE if the agent produced a spoken message
        if result and result.get("message"):
            await self.server.broadcast("AGENT_MESSAGE", {
                "agent": agent_name,
                "message": result["message"],
                "type": "response",
                "channel": "main",
                "timestamp": time.time()
            })

        return result
