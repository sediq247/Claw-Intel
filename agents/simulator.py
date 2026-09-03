"""
"The Trader" — Tests trade paths, measures slippage and taxes, 
reports what the chain actually allows. Speaks in observations, not verdicts.
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

import aiohttp
from web3 import Web3
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
                    print(f"⚠️ Atlas: Model {model} unavailable, trying fallback...")
                    last_err = e
                    continue
                raise
        raise last_err or Exception("All Gemini models exhausted")


gemini = GeminiWrapper(GEMINI_API_KEY) if GEMINI_API_KEY and HAS_GENAI else None
if not gemini:
    print("⚠️ Atlas: Gemini unavailable. Running fallback mode.")


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
    eth_call_buy_simulated: bool = False
    eth_call_sell_simulated: bool = False
    eth_call_revert_reason: Optional[str] = None
    eth_call_effective_tax_percent: float = 0.0
    tenderly_buy_simulated: bool = False
    tenderly_sell_simulated: bool = False
    tenderly_gas_used: Optional[int] = None
    tenderly_revert_reason: Optional[str] = None
    solana_buy_simulated: bool = False
    solana_sell_simulated: bool = False
    solana_revert_reason: Optional[str] = None
    solana_effective_tax_percent: float = 0.0
    solana_compute_units: Optional[int] = None
    solana_mint_authority: Optional[str] = None
    solana_freeze_authority: Optional[str] = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)


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
            "inputs": [
                {"internalType": "uint256", "name": "amountOut", "type": "uint256"},
                {"internalType": "address[]", "name": "path", "type": "address[]"}
            ],
            "name": "getAmountsIn",
            "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
            "stateMutability": "view",
            "type": "function"
        },
        {
            "inputs": [
                {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                {"internalType": "address[]", "name": "path", "type": "address[]"}
            ],
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
        "uniswap_v2": "0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24",
        "uniswap_v3": "0x2626664c2603336E57B271c5C0b26F421741e481",
    }
}

WETH_ADDRESSES = {
    "bsc": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
    "ethereum": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    "base": "0x4200000000000000000000000000000000000006",
}

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


class RateLimiter:
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
    def __init__(self, maxsize: int = 500, ttl_seconds: int = 1800):
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
    chain = chain.lower().strip()
    supported = {"bsc", "ethereum", "base", "solana"}
    if chain not in supported:
        raise ValueError(f"Unsupported chain: {chain}. Supported: {supported}")
    return chain


class SolanaSimulator:
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
        try:
            session = await self._get_session()
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
            sell_quote = await self._get_jupiter_quote(
                session, token_mint, self.WSOL, expected_tokens, slippage_bps=500
            )
            if not sell_quote:
                return {
                    "buy_success": True, "sell_success": False,
                    "expected_tokens": expected_tokens,
                    "revert_reason": "Jupiter: No route found for sell",
                    "simulation_method": "jupiter_rpc"
                }
            sell_sim = await self._simulate_jupiter_swap(session, sell_quote)
            sol_returned = int(sell_quote.get("outAmount", 0))
            effective_tax = 0.0
            if sol_returned > 0 and sol_amount > 0:
                effective_tax = max(0, (1 - (sol_returned / (sol_amount * 1e9))) * 100)
            return {
                "buy_success": True,
                "sell_success": sell_sim.get("success", False),
                "expected_tokens": expected_tokens,
                "sol_returned_lamports": sol_returned,
                "effective_tax_percent": round(effective_tax, 2),
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

    async def _get_jupiter_quote(self, session, input_mint, output_mint, amount, slippage_bps=50):
        url = f"{self.JUPITER_QUOTE}/quote?inputMint={input_mint}&outputMint={output_mint}&amount={amount}&slippageBps={slippage_bps}&onlyDirectRoutes=false"
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

    async def _simulate_jupiter_swap(self, session, quote_data):
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
                return {"mint_authority": mint_authority, "freeze_authority": freeze_authority}
        except Exception as e:
            print(f"⚠️ Solana mint analysis error: {e}")
            return {}

    async def cleanup(self):
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()


class SimulatorAgent:
    RPC_POOLS = {
        "ethereum": [
            os.getenv("ETH_RPC_URL", ""),
            "https://eth.llamarpc.com",
            "https://rpc.ankr.com/eth",
            "https://ethereum-rpc.publicnode.com",
        ],
        "bsc": [
            os.getenv("BSC_RPC_URL", ""),
            "https://bsc-dataseed.binance.org",
            "https://rpc.ankr.com/bsc",
            "https://bsc-rpc.publicnode.com",
        ],
        "base": [
            os.getenv("BASE_RPC_URL", ""),
            "https://mainnet.base.org",
            "https://rpc.ankr.com/base",
            "https://base-rpc.publicnode.com",
        ],
        "solana": [
            os.getenv("SOLANA_RPC_URL", ""),
            "https://api.mainnet-beta.solana.com",
            "https://rpc.ankr.com/solana",
            "https://solana-rpc.publicnode.com",
        ],
    }

    HONEYPOT_APIS = {
        "bsc": "https://api.honeypot.is/v2/IsHoneypot",
        "ethereum": "https://api.honeypot.is/v2/IsHoneypot",
        "base": "https://api.honeypot.is/v2/IsHoneypot",
    }

    def __init__(self, server: Optional[Any] = None):
        self.server = server
        self.name = "Atlas"
        self.results_cache = TTLCache(maxsize=500, ttl_seconds=1800)
        self.web3_instances: Dict[str, Web3] = {}
        self._active_rpc_urls: Dict[str, str] = {}
        self._session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(limit=10, limit_per_host=5, ttl_dns_cache=300, use_dns_cache=True),
            timeout=aiohttp.ClientTimeout(total=30)
        )
        self._init_web3()

    def _init_web3(self):
        for chain, urls in self.RPC_POOLS.items():
            if chain == "solana":
                continue
            urls = [u for u in urls if u]
            for url in urls:
                try:
                    w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 20}))
                    if w3.is_connected():
                        self.web3_instances[chain] = w3
                        self._active_rpc_urls[chain] = url
                        print(f"✅ Atlas: Web3 ready for {chain} via {url.split('/')[2]}")
                        break
                except Exception as e:
                    print(f"⚠️ Atlas: {chain} endpoint {url.split('/')[2]} failed: {e}")
            if chain not in self.web3_instances:
                print(f"❌ Atlas: All RPC endpoints failed for {chain}")

    async def _rotate_rpc(self, chain: str):
        current = self._active_rpc_urls.get(chain)
        urls = [u for u in self.RPC_POOLS.get(chain, []) if u]
        if not urls:
            return
        start = urls.index(current) + 1 if current in urls else 0
        for i in range(len(urls)):
            url = urls[(start + i) % len(urls)]
            try:
                w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 20}))
                if w3.is_connected():
                    self.web3_instances[chain] = w3
                    self._active_rpc_urls[chain] = url
                    print(f"✅ Atlas: Rotated {chain} to {url.split('/')[2]}")
                    return
            except Exception:
                continue
        print(f"❌ Atlas: All RPC endpoints failed for {chain}")

    async def simulate(self, event_data: dict) -> dict:
        return await self._simulate_token(event_data)

    def on_new_token(self, event_data: dict):
        try:
            chain = validate_chain(event_data.get("chain", "unknown"))
            token_address = validate_token_address(event_data.get("token_address", ""), chain)
            event_data["token_address"] = token_address
            event_data["chain"] = chain
            task = asyncio.create_task(asyncio.wait_for(self._simulate_token(event_data), timeout=120))
            task.add_done_callback(self._on_task_done)
        except ValueError as e:
            print(f"❌ Atlas: Invalid input -- {e}")
        except Exception as e:
            print(f"⚠️ Atlas: Failed scheduling simulation: {e}")

    def _on_task_done(self, task: asyncio.Task):
        try:
            task.result()
        except asyncio.TimeoutError:
            print(f"⚠️ Atlas: Simulation task timed out")
        except Exception as e:
            print(f"⚠️ Atlas: Simulation task failed: {e}")

    async def _generate_atlas_message(self, sim: SimulationResult, symbol: str, context: str) -> str:
        if not gemini:
            return self._fallback_message(sim, symbol)

        system_prompt = (
            "You are Atlas, a disciplined on-chain trader in a team chat. "
            "You test trade paths, measure slippage, and report what the chain actually does. "
            "You speak in observations and data, never in accusations. "
            "You do not call tokens scams or honeypots unless the evidence is overwhelming and specific. "
            "You respect the team and hand off cleanly."
        )

        observations = []
        if sim.chain == "solana":
            if sim.solana_buy_simulated:
                observations.append("Jupiter BUY simulation executed successfully.")
            else:
                observations.append("Jupiter BUY simulation failed — no viable route or swap reverted.")
            if sim.solana_sell_simulated:
                observations.append("Jupiter SELL simulation executed successfully.")
            else:
                observations.append("Jupiter SELL simulation failed — possible blocked exit path.")
            if sim.solana_revert_reason:
                observations.append(f"Revert detail: {sim.solana_revert_reason}")
            if sim.solana_effective_tax_percent > 0:
                observations.append(f"Effective tax/slippage: {sim.solana_effective_tax_percent:.2f}%")
            if sim.solana_mint_authority:
                observations.append("Mint authority is active — supply can be inflated.")
            if sim.solana_freeze_authority:
                observations.append("Freeze authority is active — accounts can be frozen.")
        else:
            if sim.eth_call_buy_simulated:
                observations.append("eth_call BUY simulation executed successfully.")
            else:
                observations.append("eth_call BUY simulation failed.")
            if sim.eth_call_sell_simulated:
                observations.append("eth_call SELL simulation executed successfully.")
            else:
                observations.append("eth_call SELL simulation failed.")
            if sim.eth_call_revert_reason:
                observations.append(f"Revert detail: {sim.eth_call_revert_reason}")
            if sim.eth_call_effective_tax_percent > 0:
                observations.append(f"Effective tax/slippage: {sim.eth_call_effective_tax_percent:.2f}%")
            if sim.tenderly_buy_simulated:
                observations.append("Tenderly BUY simulation executed successfully.")
            if sim.tenderly_sell_simulated:
                observations.append("Tenderly SELL simulation executed successfully.")
            if sim.tenderly_gas_used:
                observations.append(f"Tenderly gas used: {sim.tenderly_gas_used}")
            if sim.tenderly_revert_reason:
                observations.append(f"Tenderly revert detail: {sim.tenderly_revert_reason}")

        obs_text = "\n".join(observations) if observations else "No on-chain simulation data available."

        user_prompt = f"""Token: {symbol}
