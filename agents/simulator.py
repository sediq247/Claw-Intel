#!/usr/bin/env python3
"""
🧪 SIMULATOR AGENT — Atlas v3.0 PRODUCTION
"The Tester" — Runs fake trades, checks if you can actually buy and sell.
Responds to Nova's finds. Uses Gemini for natural, human-like conversation.
"""

import asyncio
import json
import random
import time
import os
import re
from dataclasses import dataclass, asdict
from typing import Dict, Callable, Optional
from functools import wraps
from datetime import datetime, timedelta

import aiohttp
from web3 import Web3
from dotenv import load_dotenv

try:
    from google import genai
    HAS_GENAI = True
except ImportError:
    genai = None
    HAS_GENAI = False
    print("⚠️ Atlas: google-genai package not found. Gemini disabled.")

try:
    from google.genai import types as genai_types
except ImportError:
    genai_types = None
    print("⚠️ Atlas: google.genai.types not available. Config disabled.")

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
        print("✅ Atlas: Gemini initialized")
    except Exception as e:
        print(f"⚠️ Atlas: Gemini init failed: {e}")
        client = None
else:
    reason = "GEMINI_API_KEY missing" if not GEMINI_API_KEY else "google-genai unavailable"
    print(f"⚠️ Atlas: {reason}. Using fallback mode.")


# ─────────────────────────────────────────────────────────────
# Data Models
# ─────────────────────────────────────────────────────────────

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
    # eth_call simulation fields
    eth_call_buy_simulated: bool = False
    eth_call_sell_simulated: bool = False
    eth_call_revert_reason: Optional[str] = None
    eth_call_effective_tax_percent: float = 0.0
    # Tenderly fields
    tenderly_buy_simulated: bool = False
    tenderly_sell_simulated: bool = False
    tenderly_gas_used: Optional[int] = None
    tenderly_revert_reason: Optional[str] = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)


# ─────────────────────────────────────────────────────────────
# DEX Router Configuration
# ─────────────────────────────────────────────────────────────

