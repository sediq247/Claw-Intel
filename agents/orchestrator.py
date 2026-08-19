
"""
 ORCHESTRATOR — Conductor v4.1
Theatrical multi-agent investigation conductor.
Polls MongoDB for pending tokens, runs 5-stage theatrical pipeline,
broadcasts AGENT_WORKING spinners, enforces minimum stage duration.

"""

import asyncio
import time
from typing import Optional, Any, Dict

from utils.publisher import EventPublisher
from agents.watcher import WatcherAgent
from agents.simulator import SimulatorAgent
from agents.analyzer import AnalyzerAgent
from agents.memory import MemoryAgent
from agents.decision import DecisionAgent


class AgentOrchestrator:
    """
    The Conductor.
    Reads pending tokens from DB, runs theatrical 5-stage investigations,
    broadcasts progress to frontend via EventPublisher, saves results to DB.
    """

    STAGE_MIN_SECONDS = 15
    REST_SECONDS = 45
    MAX_QUEUE_SIZE = 100

    def __init__(self, server: Any, db: Any):
        """
        server: ClawIntelServer instance (monolithic) or None (decoupled).
                In decoupled mode, the publisher handles all persistence.
        db:     Database instance for reading/writing token queues, investigations.
        """
        self.server = server
        self.db = db
        self.name = "Orchestrator"
        self.running = False
        self.state = "IDLE"          
        self.rest_until = 0.0
        self._tasks: list[asyncio.Task] = []
        self.agents: Dict[str, Any] = {}
        self.nova: Optional[WatcherAgent] = None

        self.publisher = EventPublisher(db=db, server=server)

    async def start(self):
        """Initialize agents and start the main loop."""
        self.running = True
        print(f"🎭 {self.name}: Conductor v4.1 starting...")

        self.agents = {
            "atlas": SimulatorAgent(server=self.publisher),
            "vega":  AnalyzerAgent(server=self.publisher),
            "echo":  MemoryAgent(server=self.publisher, db=self.db),
            "orion": DecisionAgent(server=self.publisher),
        }
        print(f"✅ {self.name}: Agents initialized — Atlas, Vega, Echo, Orion")

        self.nova = WatcherAgent(server=self.publisher, db=self.db)
        self._tasks.append(asyncio.create_task(self.nova.start()))
        print(f"✅ {self.name}: Nova (Watcher) started as background task")

        self._tasks.append(asyncio.create_task(self._main_loop()))
        print(f"✅ {self.name}: Main loop started")

       
        await self.publisher.system_message(
            f"ClawIntel v4.1 online. Investigation cycle: ~2-3min per token, "
            f"{self.REST_SECONDS}s rest between cases. Nova scanning 4 chains..."
        )

        
        while self.running:
            await asyncio.sleep(1)

    async def stop(self):
        """Graceful shutdown."""
        print(f"🎭 {self.name}: Stopping conductor...")
        self.running = False


        if self.nova and hasattr(self.nova, "stop"):
            try:
                stop_result = self.nova.stop()
                if asyncio.iscoroutine(stop_result):
                    await stop_result
                print(f"🛑 {self.name}: Nova stopped")
            except Exception as e:
                print(f"⚠️ {self.name}: Error stopping Nova: {e}")

    
        for name, agent in self.agents.items():
            if hasattr(agent, "stop"):
                try:
                    stop_result = agent.stop()
                    if asyncio.iscoroutine(stop_result):
                        await stop_result
                    print(f"🛑 {self.name}: {name} stopped")
                except Exception as e:
                    print(f"⚠️ {self.name}: Error stopping {name}: {e}")

        
        for task in self._tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        print(f"✅ {self.name}: Conductor stopped")

    

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

        await self.publisher.agent_message(
            "Nova", nova_message, "discovery"
        )

        # ── Stage 1: Atlas (Simulation) ──
        sim_data = await self._run_stage(
            agent_name="Atlas",
            token=token,
            action="simulating trade paths",
            completion_event="SIMULATION_COMPLETE",
            work_fn=self.agents["atlas"].simulate,
            work_args=(token,)
        )

        analysis_data = await self._run_stage(
            agent_name="Vega",
            token=token,
            action="analyzing contract risks",
            completion_event="ANALYSIS_COMPLETE",
            work_fn=self.agents["vega"].analyze,
            work_args=(sim_data,)
        )
        memory_data = await self._run_stage(
            agent_name="Echo",
            token=token,
            action="searching creator archives",
            completion_event="MEMORY_INTELLIGENCE",
            work_fn=self.agents["echo"].analyze,
            work_args=(token,)
        )

        decision_data = await self._run_stage(
            agent_name="Orion",
            token=token,
            action="weighing evidence",
            completion_event="DECISION_COMPLETE",
            work_fn=self.agents["orion"].decide,
            work_args=(sim_data, analysis_data, memory_data)
        )
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

        await self.publisher.investigation_complete(investigation)

        await self.publisher.signal(
            token=token_address,
            chain=chain,
            symbol=symbol,
            verdict=decision_data.get("verdict", "UNKNOWN"),
            score=decision_data.get("final_score", 0),
            confidence=decision_data.get("confidence", 0),
        )

        try:
            if self.db and hasattr(self.db, "mark_token_completed"):
                verdict = decision_data.get("verdict", "UNKNOWN")
                await self.db.mark_token_completed(token_address, chain, verdict)
                print(f"✅ {self.name}: Token {symbol} marked completed — verdict: {verdict}")
        except Exception as e:
            print(f"⚠️ {self.name}: Failed to mark token completed: {e}")

        self.state = "RESTING"
        self.rest_until = time.time() + self.REST_SECONDS
        await self.publisher.system_message(
            f"Investigation complete on {symbol}. Verdict: {decision_data.get('verdict', 'UNKNOWN')}. "
            f"Agents resting for {self.REST_SECONDS}s."
        )
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

        await self.publisher.agent_working(
            agent=agent_name,
            token=symbol,
            action=action,
            chain=chain,
        )
        print(f"🎭 {self.name}: Stage {agent_name} started — {action} on {symbol}")

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

        elapsed = time.time() - stage_start
        if elapsed < self.STAGE_MIN_SECONDS:
            remaining = self.STAGE_MIN_SECONDS - elapsed
            print(f"⏱️ {self.name}: Stage {agent_name} done in {elapsed:.1f}s — waiting {remaining:.1f}s for theatrical minimum")
            await asyncio.sleep(remaining)

        await self.publisher.broadcast(completion_event, result)
        print(f"✅ {self.name}: Stage {agent_name} complete — {completion_event}")

        if result and result.get("message"):
            await self.publisher.agent_message(
                agent=agent_name,
                message=result["message"],
                msg_type="response",
            )

        return result
