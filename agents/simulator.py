"""
"The Tester" — Runs fake trades, checks if you can actually buy and sell.
Called directly by the Orchestrator. Returns structured results + spoken message.
"""

import asyncio
import json
import time
import os
import re
import base64
import struct
from dataclasses import dataclass, asdict
from typing import Dict, Optional, Any
from datetime import datetime

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

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

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

# ═══════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════

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
    # EVM simulation fields
    eth_call_buy_simulated: bool = False
    eth_call_sell_simulated: bool = False
    eth_call_revert_reason: Optional[str] = None
    eth_call_effective_tax_percent: float = 0.0
    # Tenderly fields
    tenderly_buy_simulated: bool = False
    tenderly_sell_simulated: bool = False
    tenderly_gas_used: Optional[int] = None
    tenderly_revert_reason: Optional[str] = None
    # Solana fields
    solana_buy_simulated: bool = False
    solana_sell_simulated: bool = False
    solana_revert_reason: Optional[str] = None
    solana_effective_tax_percent: float = 0.0
    solana_compute_units: Optional[int] = None
    solana_mint_authority: Optional[str] = None
    solana_freeze_authority: Optional[str] = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)

# ═══════════════════════════════════════════════════════════
# EVM DEX CONFIGURATION
# ═══════════════════════════════════════════════════════════

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
    },
    "base": {
        "uniswap_v2": "0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24",  # BaseSwap / Uniswap V2 on Base
        "uniswap_v3": "0x2626664c2603336E57B271c5C0b26F421741e481",
    }
}

WETH_ADDRESSES = {
    "bsc": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
    "ethereum": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    "base": "0x4200000000000000000000000000000000000006",
}

# v4.1: Use addresses with known balance history to avoid anti-bot zero-addr checks
FUNDED_WALLETS = {
    "bsc": "0x8894E0a0c962CB723c1976a4421c95949bE2D4E3",
    "ethereum": "0x0716a17FBAeE714f1E6aB0f9d59edbC5f09815C0",
    "base": "0x0B0A588666437549CeC3519249DD7D8663dC12B4",
}

