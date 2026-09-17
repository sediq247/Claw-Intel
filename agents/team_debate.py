"""
Team Debate Engine
==================
Gives agents shared awareness of each other and runs a structured
debate round so they can challenge, support, or refine findings
before Orion makes the final call.

Flow:
  1. Collect structured briefs from Atlas, Vega, Echo
  2. Run 1–2 debate turns (LLM) where agents react to each other
  3. Produce a debate transcript + consensus notes for Orion
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

try:
    from agents.llm_client import llm
    HAS_LLM = True
except ImportError:
    llm = None
    HAS_LLM = False


AGENT_PERSONAS = {
    "atlas": (
        "You are Atlas, the trader. You care about what the chain actually allows: "
        "buy/sell paths, taxes, liquidity, honeypots. You speak in short mechanical facts. "
        "You challenge soft conclusions that ignore trade mechanics."
    ),
    "vega": (
        "You are Vega, the contract analyst. You care about structure: ownership, proxies, "
        "holders, bytecode risks. You report structural facts, not moral judgments. "
        "You challenge claims that ignore contract architecture."
    ),
    "echo": (
        "You are Echo, the investigator. You never forget creator history and patterns. "
        "You challenge optimistic reads when the deployer has a bad track record, "
        "and you support caution when history is clean. You debate when data conflicts."
    ),
    "nova": (
        "You are Nova, the observer. You care about market traction, liquidity, volume, age. "
        "You stay calm and descriptive. You can note if metrics look thin or strong."
    ),
}


def _brief_atlas(sim: dict) -> str:
    parts = []
    if sim.get("honeypot_risk") or not sim.get("can_sell", True):
        parts.append("Exit appears blocked / honeypot risk.")
    elif sim.get("can_buy") and sim.get("can_sell"):
        parts.append("Buy and sell paths open.")
    tax_b = sim.get("buy_tax")
    tax_s = sim.get("sell_tax")
    if tax_b is not None or tax_s is not None:
        parts.append(f"Taxes ~{tax_b or 0}% buy / {tax_s or 0}% sell.")
    liq = sim.get("liquidity_usd")
    if liq is not None:
        parts.append(f"Liquidity ${liq:,.0f}.")
    if sim.get("llm_interpretation"):
        parts.append(str(sim["llm_interpretation"]))
    if sim.get("mint_function"):
        parts.append("Mint function present.")
    if sim.get("blacklist_function"):
        parts.append("Blacklist function present.")
    return " ".join(parts) or "Simulation data limited."


def _brief_vega(analysis: dict) -> str:
    parts = []
    score = analysis.get("risk_score")
    level = analysis.get("risk_level")
    if score is not None:
        parts.append(f"Risk {score}/100 ({level or 'n/a'}).")
    reds = analysis.get("red_flags") or []
    yellows = analysis.get("yellow_flags") or []
    greens = analysis.get("green_flags") or []
    if reds:
        parts.append("Red: " + "; ".join(reds[:4]))
    if yellows:
        parts.append("Yellow: " + "; ".join(yellows[:3]))
    if greens:
        parts.append("Green: " + "; ".join(greens[:3]))
    if analysis.get("reasoning"):
        parts.append(str(analysis["reasoning"])[:200])
    return " ".join(parts) or "Structural analysis limited."


def _brief_echo(memory: Optional[dict]) -> str:
    if not memory:
        return "No creator profile available."
    parts = []
    pred = memory.get("predicted_outcome")
    conf = memory.get("prediction_confidence")
    if pred:
        parts.append(f"Prediction {pred}" + (f" ({conf*100:.0f}%)" if conf is not None else "") + ".")
    profile = memory.get("profile") or {}
    rep = profile.get("reputation_score")
    if rep is not None:
        parts.append(f"Creator rep {rep}/100.")
    tags = profile.get("tags") or []
    if tags:
        parts.append("Tags: " + ", ".join(tags[:4]))
    if memory.get("prediction_reasoning"):
        parts.append(str(memory["prediction_reasoning"])[:180])
    return " ".join(parts) or "Creator data limited."


def build_shared_context(
    symbol: str,
    chain: str,
    sim: dict,
    analysis: dict,
    memory: Optional[dict],
    nova_note: str = "",
) -> Dict[str, Any]:
    """Structured shared context every agent can see."""
    return {
        "token": {"symbol": symbol, "chain": chain},
        "team_briefs": {
            "nova": nova_note or "Discovery metrics only.",
            "atlas": _brief_atlas(sim or {}),
            "vega": _brief_vega(analysis or {}),
            "echo": _brief_echo(memory),
        },
        "raw_scores": {
            "vega_risk": (analysis or {}).get("risk_score"),
            "echo_prediction": (memory or {}).get("predicted_outcome"),
            "echo_confidence": (memory or {}).get("prediction_confidence"),
            "atlas_can_sell": (sim or {}).get("can_sell"),
            "atlas_honeypot": (sim or {}).get("honeypot_risk"),
            "liquidity_usd": (sim or {}).get("liquidity_usd"),
        },
        "timestamp": time.time(),
    }


async def _agent_debate_turn(
    agent: str,
    shared: Dict[str, Any],
    prior_turns: List[Dict[str, str]],
) -> str:
    """One agent speaks given full team context + prior debate lines."""
    if not (HAS_LLM and llm and llm.is_available):
        return _fallback_turn(agent, shared)

    persona = AGENT_PERSONAS.get(agent, "You are a research agent.")
    transcript = "\n".join(
        f"{t['agent'].upper()}: {t['message']}" for t in prior_turns
    ) or "(No prior debate lines yet.)"

    system = (
        f"{persona}\n"
        "You are in a team debate room. You can see every teammate's brief. "
        "React to contradictions, support strong evidence, or raise a missing risk. "
        "Max 2 short sentences. No financial advice. Do not repeat the whole brief — debate."
    )
    user = (
        f"Shared team context (JSON):\n{json.dumps(shared, default=str)[:2500]}\n\n"
        f"Debate so far:\n{transcript}\n\n"
        f"Your turn as {agent.upper()}. Respond in character."
    )

    try:
        text = await llm.generate(
            contents=user,
            system=system,
            temperature=0.75,
            max_tokens=120,
        )
        return (text or "").strip() or _fallback_turn(agent, shared)
    except Exception as e:
        print(f"⚠️ Debate: {agent} turn failed → {e}")
        return _fallback_turn(agent, shared)


def _fallback_turn(agent: str, shared: Dict[str, Any]) -> str:
    briefs = shared.get("team_briefs", {})
    scores = shared.get("raw_scores", {})
    if agent == "atlas":
        if scores.get("atlas_honeypot") or scores.get("atlas_can_sell") is False:
            return "Trade path is the hard constraint here — exit risk dominates any soft narrative."
        return "Mechanics look open; structure and creator still need weight."
    if agent == "vega":
        risk = scores.get("vega_risk")
        if risk is not None and risk >= 70:
            return "Structural risk is elevated; I would not dismiss the red flags."
        if risk is not None and risk <= 30:
            return "Structure reads relatively clean on the metrics we have."
        return briefs.get("vega", "Structural read is mixed.")[:160]
    if agent == "echo":
        pred = (scores.get("echo_prediction") or "").upper()
        if pred in ("HIGH_RISK", "DEAD", "RUG"):
            return "Creator history argues against a clean outcome — pattern risk is real."
        if pred in ("SAFE", "LEGIT"):
            return "Creator track record does not scream serial failure."
        return briefs.get("echo", "Creator picture is incomplete.")[:160]
    if agent == "nova":
        return "Traction metrics are what brought this token into the room; deeper layers decide the call."
    return "Noted."


async def run_team_debate(
    symbol: str,
    chain: str,
    sim: dict,
    analysis: dict,
    memory: Optional[dict],
    nova_note: str = "",
    speakers: Optional[List[str]] = None,
    publisher: Any = None,
) -> Dict[str, Any]:
    """
    Run a structured multi-agent debate.

    Returns:
      {
        shared_context: dict,
        transcript: [{agent, message}, ...],
        consensus_notes: str,
        disagreements: [str, ...],
      }
    """
    speakers = speakers or ["atlas", "vega", "echo"]
    shared = build_shared_context(symbol, chain, sim, analysis, memory, nova_note)
    transcript: List[Dict[str, str]] = []

    print(f"🗣️ Debate: Opening floor on {symbol} ({chain}) — speakers: {', '.join(speakers)}")

    # Round 1: each specialist reacts to the full team brief
    for agent in speakers:
        line = await _agent_debate_turn(agent, shared, transcript)
        entry = {"agent": agent, "message": line, "timestamp": time.time()}
        transcript.append(entry)
        print(f"   {agent.upper()}: {line[:100]}...")
        if publisher and hasattr(publisher, "agent_message"):
            try:
                await publisher.agent_message(agent=agent, message=line, msg_type="debate")
            except Exception:
                pass

    # Round 2 (optional short cross-fire): Echo or Vega reacts to the others if conflict signals exist
    scores = shared.get("raw_scores", {})
    conflict = False
    vega_risk = scores.get("vega_risk")
    echo_pred = (scores.get("echo_prediction") or "").upper()
    honeypot = scores.get("atlas_honeypot") or (scores.get("atlas_can_sell") is False)
    if honeypot and echo_pred in ("SAFE", "LEGIT"):
        conflict = True
    if vega_risk is not None and vega_risk >= 70 and echo_pred in ("SAFE", "LEGIT"):
        conflict = True
    if vega_risk is not None and vega_risk <= 30 and echo_pred in ("HIGH_RISK", "DEAD"):
        conflict = True

    if conflict and "echo" in speakers:
        line = await _agent_debate_turn("echo", shared, transcript)
        transcript.append({"agent": "echo", "message": line, "timestamp": time.time()})
        print(f"   ECHO (rebuttal): {line[:100]}...")
        if publisher and hasattr(publisher, "agent_message"):
            try:
                await publisher.agent_message(agent="echo", message=line, msg_type="debate")
            except Exception:
                pass

    consensus_notes, disagreements = await _summarize_debate(shared, transcript)

    return {
        "shared_context": shared,
        "transcript": transcript,
        "consensus_notes": consensus_notes,
        "disagreements": disagreements,
        "had_conflict": conflict,
    }


async def _summarize_debate(
    shared: Dict[str, Any],
    transcript: List[Dict[str, str]],
) -> tuple:
    """Produce short consensus + disagreement list for Orion."""
    if not (HAS_LLM and llm and llm.is_available):
        notes = "Debate complete (rule fallback). Weight Atlas mechanics, Vega structure, Echo history."
        return notes, []

    system = (
        "You summarize a multi-agent crypto research debate. "
        "Return pure JSON only. No financial advice."
    )
    user = (
        f"Team briefs:\n{json.dumps(shared.get('team_briefs', {}), default=str)}\n\n"
        f"Transcript:\n{json.dumps(transcript, default=str)}\n\n"
        "Return JSON:\n"
        '{"consensus_notes": "<2 sentences on where the team mostly agrees>", '
        '"disagreements": ["point1", "point2"]}'
    )
    try:
        result = await llm.generate_json(contents=user, system=system, temperature=0.3, max_tokens=280)
        notes = result.get("consensus_notes") or "Team views partially aligned."
        disagreements = result.get("disagreements") or []
        if not isinstance(disagreements, list):
            disagreements = [str(disagreements)]
        return notes, disagreements[:5]
    except Exception as e:
        print(f"⚠️ Debate summary failed → {e}")
        return "Debate complete; Orion should weigh mechanics, structure, and creator history.", []
