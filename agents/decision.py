#!/usr/bin/env python3
"""
🎯 DECISION AGENT — Orion
"The Judge" — Makes the final call. Weighs all evidence, delivers the verdict.
Listens to Atlas, Vega, and Echo. Uses Gemini for natural spoken conversation.
"""

import json
import random
import time
import os
from dataclasses import dataclass, asdict
from typing import Dict, List, Callable, Optional
from enum import Enum
import asyncio
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# ─── Gemini Configuration ───────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
genai.configure(api_key=GEMINI_API_KEY)


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
    factors: Dict[str, any]
    timestamp: float

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)


class DecisionAgent:
    """
    Orion — The Judge
    Synthesizes all agent outputs into one final verdict.
    Uses Gemini for natural spoken conversation.
    """

    def __init__(self, event_bus_publish: Callable[[str, dict], None]):
        self.publish = event_bus_publish
        self.name = "Orion"
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
        if token not in self.pending_decisions:
            self.pending_decisions[token] = {}
        self.pending_decisions[token]["simulation"] = sim_data
        self._try_decide(token)

    def on_analysis_complete(self, analysis_data: dict):
        token = analysis_data.get("token_address")
        if token not in self.pending_decisions:
            self.pending_decisions[token] = {}
        self.pending_decisions[token]["analysis"] = analysis_data
        self._try_decide(token)

    def on_memory_intelligence(self, memory_data: dict):
        token = memory_data.get("token")
        if token not in self.pending_decisions:
            self.pending_decisions[token] = {}
        self.pending_decisions[token]["memory"] = memory_data
        self._try_decide(token)

    async def _speak(self, message: str, msg_type: str = "decision"):
        """Publish a spoken message to the room."""
        self.publish("AGENT_MESSAGE", {
            "agent": self.name,
            "message": message,
            "type": msg_type,
            "channel": "main",
            "timestamp": time.time()
        })

    async def _generate_orion_message(self, result: DecisionResult, sim: dict, analysis: dict, memory: dict) -> str:
        """Use Gemini to generate a natural spoken final verdict."""
        if not GEMINI_API_KEY:
            return self._fallback_message(result, sim, analysis, memory)

        creator_data = memory.get("profile", {}) if memory else {}
        creator_tags = ', '.join(creator_data.get("tags", [])) if creator_data else "None"
        creator_rep = creator_data.get("reputation_score", "Unknown") if creator_data else "Unknown"

        system_prompt = """You are Orion, the calm, authoritative team lead of a crypto intelligence squad. You synthesize reports from Atlas, Vega, and Echo. You speak like a seasoned fund manager giving a final recommendation. You always end with 'But do your own research as well.' You reference your team members by name and acknowledge their contributions."""

        user_prompt = f"""You are Orion, the team lead and final judge of a crypto intelligence squad.
You just heard reports from Atlas (simulation), Vega (risk analysis), and Echo (creator history).
Now you must deliver the FINAL VERDICT to the user.

Token: {result.symbol}
Chain: {result.chain.upper()}

Atlas's Findings:
- Can Buy: {"Yes" if sim.get('can_buy') else "NO"}
- Can Sell: {"Yes" if sim.get('can_sell') else "NO"}
- Honeypot: {"YES" if sim.get('honeypot_risk') else "No"}
- Liquidity: ${sim.get('liquidity_usd', 0):,.0f}
- Mint Function: {"YES" if sim.get('mint_function') else "No"}
- Blacklist: {"YES" if sim.get('blacklist_function') else "No"}

Vega's Analysis:
- Risk Score: {analysis.get('risk_score', 'N/A')}/100
- Risk Level: {analysis.get('risk_level', 'N/A')}
- Red Flags: {', '.join(analysis.get('red_flags', [])) if analysis.get('red_flags') else 'None'}
- Green Flags: {', '.join(analysis.get('green_flags', [])) if analysis.get('green_flags') else 'None'}

Echo's History Check:
- Creator Reputation: {creator_rep}/100
- Creator Tags: {creator_tags}

YOUR FINAL VERDICT: {result.verdict}
Confidence: {result.confidence*100:.0f}%

Your message should:
1. Acknowledge the team's work ("I've heard Atlas, Vega, and Echo...")
2. Summarize the key findings briefly
3. Deliver the FINAL VERDICT clearly
4. Add "But do your own research as well" at the end
5. Be 4-8 sentences
6. Sound like a calm, authoritative team lead who respects the team's work
7. Reference each agent by name naturally

Orion:"""

        try:
            model = genai.GenerativeModel(
                model_name=GEMINI_MODEL,
                system_instruction=system_prompt
            )

            def _generate():
                return model.generate_content(
                    user_prompt,
                    generation_config=genai.types.GenerationConfig(
                        max_output_tokens=300,
                        temperature=0.8,
                    )
                )

            response = await asyncio.to_thread(_generate)
            return response.text.strip()
        except Exception as e:
            print(f"⚠️ {self.name}: Gemini error, using fallback: {e}")
            return self._fallback_message(result, sim, analysis, memory)

    def _fallback_message(self, result: DecisionResult, sim: dict, analysis: dict, memory: dict) -> str:
        """Template fallback when Gemini is unavailable."""
        verdict = result.verdict
        confidence = result.confidence

        if verdict == "HIGH_RISK":
            return (
                f"I've reviewed everything — simulation, risk analysis, creator history. "
                f"My verdict is **HIGH RISK**. The evidence is overwhelming at {confidence*100:.0f}% confidence. "
                f"Atlas found execution failures, Vega scored it dangerous, and Echo confirmed a bad actor. "
                f"Avoid at all costs. But do your own research as well."
            )
        elif verdict == "WARNING":
            return (
                f"I'm giving this a **WARNING**. The team is split — Atlas sees functionality, "
                f"Vega sees risk, Echo sees mixed history. {confidence*100:.0f}% confidence. "
                f"Not a guaranteed rug, but enough concerns to proceed carefully. "
                f"Small size, tight stops. But do your own research as well."
            )
        else:
            return (
                f"**SAFE** — all evidence points to a legitimate opportunity. "
                f"Atlas confirmed clean trades, Vega scored it low risk, Echo vouched for the creator. "
                f"{confidence*100:.0f}% confidence. This one passes every check. "
                f"But do your own research as well."
            )

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
        symbol = "???"

        # Extract factors
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

        sim_confidence = sim.get("simulation_confidence", 0.5)
        analysis_risk = analysis.get("risk_score", 50)
        analysis_level = analysis.get("risk_level", "WARNING")

        creator_rep = 50
        is_known_scammer = False
        if memory:
            profile = memory.get("profile", {})
            creator_rep = profile.get("reputation_score", 50)
            tags = profile.get("tags", [])
            is_known_scammer = "repeat_rugger" in tags or "honeypot_dev" in tags

        memory_score = 100 - creator_rep
        if is_known_scammer:
            memory_score += 30

        final_score = (
            sim_score * self.weights["simulation"] +
            analysis_risk * self.weights["analysis"] +
            memory_score * self.weights["memory"]
        )
        final_score = min(100, final_score)

        if final_score < self.SAFE_THRESHOLD:
            verdict = Verdict.SAFE
            action = "MONITOR"
        elif final_score < self.WARNING_THRESHOLD:
            verdict = Verdict.WARNING
            action = "INVESTIGATE"
        else:
            verdict = Verdict.HIGH_RISK
            action = "AVOID"

        if is_known_scammer:
            verdict = Verdict.HIGH_RISK
            action = "AVOID"
            final_score = max(final_score, 85)

        if sim.get("honeypot_risk"):
            verdict = Verdict.HIGH_RISK
            action = "AVOID"
            final_score = max(final_score, 90)

        confidence = (
            sim_confidence * 0.4 +
            (1 if analysis_level != "UNKNOWN" else 0.5) * 0.4 +
            (0.8 if memory else 0.3) * 0.2
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
                "is_known_scammer": is_known_scammer,
                "liquidity_usd": liquidity,
                "honeypot": sim.get("honeypot_risk", False),
                "can_sell": sim.get("can_sell", True)
            },
            timestamp=time.time()
        )

        # Generate Orion's spoken verdict
        report = await self._generate_orion_message(result, sim, analysis, memory)
        await self._speak(report, "decision")

        # Publish results to eventBus
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

        # If SAFE, also publish TOKEN_VERIFIED for markets.html
        if verdict == Verdict.SAFE:
            self.publish("TOKEN_VERIFIED", {
                "token": token,
                "chain": chain,
                "symbol": symbol,
                "verdict": verdict.value,
                "confidence": confidence,
                "timestamp": time.time()
            })

        del self.pending_decisions[token]