ERC20_ABI = [
    {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"},
    {"constant": False, "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}, {"name": "_spender", "type": "address"}], "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
]

OWNERSHIP_ABI = [
    {"constant": True, "inputs": [], "name": "owner", "outputs": [{"name": "", "type": "address"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "getOwner", "outputs": [{"name": "", "type": "address"}], "type": "function"},
]

# ═══════════════════════════════════════════════════════════
# UTILITIES
# ═══════════════════════════════════════════════════════════

class RateLimiter:
    """Simple per-domain rate limiter."""
    def __init__(self):
        self._last_call: Dict[str, float] = {}
        self._min_interval = 1.5
        self._lock = asyncio.Lock()

    async def wait(self, domain: str):
        async with self._lock:
            now = time.time()
            last = self._last_call.get(domain, 0)
            elapsed = now - last
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_call[domain] = time.time()

rate_limiter = RateLimiter()

class TTLCache:
    """Simple TTL cache with max size."""
    def __init__(self, maxsize: int = 1000, ttl_seconds: int = 3600):
        self.maxsize = maxsize
        self.ttl = ttl_seconds
        self._data: Dict[str, tuple] = {}
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
                oldest_key = min(self._data, key=lambda k: self._data[k][1])
                del self._data[oldest_key]
            self._data[key] = (value, time.time() + self.ttl)

    async def clear_expired(self):
        async with self._lock:
            now = time.time()
            expired = [k for k, (_, exp) in self._data.items() if now > exp]
            for k in expired:
                del self._data[k]

def validate_token_address(address: str, chain: Optional[str] = None) -> str:
    """Validate and checksum/normalize a token address. Raises ValueError if invalid."""
    if not address:
        raise ValueError("Token address is empty")

    address = address.strip()
    is_solana_chain = chain == "solana" if chain else False
    looks_like_solana = not address.startswith("0x") and 32 <= len(address) <= 44

    if is_solana_chain or looks_like_solana:
        base58_chars = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")
        if all(c in base58_chars for c in address):
            return address
        if is_solana_chain:
            raise ValueError(f"Invalid Solana address format: {address}")

    if not re.match(r'^0x[a-fA-F0-9]{40}$', address):
        raise ValueError(f"Invalid token address format: {address}")

    try:
        return Web3.to_checksum_address(address)
    except Exception as e:
        raise ValueError(f"Invalid checksum for address {address}: {e}")

def validate_chain(chain: str) -> str:
    """Validate chain identifier."""
    chain = chain.lower().strip()
    supported = {"bsc", "ethereum", "base", "solana"}
    if chain not in supported:
        raise ValueError(f"Unsupported chain: {chain}. Supported: {supported}")
    return chain

# ═══════════════════════════════════════════════════════════
# SOLANA SIMULATION ENGINE
# ═══════════════════════════════════════════════════════════

class SolanaSimulator:
    """
    Solana swap simulation using Jupiter Quote API + RPC simulateTransaction.
    No capital required. No gas spent. No on-chain execution.
    """

    JUPITER_QUOTE = "https://quote-api.jup.ag/v6"
    JUPITER_SWAP = "https://quote-api.jup.ag/v6/swap"
    WSOL = "So11111111111111111111111111111111111111112"
    DEFAULT_SIM_WALLET = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"

    def __init__(self, rpc_url: str, sim_wallet: Optional[str] = None, session: Optional[aiohttp.ClientSession] = None):
        self.rpc_url = rpc_url
        self.sim_wallet = sim_wallet or os.getenv("SOLANA_SIM_WALLET", self.DEFAULT_SIM_WALLET)
        self._session = session
        self._owns_session = session is None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is not None and not self._session.closed:
            return self._session
        self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        self._owns_session = True
        return self._session

    async def simulate_buy_sell(self, token_mint: str, sol_amount: float = 0.01) -> dict:
        """Simulate buy (SOL->Token) and sell (Token->SOL) via Jupiter + RPC."""
        try:
            session = await self._get_session()

            # BUY quote
            buy_quote = await self._get_jupiter_quote(
                session, self.WSOL, token_mint, int(sol_amount * 1e9), slippage_bps=500
            )
            if not buy_quote:
                return {
                    "buy_success": False, "sell_success": False,
                    "revert_reason": "Jupiter: No route found for buy",
                    "simulation_method": "jupiter_rpc"
                }

            buy_sim = await self._simulate_jupiter_swap(session, buy_quote)
            if not buy_sim.get("success"):
                return {
                    "buy_success": False, "sell_success": False,
                    "revert_reason": f"Buy sim failed: {buy_sim.get('error')}",
                    "simulation_method": "jupiter_rpc",
                    "logs": buy_sim.get("logs", [])
                }

            expected_tokens = int(buy_quote.get("outAmount", 0))
            if expected_tokens <= 0:
                return {
                    "buy_success": True, "sell_success": False, "expected_tokens": 0,
                    "revert_reason": "Zero token output from buy -- likely no liquidity or extreme tax",
                    "simulation_method": "jupiter_rpc"
                }

            # SELL quote
            sell_quote = await self._get_jupiter_quote(
                session, token_mint, self.WSOL, expected_tokens, slippage_bps=500
            )
            if not sell_quote:
                return {
                    "buy_success": True, "sell_success": False,
                    "expected_tokens": expected_tokens,
                    "revert_reason": "Jupiter: No route found for sell -- possible honeypot",
                    "simulation_method": "jupiter_rpc"
                }

            sell_sim = await self._simulate_jupiter_swap(session, sell_quote)

            sol_returned = int(sell_quote.get("outAmount", 0))
            effective_tax = 0.0
            if sol_returned > 0 and sol_amount > 0:
                effective_tax = max(0, (1 - (sol_returned / (sol_amount * 1e9))) * 100)

            is_honeypot = False
            if not sell_sim.get("success"):
                error_lower = str(sell_sim.get("error", "")).lower()
                honeypot_indicators = [
                    "transfer failed", "insufficient funds", "account frozen",
                    "invalid account data", "program error", "custom program error",
                    "slippage tolerance exceeded", "0x11", "0x12", "account not found",
                    "missing associated token account", "insufficient lamports"
                ]
                is_honeypot = any(kw in error_lower for kw in honeypot_indicators)

            return {
                "buy_success": True,
                "sell_success": sell_sim.get("success", False),
                "expected_tokens": expected_tokens,
                "sol_returned_lamports": sol_returned,
                "effective_tax_percent": round(effective_tax, 2),
                "is_honeypot": is_honeypot,
                "revert_reason": sell_sim.get("error"),
                "simulation_method": "jupiter_rpc",
                "compute_units": sell_sim.get("compute_units") or buy_sim.get("compute_units"),
                "logs": (sell_sim.get("logs", []) + buy_sim.get("logs", []))[:50]
            }

        except Exception as e:
            return {
                "buy_success": False, "sell_success": False,
                "revert_reason": str(e)[:200],
                "simulation_method": "jupiter_rpc"
            }

    async def _get_jupiter_quote(
        self, session: aiohttp.ClientSession, input_mint: str,
        output_mint: str, amount: int, slippage_bps: int = 50
    ) -> Optional[dict]:
        url = (
            f"{self.JUPITER_QUOTE}/quote?"
            f"inputMint={input_mint}&outputMint={output_mint}&amount={amount}"
            f"&slippageBps={slippage_bps}&onlyDirectRoutes=false"
        )
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    return await resp.json()
                elif resp.status == 400:
                    data = await resp.json()
                    print(f"⚠️ Jupiter quote error: {data.get('error', 'Unknown')}")
                    return None
                else:
                    print(f"⚠️ Jupiter quote HTTP {resp.status}")
                    return None
        except Exception as e:
            print(f"⚠️ Jupiter quote request failed: {e}")
            return None

    async def _simulate_jupiter_swap(
        self, session: aiohttp.ClientSession, quote_data: dict
    ) -> dict:
        try:
            swap_body = {
                "quoteResponse": quote_data,
                "userPublicKey": self.sim_wallet,
                "wrapAndUnwrapSol": True,
                "computeUnitPriceMicroLamports": 50000,
            }
            async with session.post(
                self.JUPITER_SWAP, json=swap_body, timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    return {"success": False, "error": f"Jupiter swap API error: {resp.status} -- {text[:100]}"}
                swap_data = await resp.json()
                swap_tx_b64 = swap_data.get("swapTransaction")
                if not swap_tx_b64:
                    return {"success": False, "error": "No swapTransaction in Jupiter response"}

                rpc_payload = {
                    "jsonrpc": "2.0", "id": 1,
                    "method": "simulateTransaction",
                    "params": [
                        swap_tx_b64,
                        {
                            "encoding": "base64",
                            "commitment": "confirmed",
                            "replaceRecentBlockhash": True,
                            "sigVerify": False,
                        }
                    ]
                }
                async with session.post(
                    self.rpc_url, json=rpc_payload, timeout=aiohttp.ClientTimeout(total=20)
                ) as sim_resp:
                    if sim_resp.status != 200:
                        return {"success": False, "error": f"RPC error: {sim_resp.status}"}
                    sim_result = await sim_resp.json()
                    value = sim_result.get("result", {}).get("value", {})
                    err = value.get("err")
                    logs = value.get("logs", [])
                    compute_units = value.get("unitsConsumed")
                    if err:
                        error_str = json.dumps(err) if isinstance(err, dict) else str(err)
                        return {"success": False, "error": error_str, "logs": logs, "compute_units": compute_units}
                    return {"success": True, "logs": logs, "compute_units": compute_units}
        except Exception as e:
            return {"success": False, "error": str(e)[:200]}

    async def analyze_mint_account(self, token_mint: str) -> dict:
        """Check SPL token mint authority and freeze authority via RPC."""
        try:
            session = await self._get_session()
            payload = {
                "jsonrpc": "2.0", "id": 1,
                "method": "getAccountInfo",
                "params": [token_mint, {"encoding": "base64"}]
            }
            async with session.post(
                self.rpc_url, json=payload, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()
                result = data.get("result", {}).get("value", {})
                if not result:
                    return {}
                account_data_b64 = result.get("data", [None])[0]
                if not account_data_b64:
                    return {}
                raw = base64.b64decode(account_data_b64)
                if len(raw) < 82:
                    return {}
                mint_auth_option = struct.unpack("<I", raw[0:4])[0]
                mint_authority = None
                if mint_auth_option == 1:
                    mint_authority = base64.b64encode(raw[4:36]).decode()
                freeze_auth_option = struct.unpack("<I", raw[46:50])[0]
                freeze_authority = None
                if freeze_auth_option == 1:
                    freeze_authority = base64.b64encode(raw[50:82]).decode()
                return {
                    "mint_authority": mint_authority,
                    "freeze_authority": freeze_authority,
                }
        except Exception as e:
            print(f"⚠️ Solana mint analysis error: {e}")
            return {}

    async def cleanup(self):
        """Close session only if we own it (i.e., it was not shared from Atlas)."""
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

# ═══════════════════════════════════════════════════════════
# MAIN SIMULATOR AGENT
# ═══════════════════════════════════════════════════════════

class SimulatorAgent:
    """
    Atlas — The Tester
    Runs fake trades, checks if you can actually buy and sell.
    v4.1: Orchestrator-driven, returns structured results + spoken message.
    """

    def __init__(self, server: Optional[Any] = None):
        self.server = server
        self.name = "Atlas"
        self.results_cache = TTLCache(maxsize=500, ttl_seconds=1800)
        self.web3_instances: Dict[str, Web3] = {}
        self.honeypot_apis = {
            "bsc": "https://api.honeypot.is/v2/IsHoneypot",
            "ethereum": "https://api.honeypot.is/v2/IsHoneypot",
            "base": "https://api.honeypot.is/v2/IsHoneypot",
        }
        self._session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(limit=10, limit_per_host=5, ttl_dns_cache=300, use_dns_cache=True),
            timeout=aiohttp.ClientTimeout(total=30)
        )
        self._init_web3()

    def _init_web3(self):
        chains = {
            "bsc": os.getenv("BSC_RPC_URL"),
            "ethereum": os.getenv("ETH_RPC_URL"),
            "base": os.getenv("BASE_RPC_URL"),
        }
        for chain, rpc in chains.items():
            if not rpc:
                print(f"⚠️ {self.name}: No RPC for {chain} -- eth_call disabled")
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

    # v4.1: Public entry point for the Orchestrator
    async def simulate(self, event_data: dict) -> dict:
        """Run full simulation and return structured result + spoken message."""
        return await self._simulate_token(event_data)

    # v4.1: Backward-compatible fire-and-forget wrapper (not used by Orchestrator)
    def on_new_token(self, event_data: dict):
        """Schedule a simulation. Catches crashes so they never kill the event loop."""
        try:
            chain = validate_chain(event_data.get("chain", "unknown"))
            token_address = validate_token_address(event_data.get("token_address", ""), chain)
            event_data["token_address"] = token_address
            event_data["chain"] = chain
            task = asyncio.create_task(asyncio.wait_for(self._simulate_token(event_data), timeout=120))
            task.add_done_callback(self._on_task_done)
        except ValueError as e:
            print(f"❌ {self.name}: Invalid input -- {e}")
        except Exception as e:
            print(f"⚠️ {self.name}: Failed scheduling simulation: {e}")

    def _on_task_done(self, task: asyncio.Task):
        try:
            task.result()
        except asyncio.TimeoutError:
            print(f"⚠️ {self.name}: Simulation task timed out")
        except Exception as e:
            print(f"⚠️ {self.name}: Simulation task failed: {e}")

    async def _speak(self, message: str, msg_type: str = "response"):
        """Broadcast a spoken message. Used for standalone/testing only.
        During orchestrated analysis, the Orchestrator handles all messaging."""
        try:
            if self.server and hasattr(self.server, 'broadcast'):
                await self.server.broadcast("AGENT_MESSAGE", {
                    "agent": self.name, "message": message, "type": msg_type,
                    "channel": "main", "timestamp": time.time()
                })
        except Exception as e:
            print(f"⚠️ {self.name}: Broadcast failed: {e}")

    async def _generate_atlas_message(self, sim: SimulationResult, symbol: str, context: str) -> str:
        if not client:
            return self._fallback_message(sim, symbol)

        system_prompt = (
            "You are Atlas, a battle-hardened crypto contract auditor in a team chat. "
            "You have seen hundreds of rugs, honeypots, and exploits. You speak with the "
            "calm authority of someone who has been burned before. You reference Nova's discovery "
            "naturally, then walk through your findings methodically. Be technical but accessible. "
            "Never hype -- your credibility is your currency."
        )

        sim_details = []
        if sim.chain == "solana":
            if sim.solana_buy_simulated:
                sim_details.append("Jupiter BUY simulation: PASSED")
            else:
                sim_details.append("Jupiter BUY simulation: FAILED")
            if sim.solana_sell_simulated:
                sim_details.append("Jupiter SELL simulation: PASSED")
            else:
                sim_details.append("Jupiter SELL simulation: FAILED")
            if sim.solana_revert_reason:
                sim_details.append(f"Revert reason: {sim.solana_revert_reason}")
            if sim.solana_effective_tax_percent > 0:
                sim_details.append(f"Effective tax/slippage: {sim.solana_effective_tax_percent:.2f}%")
            if sim.solana_compute_units:
                sim_details.append(f"Compute units: {sim.solana_compute_units}")
            if sim.solana_mint_authority:
                sim_details.append("Mint authority is ACTIVE -- supply can be inflated")
            if sim.solana_freeze_authority:
                sim_details.append("Freeze authority is ACTIVE -- accounts can be frozen")
        else:
            if sim.eth_call_buy_simulated:
                sim_details.append("eth_call BUY simulation: PASSED")
            else:
                sim_details.append("eth_call BUY simulation: FAILED")
            if sim.eth_call_sell_simulated:
                sim_details.append("eth_call SELL simulation: PASSED")
            else:
                sim_details.append("eth_call SELL simulation: FAILED")
            if sim.eth_call_revert_reason:
                sim_details.append(f"Revert reason: {sim.eth_call_revert_reason}")
            if sim.eth_call_effective_tax_percent > 0:
                sim_details.append(f"Effective tax/slippage: {sim.eth_call_effective_tax_percent:.2f}%")
            if sim.tenderly_buy_simulated:
                sim_details.append("Tenderly BUY simulation: PASSED")
            if sim.tenderly_sell_simulated:
                sim_details.append("Tenderly SELL simulation: PASSED")
            if sim.tenderly_gas_used:
                sim_details.append(f"Tenderly gas used: {sim.tenderly_gas_used}")
            if sim.tenderly_revert_reason:
                sim_details.append(f"Tenderly revert: {sim.tenderly_revert_reason}")

        sim_detail_text = "\n".join(sim_details) if sim_details else "Static analysis only (no on-chain simulation available)"

        user_prompt = f"""
Token: {symbol}
Chain: {sim.chain.upper()}

Simulation Results:
- Can Buy: {"Yes -- path is open" if sim.can_buy else "NO -- buy path is BLOCKED"}
- Can Sell: {"Yes -- exit is open" if sim.can_sell else "NO -- exit is BLOCKED"}
- Honeypot Risk: {"YES -- this is a trap" if sim.honeypot_risk else "No honeypot behavior detected"}
- Liquidity: ${sim.liquidity_usd:,.0f}
- Liquidity Locked: {"Yes -- funds are secured" if sim.liquidity_locked else "No -- liquidity is unlocked"}
- Buy Tax: {sim.buy_tax}%
- Sell Tax: {sim.sell_tax}%
- Mint Function: {"YES -- owner can print tokens" if sim.mint_function else "No mint function"}
- Blacklist Function: {"YES -- owner can freeze wallets" if sim.blacklist_function else "No blacklist function"}
- Ownership Renounced: {"Yes -- contract is immutable" if sim.owner_renounced else "No -- owner still has control"}

On-Chain Simulation:
{sim_detail_text}

Context:
{context}

Requirements:
- Acknowledge Nova's find naturally and briefly
- Walk through the biggest risks first, then positives
- Mention the sell path explicitly -- that is what kills most people
- Reference the simulation results if available
- Hand off to Vega naturally
- Keep it conversational and under 5 sentences
- Sound like a technician who respects the chain but trusts no contract
"""

        try:
            def _generate():
                kwargs = {"model": GEMINI_MODEL, "contents": f"{system_prompt}\n\n{user_prompt}"}
                if genai_types:
                    kwargs["config"] = genai_types.GenerateContentConfig(temperature=0.85, max_output_tokens=250)
                response = client.models.generate_content(**kwargs)
                return response.text if hasattr(response, "text") else str(response)

            response = await asyncio.wait_for(asyncio.to_thread(_generate), timeout=15)
            if response:
                return response.strip()
            return self._fallback_message(sim, symbol)
        except asyncio.TimeoutError:
            print(f"⚠️ {self.name}: Gemini call timed out")
            return self._fallback_message(sim, symbol)
        except Exception as e:
            print(f"⚠️ {self.name}: Gemini error: {e}")
            return self._fallback_message(sim, symbol)

    def _fallback_message(self, sim: SimulationResult, symbol: str) -> str:
        parts = []
        if sim.honeypot_risk or not sim.can_sell:
            parts.append(f"Nova found it, but I'm calling it -- {symbol} is a honeypot. Sells are dead.")
        else:
            parts.append(f"Buy and sell paths are open on {symbol}. No honeypot behavior detected.")

        if sim.chain == "solana":
            if sim.solana_buy_simulated and sim.solana_sell_simulated:
                parts.append("I ran Jupiter simulation -- both buy and sell executed successfully on Solana.")
            elif sim.solana_buy_simulated and not sim.solana_sell_simulated:
                parts.append("Jupiter buy worked, but sell reverted. Classic honeypot pattern on Solana.")
            if sim.solana_effective_tax_percent > 10:
                parts.append(f"High effective tax detected: {sim.solana_effective_tax_percent:.1f}% -- that's a rug in slow motion.")
            if sim.solana_mint_authority:
                parts.append("Token has an active MINT authority -- supply can be inflated at any time.")
            if sim.solana_freeze_authority:
                parts.append("Freeze authority is active -- your token account could be frozen.")
        else:
            if sim.eth_call_buy_simulated and sim.eth_call_sell_simulated:
                parts.append("I ran eth_call simulation -- both buy and sell executed successfully on-chain.")
            elif sim.eth_call_buy_simulated and not sim.eth_call_sell_simulated:
                parts.append("eth_call buy worked, but sell reverted. Classic honeypot pattern.")
            if sim.eth_call_effective_tax_percent > 10:
                parts.append(f"High effective tax detected: {sim.eth_call_effective_tax_percent:.1f}% -- that's a rug in slow motion.")
            if sim.mint_function:
                parts.append("Contract includes a MINT function -- owner can print infinite supply.")
            if sim.blacklist_function:
                parts.append("Blacklist capability detected -- your wallet could be frozen.")

        liq = sim.liquidity_usd
        if liq == 0:
            parts.append("Liquidity is basically zero -- you're trading air.")
        elif liq < 1000:
            parts.append(f"Low liquidity warning: ${liq:,.0f}. Slippage will eat you alive.")
        elif liq >= 10000:
            parts.append(f"Solid liquidity: ${liq:,.0f}. At least you can get in and out.")

        parts.append("Vega, your turn for deeper analysis.")
        return " ".join(parts)

    # ═══════════════════════════════════════════════════════════
    # MAIN SIMULATION PIPELINE
    # ═══════════════════════════════════════════════════════════

    async def _simulate_token(self, event_data: dict) -> dict:
        # v4.1 FIX: support both "symbol" (from queue) and "token_symbol" (legacy)
        token_address = event_data.get("token_address")
        chain = event_data.get("chain", "unknown")
        symbol = event_data.get("token_symbol", event_data.get("symbol", "???"))
        name = event_data.get("token_name", event_data.get("name", "Unknown"))

        try:
            cached = await self.results_cache.get(token_address)
            if cached:
                print(f"📦 {self.name}: Cache hit for {symbol}")
                # FIX: Removed direct broadcast. Just log and return.
                report = await self._generate_atlas_message(cached, symbol, "Cache hit — returning previous simulation.")
                return {**cached.__dict__, "message": report, "token_symbol": symbol, "token_name": name, "token_address": token_address, "chain": chain}

            # FIX: Removed the early ack broadcast. Atlas works silently.
            # The Orchestrator broadcasts AGENT_WORKING before this method starts
            # and AGENT_MESSAGE after it returns.
            print(f"🧪 {self.name}: Simulating {symbol} ({chain})...")

            # Tier 1: Static Analysis
            print(f"🔍 {self.name}: Tier 1 -- Static analysis...")
            static_results = await asyncio.gather(
                self._check_honeypot(token_address, chain),
                self._check_liquidity(token_address, chain),
                self._analyze_contract(token_address, chain),
                return_exceptions=True
            )
            honeypot_data = static_results[0] if not isinstance(static_results[0], Exception) else {}
            liquidity_data = static_results[1] if not isinstance(static_results[1], Exception) else {}
            contract_data = static_results[2] if not isinstance(static_results[2], Exception) else {}

            # Chain-branching simulation
            eth_call_result = None
            tenderly_result = None
            solana_result = None
            solana_contract = {}

            if chain == "solana":
                print(f"🔍 {self.name}: Tier 2 -- Solana Jupiter + RPC simulation...")
                sol_rpc = os.getenv("SOLANA_RPC_URL")
                if sol_rpc:
                    sol_sim = SolanaSimulator(sol_rpc, session=self._session)
                    try:
                        if not event_data.get("jupiter_failed"):
                            solana_result = await asyncio.wait_for(
                                sol_sim.simulate_buy_sell(token_address, sol_amount=0.01), timeout=60
                            )
                        else:
                            print(f"⚠️ {self.name}: Jupiter failed flag set — skipping Jupiter simulation")
                        solana_contract = await asyncio.wait_for(
                            sol_sim.analyze_mint_account(token_address), timeout=15
                        )
                    except asyncio.TimeoutError:
                        print(f"⚠️ {self.name}: Solana simulation timed out")
                    finally:
                        await sol_sim.cleanup()
                else:
                    print(f"⚠️ {self.name}: No SOLANA_RPC_URL configured")
            else:
                if chain in self.web3_instances and chain in ROUTER_ADDRESSES:
                    print(f"🔍 {self.name}: Tier 2 -- eth_call simulation...")
                    try:
                        eth_call_result = await asyncio.wait_for(
                            self._simulate_eth_call_swap(token_address, chain), timeout=45
                        )
                    except asyncio.TimeoutError:
                        print(f"⚠️ {self.name}: eth_call simulation timed out")
                    except Exception as e:
                        print(f"⚠️ {self.name}: eth_call simulation failed: {e}")
                else:
                    print(f"⚠️ {self.name}: eth_call not available for {chain} (no Web3 or router config)")

                if os.getenv("TENDERLY_API_KEY") and chain in ("bsc", "ethereum", "base"):
                    print(f"🔍 {self.name}: Tier 3 -- Tenderly simulation...")
                    try:
                        tenderly_result = await asyncio.wait_for(
                            self._simulate_tenderly(token_address, chain), timeout=45
                        )
                    except asyncio.TimeoutError:
                        print(f"⚠️ {self.name}: Tenderly simulation timed out")
                    except Exception as e:
                        print(f"⚠️ {self.name}: Tenderly simulation failed: {e}")

            simulation = self._build_result(
                token_address, chain, symbol,
                honeypot_data, liquidity_data, contract_data,
                eth_call_result, tenderly_result, solana_result, solana_contract
            )

            await self.results_cache.set(token_address, simulation)

            context = f"Token discovered by Nova on {chain}. Running trade simulation."
            report = await self._generate_atlas_message(simulation, symbol, context)

            result = {**simulation.__dict__, "message": report, "token_symbol": symbol, "token_name": name, "token_address": token_address, "chain": chain}
            # Preserve fields from upstream (Nova's queue data)
            for key in ["creator", "origin_source", "timestamp", "attention_score", "volume_24h", "liquidity_usd", "market_cap"]:
                if key in event_data and key not in result:
                    result[key] = event_data[key]
            return result

        except asyncio.TimeoutError:
            print(f"⚠️ {self.name}: Simulation timed out")
            return {
                "token_address": token_address, "chain": chain, "token_symbol": symbol, "token_name": name,
                "error": "timeout", "message": f"Simulation on {symbol} timed out. Treat with caution.",
                "can_buy": False, "can_sell": False, "honeypot_risk": True,
                "liquidity_usd": 0, "simulation_confidence": 0,
            }
        except Exception as e:
            print(f"❌ {self.name}: Fatal simulation error: {e}")
            return {
                "token_address": token_address, "chain": chain, "token_symbol": symbol, "token_name": name,
                "error": str(e), "message": f"Simulation crashed on {symbol}: {e}",
                "can_buy": False, "can_sell": False, "honeypot_risk": True,
                "liquidity_usd": 0, "simulation_confidence": 0,
            }

    # ═══════════════════════════════════════════════════════════
    # TIER 1: STATIC ANALYSIS
    # ═══════════════════════════════════════════════════════════

    async def _check_honeypot(self, token_address: str, chain: str) -> dict:
        try:
            if chain not in ["bsc", "ethereum", "base"]:
                return {"buyable": True, "sellable": True, "is_honeypot": False, "buyTax": 0, "sellTax": 0}
            await rate_limiter.wait("honeypot.is")
            url = f"{self.honeypot_apis[chain]}?address={token_address}"
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
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
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs", [])
                    if pairs:
                        top_pair = max(pairs, key=lambda x: x.get("liquidity", {}).get("usd", 0) or 0)
                        liquidity = top_pair.get("liquidity", {})
                        liquidity_usd = liquidity.get("usd", 0) or 0
                        return {"liquidity_usd": liquidity_usd, "locked": liquidity_usd > 1000, "dex": top_pair.get("dexId")}
                return {"liquidity_usd": 0, "locked": False}
        except Exception as e:
            print(f"⚠️ {self.name}: Liquidity check failed: {e}")
            return {"liquidity_usd": 0, "locked": False}

    async def _analyze_contract(self, token_address: str, chain: str) -> dict:
        """v4.1 FIX: All sync Web3 calls wrapped in asyncio.to_thread()"""
        try:
            if chain == "solana":
                return {}
            if chain not in ["bsc", "ethereum", "base"]:
                return {}
            rpc_key = "BSC_RPC_URL" if chain == "bsc" else "ETH_RPC_URL" if chain == "ethereum" else "BASE_RPC_URL"
            rpc_url = os.getenv(rpc_key)
            if not rpc_url:
                return {}
            w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))
            dangerous_sigs = {"mint": "0x40c10f19", "blacklist": "0xf9f92be4", "pause": "0x8456cb59"}

            try:
                code = await asyncio.to_thread(
                    lambda: w3.eth.get_code(Web3.to_checksum_address(token_address)).hex()
                )
            except Exception:
                return {}

            owner_renounced = False
            try:
                token_contract = w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=OWNERSHIP_ABI)
                try:
                    owner_addr = await asyncio.to_thread(token_contract.functions.owner().call)
                    owner_renounced = owner_addr == "0x0000000000000000000000000000000000000000"
                except Exception:
                    try:
                        owner_addr = await asyncio.to_thread(token_contract.functions.getOwner().call)
                        owner_renounced = owner_addr == "0x0000000000000000000000000000000000000000"
                    except Exception:
                        pass
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
    # TIER 2: eth_call SIMULATION
    # ═══════════════════════════════════════════════════════════

    async def _simulate_eth_call_swap(self, token_address: str, chain: str) -> dict:
        """v4.1 FIX: All sync Web3 RPC calls wrapped in asyncio.to_thread()"""
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
            token = w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=ERC20_ABI)

            # v4.1: Wrap all sync RPC calls
            try:
                decimals = await asyncio.to_thread(token.functions.decimals().call)
            except Exception:
                decimals = 18

            amount_in_eth = 0.001
            amount_in_wei = w3.to_wei(amount_in_eth, 'ether')

            try:
                nonce = await asyncio.to_thread(w3.eth.get_transaction_count, funded_wallet)
            except Exception:
                nonce = 0

            print(f"🔬 {self.name}: eth_call BUY {amount_in_eth} ETH -> {token_address[:8]}...")

            buy_tx = router.functions.swapExactETHForTokens(
                0, [weth, Web3.to_checksum_address(token_address)], funded_wallet, 2**64
            ).build_transaction({
                'from': funded_wallet, 'value': amount_in_wei, 'gas': 300000,
                'gasPrice': await asyncio.to_thread(lambda: w3.eth.gas_price), 'nonce': nonce,
            })

            await asyncio.to_thread(w3.eth.call, buy_tx)
            buy_success = True
            print(f"✅ {self.name}: eth_call BUY succeeded")

            try:
                amounts_out = await asyncio.to_thread(
                    router.functions.getAmountsOut(
                        amount_in_wei, [weth, Web3.to_checksum_address(token_address)]
                    ).call
                )
                expected_tokens = amounts_out[-1] if amounts_out else 0
            except Exception:
                expected_tokens = 0

            print(f"🔬 {self.name}: eth_call APPROVE {expected_tokens} tokens for router...")
            approve_success = False
            if expected_tokens > 0:
                try:
                    approve_tx = token.functions.approve(router_address, expected_tokens).build_transaction({
                        'from': funded_wallet, 'gas': 100000,
                        'gasPrice': await asyncio.to_thread(lambda: w3.eth.gas_price), 'nonce': nonce + 1,
                    })
                    await asyncio.to_thread(w3.eth.call, approve_tx)
                    approve_success = True
                    print(f"✅ {self.name}: eth_call APPROVE succeeded")
                except Exception as e:
                    print(f"⚠️ {self.name}: eth_call APPROVE failed: {e}")

            print(f"🔬 {self.name}: eth_call SELL {expected_tokens} tokens -> ETH...")
            sell_success = False
            eth_returned = 0
            effective_tax = 0.0
            sell_revert_reason = None

            if expected_tokens > 0:
                try:
                    sell_tx = router.functions.swapExactTokensForETH(
                        expected_tokens, 0,
                        [Web3.to_checksum_address(token_address), weth], funded_wallet, 2**64
                    ).build_transaction({
                        'from': funded_wallet, 'gas': 300000,
                        'gasPrice': await asyncio.to_thread(lambda: w3.eth.gas_price), 'nonce': nonce + 2,
                    })
                    await asyncio.to_thread(w3.eth.call, sell_tx)
                    sell_success = True
                    print(f"✅ {self.name}: eth_call SELL succeeded")

                    try:
                        amounts_in = await asyncio.to_thread(
                            router.functions.getAmountsIn(
                                expected_tokens, [weth, Web3.to_checksum_address(token_address)]
                            ).call
                        )
                        eth_returned = amounts_in[0] if amounts_in else 0
                    except Exception:
                        eth_returned = 0

                    if eth_returned > 0 and amount_in_wei > 0:
                        effective_tax = max(0, (1 - (eth_returned / amount_in_wei)) * 100)
                except Exception as e:
                    sell_revert_reason = str(e)
                    print(f"🚨 {self.name}: eth_call SELL failed -- {sell_revert_reason[:100]}")
            else:
                sell_revert_reason = "Zero token output from buy -- likely no liquidity"
                print(f"⚠️ {self.name}: {sell_revert_reason}")

            is_honeypot = False
            if sell_revert_reason:
                error_lower = sell_revert_reason.lower()
                honeypot_indicators = [
                    "transfer failed", "transfer_from_failed", "blacklisted",
                    "uniswapv2: k", "pancake: k", "ds-math-sub-underflow",
                    "insufficient liquidity", "safemath: subtraction overflow"
                ]
                is_honeypot = any(kw in error_lower for kw in honeypot_indicators)

            return {
                "buy_success": buy_success, "sell_success": sell_success,
                "approve_success": approve_success, "expected_tokens": expected_tokens,
                "eth_returned_wei": eth_returned, "effective_tax_percent": round(effective_tax, 2),
                "is_honeypot": is_honeypot, "revert_reason": sell_revert_reason,
                "simulation_method": "eth_call",
            }
        except Exception as e:
            error_msg = str(e)
            print(f"⚠️ {self.name}: eth_call simulation error: {error_msg[:100]}")
            return {
                "buy_success": False, "sell_success": False,
                "expected_tokens": 0, "eth_returned_wei": 0,
                "effective_tax_percent": 0, "is_honeypot": False,
                "revert_reason": error_msg[:200], "simulation_method": "eth_call",
            }

    # ═══════════════════════════════════════════════════════════
    # TIER 3: TENDERLY SIMULATION
    # ═══════════════════════════════════════════════════════════

    async def _simulate_tenderly(self, token_address: str, chain: str) -> dict:
        api_key = os.getenv("TENDERLY_API_KEY")
        account = os.getenv("TENDERLY_ACCOUNT")
        project = os.getenv("TENDERLY_PROJECT")

        if not api_key or not account or not project:
            return {"error": "Tenderly not configured (need API_KEY, ACCOUNT, PROJECT)"}

        chain_id = 56 if chain == "bsc" else 1 if chain == "ethereum" else 8453 if chain == "base" else None
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

            print(f"🔬 {self.name}: Tenderly BUY simulation...")

            buy_swap_data = router.encodeABI(
                fn_name="swapExactETHForTokens",
                args=[0, [weth, Web3.to_checksum_address(token_address)], funded_wallet, 2**64]
            )

            buy_url = f"https://api.tenderly.co/api/v1/account/{account}/project/{project}/simulate"
            buy_body = {
                "network_id": str(chain_id), "from": funded_wallet,
                "to": router_address, "input": buy_swap_data,
                "value": str(amount_in_wei), "save": True, "simulation_type": "full"
            }

            async with self._session.post(
                buy_url, json=buy_body, headers={"X-Access-Key": api_key},
                timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    print(f"⚠️ {self.name}: Tenderly BUY error {resp.status}: {text[:200]}")
                    return {"error": f"Tenderly BUY API error: {resp.status}"}
                result = await resp.json()
                tx = result.get("transaction", {})
                buy_success = tx.get("status") is True
                buy_gas = tx.get("gas_used")
                buy_revert = tx.get("error_message")

                if not buy_success:
                    return {
                        "buy_success": False, "sell_success": False,
                        "gas_used": buy_gas, "revert_reason": buy_revert or "Buy simulation failed",
                        "simulation_method": "tenderly",
                    }

            print(f"🔬 {self.name}: Tenderly SELL simulation...")
            try:
                amounts_out = await asyncio.to_thread(
                    router.functions.getAmountsOut(
                        amount_in_wei, [weth, Web3.to_checksum_address(token_address)]
                    ).call
                )
                expected_tokens = amounts_out[-1] if amounts_out else 0
            except Exception:
                expected_tokens = 0

            if expected_tokens == 0:
                return {
                    "buy_success": True, "sell_success": False,
                    "gas_used": buy_gas, "revert_reason": "Zero token output from buy -- cannot simulate sell",
                    "simulation_method": "tenderly",
                }

            sell_swap_data = router.encodeABI(
                fn_name="swapExactTokensForETH",
                args=[expected_tokens, 0, [Web3.to_checksum_address(token_address), weth], funded_wallet, 2**64]
            )

            sell_body = {
                "network_id": str(chain_id), "from": funded_wallet,
                "to": router_address, "input": sell_swap_data,
                "value": "0", "save": True, "simulation_type": "full"
            }

            async with self._session.post(
                buy_url, json=sell_body, headers={"X-Access-Key": api_key},
                timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    print(f"⚠️ {self.name}: Tenderly SELL error {resp.status}: {text[:200]}")
                    return {
                        "buy_success": True, "sell_success": False,
                        "gas_used": buy_gas, "revert_reason": f"Tenderly SELL API error: {resp.status}",
                        "simulation_method": "tenderly",
                    }
                result = await resp.json()
                tx = result.get("transaction", {})
                sell_success = tx.get("status") is True
                sell_gas = tx.get("gas_used")
                sell_revert = tx.get("error_message")

            return {
                "buy_success": buy_success, "sell_success": sell_success,
                "gas_used": buy_gas or sell_gas, "revert_reason": sell_revert,
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
        tenderly_result: Optional[dict],
        solana_result: Optional[dict] = None,
        solana_contract: Optional[dict] = None
    ) -> SimulationResult:
        can_buy = honeypot_data.get("buyable", True)
        can_sell = honeypot_data.get("sellable", True)
        is_honeypot = honeypot_data.get("is_honeypot", False)
        confidence = self._calculate_confidence(honeypot_data, liquidity_data, contract_data)

        eth_call_buy = False
        eth_call_sell = False
        eth_call_reason = None
        eth_call_tax = 0.0

        if eth_call_result and "error" not in eth_call_result:
            eth_call_buy = eth_call_result.get("buy_success", False)
            eth_call_sell = eth_call_result.get("sell_success", False)
            eth_call_reason = eth_call_result.get("revert_reason")
            eth_call_tax = eth_call_result.get("effective_tax_percent", 0.0)
            if not eth_call_sell:
                can_sell = False
            if eth_call_result.get("is_honeypot", False):
                is_honeypot = True
                confidence = min(confidence + 0.2, 1.0)
            if eth_call_tax > 50:
                is_honeypot = True
                can_sell = False
                confidence = min(confidence + 0.15, 1.0)

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

        solana_buy = False
        solana_sell = False
        solana_tax = 0.0
        solana_reason = None
        solana_mint_auth = None
        solana_freeze_auth = None

        if solana_result and "error" not in solana_result:
            solana_buy = solana_result.get("buy_success", False)
            solana_sell = solana_result.get("sell_success", False)
            solana_tax = solana_result.get("effective_tax_percent", 0.0)
            solana_reason = solana_result.get("revert_reason")
            can_buy = solana_buy
            can_sell = solana_sell
            if solana_result.get("is_honeypot", False):
                is_honeypot = True
                confidence = min(confidence + 0.2, 1.0)
            if solana_tax > 50:
                is_honeypot = True
                can_sell = False
                confidence = min(confidence + 0.15, 1.0)

        if solana_contract:
            solana_mint_auth = solana_contract.get("mint_authority")
            solana_freeze_auth = solana_contract.get("freeze_authority")

        return SimulationResult(
            token_address=token_address, chain=chain,
            can_buy=can_buy, can_sell=can_sell,
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
            details="", timestamp=time.time(),
            eth_call_buy_simulated=eth_call_buy,
            eth_call_sell_simulated=eth_call_sell,
            eth_call_revert_reason=eth_call_reason,
            eth_call_effective_tax_percent=eth_call_tax,
            tenderly_buy_simulated=tenderly_buy,
            tenderly_sell_simulated=tenderly_sell,
            tenderly_gas_used=tenderly_gas,
            tenderly_revert_reason=tenderly_reason,
            solana_buy_simulated=solana_buy,
            solana_sell_simulated=solana_sell,
            solana_revert_reason=solana_reason,
            solana_effective_tax_percent=solana_tax,
            solana_compute_units=solana_result.get("compute_units") if solana_result else None,
            solana_mint_authority=solana_mint_auth,
            solana_freeze_authority=solana_freeze_auth,
        )

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
        if checks == 0:
            return 0.0
        return passed / checks

    async def cleanup(self):
        await self.results_cache.clear_expired()

    async def stop(self):
        """v4.1: Close the shared session."""
        print(f"🛑 {self.name}: Simulator stopped.")
        await self.cleanup()
        if self._session and not self._session.closed:
            await self._session.close()
