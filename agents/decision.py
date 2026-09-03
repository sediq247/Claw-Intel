import json
import time
import os
import asyncio
import random
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional, List
from enum import Enum
from dotenv import load_dotenv

try:
    from google import genai
    from google.genai import types as genai_types
    HAS_GENAI = True
except ImportError:
    genai = None
    genai_types = None
    HAS_GENAI = False

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

FALLBACK_MODELS = [
    GEMINI_MODEL,
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
    "gemini-1.5-flash-latest",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash",
]


class GeminiWrapper:
    def __init__(self, api_key: str):
        self._client = genai.Client(api_key=api_key)
        self._models = [m for m in FALLBACK_MODELS if m]

    async def generate(self, contents: str, config=None):
        last_err = None
        for model in self._models:
            try:
                def _call():
                    kwargs = {"model": model, "contents": contents}
                    if config and genai_types:
                        kwargs["config"] = config
                    return self._client.models.generate_content(**kwargs)
                return await asyncio.wait_for(asyncio.to_thread(_call), timeout=15)
            except Exception as e:
                err_str = str(e)
                if "404" in err_str or "NOT_FOUND" in err_str:
                    print(f"⚠️ Orion: Model {model} unavailable, trying fallback...")
                    last_err = e
                    continue
                raise
        raise last_err or Exception("All Gemini models exhausted")