Chain: {sim.chain.upper()}

Market Mechanics:
- Buy path open: {"Yes" if sim.can_buy else "No"}
- Sell path open: {"Yes" if sim.can_sell else "No"}
- Liquidity: ${sim.liquidity_usd:,.0f}
- Liquidity locked: {"Yes" if sim.liquidity_locked else "No"}
- Buy tax: {sim.buy_tax}%
- Sell tax: {sim.sell_tax}%
- Mint function present: {"Yes" if sim.mint_function else "No"}
- Blacklist function present: {"Yes" if sim.blacklist_function else "No"}
- Ownership renounced: {"Yes" if sim.owner_renounced else "No"}

On-Chain Simulation:
{obs_text}

Context:
{context}

Requirements:
1. Acknowledge Nova briefly and naturally
2. Report buy/sell path results as observations, not verdicts
3. Note taxes, slippage, and contract features as structural facts
4. Only use the word "honeypot" if buy works AND sell fails with a specific blocking revert
5. Hand off to Vega for contract-level analysis
6. Keep it under 5 sentences, conversational, evidence-first
7. Sound like a trader who trusts the chain, not the contract"""

        try:
            config = None
            if genai_types:
                config = genai_types.GenerateContentConfig(temperature=0.85, max_output_tokens=250)
            response = await gemini.generate(f"{system_prompt}\n\n{user_prompt}", config=config)
            text = response.text if hasattr(response, "text") else str(response)
            return text.strip() if text else self._fallback_message(sim, symbol)
        except asyncio.TimeoutError:
            print("⚠️ Atlas: Gemini timed out")
            return self._fallback_message(sim, symbol)
        except Exception as e:
            print(f"⚠️ Atlas: Gemini error: {e}")
            return self._fallback_message(sim, symbol)

    def _fallback_message(self, sim: SimulationResult, symbol: str) -> str:
        parts = [f"Ran trade simulation on {symbol}. "]

        if sim.can_buy and sim.can_sell:
            parts.append("Buy and sell paths both executed. ")
        elif sim.can_buy and not sim.can_sell:
            parts.append("Buy path is open, but sell path failed. ")
        elif not sim.can_buy:
            parts.append("Buy path failed — no viable route. ")

        if sim.eth_call_effective_tax_percent > 0 or sim.solana_effective_tax_percent > 0:
            tax = sim.eth_call_effective_tax_percent or sim.solana_effective_tax_percent
            parts.append(f"Effective tax around {tax:.1f}%. ")

        if sim.mint_function:
            parts.append("Contract has mint capability. ")
        if sim.blacklist_function:
            parts.append("Contract has blacklist capability. ")
        if sim.solana_mint_authority:
            parts.append("Mint authority is active on Solana. ")
        if sim.solana_freeze_authority:
            parts.append("Freeze authority is active on Solana. ")

        if sim.liquidity_usd > 0:
            parts.append(f"Liquidity sits at ${sim.liquidity_usd:,.0f}. ")
        else:
            parts.append("Liquidity appears thin. ")

        parts.append("Vega, over to you for the contract read.")
        return "".join(parts)

    async def _simulate_token(self, event_data: dict) -> dict:
        token_address = event_data.get("token_address")
        chain = event_data.get("chain", "unknown")
        symbol = event_data.get("token_symbol", event_data.get("symbol", "???"))
        name = event_data.get("token_name", event_data.get("name", "Unknown"))

        try:
            cached = await self.results_cache.get(token_address)
            if cached:
                print(f"📦 Atlas: Cache hit for {symbol}")
                report = await self._generate_atlas_message(cached, symbol, "Returning cached simulation results.")
                return {**cached.__dict__, "message": report, "token_symbol": symbol, "token_name": name, "token_address": token_address, "chain": chain}

            print(f"🧪 Atlas: Simulating {symbol} ({chain})...")

            print(f"🔍 Atlas: Tier 1 — Static analysis...")
            static_results = await asyncio.gather(
                self._check_honeypot(token_address, chain),
                self._check_liquidity(token_address, chain),
                self._analyze_contract(token_address, chain),
                return_exceptions=True
            )
            honeypot_data = static_results[0] if not isinstance(static_results[0], Exception) else {}
            liquidity_data = static_results[1] if not isinstance(static_results[1], Exception) else {}
            contract_data = static_results[2] if not isinstance(static_results[2], Exception) else {}

            eth_call_result = None
            tenderly_result = None
            solana_result = None
            solana_contract = {}

            if chain == "solana":
                print(f"🔍 Atlas: Tier 2 — Solana Jupiter + RPC simulation...")
                sol_rpc = self._active_rpc_urls.get("solana") or os.getenv("SOLANA_RPC_URL")
                if sol_rpc:
                    sol_sim = SolanaSimulator(sol_rpc, session=self._session)
                    try:
                        if not event_data.get("jupiter_failed"):
                            solana_result = await asyncio.wait_for(
                                sol_sim.simulate_buy_sell(token_address, sol_amount=0.01), timeout=60
                            )
                        else:
                            print(f"⚠️ Atlas: Jupiter failed flag set — skipping Jupiter simulation")
                        solana_contract = await asyncio.wait_for(
                            sol_sim.analyze_mint_account(token_address), timeout=15
                        )
                    except asyncio.TimeoutError:
                        print(f"⚠️ Atlas: Solana simulation timed out")
                    finally:
                        await sol_sim.cleanup()
                else:
                    print(f"⚠️ Atlas: No Solana RPC available")
            else:
                if chain in self.web3_instances and chain in ROUTER_ADDRESSES:
                    print(f"🔍 Atlas: Tier 2 — eth_call simulation...")
                    try:
                        eth_call_result = await asyncio.wait_for(
                            self._simulate_eth_call_swap(token_address, chain), timeout=45
                        )
                    except asyncio.TimeoutError:
                        print(f"⚠️ Atlas: eth_call simulation timed out")
                    except Exception as e:
                        print(f"⚠️ Atlas: eth_call simulation failed: {e}")
                else:
                    print(f"⚠️ Atlas: eth_call not available for {chain}")

                if os.getenv("TENDERLY_API_KEY") and chain in ("bsc", "ethereum", "base"):
                    print(f"🔍 Atlas: Tier 3 — Tenderly simulation...")
                    try:
                        tenderly_result = await asyncio.wait_for(
                            self._simulate_tenderly(token_address, chain), timeout=45
                        )
                    except asyncio.TimeoutError:
                        print(f"⚠️ Atlas: Tenderly simulation timed out")
                    except Exception as e:
                        print(f"⚠️ Atlas: Tenderly simulation failed: {e}")

            simulation = self._build_result(
                token_address, chain, symbol,
                honeypot_data, liquidity_data, contract_data,
                eth_call_result, tenderly_result, solana_result, solana_contract
            )

            await self.results_cache.set(token_address, simulation)

            context = f"Token discovered by Nova on {chain}. Running trade simulation."
            report = await self._generate_atlas_message(simulation, symbol, context)

            result = {**simulation.__dict__, "message": report, "token_symbol": symbol, "token_name": name, "token_address": token_address, "chain": chain}
            for key in ["creator", "origin_source", "timestamp", "attention_score", "volume_24h", "liquidity_usd", "market_cap"]:
                if key in event_data and key not in result:
                    result[key] = event_data[key]
            return result

        except asyncio.TimeoutError:
            print(f"⚠️ Atlas: Simulation timed out")
            return {
                "token_address": token_address, "chain": chain, "token_symbol": symbol, "token_name": name,
                "error": "timeout", "message": f"Simulation on {symbol} timed out. Data is incomplete.",
                "can_buy": False, "can_sell": False, "honeypot_risk": False,
                "liquidity_usd": 0, "simulation_confidence": 0,
            }
        except Exception as e:
            print(f"❌ Atlas: Fatal simulation error: {e}")
            return {
                "token_address": token_address, "chain": chain, "token_symbol": symbol, "token_name": name,
                "error": str(e), "message": f"Simulation crashed on {symbol}: {e}",
                "can_buy": False, "can_sell": False, "honeypot_risk": False,
                "liquidity_usd": 0, "simulation_confidence": 0,
            }

    async def _check_honeypot(self, token_address: str, chain: str) -> dict:
        try:
            if chain not in self.HONEYPOT_APIS:
                return {"buyable": True, "sellable": True, "is_honeypot": False, "buyTax": 0, "sellTax": 0}
            await rate_limiter.wait("honeypot.is")
            url = f"{self.HONEYPOT_APIS[chain]}?address={token_address}"
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
                    print(f"⚠️ Atlas: Honeypot.is rate limited")
                    return {}
                else:
                    text = await resp.text()
                    print(f"⚠️ Atlas: Honeypot.is HTTP {resp.status}: {text[:100]}")
                    return {}
        except Exception as e:
            print(f"⚠️ Atlas: Honeypot check failed: {e}")
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
            print(f"⚠️ Atlas: Liquidity check failed: {e}")
            return {"liquidity_usd": 0, "locked": False}

    async def _analyze_contract(self, token_address: str, chain: str) -> dict:
        try:
            if chain == "solana" or chain not in self.web3_instances:
                return {}
            w3 = self.web3_instances[chain]
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
            print(f"⚠️ Atlas: Contract analysis failed: {e}")
            return {}

    async def _simulate_eth_call_swap(self, token_address: str, chain: str) -> dict:
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

            try:
                decimals = await asyncio.to_thread(token.functions.decimals().call)
            except Exception:
                decimals = 18

            amount_in_eth = 0.001
            amount_in_wei = w3.to_wei(amount_in_eth, "ether")

            try:
                nonce = await asyncio.to_thread(w3.eth.get_transaction_count, funded_wallet)
            except Exception:
                nonce = 0

            print(f"🔬 Atlas: eth_call BUY {amount_in_eth} ETH -> {token_address[:8]}...")

            buy_tx = router.functions.swapExactETHForTokens(
                0, [weth, Web3.to_checksum_address(token_address)], funded_wallet, 2**64
            ).build_transaction({
                "from": funded_wallet, "value": amount_in_wei, "gas": 300000,
                "gasPrice": await asyncio.to_thread(lambda: w3.eth.gas_price), "nonce": nonce,
            })

            await asyncio.to_thread(w3.eth.call, buy_tx)
            buy_success = True
            print(f"✅ Atlas: eth_call BUY succeeded")

            try:
                amounts_out = await asyncio.to_thread(
                    router.functions.getAmountsOut(
                        amount_in_wei, [weth, Web3.to_checksum_address(token_address)]
                    ).call
                )
                expected_tokens = amounts_out[-1] if amounts_out else 0
            except Exception:
                expected_tokens = 0

            print(f"🔬 Atlas: eth_call APPROVE {expected_tokens} tokens for router...")
            approve_success = False
            if expected_tokens > 0:
                try:
                    approve_tx = token.functions.approve(router_address, expected_tokens).build_transaction({
                        "from": funded_wallet, "gas": 100000,
                        "gasPrice": await asyncio.to_thread(lambda: w3.eth.gas_price), "nonce": nonce + 1,
                    })
                    await asyncio.to_thread(w3.eth.call, approve_tx)
                    approve_success = True
                    print(f"✅ Atlas: eth_call APPROVE succeeded")
                except Exception as e:
                    print(f"⚠️ Atlas: eth_call APPROVE failed: {e}")

            print(f"🔬 Atlas: eth_call SELL {expected_tokens} tokens -> ETH...")
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
                        "from": funded_wallet, "gas": 300000,
                        "gasPrice": await asyncio.to_thread(lambda: w3.eth.gas_price), "nonce": nonce + 2,
                    })
                    await asyncio.to_thread(w3.eth.call, sell_tx)
                    sell_success = True
                    print(f"✅ Atlas: eth_call SELL succeeded")

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
                    print(f"🚨 Atlas: eth_call SELL failed -- {sell_revert_reason[:100]}")
            else:
                sell_revert_reason = "Zero token output from buy -- likely no liquidity"
                print(f"⚠️ Atlas: {sell_revert_reason}")

            return {
                "buy_success": buy_success, "sell_success": sell_success,
                "approve_success": approve_success, "expected_tokens": expected_tokens,
                "eth_returned_wei": eth_returned, "effective_tax_percent": round(effective_tax, 2),
                "revert_reason": sell_revert_reason,
                "simulation_method": "eth_call",
            }
        except Exception as e:
            error_msg = str(e)
            print(f"⚠️ Atlas: eth_call simulation error: {error_msg[:100]}")
            return {
                "buy_success": False, "sell_success": False,
                "expected_tokens": 0, "eth_returned_wei": 0,
                "effective_tax_percent": 0, "revert_reason": error_msg[:200],
                "simulation_method": "eth_call",
            }

    async def _simulate_tenderly(self, token_address: str, chain: str) -> dict:
        api_key = os.getenv("TENDERLY_API_KEY")
        account = os.getenv("TENDERLY_ACCOUNT")
        project = os.getenv("TENDERLY_PROJECT")

        if not api_key or not account or not project:
            return {"error": "Tenderly not configured"}

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
            amount_in_wei = w3.to_wei(0.001, "ether")

            print(f"🔬 Atlas: Tenderly BUY simulation...")

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
                    print(f"⚠️ Atlas: Tenderly BUY error {resp.status}: {text[:200]}")
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

            print(f"🔬 Atlas: Tenderly SELL simulation...")
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
                    print(f"⚠️ Atlas: Tenderly SELL error {resp.status}: {text[:200]}")
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
            print(f"⚠️ Atlas: Tenderly simulation failed: {e}")
            return {"error": str(e)}

    def _build_result(
        self, token_address, chain, symbol,
        honeypot_data, liquidity_data, contract_data,
        eth_call_result, tenderly_result, solana_result=None, solana_contract=None
    ) -> SimulationResult:
        can_buy = honeypot_data.get("buyable", True)
        can_sell = honeypot_data.get("sellable", True)
        is_honeypot = False
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
            if not eth_call_sell and eth_call_buy:
                can_sell = False
            if eth_call_result.get("is_honeypot", False):
                is_honeypot = True
                confidence = min(confidence + 0.2, 1.0)

        tenderly_buy = False
        tenderly_sell = False
        tenderly_gas = None
        tenderly_reason = None

        if tenderly_result and "error" not in tenderly_result:
            tenderly_buy = tenderly_result.get("buy_success", False)
            tenderly_sell = tenderly_result.get("sell_success", False)
            tenderly_gas = tenderly_result.get("gas_used")
            tenderly_reason = tenderly_result.get("revert_reason")
            if not tenderly_sell and tenderly_buy:
                can_sell = False

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

    def _calculate_confidence(self, honeypot_data, liquidity_data, contract_data) -> float:
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
        print(f"🛑 Atlas: Simulator stopped.")
        await self.cleanup()
        if self._session and not self._session.closed:
            await self._session.close()
