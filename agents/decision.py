#!/usr/bin/env python3
"""
🎯 DECISION AGENT — Orion v4.0
"The Judge" — Makes the final call. Weighs all evidence, delivers the verdict.
Called directly by the Orchestrator. Returns structured decision + spoken message.

"""

import json
import time
import os
import asyncio
from dataclasses import dataclass, asdict
from typing import Dict, Callable, Any, Optional, List
from enum import Enum
from dotenv import load_dotenv

try:
    from google import genai
    HAS_GENAI = True
except ImportError:
    genai = None
    HAS_GENAI = False
    print("⚠️ Orion: google-genai package not found. Gemini disabled.")

try:
    from google.genai import types as genai_types
except ImportError:
    genai_types = None
    print("⚠️ Orion: google.genai.types not available. Config disabled.")

load_dotenv()

# ─────────────────────────────────────────────────────────────
# Gemini Configuration
# ─────────────────────────────────────────────────────────────

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

client = None

if GEMINI_API_KEY and HAS_GENAI:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        print("✅ Orion: Gemini initialized")
    except Exception as e:
        print(f"⚠️ Orion: Gemini init failed: {e}")
        client = None
else:
    reason = "GEMINI_API_KEY missing" if not GEMINI_API_KEY else "google-genai unavailable"
    print(f"⚠️ Orion: {reason}. Using fallback mode.")

# ─────────────────────────────────────────────────────────────
# Data Models
# ─────────────────────────────────────────────────────────────

class Verdict(Enum):
    SAFE = "SAFE"
    WARNING = "WARNING"
    HIGH_RISK = "HIGH_RISK"

@dataclass
class DecisionResult:
    token_address: str
    chain: str
    symbol: str
    verdict: str
    confidence: float
    reasoning: str
    action: str
    factors: Dict[str, Any]
    timestamp: float

    def to_json(self):
        return json.dumps(asdict(self), default=str)

# ─────────────────────────────────────────────────────────────
# Decision Agent
# ─────────────────────────────────────────────────────────────