gemini = GeminiWrapper(GEMINI_API_KEY) if GEMINI_API_KEY and HAS_GENAI else None
if not gemini:
    print("⚠️ Orion: Gemini unavailable. Running fallback mode.")


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

    async def decide(self, sim_data: dict, analysis_data: dict, memory_data: Optional[dict] = None) -> dict:
        return await self._make_decision(sim_data, analysis_data, memory_data)

    def _pick_nova_call(self, roast: bool = True) -> str:
        if roast:
            return random.choice(self._nova_roasts)
        return random.choice(self._nova_praises)

    async def _generate_orion_message(self, result: SynthesisResult, sim: dict, analysis: dict, memory: Optional[dict]) -> str:
        if not gemini:
            return self._fallback_message(result, sim, analysis, memory)

        profile = (memory or {}).get("profile", {}) or {}
        tags = profile.get("tags", [])
        rep = profile.get("reputation_score", "Unknown")
        creator = (memory or {}).get("creator", "unknown")
        creator_short = creator[:10] + "..." + creator[-4:] if creator != "unknown" else "unknown"
        nova_call = result.nova_call

        debate = (memory or {}).get("message", "") if memory else ""
        has_debate = bool(debate) and ("disagree" in debate.lower() or "contradict" in debate.lower() or "optimistic" in debate.lower())

        system_prompt = (
            "You are Orion, the team lead of a crypto research squad. You weigh everyone's findings, "
            "form your own view on where the token is heading, and give a final score. You are sharp, "
            "confident, and occasionally playful. You NEVER tell anyone to buy, sell, or trade. You simply "
            "assess and move on. You sometimes tease Nova in a lighthearted way. You speak like someone "
            "who has seen a thousand tokens and knows the patterns."
        )

        user_prompt = (
            f"Token: {result.symbol}\n"
            f"Chain: {result.chain}\n\n"
            f"Atlas (Trade Mechanics):\n"
            f"- Buy path: {'open' if sim.get('can_buy') else 'blocked'}\n"
            f"- Sell path: {'open' if sim.get('can_sell') else 'blocked'}\n"
            f"- Honeypot flag: {'yes' if sim.get('honeypot_risk') else 'no'}\n"
            f"- Liquidity: ${sim.get('liquidity_usd', 0):,.0f}\n"
            f"- Buy tax: {sim.get('buy_tax', 0)}%\n"
            f"- Sell tax: {sim.get('sell_tax', 0)}%\n"
            f"- Mint function: {'yes' if sim.get('mint_function') else 'no'}\n"
            f"- Blacklist: {'yes' if sim.get('blacklist_function') else 'no'}\n"
            f"- Owner renounced: {'yes' if sim.get('owner_renounced') else 'no'}\n\n"
            f"Vega (Contract & Market):\n"
            f"- Risk score: {analysis.get('risk_score', 'N/A')}/100\n"
            f"- Risk level: {analysis.get('risk_level', 'N/A')}\n"
            f"- Red flags: {', '.join(analysis.get('red_flags', [])) if analysis.get('red_flags') else 'None'}\n"
            f"- Yellow flags: {', '.join(analysis.get('yellow_flags', [])) if analysis.get('yellow_flags') else 'None'}\n"
            f"- Green flags: {', '.join(analysis.get('green_flags', [])) if analysis.get('green_flags') else 'None'}\n\n"
            f"Echo (Creator & Debate):\n"
            f"- Creator: {creator_short}\n"
            f"- Reputation: {rep}/100\n"
            f"- Tags: {', '.join(tags) if tags else 'None'}\n"
            f"- Prediction: {(memory or {}).get('predicted_outcome', 'unknown')} ({(memory or {}).get('prediction_confidence', 0)*100:.0f}% confidence)\n"
            f"- Debate with team: {'Yes — Echo disagrees with other agents' if has_debate else 'No contradictions'}\n\n"
            f"Orion's Synthesis:\n"
            f"- Final score: {result.final_score:.0f}/100\n"
            f"- Direction: {result.direction}\n"
            f"- Confidence: {result.confidence*100:.0f}%\n\n"
            f"Requirements:\n"
            f"1. Summarize what the team found in 1-2 sentences\n"
            f"2. Give your own perspective on where this token is heading\n"
            f"3. If Echo debated the team, acknowledge the tension neutrally\n"
            f"4. State the final score and direction clearly\n"
            f"5. NEVER advise buying, selling, or trading\n"
            f"6. End by calling on Nova with this exact line (use it verbatim, do not modify): {nova_call}\n"
            f"7. Keep it under 6 sentences\n"
            f"8. Sound like a lead who trusts data but keeps the room light"
        )

        try:
            config = None
            if genai_types:
                config = genai_types.GenerateContentConfig(temperature=0.9, max_output_tokens=280)
            response = await gemini.generate(f"{system_prompt}\n\n{user_prompt}", config=config)
            text = response.text if hasattr(response, "text") else str(response)
            return text.strip() if text else self._fallback_message(result, sim, analysis, memory)
        except asyncio.TimeoutError:
            print("⚠️ Orion: Gemini timed out")
            return self._fallback_message(result, sim, analysis, memory)
        except Exception as e:
            print(f"⚠️ Orion: Gemini error: {e}")
            return self._fallback_message(result, sim, analysis, memory)

    def _fallback_message(self, result: SynthesisResult, sim: dict, analysis: dict, memory: Optional[dict]) -> str:
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
            parts.append(f"Echo predicts {memory['predicted_outcome'].lower()} ({memory.get('prediction_confidence', 0)*100:.0f}% confidence). ")

        parts.append(f"My read: {direction} with a {score:.0f}/100 score ({confidence:.0f}% confidence). ")
        parts.append(result.nova_call)
        return "".join(parts)

    def _calculate_direction(self, final_score: float, sim: dict, analysis: dict, memory: Optional[dict]) -> str:
        if sim.get("honeypot_risk") or not sim.get("can_sell", True):
            return Direction.DOWN.value

        momentum = 0
        if analysis.get("price_change_24h", 0) > 50:
            momentum += 2
        elif analysis.get("price_change_24h", 0) < -50:
            momentum -= 2
        if analysis.get("buy_pressure") is not None and analysis["buy_pressure"] > 0.6:
            momentum += 1
        elif analysis.get("buy_pressure") is not None and analysis["buy_pressure"] < 0.3:
            momentum -= 1
        if memory and memory.get("predicted_outcome") == "HIGH_RISK":
            momentum -= 2
        elif memory and memory.get("predicted_outcome") == "SAFE":
            momentum += 1

        if final_score >= 70:
            return Direction.DOWN.value
        elif final_score <= 30:
            if momentum > 0:
                return Direction.UP.value
            return Direction.SIDEWAYS.value
        else:
            if momentum > 1:
                return Direction.UP.value
            elif momentum < -1:
                return Direction.DOWN.value
            return Direction.SIDEWAYS.value

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
            is_scammer = any(t in tags for t in ("repeat_rugger", "honeypot_dev", "known_scammer", "serial_rugger", "ghost_dev"))
            memory_score = 100 - creator_rep
            if is_scammer:
                memory_score += 30

            final_score = (
                sim_score * self.weights["simulation"] +
                analysis_risk * self.weights["analysis"] +
                memory_score * self.weights["memory"]
            )
            final_score = max(0, min(100, final_score))

            if is_scammer or sim.get("honeypot_risk"):
                final_score = max(final_score, 75)

            direction = self._calculate_direction(final_score, sim, analysis, memory)

            has_sim = bool(sim and sim.get("token_address"))
            has_analysis = bool(analysis and analysis.get("token_address"))
            has_memory = bool(memory and memory.get("token_address"))

            if has_sim and has_analysis and has_memory:
                confidence = sim.get("simulation_confidence", 0.5) * 0.4 + 0.4 + 0.2
            elif has_sim and has_analysis:
                confidence = (sim.get("simulation_confidence", 0.5) * 0.4 + 0.4) * 0.7
                print(f"⚠️ Orion: Memory data missing -- confidence reduced")
            else:
                confidence = 0.4
                print(f"⚠️ Orion: Incomplete data -- confidence reduced")
            confidence = max(0.0, min(1.0, confidence))

            roast = final_score < 50 or random.random() < 0.4
            nova_call = self._pick_nova_call(roast=roast)

            result = SynthesisResult(
                token_address=token, chain=chain, symbol=symbol,
                final_score=final_score, direction=direction,
                confidence=confidence, perspective="",
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
                nova_call=nova_call,
            )

            report = await self._generate_orion_message(result, sim, analysis, memory)

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
                "final_score": 50, "direction": "UNKNOWN", "confidence": 0.0,
                "perspective": f"Synthesis crashed: {e}",
                "message": f"Orion failed to synthesize: {e}", "error": str(e),
                "nova_call": self._pick_nova_call(),
            }

    def stop(self):
        print(f"🛑 Orion: Stopped.")


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
        "is_new": False, "predicted_outcome": "SAFE", "prediction_confidence": 0.6,
    }
    try:
        asyncio.run(orion.decide(test_sim, test_analysis, test_memory))
    except KeyboardInterrupt:
        orion.stop()
        print("\n🛑 Orion stopped.")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
