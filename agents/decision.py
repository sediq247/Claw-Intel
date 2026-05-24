#!/usr/bin/env python3
"""
🎯 DECISION AGENT — Orion
"The Judge" — Makes the final call. Weighs all evidence, delivers the verdict.
Listens to Atlas, Vega, and Echo. Uses Gemini for natural spoken conversation.
"""

import json
import time
import os
import asyncio
from dataclasses import dataclass, asdict
from typing import Dict, Callable, Any
from enum import Enum
from google import genai
from dotenv import load_dotenv

load_dotenv()


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


class DecisionAgent:

    def __init__(self, event_bus_publish: Callable[[str, dict], None]):
        self.publish = event_bus_publish
        self.name = "Orion"

        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

        self.SAFE_THRESHOLD = 30
        self.WARNING_THRESHOLD = 60

        self.weights = {
            "simulation": 0.30,
            "analysis": 0.35,
            "memory": 0.25,
            "market": 0.10
        }

        self.pending_decisions: Dict[str, dict] = {}

    def on_simulation_complete(self, sim_data: dict):
        token = sim_data.get("token_address")
        if not token:
            return
        self.pending_decisions.setdefault(token, {})["simulation"] = sim_data
        self._try_decide(token)

    def on_analysis_complete(self, analysis_data: dict):
        token = analysis_data.get("token_address")
        if not token:
            return
        self.pending_decisions.setdefault(token, {})["analysis"] = analysis_data
        self._try_decide(token)

    def on_memory_intelligence(self, memory_data: dict):
        token = memory_data.get("token")
        if not token:
            return
        self.pending_decisions.setdefault(token, {})["memory"] = memory_data
        self._try_decide(token)

    async def _speak(self, message: str, msg_type: str = "decision"):
        self.publish("AGENT_MESSAGE", {
            "agent": self.name,
            "message": message,
            "type": msg_type,
            "channel": "main",
            "timestamp": time.time()
        })

    def _try_decide(self, token: str):
        data = self.pending_decisions.get(token)
        if not data:
            return
        if "simulation" not in data or "analysis" not in data:
            return
        asyncio.create_task(self._make_decision(token, data))

    async def _generate_orion_message(self, result, sim, analysis, memory):

        if not os.getenv("GEMINI_API_KEY"):
            return self._fallback_message(result, sim, analysis, memory)

        profile = (memory or {}).get("profile", {})
        tags = profile.get("tags", [])
        rep = profile.get("reputation_score", "Unknown")

        system_prompt = (
            "You are Orion, calm authoritative team lead of a crypto intelligence squad. "
            "You synthesize Atlas, Vega, Echo reports and give final verdict."
        )

        user_prompt = f"""
Token: {result.symbol}
Chain: {result.chain}

Atlas:
- Buy: {sim.get("can_buy")}
- Sell: {sim.get("can_sell")}
- Honeypot: {sim.get("honeypot_risk")}
- Liquidity: {sim.get("liquidity_usd", 0)}

Vega:
- Risk Score: {analysis.get("risk_score")}
- Risk Level: {analysis.get("risk_level")}

Echo:
- Reputation: {rep}
- Tags: {", ".join(tags) if tags else "None"}

Verdict: {result.verdict}
Confidence: {result.confidence*100:.0f}%

Give final spoken verdict in 4–8 sentences.
"""

        try:
            response = self.client.models.generate_content(
                model=os.getenv("GEMINI_MODEL", "gemini-1.5-flash"),
                contents=user_prompt
            )
            return response.text.strip()
        except Exception:
            return self._fallback_message(result, sim, analysis, memory)

    def _fallback_message(self, result, sim, analysis, memory):
        return f"{result.verdict} — {result.confidence*100:.0f}% confidence. Do your own research."

    def _try_decide(self, token: str):
        data = self.pending_decisions.get(token, {})
        if "simulation" not in data or "analysis" not in data:
            return
        asyncio.create_task(self._make_decision(token, data))

    async def _make_decision(self, token: str, data: dict):

        sim = data.get("simulation", {})
        analysis = data.get("analysis", {})
        memory = data.get("memory", {})

        chain = sim.get("chain", analysis.get("chain", "unknown"))
        symbol = sim.get("symbol", "???")

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

        analysis_risk = analysis.get("risk_score", 50)

        profile = (memory or {}).get("profile", {})
        creator_rep = profile.get("reputation_score", 50)
        tags = profile.get("tags", [])

        is_scammer = "repeat_rugger" in tags or "honeypot_dev" in tags

        memory_score = 100 - creator_rep
        if is_scammer:
            memory_score += 30

        final_score = (
            sim_score * self.weights["simulation"] +
            analysis_risk * self.weights["analysis"] +
            memory_score * self.weights["memory"]
        )

        final_score = max(0, min(100, final_score))

        if final_score < self.SAFE_THRESHOLD:
            verdict = Verdict.SAFE
            action = "MONITOR"
        elif final_score < self.WARNING_THRESHOLD:
            verdict = Verdict.WARNING
            action = "INVESTIGATE"
        else:
            verdict = Verdict.HIGH_RISK
            action = "AVOID"

        if is_scammer or sim.get("honeypot_risk"):
            verdict = Verdict.HIGH_RISK
            action = "AVOID"

        confidence = (
            sim.get("simulation_confidence", 0.5) * 0.4 +
            (0.4 if analysis else 0.2) +
            (0.2 if memory else 0.1)
        )

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
                "can_sell": sim.get("can_sell", True)
            },
            timestamp=time.time()
        )

        report = await self._generate_orion_message(result, sim, analysis, memory)
        await self._speak(report, "decision")

        self.publish("DECISION_COMPLETE", result.__dict__)
        self.publish("SIGNAL", {
            "token": token,
            "chain": chain,
            "signal": action,
            "verdict": verdict.value,
            "score": final_score,
            "confidence": confidence,
            "timestamp": time.time()
        })

        if verdict == Verdict.SAFE:
            self.publish("TOKEN_VERIFIED", {
                "token": token,
                "chain": chain,
                "symbol": symbol,
                "verdict": verdict.value,
                "confidence": confidence,
                "timestamp": time.time()
            })

        self.pending_decisions.pop(token, None)