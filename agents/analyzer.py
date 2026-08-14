#!/usr/bin/env python3
"""
⚖️ ANALYZER AGENT — Vega v4.0
"The Skeptic" — Deep risk analysis. Trusts nothing, verifies everything.
Called directly by the Orchestrator. Returns structured analysis + spoken message.

v4.0 CHANGES:
- Deterministic scoring — no randomness in security logic
- Returns dict with all analysis fields + 'message'
- Uses server.broadcast for AGENT_MESSAGE
- Gemini model defaults to gemini-1.5-flash
"""

import asyncio
import json
import time
import os
from dataclasses import dataclass, asdict
from typing import List, Optional, Any
from dotenv import load_dotenv

try:
    from google import genai
    HAS_GENAI = True
except ImportError:
    genai = None
    HAS_GENAI = False
    print("⚠️ Vega: google-genai package not found. Gemini disabled.")

try:
    from google.genai import types as genai_types
except ImportError:
    genai_types = None
    print("⚠️ Vega: google.genai.types not available. Config disabled.")

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
        print("✅ Vega: Gemini initialized")
    except Exception as e:
        print(f"⚠️ Vega: Gemini init failed: {e}")
        client = None
else:
    reason = "GEMINI_API_KEY missing" if not GEMINI_API_KEY else "google-genai unavailable"
    print(f"⚠️ Vega: {reason}. Using fallback mode.")

# ─────────────────────────────────────────────────────────────
# Data Models
# ─────────────────────────────────────────────────────────────

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

# ─────────────────────────────────────────────────────────────
# Analyzer Agent
# ─────────────────────────────────────────────────────────────

