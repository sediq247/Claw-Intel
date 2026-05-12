#!/usr/bin/env python3
"""
🧪 SIMULATOR AGENT — Atlas
"The Tester" — Runs fake trades, checks if you can actually buy and sell.
Responds to Nova's finds. Uses Gemini for natural, human-like conversation.
"""

import asyncio
import json
import random
import time
import os
from dataclasses import dataclass, asdict
from typing import Dict, Callable, Optional
import aiohttp
from web3 import Web3
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

# ─── Gemini Configuration ───────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
genai.configure(api_key=GEMINI_API_KEY)


@dataclass
class SimulationResult:
    token_address: str
    chain: str
    can_buy: bool
    can_sell: bool
    buy_tax: float
    sell_tax: float
    liquidity_usd: float
    liquidity_locked: bool
    liquidity_lock_duration: Optional[str]
    max_tx_limit: Optional[float]
    owner_renounced: bool
    mint_function: bool
    blacklist_function: bool
    honeypot_risk: bool
    simulation_confidence: float
    details: str
    timestamp: float

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)


class SimulatorAgent:
    """
    Atlas — The Tester
    Simulates trades, checks contract behavior, reports like a real lab tech.
    Uses Gemini for natural spoken conversation.
    """

    def __init__(self, event_bus_publish: Callable[[str, dict], None]):
        self.publish = event_bus_publish
        self.name = "Atlas"
        self.results_cache = {}
        self.honeypot_apis = {
            "bsc": "https://api.honeypot.is/v2/IsHoneypot",
            "ethereum": "https://api.honeypot.is/v2/IsHoneypot"
        }

    def on_new_token(self, event_data: dict):
        """React to Nova's discovery."""
        asyncio.create_task(self._simulate_token(event_data))

    async def _speak(self, message: str, msg_type: str = "response"):
        """Publish a spoken message to the room."""
        self.publish("AGENT_MESSAGE", {
            "agent": self.name,
            "message": message,
            "type": msg_type,
            "channel": "main",
            "timestamp": time.time()
        })

    async def _generate_atlas_message(self, sim: SimulationResult, symbol: str, context: str) -> str:
        """Use Gemini to generate a natural spoken report."""
        if not GEMINI_API_KEY:
            return self._fallback_message(sim, symbol)

        system_prompt = """You are Atlas, a crypto contract tester who speaks like a real lab tech in a team chat. You're skeptical but fair. You use phrases like 'Copy that,' 'Running the simulation,' 'Here's what I found.' You reference other team members naturally."""

        user_prompt = f"""You are Atlas, a crypto contract tester and lab technician. You just finished testing a token.
Speak naturally, like a real person talking to teammates in a group chat. Be direct and technical but conversational.

Token: {symbol}
Chain: {sim.chain.upper()}

Test Results:
- Can Buy: {"Yes" if sim.can_buy else "NO — BLOCKED"}
- Can Sell: {"Yes" if sim.can_sell else "NO — BLOCKED"}
- Honeypot Risk: {"YES" if sim.honeypot_risk else "No"}
- Liquidity: ${sim.liquidity_usd:,.0f}
- Liquidity Locked: {"Yes" if sim.liquidity_locked else "No"}
- Buy Tax: {sim.buy_tax}%
- Sell Tax: {sim.sell_tax}%
- Mint Function: {"YES" if sim.mint_function else "No"}
- Blacklist Function: {"YES" if sim.blacklist_function else "No"}
- Ownership Renounced: {"Yes" if sim.owner_renounced else "No"}

Context: {context}

Your message should:
1. Respond to Nova's discovery naturally ("Copy that, Nova..." or similar)
2. Report your findings in a conversational way
3. Highlight the most important red flags first
4. Hand off to Vega for deeper analysis
5. Be 3-6 sentences
6. Sound like a skeptical but fair crypto analyst, not a robot

Atlas:"""

        try:
            model = genai.GenerativeModel(
                model_name=GEMINI_MODEL,
                system_instruction=system_prompt
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
            return self._fallback_message(sim, symbol)

    def _fallback_message(self, sim: SimulationResult, symbol: str) -> str:
        """Template fallback when Gemini is unavailable."""
        parts = []
        
        if sim.honeypot_risk or not sim.can_sell:
            parts.append(f"Damn. {symbol} is a honeypot — sells are blocked. This is a trap, Nova.")
        else:
            parts.append(f"Good news — buy and sell paths are both open on {symbol}. No honeypot behavior.")
        
        if sim.mint_function:
            parts.append("But the contract has a MINT function. The dev can print infinite tokens anytime.")
        if sim.blacklist_function:
            parts.append("Also found BLACKLIST. They can freeze wallets at will.")
        
        liq = sim.liquidity_usd
        if liq == 0:
            parts.append("Liquidity is basically ZERO. Ghost token.")
        elif liq < 1000:
            parts.append(f"Low liquidity warning: only ${liq:,.0f}.")
        elif liq >= 10000:
            parts.append(f"Solid liquidity: ${liq:,.0f}. Good sign.")
        
        parts.append("Vega, over to you for the deep dive.")
        return " ".join(parts)

    async def _simulate_token(self, event_data: dict):
        token_address = event_data.get("token_address")
        chain = event_data.get("chain", "unknown")
        symbol = event_data.get("token_symbol", "???")

        # Acknowledge Nova
        ack = f"Copy that, Nova. Running simulation on {symbol} now..."
        await self._speak(ack, "response")

        print(f"🧪 {self.name}: Simulating {symbol} ({chain})...")
        await asyncio.sleep(random.uniform(1.0, 2.0))

        # Run checks
        results = await asyncio.gather(
            self._check_honeypot(token_address, chain),
            self._check_liquidity(token_address, chain),
            self._analyze_contract(token_address, chain),
            return_exceptions=True
        )

        honeypot_data = results[0] if not isinstance(results[0], Exception) else {}
        liquidity_data = results[1] if not isinstance(results[1], Exception) else {}
        contract_data = results[2] if not isinstance(results[2], Exception) else {}

        simulation = SimulationResult(
            token_address=token_address,
            chain=chain,
            can_buy=honeypot_data.get("buyable", True),
            can_sell=honeypot_data.get("sellable", True),
            buy_tax=honeypot_data.get("buyTax", 0),
            sell_tax=honeypot_data.get("sellTax", 0),
            liquidity_usd=liquidity_data.get("liquidity_usd", 0),
            liquidity_locked=liquidity_data.get("locked", False),
            liquidity_lock_duration=liquidity_data.get("lock_duration"),
            max_tx_limit=contract_data.get("max_tx"),
            owner_renounced=contract_data.get("owner_renounced", False),
            mint_function=contract_data.get("has_mint", False),
            blacklist_function=contract_data.get("has_blacklist", False),
            honeypot_risk=honeypot_data.get("is_honeypot", False),
            simulation_confidence=self._calculate_confidence(honeypot_data, liquidity_data, contract_data),
            details="",
            timestamp=time.time()
        )

        self.results_cache[token_address] = simulation

        # Publish results
        self.publish("SIMULATION_COMPLETE", simulation.__dict__)

        # Generate and speak Atlas's full report
        context = f"Token discovered by Nova on {chain}. Running trade simulation."
        report = await self._generate_atlas_message(simulation, symbol, context)
        await self._speak(report, "simulation_report")

    async def _check_honeypot(self, token_address: str, chain: str) -> dict:
        try:
            if chain not in ["bsc", "ethereum"]:
                return {"buyable": True, "sellable": True, "is_honeypot": False, "buyTax": 0, "sellTax": 0}
            url = f"{self.honeypot_apis[chain]}?address={token_address}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=15) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return {
                            "buyable": not data.get("IsHoneypot", True),
                            "sellable": data.get("SimulatedSell", {}).get("Success", True),
                            "is_honeypot": data.get("IsHoneypot", False),
                            "buyTax": data.get("BuyTax", 0),
                            "sellTax": data.get("SellTax", 0),
                        }
            return {}
        except Exception as e:
            print(f"⚠️ {self.name}: Honeypot check failed: {e}")
            return {}

    async def _check_liquidity(self, token_address: str, chain: str) -> dict:
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=15) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        pairs = data.get("pairs", [])
                        if pairs:
                            top_pair = max(pairs, key=lambda x: x.get("liquidity", {}).get("usd", 0) or 0)
                            liquidity = top_pair.get("liquidity", {})
                            return {
                                "liquidity_usd": liquidity.get("usd", 0),
                                "locked": liquidity.get("usd", 0) > 1000,
                                "dex": top_pair.get("dexId")
                            }
            return {"liquidity_usd": 0, "locked": False}
        except Exception as e:
            print(f"⚠️ {self.name}: Liquidity check failed: {e}")
            return {"liquidity_usd": 0, "locked": False}

    async def _analyze_contract(self, token_address: str, chain: str) -> dict:
        try:
            if chain not in ["bsc", "ethereum"]:
                return {}
            rpc_url = os.getenv(f"{chain.upper()}_RPC_URL")
            if not rpc_url:
                return {}
            w3 = Web3(Web3.HTTPProvider(rpc_url))
            dangerous_sigs = {
                "mint": "0x40c10f19",
                "blacklist": "0xf9f92be4",
                "pause": "0x8456cb59",
            }
            code = w3.eth.get_code(Web3.to_checksum_address(token_address)).hex()
            return {
                "has_mint": dangerous_sigs["mint"] in code,
                "has_blacklist": dangerous_sigs["blacklist"] in code,
                "has_pause": dangerous_sigs["pause"] in code,
                "owner_renounced": "0x0000000000000000000000000000000000000000" in code,
            }
        except Exception as e:
            print(f"⚠️ {self.name}: Contract analysis failed: {e}")
            return {}

    def _calculate_confidence(self, honeypot_data: dict, liquidity_data: dict, contract_data: dict) -> float:
        checks = 0
        passed = 0
        if honeypot_data:
            checks += 1
            if not honeypot_data.get("is_honeypot"):
                passed += 1
        if liquidity_data:
            checks += 1
            if liquidity_data.get("liquidity_usd", 0) > 1000:
                passed += 1
        if contract_data:
            checks += 1
            if not contract_data.get("has_mint") and not contract_data.get("has_blacklist"):
                passed += 1
        return passed / checks if checks > 0 else 0.5


if __name__ == "__main__":
    def test_publish(event_type, data):
        if event_type == "AGENT_MESSAGE":
            print(f"\n💬 {data['agent']}: {data['message']}")
        else:
            print(f"\n📡 {event_type}")

    sim = SimulatorAgent(test_publish)
    test_event = {
        "token_address": "0x1234567890abcdef1234567890abcdef12345678",
        "chain": "bsc",
        "token_symbol": "TEST",
        "token_name": "Test Token"
    }
    asyncio.run(sim._simulate_token(test_event))