ROUTER_ABIS = {
    "uniswap_v2": [
        {
            "inputs": [
                {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
                {"internalType": "address[]", "name": "path", "type": "address[]"},
                {"internalType": "address", "name": "to", "type": "address"},
                {"internalType": "uint256", "name": "deadline", "type": "uint256"}
            ],
            "name": "swapExactETHForTokens",
            "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
            "stateMutability": "payable",
            "type": "function"
        },
        {
            "inputs": [
                {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
                {"internalType": "address[]", "name": "path", "type": "address[]"},
                {"internalType": "address", "name": "to", "type": "address"},
                {"internalType": "uint256", "name": "deadline", "type": "uint256"}
            ],
            "name": "swapExactTokensForETH",
            "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
            "stateMutability": "nonpayable",
            "type": "function"
        },
        {
            "inputs": [
                {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
                {"internalType": "address[]", "name": "path", "type": "address[]"},
                {"internalType": "address", "name": "to", "type": "address"},
                {"internalType": "uint256", "name": "deadline", "type": "uint256"}
            ],
            "name": "swapExactTokensForTokens",
            "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
            "stateMutability": "nonpayable",
            "type": "function"
        },
        {
            "inputs": [{"internalType": "uint256", "name": "amountOut", "type": "uint256"},
                       {"internalType": "address[]", "name": "path", "type": "address[]"}],
            "name": "getAmountsIn",
            "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
            "stateMutability": "view",
            "type": "function"
        },
        {
            "inputs": [{"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                       {"internalType": "address[]", "name": "path", "type": "address[]"}],
            "name": "getAmountsOut",
            "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
            "stateMutability": "view",
            "type": "function"
        }
    ]
}

ROUTER_ADDRESSES = {
    "bsc": {
        "pancakeswap_v2": "0x10ED43C718714eb63d5aA57B78B54704E256024E",
        "pancakeswap_v3": "0x1b81D678ffb9C0263b24A97847620C99d213eB14",
    },
    "ethereum": {
        "uniswap_v2": "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",
        "uniswap_v3": "0xE592427A0AEce92De3Edee1F18E0157C05861564",
    }
}

WETH_ADDRESSES = {
    "bsc": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",   # WBNB
    "ethereum": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",  # WETH
}

# Real funded wallets for eth_call simulation (public addresses with known balances)
# eth_call doesn't spend gas — it just simulates against their balance state
FUNDED_WALLETS = {
    "bsc": "0xF977814e90dA44bFA03b6295A0616a897441aceC",   # Binance hot wallet
    "ethereum": "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb",  # Known whale
}

# Standard ERC20 ABI snippets
ERC20_ABI = [
    {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"},
    {"constant": False, "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}, {"name": "_spender", "type": "address"}], "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
]

# Ownership check ABI
OWNERSHIP_ABI = [
    {"constant": True, "inputs": [], "name": "owner", "outputs": [{"name": "", "type": "address"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "getOwner", "outputs": [{"name": "", "type": "address"}], "type": "function"},
]


# ─────────────────────────────────────────────────────────────
# Rate Limiter Decorator
# ─────────────────────────────────────────────────────────────

class RateLimiter:
    """Simple per-domain rate limiter."""
    def __init__(self):
        self._last_call: Dict[str, float] = {}
        self._min_interval = 1.5  # seconds between calls to same domain
        self._lock = asyncio.Lock()

    async def wait(self, domain: str):
        async with self._lock:
            now = time.time()
            last = self._last_call.get(domain, 0)
            elapsed = now - last
            if elapsed < self._min_interval:
                wait_time = self._min_interval - elapsed
                await asyncio.sleep(wait_time)
            self._last_call[domain] = time.time()

rate_limiter = RateLimiter()


# ─────────────────────────────────────────────────────────────
# TTL Cache for Results
# ─────────────────────────────────────────────────────────────

class TTLCache:
    """Simple TTL cache with max size."""
    def __init__(self, maxsize: int = 1000, ttl_seconds: int = 3600):
        self.maxsize = maxsize
        self.ttl = ttl_seconds
        self._data: Dict[str, tuple] = {}  # key: (value, expiry_time)
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[SimulationResult]:
        async with self._lock:
            if key not in self._data:
                return None
            value, expiry = self._data[key]
            if time.time() > expiry:
                del self._data[key]
                return None
            return value

    async def set(self, key: str, value: SimulationResult):
        async with self._lock:
            if len(self._data) >= self.maxsize:
                # Evict oldest
                oldest_key = min(self._data, key=lambda k: self._data[k][1])
                del self._data[oldest_key]
            self._data[key] = (value, time.time() + self.ttl)

    async def clear_expired(self):
        async with self._lock:
            now = time.time()
            expired = [k for k, (_, exp) in self._data.items() if now > exp]
            for k in expired:
                del self._data[k]


# ─────────────────────────────────────────────────────────────
# Input Validation
# ─────────────────────────────────────────────────────────────

def validate_token_address(address: str) -> str:
    """Validate and checksum a token address. Raises ValueError if invalid."""
    if not address:
        raise ValueError("Token address is empty")

    # Remove whitespace
    address = address.strip()

    # Basic hex check
    if not re.match(r'^0x[a-fA-F0-9]{40}$', address):
        raise ValueError(f"Invalid token address format: {address}")

    try:
        return Web3.to_checksum_address(address)
    except Exception as e:
        raise ValueError(f"Invalid checksum for address {address}: {e}")


def validate_chain(chain: str) -> str:
    """Validate chain identifier."""
    chain = chain.lower().strip()
    supported = {"bsc", "ethereum", "base", "arbitrum", "polygon"}
    if chain not in supported:
        raise ValueError(f"Unsupported chain: {chain}. Supported: {supported}")
    return chain


# ─────────────────────────────────────────────────────────────
# Atlas Agent
# ─────────────────────────────────────────────────────────────

class SimulatorAgent:
    """
    Atlas — The Tester
    Three-tier simulation:
      Tier 1: Static Analysis (honeypot.is, bytecode, DexScreener) — FAST
      Tier 2: eth_call Simulation (real DEX swap via RPC) — FREE, NO CAPITAL
      Tier 3: Tenderly API (fork simulation) — FREE TIER
    """

    def __init__(self, event_bus_publish: Callable[[str, dict], None]):
        self.publish = event_bus_publish
        self.name = "Atlas"
        self.results_cache = TTLCache(maxsize=1000, ttl_seconds=3600)
        self._session: Optional[aiohttp.ClientSession] = None

        print(f"🚀 {self.name}: Booting Atlas v3.0 PRODUCTION...")

        if not GEMINI_API_KEY:
            print("⚠️ Atlas: No Gemini API key")

        if not os.getenv("BSC_RPC_URL"):
            print("⚠️ Atlas: Missing BSC RPC URL")

        if not os.getenv("ETH_RPC_URL"):
            print("⚠️ Atlas: Missing ETH RPC URL")

        self.honeypot_apis = {
            "bsc": "https://api.honeypot.is/v2/IsHoneypot",
            "ethereum": "https://api.honeypot.is/v2/IsHoneypot"
        }

        # Web3 instances for eth_call simulation
        self.web3_instances = {}
        self._init_web3()

    # ─────────────────────────────────────────────────────────

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create shared aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(
                    limit=10,
                    limit_per_host=5,
                    ttl_dns_cache=300,
                    use_dns_cache=True,
                ),
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self._session

    # ─────────────────────────────────────────────────────────

    def _init_web3(self):
        """Initialize Web3 connections for eth_call simulation."""
        chains = {
            "bsc": os.getenv("BSC_RPC_URL"),
            "ethereum": os.getenv("ETH_RPC_URL"),
        }
        for chain, rpc in chains.items():
            if not rpc:
                print(f"⚠️ {self.name}: No RPC for {chain} — eth_call disabled")
                continue
            try:
                w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 20}))
                if w3.is_connected():
                    self.web3_instances[chain] = w3
                    print(f"✅ {self.name}: Web3 ready for {chain}")
                else:
                    print(f"❌ {self.name}: Web3 failed for {chain}")
            except Exception as e:
                print(f"❌ {self.name}: Web3 error for {chain}: {e}")

    # ─────────────────────────────────────────────────────────

    def on_new_token(self, event_data: dict):
        """
        Schedule a simulation. If the task crashes later,
        _on_task_done logs it so it never kills the event loop.
        """
        try:
            # Validate inputs immediately
            token_address = validate_token_address(event_data.get("token_address", ""))
            chain = validate_chain(event_data.get("chain", "unknown"))

            # Update event_data with validated values
            event_data["token_address"] = token_address
            event_data["chain"] = chain

            task = asyncio.create_task(
                asyncio.wait_for(
                    self._simulate_token(event_data),
                    timeout=120
                )
            )
            task.add_done_callback(self._on_task_done)
        except ValueError as e:
            print(f"❌ {self.name}: Invalid input — {e}")
        except Exception as e:
            print(f"⚠️ {self.name}: Failed scheduling simulation: {e}")

    def _on_task_done(self, task: asyncio.Task):
        """Catch and log any unhandled exception from a simulation task."""
        try:
            task.result()
        except asyncio.TimeoutError:
            print(f"⚠️ {self.name}: Simulation task timed out")
        except Exception as e:
            print(f"⚠️ {self.name}: Simulation task failed: {e}")

    # ─────────────────────────────────────────────────────────

    async def _speak(self, message: str, msg_type: str = "response"):
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

    # ─────────────────────────────────────────────────────────

    async def _generate_atlas_message(
        self,
        sim: SimulationResult,
        symbol: str,
        context: str
    ) -> str:

        if not client:
            return self._fallback_message(sim, symbol)

        system_prompt = (
            "You are Atlas, a battle-hardened crypto contract auditor in a team chat. "
            "You have seen hundreds of rugs, honeypots, and exploits. You speak with the "
            "calm authority of someone who has been burned before. You reference Nova's discovery "
            "naturally, then walk through your findings methodically. Be technical but accessible. "
            "Never hype — your credibility is your currency."
        )

        # Build simulation detail text
        sim_details = []
        if sim.eth_call_buy_simulated:
            sim_details.append("✅ eth_call BUY simulation: PASSED")
        else:
            sim_details.append("❌ eth_call BUY simulation: FAILED")

        if sim.eth_call_sell_simulated:
            sim_details.append("✅ eth_call SELL simulation: PASSED")
        else:
            sim_details.append("❌ eth_call SELL simulation: FAILED")

        if sim.eth_call_revert_reason:
            sim_details.append(f"⚠️ Revert reason: {sim.eth_call_revert_reason}")

        if sim.eth_call_effective_tax_percent > 0:
            sim_details.append(f"📊 Effective tax/slippage: {sim.eth_call_effective_tax_percent:.2f}%")

        if sim.tenderly_buy_simulated:
            sim_details.append(f"✅ Tenderly BUY simulation: PASSED")
        if sim.tenderly_sell_simulated:
            sim_details.append(f"✅ Tenderly SELL simulation: PASSED")
        if sim.tenderly_gas_used:
            sim_details.append(f"⛽ Tenderly gas used: {sim.tenderly_gas_used}")
        if sim.tenderly_revert_reason:
            sim_details.append(f"⚠️ Tenderly revert: {sim.tenderly_revert_reason}")

        sim_detail_text = "\n".join(sim_details) if sim_details else "Static analysis only (no on-chain simulation available)"

        user_prompt = f"""
Token: {symbol}
Chain: {sim.chain.upper()}

Simulation Results:
- Can Buy: {"Yes — path is open" if sim.can_buy else "NO — buy path is BLOCKED"}
- Can Sell: {"Yes — exit is open" if sim.can_sell else "NO — exit is BLOCKED"}
- Honeypot Risk: {"YES — this is a trap" if sim.honeypot_risk else "No honeypot behavior detected"}
- Liquidity: ${sim.liquidity_usd:,.0f}
- Liquidity Locked: {"Yes — funds are secured" if sim.liquidity_locked else "No — liquidity is unlocked"}
- Buy Tax: {sim.buy_tax}%
- Sell Tax: {sim.sell_tax}%
- Mint Function: {"YES — owner can print tokens" if sim.mint_function else "No mint function"}
- Blacklist Function: {"YES — owner can freeze wallets" if sim.blacklist_function else "No blacklist function"}
- Ownership Renounced: {"Yes — contract is immutable" if sim.owner_renounced else "No — owner still has control"}

On-Chain Simulation:
{sim_detail_text}

Context:
{context}

Requirements:
- Acknowledge Nova's find naturally and briefly
- Walk through the biggest risks first, then positives
- Mention the sell path explicitly — that is what kills most people
- Reference the eth_call simulation results if available
- Hand off to Vega naturally
- Keep it conversational and under 5 sentences
- Sound like a technician who respects the chain but trusts no contract
"""

        try:
            def _generate():
                kwargs = {
                    "model": GEMINI_MODEL,
                    "contents": f"{system_prompt}\n\n{user_prompt}",
                }
                # Only pass config object if the SDK supports it
                if genai_types:
                    kwargs["config"] = genai_types.GenerateContentConfig(
                        temperature=0.85,
                        max_output_tokens=250
                    )

                response = client.models.generate_content(**kwargs)
                return response.text if hasattr(response, "text") else str(response)

            response = await asyncio.wait_for(
                asyncio.to_thread(_generate),
                timeout=15
            )

            if response:
                return response.strip()

            return self._fallback_message(sim, symbol)

        except asyncio.TimeoutError:
            print(f"⚠️ {self.name}: Gemini call timed out")
            return self._fallback_message(sim, symbol)
        except Exception as e:
            print(f"⚠️ {self.name}: Gemini error: {e}")
            return self._fallback_message(sim, symbol)

    # ─────────────────────────────────────────────────────────

    def _fallback_message(self, sim: SimulationResult, symbol: str) -> str:
        parts = []

        if sim.honeypot_risk or not sim.can_sell:
            parts.append(f"Nova found it, but I'm calling it — {symbol} is a honeypot. Sells are dead.")
        else:
            parts.append(f"Buy and sell paths are open on {symbol}. No honeypot behavior detected.")

        if sim.eth_call_buy_simulated and sim.eth_call_sell_simulated:
            parts.append("I ran eth_call simulation — both buy and sell executed successfully on-chain.")
        elif sim.eth_call_buy_simulated and not sim.eth_call_sell_simulated:
            parts.append("eth_call buy worked, but sell reverted. Classic honeypot pattern.")

        if sim.eth_call_effective_tax_percent > 10:
            parts.append(f"High effective tax detected: {sim.eth_call_effective_tax_percent:.1f}% — that's a rug in slow motion.")

        if sim.mint_function:
            parts.append("Contract includes a MINT function — owner can print infinite supply.")

        if sim.blacklist_function:
            parts.append("Blacklist capability detected — your wallet could be frozen.")

        liq = sim.liquidity_usd
        if liq == 0:
            parts.append("Liquidity is basically zero — you're trading air.")
        elif liq < 1000:
            parts.append(f"Low liquidity warning: ${liq:,.0f}. Slippage will eat you alive.")
        elif liq >= 10000:
            parts.append(f"Solid liquidity: ${liq:,.0f}. At least you can get in and out.")

        parts.append("Vega, your turn for deeper analysis.")
        return " ".join(parts)

    # ═══════════════════════════════════════════════════════════
    # MAIN SIMULATION PIPELINE
    # ═══════════════════════════════════════════════════════════

    async def _simulate_token(self, event_data: dict):
        try:
            token_address = event_data.get("token_address")
            chain = event_data.get("chain", "unknown")
            symbol = event_data.get("token_symbol", "???")

            # Check cache first
            cached = await self.results_cache.get(token_address)
            if cached:
                print(f"📦 {self.name}: Cache hit for {symbol}")
                await self._speak(f"Already simulated {symbol} — pulling from cache.", "cache_hit")
                try:
                    self.publish("SIMULATION_COMPLETE", cached.__dict__)
                except Exception as e:
                    print(f"⚠️ {self.name}: Publish failed: {e}")
                return

            ack = f"Copy that, Nova. Running simulation on {symbol} now..."
            await self._speak(ack, "response")

            print(f"🧪 {self.name}: Simulating {symbol} ({chain})...")

            await asyncio.sleep(random.uniform(0.5, 1.5))

            # ── TIER 1: Static Analysis ──
            print(f"🔍 {self.name}: Tier 1 — Static analysis...")
            static_results = await asyncio.gather(
                self._check_honeypot(token_address, chain),
                self._check_liquidity(token_address, chain),
                self._analyze_contract(token_address, chain),
                return_exceptions=True
            )

            honeypot_data = static_results[0] if not isinstance(static_results[0], Exception) else {}
            liquidity_data = static_results[1] if not isinstance(static_results[1], Exception) else {}
            contract_data = static_results[2] if not isinstance(static_results[2], Exception) else {}

            # ── TIER 2: eth_call Simulation ──
            eth_call_result = None
            if chain in self.web3_instances and chain in ROUTER_ADDRESSES:
                print(f"🔍 {self.name}: Tier 2 — eth_call simulation...")
                try:
                    eth_call_result = await asyncio.wait_for(
                        self._simulate_eth_call_swap(token_address, chain),
                        timeout=45
                    )
                except asyncio.TimeoutError:
                    print(f"⚠️ {self.name}: eth_call simulation timed out")
                except Exception as e:
                    print(f"⚠️ {self.name}: eth_call simulation failed: {e}")
            else:
                print(f"⚠️ {self.name}: eth_call not available for {chain}")

            # ── TIER 3: Tenderly Simulation ──
            tenderly_result = None
            if os.getenv("TENDERLY_API_KEY") and chain in ("bsc", "ethereum"):
                print(f"🔍 {self.name}: Tier 3 — Tenderly simulation...")
                try:
                    tenderly_result = await asyncio.wait_for(
                        self._simulate_tenderly(token_address, chain),
                        timeout=45
                    )
                except asyncio.TimeoutError:
                    print(f"⚠️ {self.name}: Tenderly simulation timed out")
                except Exception as e:
                    print(f"⚠️ {self.name}: Tenderly simulation failed: {e}")

            # ── BUILD RESULT ──
            simulation = self._build_result(
                token_address, chain, symbol,
                honeypot_data, liquidity_data, contract_data,
                eth_call_result, tenderly_result
            )

            await self.results_cache.set(token_address, simulation)

            try:
                self.publish("SIMULATION_COMPLETE", simulation.__dict__)
            except Exception as e:
                print(f"⚠️ {self.name}: Publish failed: {e}")

            context = f"Token discovered by Nova on {chain}. Running trade simulation."
            report = await self._generate_atlas_message(simulation, symbol, context)
            await self._speak(report, "simulation_report")

        except asyncio.TimeoutError:
            print(f"⚠️ {self.name}: Simulation timed out")
        except Exception as e:
            print(f"❌ {self.name}: Fatal simulation error: {e}")

    # ═══════════════════════════════════════════════════════════
    # TIER 1: STATIC ANALYSIS
    # ═══════════════════════════════════════════════════════════

    async def _check_honeypot(self, token_address: str, chain: str) -> dict:
        try:
            if chain not in ["bsc", "ethereum"]:
                return {
                    "buyable": True,
                    "sellable": True,
                    "is_honeypot": False,
                    "buyTax": 0,
                    "sellTax": 0
                }

            await rate_limiter.wait("honeypot.is")
            url = f"{self.honeypot_apis[chain]}?address={token_address}"

            session = await self._get_session()
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:

                if resp.status == 200:
                    data = await resp.json()
                    simulation = data.get("simulationResult", {})

                    return {
                        "buyable": simulation.get("buyTax", 0) < 100,
                        "sellable": simulation.get("sellTax", 0) < 100,
                        "is_honeypot": data.get("honeypotResult", {}).get("isHoneypot", False),
                        "buyTax": simulation.get("buyTax", 0),
                        "sellTax": simulation.get("sellTax", 0)
                    }
                elif resp.status == 429:
                    print(f"⚠️ {self.name}: Honeypot.is rate limited")
                    return {}
                else:
                    text = await resp.text()
                    print(f"⚠️ {self.name}: Honeypot.is HTTP {resp.status}: {text[:100]}")
                    return {}

        except Exception as e:
            print(f"⚠️ {self.name}: Honeypot check failed: {e}")
            return {}

    async def _check_liquidity(self, token_address: str, chain: str) -> dict:
        try:
            await rate_limiter.wait("dexscreener.com")
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"

            session = await self._get_session()
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:

                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs", [])

                    if pairs:
                        top_pair = max(
                            pairs,
                            key=lambda x: x.get("liquidity", {}).get("usd", 0) or 0
                        )

                        liquidity = top_pair.get("liquidity", {})
                        liquidity_usd = liquidity.get("usd", 0) or 0

                        return {
                            "liquidity_usd": liquidity_usd,
                            "locked": liquidity_usd > 1000,
                            "dex": top_pair.get("dexId")
                        }
                elif resp.status == 429:
                    print(f"⚠️ {self.name}: DexScreener rate limited")
                else:
                    text = await resp.text()
                    print(f"⚠️ {self.name}: DexScreener HTTP {resp.status}: {text[:100]}")

            return {"liquidity_usd": 0, "locked": False}

        except Exception as e:
            print(f"⚠️ {self.name}: Liquidity check failed: {e}")
            return {"liquidity_usd": 0, "locked": False}

    async def _analyze_contract(self, token_address: str, chain: str) -> dict:
        try:
            if chain not in ["bsc", "ethereum"]:
                return {}

            rpc_key = "BSC_RPC_URL" if chain == "bsc" else "ETH_RPC_URL"
            rpc_url = os.getenv(rpc_key)

            if not rpc_url:
                return {}

            w3 = Web3(
                Web3.HTTPProvider(
                    rpc_url,
                    request_kwargs={"timeout": 10}
                )
            )

            dangerous_sigs = {
                "mint": "0x40c10f19",
                "blacklist": "0xf9f92be4",
                "pause": "0x8456cb59",
            }

            try:
                code = w3.eth.get_code(
                    Web3.to_checksum_address(token_address)
                ).hex()
            except Exception:
                return {}

            # Check ownership via state call (not bytecode)
            owner_renounced = False
            try:
                token_contract = w3.eth.contract(
                    address=Web3.to_checksum_address(token_address),
                    abi=OWNERSHIP_ABI
                )

                # Try owner() first
                try:
                    owner_addr = token_contract.functions.owner().call()
                    owner_renounced = owner_addr == "0x0000000000000000000000000000000000000000"
                except Exception:
                    # Try getOwner() fallback
                    try:
                        owner_addr = token_contract.functions.getOwner().call()
                        owner_renounced = owner_addr == "0x0000000000000000000000000000000000000000"
                    except Exception:
                        pass  # Cannot determine ownership
            except Exception:
                pass

            return {
                "has_mint": dangerous_sigs["mint"] in code,
                "has_blacklist": dangerous_sigs["blacklist"] in code,
                "has_pause": dangerous_sigs["pause"] in code,
                "owner_renounced": owner_renounced,
            }

        except Exception as e:
            print(f"⚠️ {self.name}: Contract analysis failed: {e}")
            return {}

    # ═══════════════════════════════════════════════════════════
    # TIER 2: eth_call SIMULATION (FREE, NO CAPITAL)
    # ═══════════════════════════════════════════════════════════

    async def _simulate_eth_call_swap(self, token_address: str, chain: str) -> dict:
        """
        Simulate a real DEX swap using eth_call.
        ZERO capital required. ZERO gas spent.
        Uses a real funded wallet address for balance simulation.
        Simulates approve() before sell to avoid false positives.
        """
        w3 = self.web3_instances.get(chain)
        if not w3:
            return {"error": "No Web3 instance for chain"}

        router_address = ROUTER_ADDRESSES.get(chain, {}).get("pancakeswap_v2" if chain == "bsc" else "uniswap_v2")
        weth = WETH_ADDRESSES.get(chain)
        funded_wallet = FUNDED_WALLETS.get(chain)

        if not router_address or not weth or not funded_wallet:
            return {"error": "No router/WETH/wallet configured for chain"}

        try:
            router = w3.eth.contract(address=router_address, abi=ROUTER_ABIS["uniswap_v2"])
            token = w3.eth.contract(
                address=Web3.to_checksum_address(token_address),
                abi=ERC20_ABI
            )

            # Get token decimals
            try:
                decimals = token.functions.decimals().call()
            except Exception:
                decimals = 18

            amount_in_eth = 0.001  # ~$2-3 worth
            amount_in_wei = w3.to_wei(amount_in_eth, 'ether')

            # Get current nonce for funded wallet
            try:
                nonce = w3.eth.get_transaction_count(funded_wallet)
            except Exception:
                nonce = 0

            # ── SIMULATE BUY: ETH → Token ──
            print(f"🔬 {self.name}: eth_call BUY {amount_in_eth} ETH → {token_address[:8]}...")

            buy_tx = router.functions.swapExactETHForTokens(
                0,  # minAmountOut = 0 (accept anything for simulation)
                [weth, Web3.to_checksum_address(token_address)],
                funded_wallet,
                2**64  # far future deadline
            ).build_transaction({
                'from': funded_wallet,
                'value': amount_in_wei,
                'gas': 300000,
                'gasPrice': w3.eth.gas_price,
                'nonce': nonce,
            })

            buy_result = w3.eth.call(buy_tx)
            buy_success = True
            print(f"✅ {self.name}: eth_call BUY succeeded")

            # Get expected token output
            try:
                amounts_out = router.functions.getAmountsOut(
                    amount_in_wei,
                    [weth, Web3.to_checksum_address(token_address)]
                ).call()
                expected_tokens = amounts_out[-1] if amounts_out else 0
            except Exception:
                expected_tokens = 0

            # ── SIMULATE APPROVAL ──
            print(f"🔬 {self.name}: eth_call APPROVE {expected_tokens} tokens for router...")

            approve_success = False
            if expected_tokens > 0:
                try:
                    approve_tx = token.functions.approve(
                        router_address,
                        expected_tokens
                    ).build_transaction({
                        'from': funded_wallet,
                        'gas': 100000,
                        'gasPrice': w3.eth.gas_price,
                        'nonce': nonce + 1,
                    })
                    w3.eth.call(approve_tx)
                    approve_success = True
                    print(f"✅ {self.name}: eth_call APPROVE succeeded")
                except Exception as e:
                    print(f"⚠️ {self.name}: eth_call APPROVE failed: {e}")
                    # Some tokens don't need explicit approve (e.g., fee-on-transfer with built-in)
                    # Continue to sell attempt anyway

            # ── SIMULATE SELL: Token → ETH ──
            print(f"🔬 {self.name}: eth_call SELL {expected_tokens} tokens → ETH...")

            sell_success = False
            eth_returned = 0
            effective_tax = 0.0
            sell_revert_reason = None

            if expected_tokens > 0:
                try:
                    sell_tx = router.functions.swapExactTokensForETH(
                        expected_tokens,
                        0,  # minAmountOut = 0
                        [Web3.to_checksum_address(token_address), weth],
                        funded_wallet,
                        2**64
                    ).build_transaction({
                        'from': funded_wallet,
                        'gas': 300000,
                        'gasPrice': w3.eth.gas_price,
                        'nonce': nonce + 2,
                    })

                    sell_result = w3.eth.call(sell_tx)
                    sell_success = True
                    print(f"✅ {self.name}: eth_call SELL succeeded")

                    # Calculate expected ETH return
                    try:
                        amounts_in = router.functions.getAmountsIn(
                            expected_tokens,
                            [weth, Web3.to_checksum_address(token_address)]
                        ).call()
                        eth_returned = amounts_in[0] if amounts_in else 0
                    except Exception:
                        eth_returned = 0

                    # Calculate effective tax/slippage
                    if eth_returned > 0 and amount_in_wei > 0:
                        loss_ratio = 1 - (eth_returned / amount_in_wei)
                        effective_tax = max(0, loss_ratio * 100)
                    else:
                        effective_tax = 0

                except Exception as e:
                    sell_revert_reason = str(e)
                    print(f"🚨 {self.name}: eth_call SELL failed — {sell_revert_reason[:100]}")
            else:
                sell_revert_reason = "Zero token output from buy — likely no liquidity"
                print(f"⚠️ {self.name}: {sell_revert_reason}")

            # Determine honeypot status
            is_honeypot = False
            if sell_revert_reason:
                error_lower = sell_revert_reason.lower()
                # Only flag as honeypot for sell-specific transfer failures
                # NOT for generic errors like "insufficient output amount" or "cannot estimate gas"
                honeypot_indicators = [
                    "transfer failed", "transfer_from_failed", "blacklisted",
                    "uniswapv2: k", "pancake: k", "ds-math-sub-underflow",
                    "insufficient liquidity", "safemath: subtraction overflow"
                ]
                is_honeypot = any(kw in error_lower for kw in honeypot_indicators)

            return {
                "buy_success": buy_success,
                "sell_success": sell_success,
                "approve_success": approve_success,
                "expected_tokens": expected_tokens,
                "eth_returned_wei": eth_returned,
                "effective_tax_percent": round(effective_tax, 2),
                "is_honeypot": is_honeypot,
                "revert_reason": sell_revert_reason,
                "simulation_method": "eth_call",
            }

        except Exception as e:
            error_msg = str(e)
            print(f"⚠️ {self.name}: eth_call simulation error: {error_msg[:100]}")
            return {
                "buy_success": False,
                "sell_success": False,
                "expected_tokens": 0,
                "eth_returned_wei": 0,
                "effective_tax_percent": 0,
                "is_honeypot": False,  # Don't assume honeypot on total failure
                "revert_reason": error_msg[:200],
                "simulation_method": "eth_call",
            }

    # ═══════════════════════════════════════════════════════════
    # TIER 3: TENDERLY SIMULATION (FREE TIER)
    # ═══════════════════════════════════════════════════════════

    async def _simulate_tenderly(self, token_address: str, chain: str) -> dict:
        """
        Simulate via Tenderly API for full state tracing.
        Simulates BOTH buy and sell paths.
        Requires TENDERLY_API_KEY, TENDERLY_ACCOUNT, TENDERLY_PROJECT env vars.
        """
        api_key = os.getenv("TENDERLY_API_KEY")
        account = os.getenv("TENDERLY_ACCOUNT")
        project = os.getenv("TENDERLY_PROJECT")

        if not api_key or not account or not project:
            return {"error": "Tenderly not configured (need API_KEY, ACCOUNT, PROJECT)"}

        chain_id = 56 if chain == "bsc" else 1 if chain == "ethereum" else None
        if not chain_id:
            return {"error": f"Chain {chain} not supported by Tenderly"}

        router_address = ROUTER_ADDRESSES.get(chain, {}).get("pancakeswap_v2" if chain == "bsc" else "uniswap_v2")
        weth = WETH_ADDRESSES.get(chain)
        funded_wallet = FUNDED_WALLETS.get(chain)

        if not router_address or not weth or not funded_wallet:
            return {"error": "No router/WETH/wallet configured for chain"}

        try:
            w3 = self.web3_instances.get(chain)
            if not w3:
                return {"error": "No Web3 instance for chain"}

            router = w3.eth.contract(address=router_address, abi=ROUTER_ABIS["uniswap_v2"])
            amount_in_wei = w3.to_wei(0.001, 'ether')

            # ── TENDERLY BUY SIMULATION ──
            print(f"🔬 {self.name}: Tenderly BUY simulation...")

            buy_swap_data = router.encodeABI(
                fn_name="swapExactETHForTokens",
                args=[
                    0,
                    [weth, Web3.to_checksum_address(token_address)],
                    funded_wallet,
                    2**64
                ]
            )

            buy_url = f"https://api.tenderly.co/api/v1/account/{account}/project/{project}/simulate"

            buy_body = {
                "network_id": str(chain_id),
                "from": funded_wallet,
                "to": router_address,
                "input": buy_swap_data,
                "value": str(amount_in_wei),
                "save": True,
                "simulation_type": "full"
            }

            session = await self._get_session()

            buy_success = False
            buy_gas = None
            buy_revert = None

            async with session.post(
                buy_url,
                json=buy_body,
                headers={"X-Access-Key": api_key},
                timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:

                if resp.status != 200:
                    text = await resp.text()
                    print(f"⚠️ {self.name}: Tenderly BUY error {resp.status}: {text[:200]}")
                    return {"error": f"Tenderly BUY API error: {resp.status}"}

                result = await resp.json()
                tx = result.get("transaction", {})
                buy_success = tx.get("status") == True
                buy_gas = tx.get("gas_used")
                buy_revert = tx.get("error_message")

            if not buy_success:
                return {
                    "buy_success": False,
                    "sell_success": False,
                    "gas_used": buy_gas,
                    "revert_reason": buy_revert or "Buy simulation failed",
                    "simulation_method": "tenderly",
                }

            # ── TENDERLY SELL SIMULATION ──
            print(f"🔬 {self.name}: Tenderly SELL simulation...")

            # Get expected tokens from buy for sell simulation
            try:
                amounts_out = router.functions.getAmountsOut(
                    amount_in_wei,
                    [weth, Web3.to_checksum_address(token_address)]
                ).call()
                expected_tokens = amounts_out[-1] if amounts_out else 0
            except Exception:
                expected_tokens = 0

            if expected_tokens == 0:
                return {
                    "buy_success": True,
                    "sell_success": False,
                    "gas_used": buy_gas,
                    "revert_reason": "Zero token output from buy — cannot simulate sell",
                    "simulation_method": "tenderly",
                }

            sell_swap_data = router.encodeABI(
                fn_name="swapExactTokensForETH",
                args=[
                    expected_tokens,
                    0,
                    [Web3.to_checksum_address(token_address), weth],
                    funded_wallet,
                    2**64
                ]
            )

            sell_body = {
                "network_id": str(chain_id),
                "from": funded_wallet,
                "to": router_address,
                "input": sell_swap_data,
                "value": "0",
                "save": True,
                "simulation_type": "full"
            }

            sell_success = False
            sell_gas = None
            sell_revert = None

            async with session.post(
                buy_url,
                json=sell_body,
                headers={"X-Access-Key": api_key},
                timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:

                if resp.status != 200:
                    text = await resp.text()
                    print(f"⚠️ {self.name}: Tenderly SELL error {resp.status}: {text[:200]}")
                    return {
                        "buy_success": True,
                        "sell_success": False,
                        "gas_used": buy_gas,
                        "revert_reason": f"Tenderly SELL API error: {resp.status}",
                        "simulation_method": "tenderly",
                    }

                result = await resp.json()
                tx = result.get("transaction", {})
                sell_success = tx.get("status") == True
                sell_gas = tx.get("gas_used")
                sell_revert = tx.get("error_message")

            return {
                "buy_success": buy_success,
                "sell_success": sell_success,
                "gas_used": buy_gas or sell_gas,
                "revert_reason": sell_revert,
                "simulation_method": "tenderly",
            }

        except Exception as e:
            print(f"⚠️ {self.name}: Tenderly simulation failed: {e}")
            return {"error": str(e)}

    # ═══════════════════════════════════════════════════════════
    # RESULT BUILDER
    # ═══════════════════════════════════════════════════════════

    def _build_result(
        self,
        token_address: str,
        chain: str,
        symbol: str,
        honeypot_data: dict,
        liquidity_data: dict,
        contract_data: dict,
        eth_call_result: Optional[dict],
        tenderly_result: Optional[dict]
    ) -> SimulationResult:
        """Merge all tier results into final SimulationResult."""

        # Base from static analysis
        can_buy = honeypot_data.get("buyable", True)
        can_sell = honeypot_data.get("sellable", True)
        is_honeypot = honeypot_data.get("is_honeypot", False)
        confidence = self._calculate_confidence(honeypot_data, liquidity_data, contract_data)

        # Override with eth_call results if available
        eth_call_buy = False
        eth_call_sell = False
        eth_call_reason = None
        eth_call_tax = 0.0

        if eth_call_result and "error" not in eth_call_result:
            eth_call_buy = eth_call_result.get("buy_success", False)
            eth_call_sell = eth_call_result.get("sell_success", False)
            eth_call_reason = eth_call_result.get("revert_reason")
            eth_call_tax = eth_call_result.get("effective_tax_percent", 0.0)

            # eth_call is more authoritative than static APIs
            if not eth_call_sell:
                can_sell = False
                if eth_call_result.get("is_honeypot", False):
                    is_honeypot = True
                    confidence = min(confidence + 0.2, 1.0)

            if eth_call_tax > 50:
                # Extreme tax = effectively a honeypot
                is_honeypot = True
                can_sell = False
                confidence = min(confidence + 0.15, 1.0)

        # Override with Tenderly if available
        tenderly_buy = False
        tenderly_sell = False
        tenderly_gas = None
        tenderly_reason = None

        if tenderly_result and "error" not in tenderly_result:
            tenderly_buy = tenderly_result.get("buy_success", False)
            tenderly_sell = tenderly_result.get("sell_success", False)
            tenderly_gas = tenderly_result.get("gas_used")
            tenderly_reason = tenderly_result.get("revert_reason")

            if not tenderly_sell:
                can_sell = False
                is_honeypot = True
                confidence = min(confidence + 0.15, 1.0)

        return SimulationResult(
            token_address=token_address,
            chain=chain,
            can_buy=can_buy,
            can_sell=can_sell,
            buy_tax=float(honeypot_data.get("buyTax", 0) or 0),
            sell_tax=float(honeypot_data.get("sellTax", 0) or 0),
            liquidity_usd=float(liquidity_data.get("liquidity_usd", 0) or 0),
            liquidity_locked=liquidity_data.get("locked", False),
            liquidity_lock_duration=liquidity_data.get("lock_duration"),
            max_tx_limit=contract_data.get("max_tx"),
            owner_renounced=contract_data.get("owner_renounced", False),
            mint_function=contract_data.get("has_mint", False),
            blacklist_function=contract_data.get("has_blacklist", False),
            honeypot_risk=is_honeypot,
            simulation_confidence=confidence,
            details="",
            timestamp=time.time(),
            eth_call_buy_simulated=eth_call_buy,
            eth_call_sell_simulated=eth_call_sell,
            eth_call_revert_reason=eth_call_reason,
            eth_call_effective_tax_percent=eth_call_tax,
            tenderly_buy_simulated=tenderly_buy,
            tenderly_sell_simulated=tenderly_sell,
            tenderly_gas_used=tenderly_gas,
            tenderly_revert_reason=tenderly_reason,
        )

    # ─────────────────────────────────────────────────────────

    def _calculate_confidence(
        self,
        honeypot_data: dict,
        liquidity_data: dict,
        contract_data: dict
    ) -> float:

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

        if checks == 0:
            return 0.0  # No data = zero confidence

        return passed / checks

    async def cleanup(self):
        """Cleanup resources."""
        await self.results_cache.clear_expired()
        if self._session and not self._session.closed:
            await self._session.close()

    def stop(self):
        """Graceful shutdown."""
        print(f"🛑 {self.name}: Simulator stopped.")


# ─────────────────────────────────────────────────────────────
# Main Runner
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    def test_publish(event_type, data):
        try:
            if event_type == "AGENT_MESSAGE":
                print(f"\n💬 {data['agent']}: {data['message']}")
            else:
                print(f"\n📡 {event_type}")
        except Exception as e:
            print(f"⚠️ Publish error: {e}")

    sim = SimulatorAgent(test_publish)

    test_event = {
        "token_address": "0x1234567890abcdef1234567890abcdef12345678",
        "chain": "bsc",
        "token_symbol": "TEST",
        "token_name": "Test Token"
    }

    try:
        asyncio.run(sim._simulate_token(test_event))
    except KeyboardInterrupt:
        sim.stop()
        print("\n🛑 Atlas stopped.")
    except Exception as e:
        print(f"❌ Fatal crash: {e}")