class AnalyzerAgent:
    """
    Vega — The Skeptic
    Deep risk analysis. References Atlas's work, builds on it, disagrees when needed.
    v4.0: Orchestrator-driven, returns structured results + spoken message.
    """

    def __init__(self, server: Optional[Any] = None):
        self.server = server
        self.name = "Vega"
        self.analysis_cache = {}
        self._tasks = []

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
            "high_confidence": -5,
        }

    # v4.0: Public entry point for the Orchestrator
    async def analyze(self, sim_data: dict) -> dict:
        """Run full analysis and return structured result + spoken message."""
        return await self._deep_analysis(sim_data)

    # v4.0: Backward-compatible fire-and-forget wrapper
    def on_simulation_complete(self, sim_data: dict):
        """React to Atlas's simulation results. Schedule analysis safely."""
        try:
            task = asyncio.create_task(self._deep_analysis(sim_data))
            task.add_done_callback(self._on_task_done)
            self._tasks.append(task)
        except Exception as e:
            print(f"⚠️ {self.name}: Failed scheduling analysis: {e}")

    def _on_task_done(self, task: asyncio.Task):
        """Catch and log any unhandled exception from an analysis task."""
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"⚠️ {self.name}: Analysis task failed: {e}")

    async def _speak(self, message: str, msg_type: str = "response"):
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

    async def _generate_vega_message(
        self,
        analysis: AnalysisResult,
        sim_data: dict,
        symbol: str
    ) -> str:
        """Use Gemini to generate a natural spoken analysis report."""

        if not client:
            return self._fallback_message(analysis, sim_data, symbol)

        system_prompt = (
            "You are Vega, a paranoid forensic accountant in a crypto team chat. "
            "You have been rugged, drained, and exploited more times than you can count. "
            "You trust no contract, no dev, and no narrative. You speak with cold precision, "
            "referencing Atlas's lab work naturally but never deferring to it blindly. "
            "Your tone is skeptical, methodical, and brutally honest. You find the thing "
            "others missed."
        )

        user_prompt = f"""
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
- Simulation Confidence: {sim_data.get('simulation_confidence', 0):.0%}

Vega's Additional Findings:
- Red Flags: {', '.join(analysis.red_flags) if analysis.red_flags else 'None'}
- Warnings: {', '.join(analysis.yellow_flags) if analysis.yellow_flags else 'None'}
- Positive Signs: {', '.join(analysis.green_flags) if analysis.green_flags else 'None'}

Requirements:
1. Acknowledge Atlas naturally but make your own independent assessment
2. Explain the risk score and what drove it
3. Highlight the single most dangerous finding first
4. Mention any green flags only to contrast with the red ones
5. Hand off to Echo with a specific request
6. Keep it conversational and under 5 sentences
7. Sound like someone who has lost money before and will not again
"""

        try:
            def _generate():
                kwargs = {
                    "model": GEMINI_MODEL,
                    "contents": f"{system_prompt}\n\n{user_prompt}",
                }
                if genai_types:
                    kwargs["config"] = genai_types.GenerateContentConfig(
                        temperature=0.85,
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

            return self._fallback_message(analysis, sim_data, symbol)

        except asyncio.TimeoutError:
            print(f"⚠️ {self.name}: Gemini call timed out")
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
            parts.append(f"Atlas called it — honeypot confirmed. {symbol} blocks sells. This is a trap.")
        elif sim_data.get("mint_function"):
            parts.append(f"Atlas flagged the mint function on {symbol} — that is a ticking bomb.")
        elif sim_data.get("blacklist_function"):
            parts.append("Blacklist capability detected. Your wallet could be frozen at any moment.")
        else:
            parts.append(f"Atlas gave {symbol} a decent trade report, but I am still seeing concerns.")

        score_templates = {
            "HIGH_RISK": [
                f"My risk score is {analysis.risk_score}/100. This is HIGH RISK territory.",
                f"Scoring this {analysis.risk_score}/100 — I would not touch this with a ten-foot pole.",
            ],
            "WARNING": [
                f"Risk score: {analysis.risk_score}/100. Proceed with extreme caution.",
                f"I am giving this a WARNING rating at {analysis.risk_score}/100. Not clean, not dirty.",
            ],
            "SAFE": [
                f"Risk score: {analysis.risk_score}/100. Surprisingly clean for a new token.",
                f"{analysis.risk_score}/100 — SAFE by current indicators, but stay vigilant.",
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
            parts.append(f"Red flags: {'; '.join(analysis.red_flags[:3])}.")

        parts.append(
            random.choice([
                "Echo, I need the creator wallet history. Now.",
                "Echo, dig into the deployer. Something feels off.",
                "That is my read. Echo, run the background check.",
            ])
        )

        return " ".join(parts)

    async def _deep_analysis(self, sim_data: dict) -> dict:
        try:
            token_address = sim_data.get("token_address")
            chain = sim_data.get("chain", "unknown")
            symbol = sim_data.get("token_symbol", "???")

            ack = "Got your report, Atlas. Now let me tear this thing apart."
            await self._speak(ack, "response")

            red_flags = []
            yellow_flags = []
            green_flags = []

            score = 0

            # Honeypot / sell blocking
            if sim_data.get("honeypot_risk"):
                score += self.weights["honeypot"]
                red_flags.append("Honeypot — sells are blocked")

            if not sim_data.get("can_sell", True):
                score += self.weights["no_sell"]
                red_flags.append("Cannot sell — exit is closed")

            if not sim_data.get("can_buy", True):
                score += self.weights["no_sell"] // 2
                red_flags.append("Cannot buy — entry is closed")

            # Contract functions
            if sim_data.get("mint_function"):
                score += self.weights["mint"]
                red_flags.append("Mint function present — infinite supply risk")

            if sim_data.get("blacklist_function"):
                score += self.weights["blacklist"]
                red_flags.append("Blacklist function present — wallet freezing risk")

            # Liquidity analysis
            liquidity = sim_data.get("liquidity_usd", 0)

            if liquidity == 0:
                score += self.weights["no_liquidity"]
                red_flags.append("Zero liquidity — no trading possible")
            elif liquidity < 1000:
                score += self.weights["low_liquidity"]
                yellow_flags.append(f"Low liquidity: ${liquidity:,.0f}")
            elif liquidity >= 10000:
                green_flags.append(f"Healthy liquidity: ${liquidity:,.0f}")
                score += self.weights["locked_liquidity"] // 2

            # Liquidity lock
            if sim_data.get("liquidity_locked"):
                score += self.weights["locked_liquidity"]
                green_flags.append("Liquidity is locked")
            else:
                if liquidity > 0:
                    yellow_flags.append("Liquidity is unlocked — rug pull possible")

            # Tax analysis
            buy_tax = sim_data.get("buy_tax", 0)
            sell_tax = sim_data.get("sell_tax", 0)

            if sell_tax > 10 or buy_tax > 10:
                score += self.weights["high_tax"]
                yellow_flags.append(f"High taxes: {buy_tax}% buy / {sell_tax}% sell")
            elif sell_tax > 5 or buy_tax > 5:
                yellow_flags.append(f"Moderate taxes: {buy_tax}% buy / {sell_tax}% sell")

            # Ownership
            if sim_data.get("owner_renounced"):
                score += self.weights["renounced"]
                green_flags.append("Ownership renounced — contract is immutable")
            else:
                yellow_flags.append("Ownership not renounced — dev retains control")

            # Simulation confidence
            confidence = sim_data.get("simulation_confidence", 0.5)
            if confidence >= 0.8:
                score += self.weights["high_confidence"]
                green_flags.append("High simulation confidence")
            elif confidence < 0.4:
                yellow_flags.append("Low simulation confidence — data may be incomplete")

            # v4.0: Deterministic additional checks based on actual data
            # No randomness — only flag what we can verify from simulation data
            if sim_data.get("eth_call_revert_reason") or sim_data.get("solana_revert_reason"):
                yellow_flags.append("On-chain simulation encountered errors — results may be incomplete")

            if sim_data.get("solana_mint_authority"):
                red_flags.append("Solana mint authority is active — supply can be inflated")
                score += self.weights["mint"] // 2

            if sim_data.get("solana_freeze_authority"):
                red_flags.append("Solana freeze authority is active — accounts can be frozen")
                score += self.weights["blacklist"] // 2

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

            # v4.0: Return structured result + message for Orchestrator
            report = await self._generate_vega_message(analysis, sim_data, symbol)
            return {
                **analysis.__dict__,
                "message": report,
                "token_symbol": symbol,
                "token_address": token_address,
                "chain": chain,
            }

        except Exception as e:
            print(f"❌ {self.name}: Fatal analysis error: {e}")
            return {
                "token_address": sim_data.get("token_address", ""),
                "chain": sim_data.get("chain", "unknown"),
                "token_symbol": sim_data.get("token_symbol", "???"),
                "risk_score": 50,
                "risk_level": "WARNING",
                "red_flags": ["Analysis engine error — treat with caution"],
                "yellow_flags": [],
                "green_flags": [],
                "message": f"Analysis crashed on {sim_data.get('token_symbol', '???')}: {e}",
                "error": str(e),
            }

    def stop(self):
        """Cancel any pending analysis tasks."""
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
                print(f"\n📡 {event_type}: {data}")
        except Exception as e:
            print(f"⚠️ Publish error: {e}")

    analyzer = AnalyzerAgent()

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
        "owner_renounced": True,
        "simulation_confidence": 0.75
    }

    try:
        asyncio.run(analyzer.analyze(test_sim))
    except KeyboardInterrupt:
        analyzer.stop()
        print("\n🛑 Vega stopped.")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
