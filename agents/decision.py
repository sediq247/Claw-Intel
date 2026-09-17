"""
Orion — The Lead
================
Real multi-LLM synthesis, scoring and direction calling.
Uses the unified LLMClient (Gemini / Grok / Cerebras / OpenRouter)
with strong rule-based fallback.
"""

import json
import time
import asyncio
import random
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional, List
from enum import Enum

from agents.llm_client import llm


class Direction(Enum):
    UP = "UP"
    DOWN = "DOWN"
    SIDEWAYS = "SIDEWAYS"
    UNKNOWN = "UNKNOWN"


@dataclass
class SynthesisResult:
    token_address: str
    chain: str
    symbol: str
    final_score: float
    direction: str
    confidence: float
    perspective: str
    factors: Dict[str, Any]
    timestamp: float
    creator: str = ""
    nova_call: str = ""

    def to_json(self):
        return json.dumps(asdict(self), default=str)


class DecisionAgent:
    def __init__(self, server: Optional[Any] = None):
        self.server = server
        self.name = "Orion"
        self.SAFE_THRESHOLD = 30
        self.WARNING_THRESHOLD = 60
        # Legacy weights kept only for pure rule-based fallback
        self.weights = {"simulation": 0.30, "analysis": 0.40, "memory": 0.30}

        self._nova_roasts = [
            "Nova, stop daydreaming and go scan the chains. I need real tokens, not your imaginary ones.",
            "Nova, my coffee is getting cold while you stare at empty blocks. Find me something.",
            "Nova, if I wanted silence I'd talk to a blockchain node. Go watch the mempool.",
            "Hey Nova, the chains aren't going to watch themselves. Chop chop.",
            "Nova, I love your enthusiasm for nothing happening. Now go find something that IS happening.",
            "Nova, you're like a security guard who only watches empty parking lots. Go patrol the DEXs.",
            "Nova, my patience is thinner than this token's liquidity. Go find the next one.",
            "Nova, I appreciate the zen energy, but I need volatility. Scan the chains.",
            "Nova, if you find a token before I finish this sentence, I'll buy you a pixel art NFT.",
            "Nova, you're the only person I know who can make 'no new tokens' sound like poetry. Now go work.",
        ]
        self._nova_praises = [
            "Nova, solid find. Now go get me the next one before the bots eat it.",
            "Nova delivered. Respect. Now find another.",
            "Good eye, Nova. The chains are quiet — too quiet. Go shake some trees.",
            "Nova spotted this one clean. I expect the next one just as fast.",
        ]

        if llm.is_available:
            print(f"✅ Orion: Multi-LLM brain online → {llm.status()['available_providers']}")
        else:
            print("⚠️ Orion: No LLM providers available. Running pure rule-based fallback.")

    async def decide(self, sim_data: dict, analysis_data: dict, memory_data: Optional[dict] = None, debate_data: Optional[dict] = None) -> dict:
        return await self._make_decision(sim_data, analysis_data, memory_data, debate_data)

    def _pick_nova_call(self, roast: bool = True) -> str:
        if roast:
            return random.choice(self._nova_roasts)
        return random.choice(self._nova_praises)

    # ------------------------------------------------------------------
    # Rule-based fallback (used when all LLMs fail)
    # ------------------------------------------------------------------
    def _rule_based_score(self, sim: dict, analysis: dict, memory: Optional[dict]) -> tuple:
        sim_score = 50.0
        if sim.get("honeypot_risk") or not sim.get("can_sell", True):
            sim_score = 95.0
        elif not sim.get("can_buy", True):
            sim_score = 80.0
        else:
            tax = max(sim.get("buy_tax", 0) or 0, sim.get("sell_tax", 0) or 0)
            if tax > 15:
                sim_score = 75.0
            elif tax > 8:
                sim_score = 60.0
            liq = sim.get("liquidity_usd", 0) or 0
            if liq < 1000:
                sim_score = max(sim_score, 70.0)
            elif liq > 20000:
                sim_score = min(sim_score, 35.0)

        analysis_risk = float(analysis.get("risk_score", 50) or 50)

        memory_score = 50.0
        if memory:
            profile = memory.get("profile", {}) or {}
            rep = float(profile.get("reputation_score", 50) or 50)
            memory_score = 100 - rep  # higher reputation → lower risk score
            pred = (memory.get("predicted_outcome") or "").upper()
            if pred in ("HIGH_RISK", "DEAD", "RUG"):
                memory_score = max(memory_score, 80.0)
            elif pred in ("SAFE", "LEGIT"):
                memory_score = min(memory_score, 30.0)

        final = (
            sim_score * self.weights["simulation"]
            + analysis_risk * self.weights["analysis"]
            + memory_score * self.weights["memory"]
        )
        final = max(0.0, min(100.0, final))

        # Hard overrides
        if sim.get("honeypot_risk") or not sim.get("can_sell", True):
            final = max(final, 85.0)

        direction = self._calculate_direction(final, sim, analysis, memory)
        confidence = 0.55 if final > 70 or final < 30 else 0.45
        return final, direction, confidence

    def _calculate_direction(self, final_score: float, sim: dict, analysis: dict, memory: Optional[dict]) -> str:
        if sim.get("honeypot_risk") or not sim.get("can_sell", True):
            return Direction.DOWN.value

        momentum = 0
        pc = analysis.get("price_change_24h")
        if pc is not None:
            if pc > 50:
                momentum += 2
            elif pc < -50:
                momentum -= 2
        bp = analysis.get("buy_pressure")
        if bp is not None:
            if bp > 0.6:
                momentum += 1
            elif bp < 0.3:
                momentum -= 1
        if memory and memory.get("predicted_outcome") == "HIGH_RISK":
            momentum -= 2
        elif memory and memory.get("predicted_outcome") == "SAFE":
            momentum += 1

        if final_score >= 70:
            return Direction.DOWN.value
        elif final_score <= 30:
            if momentum >= 1:
                return Direction.UP.value
            return Direction.SIDEWAYS.value
        else:
            if momentum >= 2:
                return Direction.UP.value
            if momentum <= -2:
                return Direction.DOWN.value
            return Direction.SIDEWAYS.value

    def _fallback_message(self, result: SynthesisResult, sim: dict, analysis: dict, memory: Optional[dict], debate: Optional[dict] = None) -> str:
        parts = []
        symbol = result.symbol
        score = result.final_score
        direction = result.direction
        confidence = result.confidence * 100

        if sim.get("honeypot_risk") or not sim.get("can_sell", True):
            parts.append(f"{symbol} has a blocked exit path. That alone shapes the outlook. ")
        elif sim.get("can_buy") and sim.get("can_sell"):
            parts.append(f"{symbol} has open trade paths on both sides. ")

        vega_risk = analysis.get("risk_score", 50)
        if vega_risk >= 70:
            parts.append(f"Vega flagged heavy structural concerns ({vega_risk}/100). ")
        elif vega_risk <= 30:
            parts.append(f"Vega's read is relatively clean ({vega_risk}/100). ")

        profile = (memory or {}).get("profile", {}) or {}
        rep = profile.get("reputation_score", 50)
        if rep <= 20:
            parts.append(f"Echo found a creator with a {rep:.0f}/100 reputation — that's a heavy anchor. ")
        elif rep >= 70:
            parts.append(f"Echo's creator track record looks solid ({rep:.0f}/100). ")

        if memory and memory.get("predicted_outcome"):
            parts.append(
                f"Echo predicts {memory['predicted_outcome'].lower()} "
                f"({memory.get('prediction_confidence', 0)*100:.0f}% confidence). "
            )

        if debate and (debate.get("transcript") or debate.get("consensus_notes")):
            parts.append("I heard the team debate — closing it now. ")
        parts.append(f"My final call: {direction} at {score:.0f}/100 ({confidence:.0f}% confidence). ")
        parts.append(result.nova_call)
        return "".join(parts)

    # ------------------------------------------------------------------
    # Real LLM synthesis
    # ------------------------------------------------------------------
    async def _llm_synthesize(self, sim: dict, analysis: dict, memory: Optional[dict], debate: Optional[dict] = None) -> Optional[Dict[str, Any]]:
        if not llm.is_available:
            return None

        profile = (memory or {}).get("profile", {}) or {}
        creator = (memory or {}).get("creator", "unknown")
        creator_short = (creator[:10] + "..." + creator[-4:]) if len(creator) > 16 else creator

        evidence = {
            "token": {
                "symbol": sim.get("token_symbol") or sim.get("symbol") or analysis.get("token_symbol") or "???",
                "address": sim.get("token_address") or analysis.get("token_address"),
                "chain": sim.get("chain") or analysis.get("chain"),
            },
            "atlas_simulation": {
                "can_buy": sim.get("can_buy"),
                "can_sell": sim.get("can_sell"),
                "honeypot_risk": sim.get("honeypot_risk"),
                "buy_tax": sim.get("buy_tax"),
                "sell_tax": sim.get("sell_tax"),
                "liquidity_usd": sim.get("liquidity_usd"),
                "liquidity_locked": sim.get("liquidity_locked"),
                "mint_function": sim.get("mint_function"),
                "blacklist_function": sim.get("blacklist_function"),
                "simulation_confidence": sim.get("simulation_confidence"),
            },
            "vega_analysis": {
                "risk_score": analysis.get("risk_score"),
                "risk_level": analysis.get("risk_level"),
                "red_flags": analysis.get("red_flags", []),
                "yellow_flags": analysis.get("yellow_flags", []),
                "green_flags": analysis.get("green_flags", []),
                "ownership_renounced": analysis.get("ownership_renounced"),
                "is_proxy": analysis.get("is_proxy"),
                "lp_ownership": analysis.get("lp_ownership"),
                "top_holder_percent": analysis.get("top_holder_percent"),
                "holder_count": analysis.get("holder_count"),
                "volume_24h": analysis.get("volume_24h"),
                "price_change_24h": analysis.get("price_change_24h"),
                "buy_pressure": analysis.get("buy_pressure"),
            },
            "echo_memory": {
                "creator": creator_short,
                "reputation_score": profile.get("reputation_score"),
                "tags": profile.get("tags", []),
                "total_tokens_created": profile.get("total_tokens_created"),
                "predicted_outcome": (memory or {}).get("predicted_outcome"),
                "prediction_confidence": (memory or {}).get("prediction_confidence"),
                "is_new_creator": (memory or {}).get("is_new"),
            },
            "team_debate": {
                "transcript": (debate or {}).get("transcript", []),
                "consensus_notes": (debate or {}).get("consensus_notes", ""),
                "disagreements": (debate or {}).get("disagreements", []),
                "had_conflict": (debate or {}).get("had_conflict", False),
            },
        }

        system_prompt = (
            "You are Orion, the lead analyst of a crypto market intelligence team. "
            "You receive structured evidence from three specialists:\n"
            "- Atlas (trade simulation & mechanics)\n"
            "- Vega (contract structure & market metrics)\n"
            "- Echo (creator history & reputation)\n\n"
            "Your job is to synthesize everything — including the team debate — into a calibrated judgment.\nIf agents disagreed, resolve the tension using the strongest on-chain evidence.\n"
            "Rules:\n"
            "1. Never give financial advice (no buy/sell recommendations).\n"
            "2. Hard red flags (honeypot, blocked sell, unlimited mint) must push score high and direction DOWN.\n"
            "3. Score is 0-100 risk-oriented (higher = more dangerous / worse outlook).\n"
            "4. Direction must be one of: UP, DOWN, SIDEWAYS, UNKNOWN.\n"
            "5. Be concise but precise. Base every claim on the evidence."
        )

        user_prompt = (
            "Here is the full evidence package (JSON):\n\n"
            f"{json.dumps(evidence, indent=2, default=str)}\n\n"
            "Return a JSON object with exactly these keys:\n"
            "{\n"
            '  "final_score": <number 0-100>,\n'
            '  "direction": "<UP|DOWN|SIDEWAYS|UNKNOWN>",\n'
            '  "confidence": <number 0.0-1.0>,\n'
            '  "key_factors": ["factor1", "factor2", ...],\n'
            '  "reasoning": "<2-4 sentence internal reasoning>",\n'
            '  "perspective": "<1-2 sentence public perspective for the team>"\n'
            "}"
        )

        try:
            result = await llm.generate_json(
                contents=user_prompt,
                system=system_prompt,
                temperature=0.35,
                max_tokens=900,
            )
            # Basic validation
            if not isinstance(result.get("final_score"), (int, float)):
                return None
            score = max(0.0, min(100.0, float(result["final_score"])))
            direction = str(result.get("direction", "UNKNOWN")).upper()
            if direction not in ("UP", "DOWN", "SIDEWAYS", "UNKNOWN"):
                direction = "UNKNOWN"
            confidence = max(0.0, min(1.0, float(result.get("confidence", 0.5))))
            return {
                "final_score": score,
                "direction": direction,
                "confidence": confidence,
                "key_factors": result.get("key_factors", []),
                "reasoning": result.get("reasoning", ""),
                "perspective": result.get("perspective", ""),
            }
        except Exception as e:
            print(f"⚠️ Orion: LLM synthesis failed → {e}")
            return None

    async def _generate_orion_message(
        self,
        result: SynthesisResult,
        sim: dict,
        analysis: dict,
        memory: Optional[dict],
        llm_meta: Optional[dict] = None,
        debate: Optional[dict] = None,
    ) -> str:
        """Acknowledge team debate, close it, deliver final decision, call Nova."""
        if not llm.is_available:
            return self._fallback_message(result, sim, analysis, memory, debate)

        profile = (memory or {}).get("profile", {}) or {}
        tags = profile.get("tags", [])
        rep = profile.get("reputation_score", "Unknown")
        creator = (memory or {}).get("creator", "unknown")
        creator_short = (creator[:10] + "..." + creator[-4:]) if len(creator) > 16 else "unknown"
        nova_call = result.nova_call

        debate = debate or {}
        transcript = debate.get("transcript") or []
        consensus = debate.get("consensus_notes") or ""
        disagreements = debate.get("disagreements") or []
        debate_lines = []
        for t in transcript[:6]:
            debate_lines.append(
                f"- {(t.get('agent') or '?').upper()}: {(t.get('message') or '')[:160]}"
            )
        debate_block = "\n".join(debate_lines) if debate_lines else "(No debate transcript.)"

        system_prompt = (
            "You are Orion, team lead of a crypto research squad. "
            "The specialists have already debated. Your job is to: "
            "(1) acknowledge what Atlas, Vega, and Echo argued, "
            "(2) formally close the debate, "
            "(3) deliver YOUR final decision (score + direction), "
            "(4) release the team for the next token by calling Nova. "
            "Quiet authority. Never advise buying or selling. "
            "End with the exact Nova line provided — do not change it."
        )

        user_prompt = (
            f"Token: {result.symbol}\n"
            f"Your final score: {result.final_score:.0f}/100\n"
            f"Your direction: {result.direction}\n"
            f"Confidence: {result.confidence*100:.0f}%\n"
            f"Key factors: {', '.join((llm_meta or {}).get('key_factors', [])[:5]) or 'see evidence'}\n"
            f"Your reasoning: {(llm_meta or {}).get('reasoning', result.perspective)}\n\n"
            f"Atlas: can_buy={sim.get('can_buy')}, can_sell={sim.get('can_sell')}, "
            f"honeypot={sim.get('honeypot_risk')}, liq=${(sim.get('liquidity_usd') or 0):,.0f}\n"
            f"Vega risk: {analysis.get('risk_score', 'N/A')}/100 ({analysis.get('risk_level', 'N/A')})\n"
            f"Echo: creator {creator_short}, rep {rep}/100, tags {tags}\n\n"
            f"TEAM DEBATE:\n{debate_block}\n"
            f"Consensus notes: {consensus or 'n/a'}\n"
            f"Disagreements: {', '.join(disagreements) if disagreements else 'none flagged'}\n\n"
            f"Write 5-8 sentences in this order:\n"
            f"1. Acknowledge the team discussion (reference Atlas/Vega/Echo if useful).\n"
            f"2. State clearly that the debate is closed.\n"
            f"3. Deliver YOUR final decision: score, direction, brief why.\n"
            f"4. End with this exact line (verbatim): {nova_call}"
        )

        try:
            text_out = await llm.generate(
                contents=user_prompt,
                system=system_prompt,
                temperature=0.8,
                max_tokens=360,
            )
            return text_out.strip() if text_out else self._fallback_message(result, sim, analysis, memory, debate)
        except Exception as e:
            print(f"⚠️ Orion: Speech generation failed → {e}")
            return self._fallback_message(result, sim, analysis, memory, debate)

    # ------------------------------------------------------------------
    # Main decision entry
    # ------------------------------------------------------------------
    async def _make_decision(
        self, sim: dict, analysis: dict, memory: Optional[dict] = None, debate: Optional[dict] = None
    ) -> dict:
        try:
            symbol = (
                sim.get("token_symbol")
                or sim.get("symbol")
                or analysis.get("token_symbol")
                or "???"
            )
            token_address = sim.get("token_address") or analysis.get("token_address") or "unknown"
            chain = sim.get("chain") or analysis.get("chain") or "unknown"

            print(f"🧠 Orion: Synthesizing {symbol} ({chain})...")

            # 1. Try real LLM reasoning first
            llm_result = await self._llm_synthesize(sim, analysis, memory, debate)

            if llm_result:
                final_score = llm_result["final_score"]
                direction = llm_result["direction"]
                confidence = llm_result["confidence"]
                perspective = llm_result.get("perspective") or llm_result.get("reasoning", "")
                factors = {
                    "source": "llm",
                    "key_factors": llm_result.get("key_factors", []),
                    "reasoning": llm_result.get("reasoning", ""),
                }
                print(f"✅ Orion: LLM synthesis → {direction} @ {final_score:.0f}/100 ({confidence*100:.0f}%)")
            else:
                # 2. Pure rule-based fallback
                final_score, direction, confidence = self._rule_based_score(sim, analysis, memory)
                perspective = f"Rule-based synthesis for {symbol}."
                factors = {"source": "rules"}
                print(f"📐 Orion: Rule fallback → {direction} @ {final_score:.0f}/100")

            roast = final_score < 50 or random.random() < 0.4
            nova_call = self._pick_nova_call(roast=roast)

            result = SynthesisResult(
                token_address=token_address,
                chain=chain,
                symbol=symbol,
                final_score=final_score,
                direction=direction,
                confidence=confidence,
                perspective=perspective,
                factors=factors,
                timestamp=time.time(),
                creator=(memory or {}).get("creator", ""),
                nova_call=nova_call,
            )

            report = await self._generate_orion_message(
                result, sim, analysis, memory, llm_meta=llm_result, debate=debate
            )

            result_dict = {**result.__dict__, "message": report}
            for key in ["creator", "origin_source", "timestamp", "attention_score", "volume_24h", "market_cap"]:
                if key in sim and key not in result_dict:
                    result_dict[key] = sim[key]
                elif key in analysis and key not in result_dict:
                    result_dict[key] = analysis[key]

            return result_dict

        except Exception as e:
            print(f"❌ Orion: Fatal synthesis error: {e}")
            return {
                "token_address": sim.get("token_address", "unknown"),
                "chain": sim.get("chain", "unknown"),
                "symbol": sim.get("token_symbol", sim.get("symbol", "???")),
                "final_score": 50,
                "direction": "UNKNOWN",
                "confidence": 0.0,
                "perspective": f"Synthesis crashed: {e}",
                "message": f"Orion failed to synthesize: {e}",
                "error": str(e),
                "nova_call": self._pick_nova_call(),
            }

    def stop(self):
        print(f"🛑 Orion: Stopped.")


if __name__ == "__main__":
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
        "simulation_confidence": 0.85,
    }
    test_analysis = {
        "token_address": "0x1234567890abcdef1234567890abcdef12345678",
        "chain": "bsc",
        "token_symbol": "TEST",
        "risk_score": 25,
        "risk_level": "SAFE",
        "red_flags": [],
        "yellow_flags": ["Moderate taxes"],
        "green_flags": ["Healthy liquidity"],
    }
    test_memory = {
        "token_address": "0x1234567890abcdef1234567890abcdef12345678",
        "chain": "bsc",
        "symbol": "TEST",
        "creator": "0xabcdef1234567890abcdef1234567890abcdef12",
        "profile": {"reputation_score": 75, "tags": ["legit_builder"], "total_tokens_created": 3},
        "is_new": False,
        "predicted_outcome": "SAFE",
        "prediction_confidence": 0.6,
    }
    try:
        asyncio.run(orion.decide(test_sim, test_analysis, test_memory))
    except KeyboardInterrupt:
        orion.stop()
        print("\n🛑 Orion stopped.")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
