#!/usr/bin/env python3
"""
⚖️ DECISION AGENT — Orion v4.1 (PATCHED)
"The Judge" — Makes the final call. Weighs all evidence, delivers the verdict.

FIXES APPLIED:
1. Removed direct AI_VERDICT broadcast from _make_decision. The Orchestrator handles
   all frontend messaging. Orion now returns his result silently and lets the Conductor
   broadcast the verdict via signal() and investigation_complete().
2. Removed dead event-driven code (on_simulation_complete, on_analysis_complete,
   on_memory_intelligence, _try_decide, etc.) that could cause double-invocation or
   confusion in the orchestrator-driven model.
3. _make_decision now returns a clean dict with message included. No side effects.
"""

import json
import time
import os
import asyncio
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional, List
from enum import Enum
from dotenv import load_dotenv

try:
    from google import genai
    HAS_GENAI = True
except ImportError:
    genai = None
    HAS_GENAI = False

try:
    from google.genai import types as genai_types
except ImportError:
    genai_types = None

load_dotenv()

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
    print(f"⚠️ Orion: Gemini unavailable. Using fallback mode.")


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
    creator: str = ""
    final_score: float = 0.0

    def to_json(self):
        return json.dumps(asdict(self), default=str)


class DecisionAgent:
    RUGGER_TAG = "repeat_rugger"
    HONEYPOT_TAG = "honeypot_dev"
    SCAMMER_TAG = "known_scammer"
    LEGIT_TAG = "legit_builder"
    RAPID_TAG = "rapid_launcher"
    NEWBIE_TAG = "new_wallet"

    def __init__(self, server: Optional[Any] = None):
        self.server = server
        self.name = "Orion"
        self.SAFE_THRESHOLD = 30
        self.WARNING_THRESHOLD = 60
        self.weights = {"simulation": 0.30, "analysis": 0.40, "memory": 0.30}

    # v4.1: Public entry point for the Orchestrator
    async def decide(self, sim_data: dict, analysis_data: dict, memory_data: Optional[dict] = None) -> dict:
        """Make final decision based on all evidence. Returns structured result + spoken message."""
        return await self._make_decision(sim_data, analysis_data, memory_data)

    async def _generate_orion_message(self, result: DecisionResult, sim: dict, analysis: dict, memory: Optional[dict]) -> str:
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
            "every excuse and seen every trick. You never rush -- your word is final."
        )

        user_prompt = (
            f"Token: {result.symbol}\nChain: {result.chain}\n\n"
            f"Atlas (Trade Simulation):\n"
            f"- Buy Path: {'OPEN' if sim.get('can_buy') else 'BLOCKED'}\n"
            f"- Sell Path: {'OPEN' if sim.get('can_sell') else 'BLOCKED'}\n"
            f"- Honeypot: {'YES' if sim.get('honeypot_risk') else 'No'}\n"
            f"- Liquidity: ${sim.get('liquidity_usd', 0):,.0f}\n"
            f"- Buy Tax: {sim.get('buy_tax', 0)}%\n"
            f"- Sell Tax: {sim.get('sell_tax', 0)}%\n"
            f"- Mint Function: {'YES' if sim.get('mint_function') else 'No'}\n"
            f"- Blacklist: {'YES' if sim.get('blacklist_function') else 'No'}\n"
            f"- Owner Renounced: {'Yes' if sim.get('owner_renounced') else 'No'}\n\n"
            f"Vega (Risk Analysis):\n"
            f"- Risk Score: {analysis.get('risk_score', 'N/A')}/100\n"
            f"- Risk Level: {analysis.get('risk_level', 'N/A')}\n"
            f"- Red Flags: {', '.join(analysis.get('red_flags', [])) if analysis.get('red_flags') else 'None'}\n"
            f"- Yellow Flags: {', '.join(analysis.get('yellow_flags', [])) if analysis.get('yellow_flags') else 'None'}\n"
            f"- Green Flags: {', '.join(analysis.get('green_flags', [])) if analysis.get('green_flags') else 'None'}\n\n"
            f"Echo (Creator History):\n"
            f"- Creator: {creator_short}\n"
            f"- Reputation: {rep}/100\n"
            f"- Tags: {', '.join(tags) if tags else 'None'}\n\n"
            f"FINAL VERDICT:\n"
            f"- Decision: {result.verdict}\n"
            f"- Confidence: {result.confidence*100:.0f}%\n"
            f"- Recommended Action: {result.action}\n\n"
            f"Requirements:\n"
            f"1. Acknowledge your team naturally\n"
            f"2. Walk through the logic that led to your verdict\n"
            f"3. If HIGH_RISK: be firm and clear -- this is a no-go\n"
            f"4. If WARNING: be cautious -- trade carefully\n"
            f"5. If SAFE: be measured -- clean signals but never guarantee\n"
            f"6. End with the recommended action and a reminder to DYOR\n"
            f"7. Keep it conversational and under 6 sentences\n"
            f"8. Sound like a judge who respects the evidence but knows the final word is his"
        )

        try:
            def _generate():
                kwargs = {"model": GEMINI_MODEL, "contents": f"{system_prompt}\n\n{user_prompt}"}
                if genai_types:
                    kwargs["config"] = genai_types.GenerateContentConfig(temperature=0.75, max_output_tokens=250)
                response = client.models.generate_content(**kwargs)
                return response.text if hasattr(response, "text") else str(response)
            response = await asyncio.wait_for(asyncio.to_thread(_generate), timeout=15)
            if response:
                return response.strip()
            return self._fallback_message(result, sim, analysis, memory)
        except asyncio.TimeoutError:
            print(f"⚠️ {self.name}: Gemini timed out")
            return self._fallback_message(result, sim, analysis, memory)
        except Exception as e:
            print(f"⚠️ {self.name}: Gemini error: {e}")
            return self._fallback_message(result, sim, analysis, memory)

    def _fallback_message(self, result: DecisionResult, sim: dict, analysis: dict, memory: Optional[dict]) -> str:
        verdict = result.verdict
        confidence = result.confidence * 100
        symbol = result.symbol
        if verdict == Verdict.HIGH_RISK.value:
            return (
                f"I have reviewed the evidence on {symbol}. Atlas confirmed blocked sells, "
                f"Vega scored it {analysis.get('risk_score', 'N/A')}/100, and Echo's archives raise red flags. "
                f"Verdict: HIGH RISK ({confidence:.0f}% confidence). Action: AVOID. Do not interact."
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
        try:
            symbol = sim.get("token_symbol", sim.get("symbol",
                       analysis.get("token_symbol", analysis.get("symbol", "???"))))
            token = sim.get("token_address", analysis.get("token_address", "unknown"))
            chain = sim.get("chain", analysis.get("chain", "unknown"))
            creator = (memory or {}).get("creator", sim.get("creator", analysis.get("creator", "")))

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

            profile = (memory or {}).get("profile", {}) or {}
            creator_rep = profile.get("reputation_score", 50)
            tags = profile.get("tags", [])
            is_scammer = self.RUGGER_TAG in tags or self.HONEYPOT_TAG in tags or self.SCAMMER_TAG in tags
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

            has_sim = bool(sim and sim.get("token_address"))
            has_analysis = bool(analysis and analysis.get("token_address"))
            has_memory = bool(memory and memory.get("token_address"))

            if has_sim and has_analysis and has_memory:
                confidence = sim.get("simulation_confidence", 0.5) * 0.4 + 0.4 + 0.2
            elif has_sim and has_analysis:
                confidence = (sim.get("simulation_confidence", 0.5) * 0.4 + 0.4) * 0.7
                print(f"⚠️ {self.name}: Memory data missing -- confidence reduced")
            else:
                confidence = 0.4
                print(f"⚠️ {self.name}: Incomplete data -- confidence reduced")
            confidence = max(0.0, min(1.0, confidence))

            result = DecisionResult(
                token_address=token, chain=chain, symbol=symbol,
                verdict=verdict.value, confidence=confidence,
                reasoning="", action=action,
                factors={
                    "simulation_score": sim_score,
                    "analysis_risk": analysis_risk,
                    "memory_score": memory_score,
                    "creator_reputation": creator_rep,
                    "is_known_scammer": is_scammer,
                    "liquidity_usd": liquidity,
                    "honeypot": sim.get("honeypot_risk", False),
                    "can_sell": sim.get("can_sell", True),
                    "data_completeness": {"simulation": has_sim, "analysis": has_analysis, "memory": has_memory},
                },
                timestamp=time.time(),
                creator=creator,
                final_score=final_score,
            )

            report = await self._generate_orion_message(result, sim, analysis, memory)

            # FIX #1: Removed direct AI_VERDICT broadcast. The Orchestrator handles all messaging.
            # The Orchestrator's _run_investigation calls signal() and investigation_complete()
            # after Orion's stage, which broadcasts the verdict to the frontend properly.

            result_dict = {**result.__dict__, "message": report}
            for key in ["creator", "origin_source", "timestamp", "attention_score", "volume_24h", "market_cap"]:
                if key in sim and key not in result_dict:
                    result_dict[key] = sim[key]
                elif key in analysis and key not in result_dict:
                    result_dict[key] = analysis[key]

            return result_dict

        except Exception as e:
            print(f"❌ {self.name}: Fatal decision error: {e}")
            return {
                "token_address": sim.get("token_address", "unknown"),
                "chain": sim.get("chain", "unknown"),
                "symbol": sim.get("token_symbol", sim.get("symbol", "???")),
                "verdict": "HIGH_RISK", "confidence": 0.0, "action": "AVOID",
                "reasoning": f"Decision engine crashed: {e}",
                "message": f"Orion failed to render a verdict: {e}", "error": str(e),
            }

    def stop(self):
        print(f"🛑 {self.name}: Stopped.")


if __name__ == "__main__":
    orion = DecisionAgent()
    test_sim = {
        "token_address": "0x1234567890abcdef1234567890abcdef12345678",
        "chain": "bsc", "token_symbol": "TEST",
        "can_buy": True, "can_sell": True, "honeypot_risk": False,
        "liquidity_usd": 15000, "buy_tax": 2, "sell_tax": 3,
        "mint_function": False, "blacklist_function": False,
        "owner_renounced": True, "simulation_confidence": 0.85,
    }
    test_analysis = {
        "token_address": "0x1234567890abcdef1234567890abcdef12345678",
        "chain": "bsc", "token_symbol": "TEST",
        "risk_score": 25, "risk_level": "SAFE",
        "red_flags": [], "yellow_flags": ["Moderate taxes"], "green_flags": ["Healthy liquidity"],
    }
    test_memory = {
        "token_address": "0x1234567890abcdef1234567890abcdef12345678",
        "chain": "bsc", "symbol": "TEST",
        "creator": "0xabcdef1234567890abcdef1234567890abcdef12",
        "profile": {"reputation_score": 75, "tags": ["legit_builder"], "total_tokens_created": 3},
        "is_new": False,
    }
    try:
        asyncio.run(orion.decide(test_sim, test_analysis, test_memory))
    except KeyboardInterrupt:
        orion.stop()
        print("\n🛑 Orion stopped.")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
