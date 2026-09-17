"""
Orchestrator — The Conductor
============================
Coordinates the multi-agent pipeline and now uses the multi-LLM client for:
- Smarter startup / system messages
- Post-investigation conductor summary
- LLM status awareness
"""

import asyncio
import time
from typing import Optional, Any, Dict

from utils.publisher import EventPublisher
from agents.watcher import WatcherAgent
from agents.simulator import SimulatorAgent
from agents.analyzer import AnalyzerAgent
from agents.memory import InvestigatorAgent
from agents.decision import DecisionAgent
from utils.marketEngine import MarketEngine
from agents.team_debate import run_team_debate

try:
    from agents.llm_client import llm
    HAS_LLM = True
except ImportError:
    llm = None
    HAS_LLM = False


class AgentOrchestrator:
    STAGE_MIN_SECONDS = 10
    REST_SECONDS = 45
    MAX_QUEUE_SIZE = 100

    def __init__(self, server: Any, db: Any):
        self.server = server
        self.db = db
        self.name = "Orchestrator"
        self.running = False
        self.state = "IDLE"
        self.rest_until = 0.0
        self._tasks: list[asyncio.Task] = []
        self.agents: Dict[str, Any] = {}
        self.nova: Optional[WatcherAgent] = None
        self.market_engine: Optional[MarketEngine] = None
        self._current_token: Optional[dict] = None
        self._investigation_lock = asyncio.Lock()

        self.publisher = EventPublisher(db=db, server=server)

    async def start(self):
        self.running = True
        print(f"🎭 {self.name}: Conductor v5.1 starting...")

        # LLM status
        llm_status = "offline (rule-based fallback)"
        if HAS_LLM and llm and llm.is_available:
            providers = ", ".join(llm.status().get("available_providers", []))
            llm_status = f"online → {providers}"
            print(f"✅ {self.name}: Multi-LLM brain {llm_status}")
        else:
            print(f"⚠️ {self.name}: Multi-LLM {llm_status}")

        self.agents = {
            "atlas": SimulatorAgent(server=self.publisher),
            "vega":  AnalyzerAgent(server=self.publisher),
            "echo":  InvestigatorAgent(server=self.publisher, db=self.db),
            "orion": DecisionAgent(server=self.publisher),
        }
        print(f"✅ {self.name}: Agents initialized — Atlas, Vega, Echo, Orion")

        self.nova = WatcherAgent(server=self.publisher, db=self.db, publisher=self.publisher)
        self._tasks.append(asyncio.create_task(self.nova.start()))
        print(f"✅ {self.name}: Nova (Watcher) started as background task")

        self.market_engine = MarketEngine(publisher=self.publisher, db=self.db)
        self._tasks.append(asyncio.create_task(self.market_engine.start()))
        print(f"✅ {self.name}: Market engine started")

        self._tasks.append(asyncio.create_task(self._main_loop()))
        print(f"✅ {self.name}: Main loop started")

        # Smarter startup message (LLM-enhanced when available)
        startup_msg = await self._compose_startup_message(llm_status)
        await self.publisher.system_message(startup_msg)

        while self.running:
            await asyncio.sleep(1)

    async def _compose_startup_message(self, llm_status: str) -> str:
        base = (
            f"ClawIntel v5.1 online. One token at a time, first-come-first-serve. "
            f"Investigation cycle: ~{self.STAGE_MIN_SECONDS * 4}s per token, "
            f"{self.REST_SECONDS}s rest between cases. Multi-LLM: {llm_status}. "
            f"Nova scanning chains..."
        )
        if not (HAS_LLM and llm and llm.is_available):
            return base

        try:
            note = await llm.generate(
                contents=(
                    "Write one short, confident system announcement (max 2 sentences) "
                    "for a multi-agent crypto intelligence platform that just came online. "
                    "Mention the agents are ready and the multi-LLM brain is active. "
                    "No hype, no financial advice."
                ),
                system="You are the Orchestrator of ClawIntel. Speak briefly and precisely.",
                temperature=0.7,
                max_tokens=80,
            )
            if note and len(note.strip()) > 20:
                return note.strip()
        except Exception as e:
            print(f"⚠️ {self.name}: Startup LLM note skipped → {e}")
        return base

    async def stop(self):
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

        if self.market_engine and hasattr(self.market_engine, "stop"):
            try:
                stop_result = self.market_engine.stop()
                if asyncio.iscoroutine(stop_result):
                    await stop_result
            except Exception:
                pass

        print(f"🛑 {self.name}: Conductor stopped.")

    async def _main_loop(self):
        print(f"🎭 {self.name}: Main investigation loop running")
        while self.running:
            try:
                if self.state == "RESTING" and time.time() < self.rest_until:
                    await asyncio.sleep(1)
                    continue

                if self.state == "RESTING":
                    self.state = "IDLE"
                    print(f"🎭 {self.name}: Rest complete. Ready for next token.")

                token = None
                if self.nova and hasattr(self.nova, "get_next_token"):
                    try:
                        token = await self.nova.get_next_token()
                    except Exception as e:
                        print(f"⚠️ {self.name}: Failed to pull token from Nova: {e}")

                if not token:
                    await asyncio.sleep(2)
                    continue

                async with self._investigation_lock:
                    if self.state not in ("IDLE", "RESTING"):
                        await asyncio.sleep(1)
                        continue
                    self.state = "INVESTIGATING"
                    self._current_token = token
                    await self._investigate(token)
                    self._current_token = None

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"❌ {self.name}: Main loop error: {e}")
                self.state = "IDLE"
                await asyncio.sleep(5)

    async def _investigate(self, token: dict):
        symbol = token.get("symbol") or token.get("token_symbol") or "???"
        chain = token.get("chain", "unknown")
        token_address = token.get("token_address", "unknown")

        print(f"🎭 {self.name}: Opening investigation on {symbol} ({chain})")
        await self.publisher.system_message(
            f"New case: {symbol} on {chain}. Atlas → Vega → Echo → Orion."
        )

        # Stage 1: Atlas (simulation)
        sim_data = await self._run_stage(
            agent_name="atlas",
            token=token,
            action="Simulating trade paths",
            completion_event="simulation_complete",
            work_fn=self.agents["atlas"].simulate,
            work_args=(token,),
        )

        # Stage 2: Vega (analysis)
        analysis_data = await self._run_stage(
            agent_name="vega",
            token=token,
            action="Reading contract structure",
            completion_event="analysis_complete",
            work_fn=self.agents["vega"].analyze,
            work_args=(sim_data,),
        )

        # Stage 3: Echo (memory / creator)
        # Merge upstream findings so Echo's LLM refine can see them
        echo_input = {**token, **(sim_data or {}), **(analysis_data or {})}
        memory_data = await self._run_stage(
            agent_name="echo",
            token=token,
            action="Profiling creator & history",
            completion_event="memory_complete",
            work_fn=self.agents["echo"].analyze,
            work_args=(echo_input,),
        )

        # Stage 4: Team debate — agents see each other and argue
        await self.publisher.system_message(
            f"Debate floor open on {symbol}. Atlas, Vega, Echo — react to each other."
        )
        nova_note = (token.get("message") or token.get("nova_message") or "")[:200]
        debate_data = {}
        try:
            debate_data = await run_team_debate(
                symbol=symbol,
                chain=chain,
                sim=sim_data or {},
                analysis=analysis_data or {},
                memory=memory_data,
                nova_note=nova_note,
                speakers=["atlas", "vega", "echo"],
                publisher=self.publisher,
            )
            await self.publisher.broadcast("DEBATE_COMPLETE", {
                "symbol": symbol,
                "chain": chain,
                "transcript": debate_data.get("transcript", []),
                "consensus_notes": debate_data.get("consensus_notes"),
                "disagreements": debate_data.get("disagreements", []),
            })
            print(f"🗣️ {self.name}: Debate complete — conflict={debate_data.get('had_conflict')}")
        except Exception as e:
            print(f"⚠️ {self.name}: Debate stage failed → {e}")
            debate_data = {"transcript": [], "consensus_notes": "", "disagreements": []}

        # Stage 5: Orion (synthesis with full team + debate awareness)
        decision_data = await self._run_stage(
            agent_name="orion",
            token=token,
            action="Synthesizing final judgment (with debate)",
            completion_event="decision_complete",
            work_fn=self.agents["orion"].decide,
            work_args=(sim_data, analysis_data, memory_data, debate_data),
        )

        # Persist investigation
        investigation = {
            "token_address": token_address,
            "chain": chain,
            "symbol": symbol,
            "final_score": decision_data.get("final_score", 0),
            "direction": decision_data.get("direction", "UNKNOWN"),
            "confidence": decision_data.get("confidence", 0),
            "perspective": decision_data.get("perspective", ""),
            "simulation": sim_data,
            "analysis": analysis_data,
            "memory": memory_data,
            "decision": decision_data,
            "debate": debate_data,
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
            direction=decision_data.get("direction", "UNKNOWN"),
            score=decision_data.get("final_score", 0),
            confidence=decision_data.get("confidence", 0),
        )

        try:
            if self.db and hasattr(self.db, "mark_token_completed"):
                await self.db.mark_token_completed(
                    token_address, chain, decision_data.get("direction", "UNKNOWN")
                )
                print(
                    f"✅ {self.name}: Token {symbol} marked completed — "
                    f"direction: {decision_data.get('direction', 'UNKNOWN')}"
                )
        except Exception as e:
            print(f"⚠️ {self.name}: Failed to mark token completed: {e}")

        # Conductor summary (LLM-enhanced when available)
        summary = await self._compose_investigation_summary(
            symbol, chain, decision_data, sim_data, analysis_data, memory_data
        )
        await self.publisher.system_message(summary)

        self.state = "RESTING"
        self.rest_until = time.time() + self.REST_SECONDS
        print(f"😴 {self.name}: Investigation complete. Resting for {self.REST_SECONDS}s.")

    async def _compose_investigation_summary(
        self,
        symbol: str,
        chain: str,
        decision: dict,
        sim: dict,
        analysis: dict,
        memory: Optional[dict],
    ) -> str:
        direction = decision.get("direction", "UNKNOWN")
        score = decision.get("final_score", 0)
        conf = decision.get("confidence", 0)

        base = (
            f"Investigation complete on {symbol} ({chain}). "
            f"Direction: {direction} at {score:.0f}/100 "
            f"({conf*100:.0f}% confidence). Agents resting for {self.REST_SECONDS}s."
        )

        if not (HAS_LLM and llm and llm.is_available):
            return base

        try:
            evidence = {
                "symbol": symbol,
                "chain": chain,
                "direction": direction,
                "score": score,
                "confidence": conf,
                "can_sell": sim.get("can_sell"),
                "honeypot": sim.get("honeypot_risk"),
                "vega_risk": analysis.get("risk_score"),
                "echo_prediction": (memory or {}).get("predicted_outcome"),
            }
            note = await llm.generate(
                contents=(
                    f"Evidence: {evidence}\n\n"
                    "Write a 1-2 sentence conductor summary of this completed investigation. "
                    "Be precise. No financial advice. End by noting the agents are resting."
                ),
                system="You are the Orchestrator of ClawIntel. Speak briefly and with quiet authority.",
                temperature=0.6,
                max_tokens=100,
            )
            if note and len(note.strip()) > 25:
                return note.strip()
        except Exception as e:
            print(f"⚠️ {self.name}: Summary LLM note skipped → {e}")
        return base

    async def _run_stage(
        self,
        agent_name: str,
        token: dict,
        action: str,
        completion_event: str,
        work_fn,
        work_args: tuple,
    ) -> dict:
        symbol = token.get("symbol") or token.get("token_symbol") or "???"
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
            print(f"⏱️ {self.name}: Stage {agent_name} done in {elapsed:.1f}s — waiting {remaining:.1f}s")
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