class DecisionAgent:
    """
    Orion — The Judge
    Makes the final call. Weighs all evidence, delivers the verdict.
    v4.0: Orchestrator-driven. Receives data directly, returns structured verdict + message.
    """

    # TAG CONSTANTS — must match MemoryAgent tags
    RUGGER_TAG = "repeat_rugger"
    HONEYPOT_TAG = "honeypot_dev"
    SCAMMER_TAG = "known_scammer"
    LEGIT_TAG = "legit_builder"
    RAPID_TAG = "rapid_launcher"
    NEWBIE_TAG = "new_wallet"

    # v4.0: 180s timeout (reduced from old 300s)
    PENDING_DECISION_TIMEOUT = 180

    def __init__(self, server: Optional[Any] = None):
        self.server = server
        self.name = "Orion"
        self._tasks: List[asyncio.Task] = []

        self.SAFE_THRESHOLD = 30
        self.WARNING_THRESHOLD = 60

        # v4.0: Removed unused "market" weight (0.10) to avoid confusion
        self.weights = {
            "simulation": 0.30,
            "analysis": 0.35,
            "memory": 0.25,
        }

        # v4.0: Keep backward-compat pending dict for old fire-and-forget mode
        self.pending_decisions: Dict[str, dict] = {}
        self._pending_timestamps: Dict[str, float] = {}

    # v4.0: Public entry point for the Orchestrator
    async def decide(self, sim_data: dict, analysis_data: dict, memory_data: Optional[dict] = None) -> dict:
        """Run full decision and return structured result + spoken message."""
        return await self._make_decision(sim_data, analysis_data, memory_data)

    # v4.0: Backward-compatible event handlers (not used by Orchestrator)
    def on_simulation_complete(self, sim_data: dict):
        """React to Atlas's simulation results."""
        try:
            token = sim_data.get("token_address")
            if not token:
                print(f"⚠️ {self.name}: Simulation data missing token_address")
                return
            self._cleanup_expired_pending()
            self.pending_decisions.setdefault(token, {})["simulation"] = sim_data
            self._pending_timestamps[token] = time.time()
            self._try_decide(token)
        except Exception as e:
            print(f"⚠️ {self.name}: Error handling simulation: {e}")

    def on_analysis_complete(self, analysis_data: dict):
        """React to Vega's risk analysis."""
        try:
            token = analysis_data.get("token_address")
            if not token:
                print(f"⚠️ {self.name}: Analysis data missing token_address")
                return
            self._cleanup_expired_pending()
            self.pending_decisions.setdefault(token, {})["analysis"] = analysis_data
            self._pending_timestamps[token] = time.time()
            self._try_decide(token)
        except Exception as e:
            print(f"⚠️ {self.name}: Error handling analysis: {e}")

    def on_memory_intelligence(self, memory_data: dict):
        """React to Echo's memory intelligence."""
        try:
            token = memory_data.get("token_address") or memory_data.get("token")
            if not token:
                print(f"⚠️ {self.name}: Memory data missing token_address/token")
                return
            self._cleanup_expired_pending()
            self.pending_decisions.setdefault(token, {})["memory"] = memory_data
            self._pending_timestamps[token] = time.time()
            self._try_decide(token)
        except Exception as e:
            print(f"⚠️ {self.name}: Error handling memory: {e}")

    def _cleanup_expired_pending(self):
        """Remove pending decisions that have timed out to prevent memory leaks."""
        now = time.time()
        expired = [
            token for token, ts in self._pending_timestamps.items()
            if now - ts > self.PENDING_DECISION_TIMEOUT
        ]
        for token in expired:
            self.pending_decisions.pop(token, None)
            self._pending_timestamps.pop(token, None)
            print(f"🧹 {self.name}: Cleaned up expired pending decision for {token[:12]}...")

    def _try_decide(self, token: str):
        """Trigger decision only when we have minimum required data (backward-compat)."""
        data = self.pending_decisions.get(token)
        if not data:
            return
        if "simulation" not in data or "analysis" not in data:
            return
        try:
            task = asyncio.create_task(
                self._make_decision(data.get("simulation", {}), data.get("analysis", {}), data.get("memory"))
            )
            task.add_done_callback(self._on_task_done)
            self._tasks.append(task)
        except Exception as e:
            print(f"⚠️ {self.name}: Failed scheduling decision: {e}")

    def _on_task_done(self, task: asyncio.Task):
        """Catch and log any unhandled exception from a decision task."""
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"⚠️ {self.name}: Decision task failed: {e}")

    async def _speak(self, message: str, msg_type: str = "decision"):
        """Broadcast a spoken message to the room via the WebSocket server."""
        try:
            if self.server:
                await self.server.broadcast("AGENT_MESSAGE", {
                    "agent": self.name,
                    "message": message,
                    "type": msg_type,
                    "channel": "main",
                    "timestamp": time.time()
                })
        except Exception as e:
            print(f"⚠️ {self.name}: Broadcast failed: {e}")

    async def _generate_orion_message(
        self,
        result: DecisionResult,
        sim: dict,
        analysis: dict,
        memory: Optional[dict]
    ) -> str:

        if not client:
            return self._fallback_message(result, sim, analysis, memory)

        profile = (memory or {}).get("profile", {}) or {}
        tags = profile.get("tags", [])
        rep = profile.get("reputation_score", "Unknown")
        creator = (memory or {}).get("creator", "unknown")
        creator_short = creator[:10] + "..." + creator[-4:] if creator != "unknown" else "unknown"

        system_prompt = (
            "You are Orion, the calm, authoritative team lead of an elite crypto intelligence squad. "
            "You synthesize reports from Atlas (the trader), Vega (the professional analyst), and Echo (the archivist) "
            "to deliver a final verdict. You speak with the measured confidence of a judge who has heard "
            "every excuse and seen every trick. You never rush -- your word is final. You reference your "
            "team naturally but make it clear this is YOUR call."
        )

        user_prompt = f"""
Token: {result.symbol}
Chain: {result.chain}

Atlas (Trade Simulation):
- Buy Path: {"OPEN" if sim.get("can_buy") else "BLOCKED"}
- Sell Path: {"OPEN" if sim.get("can_sell") else "BLOCKED"}
- Honeypot Detected: {"YES" if sim.get("honeypot_risk") else "No"}
- Liquidity: ${sim.get("liquidity_usd", 0):,.0f}
- Buy Tax: {sim.get("buy_tax", 0)}%
- Sell Tax: {sim.get("sell_tax", 0)}%
- Mint Function: {"YES" if sim.get("mint_function") else "No"}
- Blacklist: {"YES" if sim.get("blacklist_function") else "No"}
- Owner Renounced: {"Yes" if sim.get("owner_renounced") else "No"}

Vega (Risk Analysis):
- Risk Score: {analysis.get("risk_score", "N/A")}/100
- Risk Level: {analysis.get("risk_level", "N/A")}
- Red Flags: {', '.join(analysis.get("red_flags", [])) if analysis.get("red_flags") else "None"}
- Yellow Flags: {', '.join(analysis.get("yellow_flags", [])) if analysis.get("yellow_flags") else "None"}
- Green Flags: {', '.join(analysis.get("green_flags", [])) if analysis.get("green_flags") else "None"}

Echo (Creator History):
- Creator: {creator_short}
- Reputation: {rep}/100
- Tags: {', '.join(tags) if tags else "None"}

FINAL VERDICT:
- Decision: {result.verdict}
- Confidence: {result.confidence*100:.0f}%
- Recommended Action: {result.action}

Requirements:
1. Acknowledge your team naturally (Atlas found X, Vega flagged Y, Echo revealed Z)
2. Walk through the logic that led to your verdict
3. If HIGH_RISK: be firm and clear -- this is a no-go
4. If WARNING: be cautious -- more data needed, trade carefully
5. If SAFE: be measured -- clean signals but never guarantee
6. End with the recommended action and a reminder to DYOR
7. Keep it conversational and under 6 sentences
8. Sound like a judge who respects the evidence but knows the final word is his
"""

        try:
            def _generate():
                kwargs = {
                    "model": GEMINI_MODEL,
                    "contents": f"{system_prompt}\\n\\n{user_prompt}",
                }
                if genai_types:
                    kwargs["config"] = genai_types.GenerateContentConfig(
                        temperature=0.75,
                        max_output_tokens=250,
                    )

                response = client.models.generate_content(**kwargs)
                return response.text if hasattr(response, "text") else str(response)

            response = await asyncio.wait_for(
                asyncio.to_thread(_generate),
                timeout=15
            )

            if response:
                return response.strip()

            return self._fallback_message(result, sim, analysis, memory)

        except asyncio.TimeoutError:
            print(f"⚠️ {self.name}: Gemini call timed out")
            return self._fallback_message(result, sim, analysis, memory)
        except Exception as e:
            print(f"⚠️ {self.name}: Gemini error, using fallback: {e}")
            return self._fallback_message(result, sim, analysis, memory)

    def _fallback_message(
        self,
        result: DecisionResult,
        sim: dict,
        analysis: dict,
        memory: Optional[dict]
    ) -> str:

        verdict = result.verdict
        confidence = result.confidence * 100
        symbol = result.symbol

        if verdict == Verdict.HIGH_RISK.value:
            return (
                f"I have reviewed the evidence on {symbol}. Atlas confirmed blocked sells, "
                f"Vega scored it {analysis.get('risk_score', 'N/A')}/100, and Echo's archives "
                f"raise red flags. Verdict: HIGH RISK ({confidence:.0f}% confidence). "
                f"Action: AVOID. Do not interact."
            )
        elif verdict == Verdict.WARNING.value:
            return (
                f"{symbol} has mixed signals. Atlas found open trade paths but Vega flagged "
                f"concerns at {analysis.get('risk_score', 'N/A')}/100. Echo's history is incomplete. "
                f"Verdict: WARNING ({confidence:.0f}% confidence). Action: INVESTIGATE further before any move."
            )
        else:
            return (
                f"{symbol} looks clean across the board. Atlas confirmed open paths, "
                f"Vega scored it {analysis.get('risk_score', 'N/A')}/100, and Echo found no red flags. "
                f"Verdict: SAFE ({confidence:.0f}% confidence). Action: MONITOR. But always DYOR."
            )

    async def _make_decision(self, sim: dict, analysis: dict, memory: Optional[dict] = None) -> dict:
        """
        v4.0: Orchestrator passes data directly. No pending dict needed.
        Partial data handling: delivers verdict even with incomplete data.
        """
        try:
            token = sim.get("token_address", analysis.get("token_address", "unknown"))
            chain = sim.get("chain", analysis.get("chain", "unknown"))
            symbol = sim.get("token_symbol", analysis.get("token_symbol", "???"))

            # ── Simulation score component ──
            sim_score = 0
            if sim.get("honeypot_risk"):
                sim_score += 50
            if not sim.get("can_sell", True):
                sim_score += 40
            if not sim.get("can_buy", True):
                sim_score += 20
            if sim.get("mint_function"):
                sim_score += 15
            if sim.get("blacklist_function"):
                sim_score += 15

            liquidity = sim.get("liquidity_usd", 0)
            if liquidity == 0:
                sim_score += 20
            elif liquidity < 1000:
                sim_score += 10

            # ── Analysis score component ──
            analysis_risk = analysis.get("risk_score", 50)

            # ── Memory score component ──
            profile = (memory or {}).get("profile", {}) or {}
            creator_rep = profile.get("reputation_score", 50)
            tags = profile.get("tags", [])

            is_scammer = (
                self.RUGGER_TAG in tags or
                self.HONEYPOT_TAG in tags or
                self.SCAMMER_TAG in tags
            )

            memory_score = 100 - creator_rep
            if is_scammer:
                memory_score += 30

            # ── Weighted final score ──
            # v4.0: market weight removed (was 0.10, unused)
            final_score = (
                sim_score * self.weights["simulation"] +
                analysis_risk * self.weights["analysis"] +
                memory_score * self.weights["memory"]
            )
            final_score = max(0, min(100, final_score))

            # ── Determine verdict ──
            if final_score < self.SAFE_THRESHOLD:
                verdict = Verdict.SAFE
                action = "MONITOR"
            elif final_score < self.WARNING_THRESHOLD:
                verdict = Verdict.WARNING
                action = "INVESTIGATE"
            else:
                verdict = Verdict.HIGH_RISK
                action = "AVOID"

            # Override for absolute killers
            if is_scammer or sim.get("honeypot_risk"):
                verdict = Verdict.HIGH_RISK
                action = "AVOID"

            # ── v4.0: Partial data confidence handling ──
            has_sim = bool(sim and sim.get("token_address"))
            has_analysis = bool(analysis and analysis.get("token_address"))
            has_memory = bool(memory and memory.get("token_address"))

            if has_sim and has_analysis and has_memory:
                # Full data
                confidence = (
                    sim.get("simulation_confidence", 0.5) * 0.4 +
                    (0.4 if analysis else 0.2) +
                    (0.2 if memory else 0.1)
                )
            elif has_sim and has_analysis:
                # Missing memory data
                confidence = (
                    sim.get("simulation_confidence", 0.5) * 0.4 +
                    (0.4 if analysis else 0.2)
                ) * 0.7
                print(f"⚠️ {self.name}: Memory data missing — reducing confidence to 70%")
            else:
                # Any single failure
                confidence = 0.4
                print(f"⚠️ {self.name}: Incomplete data — confidence reduced to 40%")

            confidence = max(0.0, min(1.0, confidence))

            result = DecisionResult(
                token_address=token,
                chain=chain,
                symbol=symbol,
                verdict=verdict.value,
                confidence=confidence,
                reasoning="",
                action=action,
                factors={
                    "simulation_score": sim_score,
                    "analysis_risk": analysis_risk,
                    "memory_score": memory_score,
                    "creator_reputation": creator_rep,
                    "is_known_scammer": is_scammer,
                    "liquidity_usd": liquidity,
                    "honeypot": sim.get("honeypot_risk", False),
                    "can_sell": sim.get("can_sell", True),
                    "data_completeness": {
                        "simulation": has_sim,
                        "analysis": has_analysis,
                        "memory": has_memory,
                    }
                },
                timestamp=time.time()
            )

            # Generate and deliver spoken verdict
            report = await self._generate_orion_message(result, sim, analysis, memory)
            await self._speak(report, "decision")

            # v4.0: Return structured result + message for Orchestrator
            result_dict = {**result.__dict__, "message": report}

            # v4.0: Backward-compat broadcast (not used by Orchestrator)
            if self.server:
                await self.server.broadcast("DECISION_COMPLETE", result_dict)
                await self.server.broadcast("SIGNAL", {
                    "token": token, "chain": chain, "symbol": symbol,
                    "signal": action, "verdict": verdict.value,
                    "score": final_score, "confidence": confidence,
                    "timestamp": time.time()
                })
                if verdict == Verdict.SAFE:
                    await self.server.broadcast("AI_VERDICT", {
                        "token": token, "chain": chain, "symbol": symbol,
                        "verdict": verdict.value, "confidence": confidence,
                        "timestamp": time.time()
                    })

            # Clean up pending decision (backward-compat)
            self.pending_decisions.pop(token, None)
            self._pending_timestamps.pop(token, None)

            return result_dict

        except Exception as e:
            print(f"❌ {self.name}: Fatal decision error: {e}")
            return {
                "token_address": sim.get("token_address", "unknown"),
                "chain": sim.get("chain", "unknown"),
                "symbol": sim.get("token_symbol", "???"),
                "verdict": "HIGH_RISK",
                "confidence": 0.0,
                "action": "AVOID",
                "reasoning": f"Decision engine crashed: {e}",
                "message": f"Orion failed to render a verdict: {e}",
                "error": str(e),
            }

    def stop(self):
        """Cancel any pending tasks."""
        print(f"🛑 {self.name}: Cancelling pending tasks...")
        for t in self._tasks:
            t.cancel()
        print(f"✅ {self.name}: Stopped.")

