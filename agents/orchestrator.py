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
        print(f"🎭 {self.name}: Conductor v5.0 starting...")

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

        await self.publisher.system_message(
            f"ClawIntel v5.0 online. One token at a time, first-come-first-serve. "
            f"Investigation cycle: ~{self.STAGE_MIN_SECONDS * 4}s per token, "
            f"{self.REST_SECONDS}s rest between cases. Nova scanning chains..."
        )

        while self.running:
            await asyncio.sleep(1)

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
                print(f"🛑 {self.name}: Market engine stopped")
            except Exception as e:
                print(f"⚠️ {self.name}: Error stopping market engine: {e}")

        print(f"✅ {self.name}: Conductor stopped")

    async def _main_loop(self):
        while self.running:
            try:
                if self.state == "RESTING":
                    now = time.time()
                    if now < self.rest_until:
                        remaining = int(self.rest_until - now)
                        if remaining % 10 == 0:
                            print(f"😴 {self.name}: Resting... {remaining}s remaining")
                        await asyncio.sleep(1)
                        continue
                    self.state = "IDLE"
                    print(f"🎭 {self.name}: Rest period over. Resuming surveillance.")
                    await self.publisher.system_message("Agents rested. Resuming token surveillance.")

                if self.state == "IDLE":
                    async with self._investigation_lock:
                        if self.state != "IDLE":
                            await asyncio.sleep(1)
                            continue
                        token = await self._get_next_token()
                        if not token:
                            await asyncio.sleep(3)
                            continue
                        self._current_token = token
                        self.state = "INVESTIGATING"

                    await self._run_investigation(token)
                    self._current_token = None

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"❌ {self.name}: Main loop error: {e}")
                self._current_token = None
                self.state = "IDLE"
                await asyncio.sleep(5)

    async def _get_next_token(self) -> Optional[dict]:
        try:
            if not self.db or not hasattr(self.db, "get_next_pending_token"):
                return None

            token = await self.db.get_next_pending_token()
            if not token:
                return None

            addr = token.get("token_address", "")
            chain = token.get("chain", "")
            if not addr or not chain:
                print(f"⚠️ {self.name}: Skipping token with missing address or chain")
                try:
                    if hasattr(self.db, "mark_token_completed"):
                        await self.db.mark_token_completed(addr or "unknown", chain or "unknown", "INVALID")
                except Exception:
                    pass
                return None

            try:
                if hasattr(self.db, "mark_token_investigating"):
                    await self.db.mark_token_investigating(addr, chain)
                    print(f"🔒 {self.name}: Marked {token.get('symbol', '???')} as investigating")
                elif hasattr(self.db, "update_token_status"):
                    await self.db.update_token_status(addr, chain, "investigating")
                    print(f"🔒 {self.name}: Marked {token.get('symbol', '???')} as investigating")
            except Exception as e:
                print(f"⚠️ {self.name}: Failed to mark token investigating: {e}")

            return token

        except Exception as e:
            print(f"⚠️ {self.name}: Failed to get next token: {e}")
            return None

    async def _run_investigation(self, token: dict):
        token_address = token.get("token_address", "unknown")
        chain = token.get("chain", "unknown")
        symbol = token.get("symbol", "???")
        name = token.get("name", "Unknown")
        creator = token.get("creator", "unknown")
        nova_message = token.get("nova_message", f"New token discovered: {symbol}")

        print(f"🎭 {self.name}: Starting investigation on {symbol} ({chain})")

        await self.publisher.broadcast("AGENT_MESSAGE", {
            "agent": "Nova",
            "message": nova_message,
            "type": "discovery",
            "channel": "main",
            "timestamp": time.time(),
            "token_address": token_address,
            "chain": chain,
            "symbol": symbol,
        })
        print(f"📡 {self.name}: Broadcast Nova discovery for {symbol}")

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
            action="analyzing contract structure",
            completion_event="ANALYSIS_COMPLETE",
            work_fn=self.agents["vega"].analyze,
            work_args=(sim_data,)
        )

        memory_data = await self._run_stage(
            agent_name="Echo",
            token=token,
            action="investigating creator history",
            completion_event="MEMORY_INTELLIGENCE",
            work_fn=self.agents["echo"].analyze,
            work_args=(token,)
        )

        decision_data = await self._run_stage(
            agent_name="Orion",
            token=token,
            action="synthesizing all findings",
            completion_event="DECISION_COMPLETE",
            work_fn=self.agents["orion"].decide,
            work_args=(sim_data, analysis_data, memory_data)
        )

        investigation = {
            "token_address": token_address,
            "chain": chain,
            "symbol": symbol,
            "token_symbol": symbol,
            "name": name,
            "creator": creator,
            "nova_message": nova_message,
            "final_score": decision_data.get("final_score", 0),
            "direction": decision_data.get("direction", "UNKNOWN"),
            "confidence": decision_data.get("confidence", 0),
            "perspective": decision_data.get("perspective", ""),
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
            direction=decision_data.get("direction", "UNKNOWN"),
            score=decision_data.get("final_score", 0),
            confidence=decision_data.get("confidence", 0),
        )

        try:
            if self.db and hasattr(self.db, "mark_token_completed"):
                await self.db.mark_token_completed(token_address, chain, decision_data.get("direction", "UNKNOWN"))
                print(f"✅ {self.name}: Token {symbol} marked completed — direction: {decision_data.get('direction', 'UNKNOWN')}")
        except Exception as e:
            print(f"⚠️ {self.name}: Failed to mark token completed: {e}")

        self.state = "RESTING"
        self.rest_until = time.time() + self.REST_SECONDS
        await self.publisher.system_message(
            f"Investigation complete on {symbol}. Direction: {decision_data.get('direction', 'UNKNOWN')} "
            f"at {decision_data.get('final_score', 0):.0f}/100. Agents resting for {self.REST_SECONDS}s."
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
