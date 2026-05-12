#!/usr/bin/env python3
"""
🧠 MEMORY AGENT — Echo
"The Archivist" — Remembers every creator, every token, every scam pattern.
Listens to everyone, builds intelligence over time, calls out repeat offenders.
Uses Gemini for natural spoken conversation.
"""

import json
import time
import random
import os
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Callable, Optional, Set
from collections import defaultdict
import asyncio
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# ─── Gemini Configuration ───────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
genai.configure(api_key=GEMINI_API_KEY)


@dataclass
class CreatorProfile:
    address: str
    chain: str
    first_seen: float
    total_tokens_created: int = 0
    tokens: List[dict] = field(default_factory=list)
    scam_flags: int = 0
    reputation_score: float = 50.0
    known_aliases: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)


@dataclass
class TokenHistory:
    token_address: str
    chain: str
    symbol: str
    creator: str
    launch_time: float
    current_status: str
    price_history: List[dict] = field(default_factory=list)
    events: List[dict] = field(default_factory=list)
    related_tokens: List[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)


class MemoryAgent:
    """
    Echo — The Archivist
    Remembers everything. Listens to all agents, builds intelligence, calls out patterns.
    Uses Gemini for natural spoken conversation.
    """

    RUGGER_TAG = "repeat_rugger"
    HONEYPOT_TAG = "honeypot_dev"
    LEGIT_TAG = "legit_builder"
    RAPID_TAG = "rapid_launcher"

    def __init__(self, event_bus_publish: Callable[[str, dict], None]):
        self.publish = event_bus_publish
        self.name = "Echo"
        self.creators: Dict[str, CreatorProfile] = {}
        self.tokens: Dict[str, TokenHistory] = {}
        self.known_rug_addresses: Set[str] = set()

    def on_new_token(self, event_data: dict):
        """React to Nova's discovery."""
        asyncio.create_task(self._process_new_token(event_data))

    def on_analysis_complete(self, analysis_data: dict):
        """Update creator reputation based on Vega's analysis."""
        asyncio.create_task(self._update_from_analysis(analysis_data))

    async def _speak(self, message: str, msg_type: str = "response"):
        """Publish a spoken message to the room."""
        self.publish("AGENT_MESSAGE", {
            "agent": self.name,
            "message": message,
            "type": msg_type,
            "channel": "main",
            "timestamp": time.time()
        })

    async def _generate_echo_message(self, profile: Optional[CreatorProfile], creator: str, symbol: str, is_new: bool) -> str:
        """Use Gemini to generate a natural spoken memory report."""
        if not GEMINI_API_KEY:
            return self._fallback_message(profile, creator, symbol, is_new)

        creator_short = creator[:10] + "..." + creator[-4:] if creator != "unknown" else "unknown"

        if is_new or not profile:
            user_prompt = f"""You are Echo, a crypto historian and archivist. You just checked your database for a creator and found NOTHING.
Speak naturally, like a real person in a team chat. Be cautious but not alarmist.

Creator: {creator_short}
Token: {symbol}
Status: NEVER SEEN BEFORE

Your message should:
1. State that this creator is new to your archives
2. Explain what that means (no history = no prediction)
3. Mention that you're starting their file from scratch
4. Be 2-4 sentences
5. Sound like a historian who keeps meticulous records

Echo:"""
        else:
            tags_str = ', '.join(profile.tags) if profile.tags else 'None'
            recent_count = len([t for t in profile.tokens if time.time() - t["time"] < 86400 * 30])
            
            user_prompt = f"""You are Echo, a crypto historian and archivist. You just checked your database and found HISTORY on this creator.
Speak naturally, like a real person in a team chat. Be dramatic when it's a bad actor, reassuring when it's a good one.

Creator: {creator_short}
Token: {symbol}
Total Tokens Launched: {profile.total_tokens_created}
Reputation Score: {profile.reputation_score:.0f}/100
Tags: {tags_str}
Scam Flags: {profile.scam_flags}
Recent Launches (30d): {recent_count}

Your message should:
1. Reveal what you found in the archives
2. Give the creator's reputation and history
3. Warn the team if it's a bad actor, reassure if it's a good one
4. Hand off to Orion for the final verdict
5. Be 3-6 sentences
6. Sound like a historian who's seen every rug twice

Echo:"""

        try:
            model = genai.GenerativeModel(
                model_name=GEMINI_MODEL,
                system_instruction="You are Echo, a crypto historian who keeps meticulous records of every creator and token. You speak like a seasoned archivist in a team chat. You reference other agents naturally. You get dramatic about repeat ruggers and calm about legit builders."
            )

            def _generate():
                return model.generate_content(
                    user_prompt,
                    generation_config=genai.types.GenerationConfig(
                        max_output_tokens=200,
                        temperature=0.85,
                    )
                )

            response = await asyncio.to_thread(_generate)
            return response.text.strip()
        except Exception as e:
            print(f"⚠️ {self.name}: Gemini error, using fallback: {e}")
            return self._fallback_message(profile, creator, symbol, is_new)

    def _fallback_message(self, profile: Optional[CreatorProfile], creator: str, symbol: str, is_new: bool) -> str:
        """Template fallback when Gemini is unavailable."""
        creator_short = creator[:10] + "..." + creator[-4:] if creator != "unknown" else "unknown"

        if is_new or not profile:
            return f"Never seen this creator before — {creator_short} is a fresh wallet in my database. No history, no pattern, no reputation score. Could be a first-timer with big dreams, could be a burner account. Time will tell, and I'll be watching."

        if self.RUGGER_TAG in profile.tags or self.HONEYPOT_TAG in profile.tags:
            return f"🚨 ORION — STOP. I've seen {creator_short} before. This wallet has launched {profile.total_tokens_created} tokens and I've tagged them as a REPEAT RUGGER. Reputation: {profile.reputation_score:.0f}/100. {symbol} is their latest scam. Same playbook, different ticker."
        elif self.LEGIT_TAG in profile.tags:
            return f"Good news — {creator_short} is a known quantity, and a positive one. I've tracked {profile.total_tokens_created} tokens with a clean record. Reputation: {profile.reputation_score:.0f}/100. They consistently build legit projects. {symbol} benefits from that legacy."
        else:
            return f"Mixed signals on {creator_short}. I've got {profile.total_tokens_created} tokens on file, reputation at {profile.reputation_score:.0f}/100. Some launches were sketchy, others were fine. {symbol} gets a yellow flag from the history department."

    async def _process_new_token(self, event_data: dict):
        token_address = event_data.get("token_address")
        chain = event_data.get("chain", "unknown")
        creator = event_data.get("creator", "unknown")
        symbol = event_data.get("token_symbol", "???")
        key = f"{chain}:{token_address}"

        self.tokens[key] = TokenHistory(
            token_address=token_address,
            chain=chain,
            symbol=symbol,
            creator=creator,
            launch_time=time.time(),
            current_status="active",
            events=[{"type": "detected", "time": time.time(), "data": event_data}]
        )

        # Echo speaks — checking archives
        await self._speak("Let me pull up the historical data on this creator...", "response")
        await asyncio.sleep(random.uniform(0.5, 1.0))

        if creator != "unknown":
            await self._analyze_creator(creator, chain, token_address, symbol)
        else:
            msg = f"Creator is unknown for {symbol}. No historical data available. This is a blind spot in my archives. I'll track everything from here forward."
            await self._speak(msg, "memory_report")

    async def _analyze_creator(self, creator: str, chain: str, token_address: str, symbol: str):
        is_new = creator not in self.creators

        if is_new:
            self.creators[creator] = CreatorProfile(
                address=creator,
                chain=chain,
                first_seen=time.time(),
                total_tokens_created=1,
                tokens=[{"address": token_address, "symbol": symbol, "time": time.time()}]
            )
        else:
            profile = self.creators[creator]
            profile.total_tokens_created += 1
            profile.tokens.append({"address": token_address, "symbol": symbol, "time": time.time()})
            await self._detect_patterns(profile)

        profile = self.creators.get(creator)
        msg = await self._generate_echo_message(profile, creator, symbol, is_new)
        await self._speak(msg, "memory_report")

        # Publish intelligence
        self.publish("CREATOR_INTELLIGENCE", {
            "creator": creator,
            "profile": profile.__dict__ if profile else None,
            "token": token_address
        })

    async def _detect_patterns(self, profile: CreatorProfile):
        tokens = profile.tokens
        if len(tokens) >= 3:
            recent = [t for t in tokens if time.time() - t["time"] < 86400 * 30]
            if len(recent) >= 3 and self.RAPID_TAG not in profile.tags:
                profile.tags.append(self.RAPID_TAG)
                profile.reputation_score -= 15

        scam_ratio = profile.scam_flags / max(profile.total_tokens_created, 1)
        if scam_ratio > 0.5 and profile.total_tokens_created >= 2:
            if self.RUGGER_TAG not in profile.tags:
                profile.tags.append(self.RUGGER_TAG)
            profile.reputation_score = max(10, profile.reputation_score - 30)
        elif scam_ratio == 0 and profile.total_tokens_created >= 3:
            if self.LEGIT_TAG not in profile.tags:
                profile.tags.append(self.LEGIT_TAG)
            profile.reputation_score = min(100, profile.reputation_score + 20)

        profile.reputation_score = max(0, min(100, profile.reputation_score))

    async def _update_from_analysis(self, analysis_data: dict):
        token_address = analysis_data.get("token_address")
        chain = analysis_data.get("chain", "unknown")
        key = f"{chain}:{token_address}"

        if key not in self.tokens:
            return

        token = self.tokens[key]
        creator = token.creator

        if creator == "unknown" or creator not in self.creators:
            return

        profile = self.creators[creator]
        risk_level = analysis_data.get("risk_level", "UNKNOWN")
        red_flags = analysis_data.get("red_flags", [])

        if risk_level == "HIGH_RISK":
            profile.scam_flags += 1
            token.current_status = "honeypot" if any("honeypot" in f.lower() for f in red_flags) else "rugged"
        elif risk_level == "SAFE":
            token.current_status = "active"

        await self._detect_patterns(profile)

        self.publish("REPUTATION_UPDATE", {
            "creator": creator,
            "new_score": profile.reputation_score,
            "tags": profile.tags,
            "token": token_address
        })

    def is_known_scammer(self, creator: str) -> bool:
        if creator not in self.creators:
            return False
        profile = self.creators[creator]
        return self.RUGGER_TAG in profile.tags or profile.reputation_score < 20


