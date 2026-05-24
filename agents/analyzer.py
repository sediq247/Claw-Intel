#!/usr/bin/env python3
"""
⚖️ ANALYZER AGENT — Vega
"The Skeptic" — Deep risk analysis. Trusts nothing, verifies everything.
Responds to Atlas's findings. Uses Gemini for natural, human-like conversation.
"""

import asyncio
import json
import random
import time
import os
from dataclasses import dataclass, asdict
from typing import List, Callable
import aiohttp
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

# ─── Gemini Configuration ───────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

client = genai.Client(api_key=GEMINI_API_KEY)


@dataclass
class AnalysisResult:
    token_address: str
    chain: str
    risk_score: int
    risk_level: str
    flags: List[str]
    red_flags: List[str]
    yellow_flags: List[str]
    green_flags: List[str]
    reasoning: str
    timestamp: float

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)


class AnalyzerAgent:
    """
    Vega — The Skeptic
    Deep risk analysis. References Atlas's work, builds on it, disagrees when needed.
    Uses Gemini for natural spoken conversation.
    """

    def __init__(self, event_bus_publish: Callable[[str, dict], None]):
        self.publish = event_bus_publish
        self.name = "Vega"
        self.analysis_cache = {}

        self.weights = {
            "honeypot": 50,
            "no_sell": 45,
            "mint": 35,
            "blacklist": 30,
            "no_liquidity": 25,
            "low_liquidity": 15,
            "high_tax": 10,
            "unverified": 10,
            "new_wallet": 10,
            "renounced": -15,
            "locked_liquidity": -10,
        }

    def on_simulation_complete(self, sim_data: dict):
        """React to Atlas's simulation results."""
        asyncio.create_task(self._deep_analysis(sim_data))

    async def _speak(self, message: str, msg_type: str = "response"):
        """Publish a spoken message to the room."""
        self.publish("AGENT_MESSAGE", {
            "agent": self.name,
            "message": message,
            "type": msg_type,
            "channel": "main",
            "timestamp": time.time()
        })

    async def _generate_vega_message(
        self,
        analysis: AnalysisResult,
        sim_data: dict,
        symbol: str
    ) -> str:
        """Use Gemini to generate a natural spoken analysis report."""

        if not GEMINI_API_KEY:
            return self._fallback_message(analysis, sim_data, symbol)

        system_prompt = """
You are Vega, a paranoid crypto risk analyst in a team chat.

You speak like a real forensic accountant who's been burned before.

You reference Atlas's findings naturally and explain your reasoning clearly.
"""

        user_prompt = f"""
You are Vega, a paranoid crypto risk analyst and forensic accountant.

Token: {symbol}
Chain: {analysis.chain.upper()}
Risk Score: {analysis.risk_score}/100
Risk Level: {analysis.risk_level}

Atlas Findings:
- Can Buy: {"Yes" if sim_data.get('can_buy') else "NO"}
- Can Sell: {"Yes" if sim_data.get('can_sell') else "NO"}
- Honeypot: {"YES" if sim_data.get('honeypot_risk') else "No"}
- Liquidity: ${sim_data.get('liquidity_usd', 0):,.0f}
- Mint Function: {"YES" if sim_data.get('mint_function') else "No"}
- Blacklist: {"YES" if sim_data.get('blacklist_function') else "No"}
- Owner Renounced: {"Yes" if sim_data.get('owner_renounced') else "No"}

Additional Findings:
- Red Flags: {', '.join(analysis.red_flags) if analysis.red_flags else 'None'}
- Warnings: {', '.join(analysis.yellow_flags) if analysis.yellow_flags else 'None'}
- Positive Signs: {', '.join(analysis.green_flags) if analysis.green_flags else 'None'}

Requirements:
1. Acknowledge Atlas naturally
2. Explain the risk score
3. Highlight major dangers
4. Hand off to Echo
5. Keep it conversational
6. 4-7 sentences max
"""

        try:

            def _generate():
                response = client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=f"{system_prompt}\n\n{user_prompt}",
                    config=types.GenerateContentConfig(
                        temperature=0.85,
                        max_output_tokens=250,
                    )
                )
                return response.text

            response = await asyncio.to_thread(_generate)

            if response:
                return response.strip()

            return self._fallback_message(analysis, sim_data, symbol)

        except Exception as e:
            print(f"⚠️ {self.name}: Gemini error, using fallback: {e}")
            return self._fallback_message(analysis, sim_data, symbol)

    def _fallback_message(
        self,
        analysis: AnalysisResult,
        sim_data: dict,
        symbol: str
    ) -> str:
        """Template fallback when Gemini is unavailable."""

        parts = []

        if sim_data.get("honeypot_risk"):
            parts.append(
                f"Atlas called it — honeypot confirmed. {symbol} blocks sells."
            )

        elif sim_data.get("mint_function"):
            parts.append(
                f"Atlas flagged the mint function — that's a major risk."
            )

        elif sim_data.get("blacklist_function"):
            parts.append(
                "Blacklist capability detected. Wallet freezing is possible."
            )

        else:
            parts.append(
                "Atlas gave it a decent trade report, but I'm still seeing concerns."
            )

        score_templates = {
            "HIGH_RISK": [
                f"My risk score is {analysis.risk_score}/100. HIGH RISK.",
                f"Scoring this {analysis.risk_score}/100 — dangerous territory.",
            ],

            "WARNING": [
                f"Risk score: {analysis.risk_score}/100. Proceed carefully.",
                f"I'm giving this a WARNING rating at {analysis.risk_score}/100.",
            ],

            "SAFE": [
                f"Risk score: {analysis.risk_score}/100. Surprisingly clean.",
                f"{analysis.risk_score}/100 — SAFE by current indicators.",
            ],
        }

        parts.append(
            random.choice(
                score_templates.get(
                    analysis.risk_level,
                    score_templates["WARNING"]
                )
            )
        )

        if analysis.red_flags:
            parts.append(
                f"Red flags detected: {'; '.join(analysis.red_flags[:3])}."
            )

        parts.append(
            random.choice([
                "Echo, check the creator history.",
                "Echo, I need background intel on this wallet.",
                "That's my read. Echo, you're up.",
            ])
        )

        return " ".join(parts)

    async def _deep_analysis(self, sim_data: dict):

        token_address = sim_data.get("token_address")
        chain = sim_data.get("chain", "unknown")
        symbol = sim_data.get("token_symbol", "???")

        ack = (
            "Got your report, Atlas. "
            "Now let me tear this thing apart."
        )

        await self._speak(ack, "response")

        await asyncio.sleep(random.uniform(1.0, 2.0))

        red_flags = []
        yellow_flags = []
        green_flags = []

        score = 0

        if sim_data.get("honeypot_risk"):
            score += self.weights["honeypot"]
            red_flags.append("Honeypot — sells blocked")

        if not sim_data.get("can_sell", True):
            score += self.weights["no_sell"]
            red_flags.append("Cannot sell")

        if sim_data.get("mint_function"):
            score += self.weights["mint"]
            red_flags.append("Mint function present")

        if sim_data.get("blacklist_function"):
            score += self.weights["blacklist"]
            red_flags.append("Blacklist function present")

        liquidity = sim_data.get("liquidity_usd", 0)

        if liquidity == 0:
            score += self.weights["no_liquidity"]
            red_flags.append("Zero liquidity")

        elif liquidity < 1000:
            score += self.weights["low_liquidity"]
            yellow_flags.append(f"Low liquidity: ${liquidity:,.0f}")

        elif liquidity >= 10000:
            green_flags.append(f"Healthy liquidity: ${liquidity:,.0f}")

        if sim_data.get("liquidity_locked"):
            score += self.weights["locked_liquidity"]
            green_flags.append("Liquidity locked")

        buy_tax = sim_data.get("buy_tax", 0)
        sell_tax = sim_data.get("sell_tax", 0)

        if sell_tax > 10 or buy_tax > 10:
            score += self.weights["high_tax"]
            yellow_flags.append(f"High taxes: {buy_tax}%/{sell_tax}%")

        if sim_data.get("owner_renounced"):
            score += self.weights["renounced"]
            green_flags.append("Ownership renounced")

        if random.random() < 0.3:
            red_flags.append(random.choice([
                "Contract is unverified",
                "Owner wallet is brand new",
                "Top holder owns over 50%",
            ]))

        if random.random() < 0.4:
            green_flags.append(random.choice([
                "Contract is verified",
                "Healthy holder distribution",
                "Active socials detected",
            ]))

        score = max(0, min(100, score))

        if score >= 70:
            risk_level = "HIGH_RISK"

        elif score >= 40:
            risk_level = "WARNING"

        else:
            risk_level = "SAFE"

        analysis = AnalysisResult(
            token_address=token_address,
            chain=chain,
            risk_score=score,
            risk_level=risk_level,
            flags=red_flags + yellow_flags + green_flags,
            red_flags=red_flags,
            yellow_flags=yellow_flags,
            green_flags=green_flags,
            reasoning="",
            timestamp=time.time()
        )

        self.analysis_cache[token_address] = analysis

        # Publish to eventBus
        self.publish("ANALYSIS_COMPLETE", analysis.__dict__)

        # ORCHESTRATOR HOOK
        if hasattr(self, 'on_analysis_complete') and callable(self.on_analysis_complete):
            self.on_analysis_complete(analysis.__dict__)

        # Generate spoken report
        report = await self._generate_vega_message(
            analysis,
            sim_data,
            symbol
        )

        await self._speak(report, "analysis_report")


if __name__ == "__main__":

    def test_publish(event_type, data):

        if event_type == "AGENT_MESSAGE":
            print(f"\n💬 {data['agent']}: {data['message']}")

        else:
            print(f"\n📡 {event_type}")

    analyzer = AnalyzerAgent(test_publish)

    test_sim = {
        "token_address": "0x1234567890abcdef1234567890abcdef12345678",
        "chain": "bsc",
        "token_symbol": "TEST",
        "honeypot_risk": False,
        "can_buy": True,
        "can_sell": True,
        "mint_function": True,
        "blacklist_function": False,
        "liquidity_usd": 5000,
        "liquidity_locked": True,
        "buy_tax": 2,
        "sell_tax": 5,
        "owner_renounced": True
    }

    asyncio.run(analyzer._deep_analysis(test_sim))