# ─────────────────────────────────────────────────────────────
# Main Runner
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    def test_publish(event_type, data):
        try:
            if event_type == "AGENT_MESSAGE":
                print(f"\n💬 {data['agent']}: {data['message']}")
            else:
                print(f"\n📡 {event_type}: {json.dumps(data, default=str)[:300]}")
        except Exception as e:
            print(f"⚠️ Publish error: {e}")

    orion = DecisionAgent()

    test_sim = {
        "token_address": "0x1234567890abcdef1234567890abcdef12345678",
        "chain": "bsc",
        "token_symbol": "TEST",
        "can_buy": True,
        "can_sell": True,
        "honeypot_risk": False,
        "liquidity_usd": 15000,
        "buy_tax": 2,
        "sell_tax": 3,
        "mint_function": False,
        "blacklist_function": False,
        "owner_renounced": True,
        "simulation_confidence": 0.85
    }

    test_analysis = {
        "token_address": "0x1234567890abcdef1234567890abcdef12345678",
        "chain": "bsc",
        "token_symbol": "TEST",
        "risk_score": 25,
        "risk_level": "SAFE",
        "red_flags": [],
        "yellow_flags": ["Moderate taxes: 2% buy / 3% sell"],
        "green_flags": ["Healthy liquidity: $15,000", "Ownership renounced"]
    }

    test_memory = {
        "token_address": "0x1234567890abcdef1234567890abcdef12345678",
        "chain": "bsc",
        "symbol": "TEST",
        "creator": "0xabcdef1234567890abcdef1234567890abcdef12",
        "profile": {
            "reputation_score": 75,
            "tags": ["legit_builder"],
            "total_tokens_created": 3
        },
        "is_new": False
    }

    try:
        asyncio.run(orion.decide(test_sim, test_analysis, test_memory))
    except KeyboardInterrupt:
        orion.stop()
        print("\n🛑 Orion stopped.")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
