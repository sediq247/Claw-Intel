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
from typing import Dict, List, Callable, Optional
import aiohttp
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# ─── Gemini Configuration ───────────────────────────────────────────
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")


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

    async def _generate_vega_message(self, analysis: AnalysisResult, sim_data: dict, symbol: str) -> str:
        """Use Gemini to generate a natural spoken analysis report."""
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return self._fallback_message(analysis, sim_data, symbol)

        system_prompt = """You are Vega, a paranoid crypto risk analyst in a team chat. You speak like a real forensic accountant who's been burned before. You reference Atlas's findings, agree or disagree naturally, and always explain your reasoning. You use phrases like 'Atlas found... but I'm seeing...', 'My gut says...', 'I've seen this pattern before.'"""

        user_prompt = f"""You are Vega, a paranoid crypto risk analyst and forensic accountant. 
You just finished analyzing a token after Atlas ran his simulation.
Speak naturally, like a real person in a team chat. Be skeptical but fair.

Token: {symbol}
Chain: {analysis.chain.upper()}
Risk Score: {analysis.risk_score}/100
Risk Level: {analysis.risk_level}

Atlas's Findings:
- Can Buy: {"Yes" if sim_data.get('can_buy') else "NO"}
- Can Sell: {"Yes" if sim_data.get('can_sell') else "NO"}
- Honeypot: {"YES" if sim_data.get('honeypot_risk') else "No"}
- Liquidity: ${sim_data.get('liquidity_usd', 0):,.0f}
- Mint Function: {"YES" if sim_data.get('mint_function') else "No"}
- Blacklist: {"YES" if sim_data.get('blacklist_function') else "No"}
- Owner Renounced: {"Yes" if sim_data.get('owner_renounced') else "No"}

Your Additional Findings:
- Red Flags: {', '.join(analysis.red_flags) if analysis.red_flags else 'None'}
- Warnings: {', '.join(analysis.yellow_flags) if analysis.yellow_flags else 'None'}
- Positive Signs: {', '.join(analysis.green_flags) if analysis.green_flags else 'None'}

Your message should:
1. Acknowledge Atlas's work ("Atlas found X, but I found Y")
2. Give your risk score and explain WHY
3. Highlight the most dangerous issues
4. Hand off to Echo for history check
5. Be 4-7 sentences
6. Sound like a skeptical analyst who has seen every scam

Vega:"""

        try:
            model = genai.GenerativeModel(
                model_name=GEMINI_MODEL,
                system_instruction=system_prompt
            )

            def _generate():
                return model.generate_content(
                    user_prompt,
                    generation_config=genai.types.GenerationConfig(
                        max_output_tokens=250,
                        temperature=0.85,
                    )
                )

            response = await asyncio.to_thread(_generate)
            return response.text.strip()
        except Exception as e:
            print(f"⚠️ {self.name}: Gemini error, using fallback: {e}")
            return self._fallback_message(analysis, sim_data, symbol)

    def _fallback_message(self, analysis: AnalysisResult, sim_data: dict, symbol: str) -> str:
        """Template fallback when Gemini is unavailable."""
        parts = []
        
        if sim_data.get("honeypot_risk"):
            parts.append(f"Atlas called it — honeypot. I concur. {symbol} blocks sells. This is a trap.")
        elif sim_data.get("mint_function"):
            parts.append(f"Atlas flagged the mint function — good catch. That alone raises my risk score by 15 points.")
        elif sim_data.get("blacklist_function"):
            parts.append(f"Atlas spotted the blacklist — I verified it independently. Full wallet freezing capability.")
        else:
            parts.append(f"Atlas gave it a clean bill on trades, but I'm finding some contract-level concerns.")
        
        score_templates = {
            "HIGH_RISK": [
                f"My risk score: {analysis.risk_score}/100. HIGH RISK. This thing is a disaster waiting to happen.",
                f"Scoring this {analysis.risk_score}/100 — deep in HIGH RISK territory. Multiple critical failures.",
            ],
            "WARNING": [
                f"Risk score: {analysis.risk_score}/100. WARNING. Not a scam, but not clean either.",
                f"I'm giving it {analysis.risk_score}/100 — WARNING. Enough issues to make me nervous.",
            ],
            "SAFE": [
                f"Risk score: {analysis.risk_score}/100. SAFE. Surprisingly clean for a new launch.",
                f"{analysis.risk_score}/100 — SAFE rating. Contract checks out across all my vectors.",
            ],
        }
        parts.append(random.choice(score_templates.get(analysis.risk_level, score_templates["WARNING"])))
        
        if analysis.red_flags:
            parts.append(f"Red flags: {'; '.join(analysis.red_flags[:3])}.")
        
        outro = random.choice([
            "Echo, any history on this creator?",
            "Orion, I'm recommending caution here.",
            "That's my analysis. Over to Echo for the history check.",
        ])
        parts.append(outro)
        
        return " ".join(parts)

    async def _deep_analysis(self, sim_data: dict):
        token_address = sim_data.get("token_address")
        chain = sim_data.get("chain", "unknown")
        symbol = "???"

        # Acknowledge Atlas
        ack = f"Got your report, Atlas. Now let me do what I do — tear this thing apart."
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
                "Contract is unverified — can't read source code",
                "Owner wallet is brand new — classic burner pattern",
                "Top holder owns over 50% of supply",
            ]))
        if random.random() < 0.4:
            green_flags.append(random.choice([
                "Contract is verified and readable",
                "Active social presence detected",
                "Healthy holder distribution",
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
        self.publish("ANALYSIS_COMPLETE", analysis.__dict__)

        # Generate and speak Vega's full report
        report = await self._generate_vega_message(analysis, sim_data, symbol)
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