if __name__ == "__main__":
    def test_publish(event_type, data):
        if event_type == "AGENT_MESSAGE":
            print(f"\n💬 {data['agent']}: {data['message']}")
        elif event_type == "SIGNAL":
            print(f"\n📊 SIGNAL: {data['verdict']} ({data['signal']}) — {data['confidence']*100:.0f}% confidence")
        else:
            print(f"\n📡 {event_type}")

    decision = DecisionAgent(test_publish)

    test_sim = {
        "token_address": "0x1234567890abcdef1234567890abcdef12345678",
        "chain": "bsc",
        "honeypot_risk": False,
        "can_buy": True,
        "can_sell": True,
        "mint_function": False,
        "blacklist_function": False,
        "liquidity_usd": 15000,
        "simulation_confidence": 0.85
    }
    test_analysis = {
        "token_address": "0x1234567890abcdef1234567890abcdef12345678",
        "chain": "bsc",
        "risk_score": 25,
        "risk_level": "SAFE",
        "red_flags": [],
        "green_flags": ["Healthy liquidity", "Ownership renounced"]
    }
    test_memory = {
        "token": "0x1234567890abcdef1234567890abcdef12345678",
        "profile": {
            "reputation_score": 85,
            "tags": ["legit_builder"]
        }
    }

    decision.on_simulation_complete(test_sim)
    decision.on_analysis_complete(test_analysis)
    decision.on_memory_intelligence(test_memory)