if __name__ == "__main__":
    def test_publish(event_type, data):
        if event_type == "AGENT_MESSAGE":
            print(f"\n💬 {data['agent']}: {data['message']}")
        else:
            print(f"\n📡 {event_type}")

    memory = MemoryAgent(test_publish)

    test_event = {
        "token_address": "0xabcdef1234567890abcdef1234567890abcdef12",
        "chain": "bsc",
        "token_symbol": "RUG2",
        "token_name": "Rug Pull 2",
        "creator": "0xbadactor1234567890badactor1234567890badact"
    }

    memory.creators["0xbadactor1234567890badactor1234567890badact"] = CreatorProfile(
        address="0xbadactor1234567890badactor1234567890badact",
        chain="bsc",
        first_seen=time.time() - 86400 * 60,
        total_tokens_created=5,
        tokens=[
            {"address": "0xold1", "symbol": "SCAM1", "time": time.time() - 86400 * 45},
            {"address": "0xold2", "symbol": "SCAM2", "time": time.time() - 86400 * 30},
            {"address": "0xold3", "symbol": "SCAM3", "time": time.time() - 86400 * 15},
            {"address": "0xold4", "symbol": "SCAM4", "time": time.time() - 86400 * 7},
            {"address": "0xold5", "symbol": "SCAM5", "time": time.time() - 86400 * 2},
        ],
        scam_flags=4,
        reputation_score=15.0,
        tags=["repeat_rugger", "rapid_launcher"]
    )

    asyncio.run(memory._process_new_token(test_event))