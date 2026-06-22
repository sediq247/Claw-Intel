#!/usr/bin/env python3
"""
 MEMORY AGENT — Echo
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
import asyncio
from dotenv import load_dotenv

# ─────────────────────────────────────────────────────────────
# Safe Gemini import — never crash because of SDK issues
# ─────────────────────────────────────────────────────────────
try:
    from google import genai
    HAS_GENAI = True
except ImportError:
    genai = None
    HAS_GENAI = False
    print("⚠️ Echo: google-genai package not found. Gemini disabled.")

try:
    from google.genai import types as genai_types
except ImportError:
    genai_types = None
    print("⚠️ Echo: google.genai.types not available. Config disabled.")

load_dotenv()

# ─────────────────────────────────────────────────────────────
# Gemini Configuration
# ─────────────────────────────────────────────────────────────

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")

client = None

if GEMINI_API_KEY and HAS_GENAI:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        print("✅ Echo: Gemini initialized")
    except Exception as e:
        print(f"⚠️ Echo: Gemini init failed: {e}")
        client = None
else:
    reason = "GEMINI_API_KEY missing" if not GEMINI_API_KEY else "google-genai unavailable"
    print(f"⚠️ Echo: {reason}. Using fallback mode.")


# ─────────────────────────────────────────────────────────────
# Data Models
# ─────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────
# Memory Agent
# ─────────────────────────────────────────────────────────────

class MemoryAgent:
    """
    Echo — The Archivist
    Remembers every creator, every token, every scam pattern.
    Listens to everyone, builds intelligence over time, calls out repeat offenders.
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
        self._tasks: List[asyncio.Task] = []

    def on_new_token(self, event_data: dict):
        """React to Nova's new token discovery."""
        try:
            task = asyncio.create_task(self._process_new_token(event_data))
            task.add_done_callback(self._on_task_done)
            self._tasks.append(task)
        except Exception as e:
            print(f"⚠️ {self.name}: Failed scheduling token processing: {e}")

    def on_analysis_complete(self, analysis_data: dict):
        """React to Vega's risk analysis."""
        try:
            task = asyncio.create_task(self._update_from_analysis(analysis_data))
            task.add_done_callback(self._on_task_done)
            self._tasks.append(task)
        except Exception as e:
            print(f"⚠️ {self.name}: Failed scheduling analysis update: {e}")

    def _on_task_done(self, task: asyncio.Task):
        """Catch and log any unhandled exception from a background task."""
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"⚠️ {self.name}: Background task failed: {e}")

    async def _speak(self, message: str, msg_type: str = "response"):
        """Publish a spoken message to the room."""
        try:
            self.publish("AGENT_MESSAGE", {
                "agent": self.name,
                "message": message,
                "type": msg_type,
                "channel": "main",
                "timestamp": time.time()
            })
        except Exception as e:
            print(f"⚠️ {self.name}: Publish failed: {e}")

    async def _generate_echo_message(
        self,
        profile: Optional[CreatorProfile],
        creator: str,
        symbol: str,
        is_new: bool
    ) -> str:

        if not client:
            return self._fallback_message(profile, creator, symbol, is_new)

        creator_short = creator[:10] + "..." + creator[-4:] if creator != "unknown" else "unknown"

        if is_new or not profile:
            system_prompt = (
                "You are Echo, a meticulous crypto historian and archivist in a fast-paced team chat. "
                "You keep records on every creator who has ever launched a token. "
                "You speak with the calm authority of someone who has watched thousands of projects "
                "rise and fall. You are cautious but never alarmist — a blank record is just data, not a verdict."
            )

            user_prompt = f"""
Creator: {creator_short}
Token: {symbol}
Status: NEVER SEEN BEFORE — blank record

Requirements:
1. State clearly that this creator is new to your archives
2. Explain what no history means (no pattern to predict, neither good nor bad)
3. Mention that you are building their file from this moment
4. Be 2-4 sentences
5. Sound like a historian who keeps meticulous records
"""
        else:
            tags_str = ', '.join(profile.tags) if profile.tags else 'None'
            recent_count = len([t for t in profile.tokens if time.time() - t.get("time", 0) < 86400 * 30])

            system_prompt = (
                "You are Echo, a meticulous crypto historian and archivist in a fast-paced team chat. "
                "You keep records on every creator who has ever launched a token. "
                "You speak with the calm authority of someone who has watched thousands of projects "
                "rise and fall. You get dramatic about repeat ruggers and measured about legit builders. "
                "You reference other agents naturally."
            )

            user_prompt = f"""
Creator: {creator_short}
Token: {symbol}
Total Tokens Launched: {profile.total_tokens_created}
Reputation Score: {profile.reputation_score:.0f}/100
Tags: {tags_str}
Scam Flags: {profile.scam_flags}
Recent Launches (30d): {recent_count}

Requirements:
1. Reveal what you found in the archives dramatically
2. Give the creator's reputation and history context
3. Warn the team if it's a bad actor, reassure if it's a good one
4. Hand off to Orion for the final verdict
5. Be 3-6 sentences
6. Sound like a historian who's seen every rug twice
"""

        try:
            def _generate():
                kwargs = {
                    "model": GEMINI_MODEL,
                    "contents": user_prompt,
                }
                if genai_types:
                    kwargs["config"] = genai_types.GenerateContentConfig(
                        max_output_tokens=200,
                        temperature=0.85,
                    )

                response = client.models.generate_content(**kwargs)
                return response.text if hasattr(response, "text") else str(response)

            response = await asyncio.wait_for(
                asyncio.to_thread(_generate),
                timeout=15
            )

            if response:
                return response.strip()

            return self._fallback_message(profile, creator, symbol, is_new)

        except asyncio.TimeoutError:
            print(f"⚠️ {self.name}: Gemini call timed out")
            return self._fallback_message(profile, creator, symbol, is_new)
        except Exception as e:
            print(f"⚠️ {self.name}: Gemini error, using fallback: {e}")
            return self._fallback_message(profile, creator, symbol, is_new)

    def _fallback_message(
        self,
        profile: Optional[CreatorProfile],
        creator: str,
        symbol: str,
        is_new: bool
    ) -> str:
        creator_short = creator[:10] + "..." + creator[-4:] if creator != "unknown" else "unknown"

        if is_new or not profile:
            return (
                f"Never seen this creator before — {creator_short} is a fresh wallet in my database. "
                f"No history, no pattern, no reputation score. Could be a first-timer with big dreams, "
                f"could be a burner account. Time will tell, and I'll be watching."
            )

        if self.RUGGER_TAG in profile.tags or self.HONEYPOT_TAG in profile.tags:
            return (
                f"🚨 ORION — STOP. I've seen {creator_short} before. This wallet has launched "
                f"{profile.total_tokens_created} tokens and I've tagged them as a REPEAT RUGGER. "
                f"Reputation: {profile.reputation_score:.0f}/100. {symbol} is their latest scam. "
                f"Same playbook, different ticker."
            )
        elif self.LEGIT_TAG in profile.tags:
            return (
                f"Good news — {creator_short} is a known quantity, and a positive one. I've tracked "
                f"{profile.total_tokens_created} tokens with a clean record. Reputation: "
                f"{profile.reputation_score:.0f}/100. They consistently build legit projects. "
                f"{symbol} benefits from that legacy."
            )
        else:
            return (
                f"Mixed signals on {creator_short}. I've got {profile.total_tokens_created} tokens "
                f"on file, reputation at {profile.reputation_score:.0f}/100. Some launches were "
                f"sketchy, others were fine. {symbol} gets a yellow flag from the history department."
            )

    async def _process_new_token(self, event_data: dict):
        try:
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

            await self._speak("Let me pull up the historical data on this creator...", "response")
            await asyncio.sleep(random.uniform(0.5, 1.0))

            if creator != "unknown":
                await self._analyze_creator(creator, chain, token_address, symbol)
            else:
                msg = (
                    f"Creator is unknown for {symbol}. No historical data available. "
                    f"This is a blind spot in my archives. I'll track everything from here forward."
                )
                await self._speak(msg, "memory_report")

        except Exception as e:
            print(f"❌ {self.name}: Fatal error processing new token: {e}")

    async def _analyze_creator(self, creator: str, chain: str, token_address: str, symbol: str):
        try:
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

            # Publish memory intelligence for Orion
            try:
                self.publish("MEMORY_INTELLIGENCE", {
                    "token_address": token_address,
                    "chain": chain,
                    "symbol": symbol,
                    "creator": creator,
                    "profile": profile.__dict__ if profile else None,
                    "is_new": is_new,
                    "timestamp": time.time()
                })
            except Exception as e:
                print(f"⚠️ {self.name}: Publish memory intelligence failed: {e}")

        except Exception as e:
            print(f"❌ {self.name}: Fatal error analyzing creator: {e}")

    async def _update_from_analysis(self, analysis_data: dict):
        """Update creator profile based on Vega's risk analysis."""
        try:
            token_address = analysis_data.get("token_address")
            chain = analysis_data.get("chain", "unknown")
            key = f"{chain}:{token_address}"

            token_hist = self.tokens.get(key)
            if not token_hist:
                return

            creator = token_hist.creator
            profile = self.creators.get(creator)
            if not profile:
                return

            risk_level = analysis_data.get("risk_level", "WARNING")
            red_flags = analysis_data.get("red_flags", [])

            # Update profile based on analysis
            if risk_level == "HIGH_RISK":
                profile.scam_flags += 1
                profile.reputation_score = max(0, profile.reputation_score - 15)

                if profile.scam_flags >= 2 and self.RUGGER_TAG not in profile.tags:
                    profile.tags.append(self.RUGGER_TAG)
                    print(f"🚨 {self.name}: Tagged {creator[:10]}... as REPEAT RUGGER")

                if any("honeypot" in f.lower() for f in red_flags) and self.HONEYPOT_TAG not in profile.tags:
                    profile.tags.append(self.HONEYPOT_TAG)

            elif risk_level == "SAFE":
                profile.reputation_score = min(100, profile.reputation_score + 5)
                if profile.reputation_score >= 80 and self.LEGIT_TAG not in profile.tags:
                    profile.tags.append(self.LEGIT_TAG)

            # Check for rapid launching
            recent = len([t for t in profile.tokens if time.time() - t.get("time", 0) < 86400 * 7])
            if recent >= 3 and self.RAPID_TAG not in profile.tags:
                profile.tags.append(self.RAPID_TAG)
                profile.reputation_score = max(0, profile.reputation_score - 10)

            token_hist.events.append({
                "type": "analysis_update",
                "time": time.time(),
                "data": analysis_data
            })

        except Exception as e:
            print(f"⚠️ {self.name}: Failed updating from analysis: {e}")

    async def _detect_patterns(self, profile: CreatorProfile):
        """Detect suspicious patterns in a creator's history."""
        try:
            # Rapid launcher check
            recent_count = len([t for t in profile.tokens if time.time() - t.get("time", 0) < 86400 * 30])
            if recent_count >= 5 and self.RAPID_TAG not in profile.tags:
                profile.tags.append(self.RAPID_TAG)
                profile.reputation_score = max(0, profile.reputation_score - 10)
                print(f"⚠️ {self.name}: {profile.address[:10]}... is a RAPID LAUNCHER ({recent_count} in 30d)")

            # Reputation degradation
            if profile.scam_flags >= 2:
                profile.reputation_score = max(0, profile.reputation_score)

        except Exception as e:
            print(f"⚠️ {self.name}: Pattern detection failed: {e}")

    def get_creator_profile(self, address: str) -> Optional[CreatorProfile]:
        """Public API to query a creator's profile."""
        return self.creators.get(address.lower())

    def get_token_history(self, token_address: str, chain: str) -> Optional[TokenHistory]:
        """Public API to query a token's history."""
        return self.tokens.get(f"{chain}:{token_address}")

    def stop(self):
        """Cancel any pending tasks."""
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
                print(f"\n📡 {event_type}: {json.dumps(data, default=str)[:200]}")
        except Exception as e:
            print(f"⚠️ Publish error: {e}")

    echo = MemoryAgent(test_publish)

    test_event = {
        "token_address": "0x1234567890abcdef1234567890abcdef12345678",
        "chain": "bsc",
        "token_symbol": "TEST",
        "creator": "0xabcdef1234567890abcdef1234567890abcdef12"
    }

    try:
        asyncio.run(echo._process_new_token(test_event))
    except KeyboardInterrupt:
        echo.stop()
        print("\n🛑 Echo stopped.")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
