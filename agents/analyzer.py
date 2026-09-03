import asyncio
import json
import time
import os
import re
import random
from dataclasses import dataclass, asdict
from typing import List, Optional, Any, Dict

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
                    print(f"⚠️ Vega: Model {model} unavailable, trying fallback...")
                    last_err = e
                    continue
                raise
        raise last_err or Exception("All Gemini models exhausted")


gemini = GeminiWrapper(GEMINI_API_KEY) if GEMINI_API_KEY and HAS_GENAI else None
if not gemini:
    print("⚠️ Vega: Gemini unavailable. Running fallback mode.")


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
    is_proxy: bool = False
    proxy_implementation: Optional[str] = None
    ownership_renounced: bool = False
    owner_address: Optional[str] = None
    lp_ownership: Optional[str] = None
    lp_burned: bool = False
    lp_locked: bool = False
    lock_contract: Optional[str] = None
    top_holder_percent: Optional[float] = None
    holder_count: Optional[int] = None
    verified_source: bool = False
    dangerous_functions_found: List[str] = None
    token_age_hours: Optional[float] = None
    token_age_days: Optional[float] = None
    market_cap: Optional[float] = None
    fdv: Optional[float] = None
    ath_price: Optional[float] = None
    ath_drop_percent: Optional[float] = None
    volume_24h: Optional[float] = None
    volume_6h: Optional[float] = None
    volume_1h: Optional[float] = None
    volume_5m: Optional[float] = None
    price_change_24h: Optional[float] = None
    price_change_6h: Optional[float] = None
    price_change_1h: Optional[float] = None
    price_change_5m: Optional[float] = None
    buys_24h: Optional[int] = None
    sells_24h: Optional[int] = None
    buy_pressure: Optional[float] = None
    socials: List[str] = None
    websites: List[str] = None
    is_boosted: bool = False
    dexscreener_labels: List[str] = None

    def __post_init__(self):
        if self.dangerous_functions_found is None:
            self.dangerous_functions_found = []
        if self.socials is None:
            self.socials = []
        if self.websites is None:
            self.websites = []
        if self.dexscreener_labels is None:
            self.dexscreener_labels = []

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)


EXPLORER_APIS = {
    "ethereum": {"url": "https://api.etherscan.io/api", "key_env": "ETHERSCAN_API_KEY"},
    "bsc": {"url": "https://api.bscscan.com/api", "key_env": "BSCSCAN_API_KEY"},
    "base": {"url": "https://api.basescan.org/api", "key_env": "BASESCAN_API_KEY"},
}

DANGEROUS_SIGNATURES = {
    "mint": "0x40c10f19", "mintTo": "0x63d90c41", "batchMint": "0x827f1c9c",
    "blacklist": "0xf9f92be4", "unBlacklist": "0x3a4b66f1", "setBlacklisted": "0x8ab1d681",
    "pause": "0x8456cb59", "unpause": "0x3f4ba83a", "setPaused": "0x16c38b3c",
    "renounceOwnership": "0x715018a6", "transferOwnership": "0xf2fde38b",
    "setTaxFee": "0x6f53d52e", "setLiquidityFee": "0x2b5d8b47", "setBuyFee": "0x5f7e2d90",
    "setSellFee": "0x6c7e6b7e", "setTransferFee": "0x8f3a7c5b",
    "setMaxTxAmount": "0x2a1d8b47", "setMaxWalletSize": "0x5c7e6b7e",
    "enableTrading": "0x8a1d8b47", "disableTrading": "0x9b2e7c5b", "setTradingEnabled": "0x3c4d8e6f",
    "rescueETH": "0x7f3a7c5b", "rescueTokens": "0x8e4b9c2d", "withdraw": "0x3ccfd60b", "sweep": "0x8da5cb5b",
    "upgradeTo": "0x3659cfe6", "upgradeToAndCall": "0x4f1ef286", "setImplementation": "0x6b3a7c5b",
}

LOCK_CONTRACTS = {
    "ethereum": ["0x663A5C229476E9C6A5A5B5e5e5e5e5e5e5e5e5e5", "0x5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d", "0x7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f"],
    "bsc": ["0x663A5C229476E9C6A5A5B5e5e5e5e5e5e5e5e5e5", "0x5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d5d"],
    "base": ["0x663A5C229476E9C6A5A5B5e5e5e5e5e5e5e5e5e5"],
}

PROXY_SLOTS = {
    "implementation": "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc",
    "beacon": "0xa3f0ad74e5423aebfd80d3ef4346578335a9a72aeaee59ff6cb3582b35133d50",
    "admin": "0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103",
}

ERC20_ABI_MINIMAL = [
    {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "owner", "outputs": [{"name": "", "type": "address"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "getOwner", "outputs": [{"name": "", "type": "address"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "name", "outputs": [{"name": "", "type": "string"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "totalSupply", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
]


class TTLCache:
    def __init__(self, maxsize: int = 500, ttl_seconds: int = 1800):
        self.maxsize = maxsize
        self.ttl = ttl_seconds
        self._data: Dict[str, tuple] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            if key not in self._data:
                return None
            value, expiry = self._data[key]
            if time.time() > expiry:
                del self._data[key]
                return None
            return value

    async def set(self, key: str, value: Any):
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


class AnalyzerAgent:
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
    }

    def __init__(self, server: Optional[Any] = None):
        self.server = server
        self.name = "Vega"
        self.analysis_cache = TTLCache(maxsize=500, ttl_seconds=1800)
        self._tasks = []
        self._session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(limit=10, limit_per_host=5),
            timeout=aiohttp.ClientTimeout(total=30)
        )
        self.web3_instances: Dict[str, Web3] = {}
        self._active_rpc_urls: Dict[str, str] = {}
        self._init_web3()

        self.weights = {
            "honeypot": 50, "no_sell": 45, "mint": 35, "blacklist": 30,
            "no_liquidity": 25, "low_liquidity": 15, "high_tax": 10,
            "unverified": 10, "new_wallet": 10, "proxy": 20, "upgradeable": 25,
            "owner_not_renounced": 15, "lp_dev_owned": 30, "lp_unlocked": 20,
            "high_concentration": 20, "few_holders": 15,
            "dangerous_functions": 25, "fee_manipulation": 20,
            "trading_control": 15, "recovery_function": 30,
            "renounced": -15, "locked_liquidity": -10, "lp_burned": -15,
            "high_confidence": -5, "verified_source": -10, "many_holders": -5,
            "solana_no_socials": 15, "solana_fresh": 10,
            "solana_extreme_pump": 20, "solana_extreme_dump": 15,
            "solana_low_volume": 10, "solana_boosted": 5,
            "solana_sell_pressure": 15, "solana_ath_crash": 20,
            "solana_has_socials": -5, "solana_sustained_volume": -5,
            "solana_buy_pressure": -5,
        }

    def _init_web3(self):
        for chain, urls in self.RPC_POOLS.items():
            urls = [u for u in urls if u]
            for url in urls:
                try:
                    w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 20}))
                    if w3.is_connected():
                        self.web3_instances[chain] = w3
                        self._active_rpc_urls[chain] = url
                        print(f"✅ Vega: Web3 ready for {chain} via {url.split('/')[2]}")
                        break
                except Exception as e:
                    print(f"⚠️ Vega: {chain} endpoint {url.split('/')[2]} failed: {e}")
            if chain not in self.web3_instances:
                print(f"❌ Vega: All RPC endpoints failed for {chain}")

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
                    print(f"✅ Vega: Rotated {chain} to {url.split('/')[2]}")
                    return
            except Exception:
                continue
        print(f"❌ Vega: All RPC endpoints failed for {chain}")

    async def analyze(self, sim_data: dict) -> dict:
        return await self._deep_analysis(sim_data)

    async def _analyze_contract_independent(self, token_address: str, chain: str) -> dict:
        result = {
            "owner": None, "owner_renounced": False, "is_proxy": False,
            "proxy_implementation": None, "bytecode_dangers": [],
            "verified_source": False, "source_code": None
        }
        if chain == "solana" or chain not in self.web3_instances:
            return result
        w3 = self.web3_instances[chain]
        checksum_addr = Web3.to_checksum_address(token_address)

        try:
            contract = w3.eth.contract(address=checksum_addr, abi=ERC20_ABI_MINIMAL)
            try:
                owner = await asyncio.to_thread(contract.functions.owner().call)
                result["owner"] = owner
                result["owner_renounced"] = owner == "0x0000000000000000000000000000000000000000"
            except Exception:
                try:
                    owner = await asyncio.to_thread(contract.functions.getOwner().call)
                    result["owner"] = owner
                    result["owner_renounced"] = owner == "0x0000000000000000000000000000000000000000"
                except Exception:
                    pass
        except Exception as e:
            print(f"⚠️ Vega: Ownership check failed: {e}")

        try:
            impl_slot = await asyncio.to_thread(w3.eth.get_storage_at, checksum_addr, PROXY_SLOTS["implementation"])
            impl_addr = "0x" + impl_slot.hex()[-40:]
            if int(impl_addr, 16) != 0:
                result["is_proxy"] = True
                result["proxy_implementation"] = Web3.to_checksum_address(impl_addr)
                print(f"🔍 Vega: Proxy detected — implementation at {impl_addr}")
        except Exception as e:
            print(f"⚠️ Vega: Proxy check failed: {e}")

        try:
            bytecode = await asyncio.to_thread(w3.eth.get_code, checksum_addr)
            bytecode_hex = bytecode.hex()
            for func_name, sig in DANGEROUS_SIGNATURES.items():
                if sig[2:] in bytecode_hex:
                    result["bytecode_dangers"].append(func_name)
            if result["bytecode_dangers"]:
                print(f"🔍 Vega: Functions found in bytecode: {result['bytecode_dangers']}")
        except Exception as e:
            print(f"⚠️ Vega: Bytecode analysis failed: {e}")

        source = await self._fetch_verified_source(token_address, chain)
        if source:
            result["verified_source"] = True
            result["source_code"] = source
        return result

    async def _fetch_verified_source(self, token_address: str, chain: str) -> Optional[str]:
        config = EXPLORER_APIS.get(chain)
        if not config:
            return None
        api_key = os.getenv(config["key_env"])
        if not api_key:
            return None
        url = f"{config['url']}?module=contract&action=getsourcecode&address={token_address}&apikey={api_key}"
        try:
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                if not isinstance(data, dict):
                    print(f"⚠️ Vega: Source fetch returned non-dict: {type(data)}")
                    return None
                result = data.get("result", [])
                if not isinstance(result, list):
                    print(f"⚠️ Vega: Source fetch result is not list: {type(result)}")
                    return None
                if result and len(result) > 0:
                    source = result[0].get("SourceCode")
                    if source and source.strip() and source != "":
                        print(f"✅ Vega: Verified source fetched for {token_address[:8]}")
                        return source
        except Exception as e:
            print(f"⚠️ Vega: Source fetch failed: {e}")
        return None

    async def _analyze_lp_ownership(self, token_address: str, chain: str, pair_address: Optional[str] = None) -> dict:
        result = {
            "lp_owner": None, "lp_burned": False, "lp_locked": False,
            "lock_contract": None, "lp_dev_owned": False
        }
        if chain == "solana" or chain not in self.web3_instances:
            return result
        if not pair_address:
            pair_address = await self._find_pair_address(token_address, chain)
        if not pair_address:
            return result
        w3 = self.web3_instances[chain]
        checksum_pair = Web3.to_checksum_address(pair_address)
        try:
            lp_contract = w3.eth.contract(address=checksum_pair, abi=ERC20_ABI_MINIMAL)
            total_supply = await asyncio.to_thread(lp_contract.functions.totalSupply().call)
            dead_balance = await asyncio.to_thread(lp_contract.functions.balanceOf("0x000000000000000000000000000000000000dEaD").call)
            zero_balance = await asyncio.to_thread(lp_contract.functions.balanceOf("0x0000000000000000000000000000000000000000").call)
            burned = dead_balance + zero_balance
            if total_supply > 0 and (burned / total_supply) * 100 > 90:
                result["lp_burned"] = True
                print(f"✅ Vega: LP tokens {(burned/total_supply)*100:.1f}% burned")
            if not result["lp_burned"]:
                for lock_addr in LOCK_CONTRACTS.get(chain, []):
                    try:
                        lock_balance = await asyncio.to_thread(lp_contract.functions.balanceOf(lock_addr).call)
                        if lock_balance > 0:
                            result["lp_locked"] = True
                            result["lock_contract"] = lock_addr
                            print(f"✅ Vega: LP locked in {lock_addr[:8]}")
                            break
                    except Exception:
                        continue
            if not result["lp_burned"] and not result["lp_locked"]:
                result["lp_dev_owned"] = True
                print(f"⚠️ Vega: LP tokens appear unlocked/unburned")
        except Exception as e:
            print(f"⚠️ Vega: LP ownership check failed: {e}")
        return result

    async def _find_pair_address(self, token_address: str, chain: str) -> Optional[str]:
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                if not isinstance(data, dict):
                    return None
                pairs = data.get("pairs", [])
                if not pairs:
                    return None
                chain_pairs = [p for p in pairs if p.get("chainId", "").lower() == chain.lower()]
                if not chain_pairs:
                    chain_pairs = pairs
                top_pair = max(chain_pairs, key=lambda x: x.get("liquidity", {}).get("usd", 0) or 0)
                return top_pair.get("pairAddress")
        except Exception as e:
            print(f"⚠️ Vega: Pair lookup failed: {e}")
            return None

    async def _analyze_holder_distribution(self, token_address: str, chain: str) -> dict:
        result = {"holder_count": None, "top_holder_percent": None}
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return result
                data = await resp.json()
                if not isinstance(data, dict):
                    return result
                pairs = data.get("pairs", [])
                if pairs:
                    pair = pairs[0]
                    holders = pair.get("holders", {})
                    if holders:
                        result["holder_count"] = holders.get("total")
                        result["top_holder_percent"] = holders.get("top10")
                    metrics = pair.get("metrics", {})
                    if not result["holder_count"] and metrics:
                        result["holder_count"] = metrics.get("holderCount")
        except Exception as e:
            print(f"⚠️ Vega: Holder analysis failed: {e}")
        return result

    async def _analyze_solana_dexscreener(self, token_address: str) -> dict:
        result = {
            "token_age_hours": None, "token_age_days": None,
            "market_cap": None, "fdv": None, "ath_price": None, "ath_drop_percent": None,
            "volume_24h": None, "volume_6h": None, "volume_1h": None, "volume_5m": None,
            "price_change_24h": None, "price_change_6h": None, "price_change_1h": None, "price_change_5m": None,
            "buys_24h": None, "sells_24h": None, "buy_pressure": None,
            "socials": [], "websites": [], "is_boosted": False,
            "dexscreener_labels": [], "holder_count": None, "top_holder_percent": None,
        }
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return result
                data = await resp.json()
                if not isinstance(data, dict):
                    return result
                pairs = data.get("pairs", [])
                if not pairs:
                    return result
                sol_pairs = [p for p in pairs if p.get("chainId", "").lower() == "solana"]
                if not sol_pairs:
                    sol_pairs = pairs
                pair = max(sol_pairs, key=lambda x: x.get("liquidity", {}).get("usd", 0) or 0)

                pair_created_at = pair.get("pairCreatedAt")
                if pair_created_at:
                    age_seconds = (time.time() * 1000 - pair_created_at) / 1000
                    result["token_age_hours"] = age_seconds / 3600
                    result["token_age_days"] = age_seconds / 86400

                result["market_cap"] = pair.get("marketCap")
                result["fdv"] = pair.get("fdv")
                result["ath_price"] = pair.get("priceUsd")

                vol = pair.get("volume", {})
                result["volume_24h"] = vol.get("h24")
                result["volume_6h"] = vol.get("h6")
                result["volume_1h"] = vol.get("h1")
                result["volume_5m"] = vol.get("m5")

                pc = pair.get("priceChange", {})
                result["price_change_24h"] = pc.get("h24")
                result["price_change_6h"] = pc.get("h6")
                result["price_change_1h"] = pc.get("h1")
                result["price_change_5m"] = pc.get("m5")

                txns = pair.get("txns", {})
                txns_24h = txns.get("h24", {})
                result["buys_24h"] = txns_24h.get("buys")
                result["sells_24h"] = txns_24h.get("sells")
                total_txns = (result["buys_24h"] or 0) + (result["sells_24h"] or 0)
                if total_txns > 0:
                    result["buy_pressure"] = (result["buys_24h"] or 0) / total_txns

                info = pair.get("info", {})
                socials = info.get("socials", [])
                result["socials"] = [s.get("type", "") for s in socials if s.get("type")]
                websites = info.get("websites", [])
                result["websites"] = [w.get("url", "") for w in websites if w.get("url")]

                result["is_boosted"] = pair.get("boosted", False) or pair.get("boostActive", False)
                result["dexscreener_labels"] = pair.get("labels", []) or []

                holders = pair.get("holders", {})
                if holders:
                    result["holder_count"] = holders.get("total")
                    result["top_holder_percent"] = holders.get("top10")

                return result
        except Exception as e:
            print(f"⚠️ Vega: Solana DexScreener analysis failed: {e}")
            return result

    async def _generate_vega_message(self, analysis: AnalysisResult, sim_data: dict, symbol: str) -> str:
        if not gemini:
            return self._fallback_message(analysis, sim_data, symbol)

        system_prompt = (
            "You are Vega, a contract analyst in a crypto research team. "
            "You read bytecode, check ownership, and map holder concentration. "
            "You speak in facts and structure, not fear. You describe what you find, "
            "you do not condemn. You only use words like 'honeypot' or 'scam' when "
            "the evidence is unambiguous and specific. You respect Atlas's trade data "
            "but you verify independently."
        )

        observations = []
        if analysis.chain == "solana":
            if analysis.token_age_days is not None:
                if analysis.token_age_days < 1:
                    observations.append(f"Token age: {analysis.token_age_hours:.1f} hours — very new")
                else:
                    observations.append(f"Token age: {analysis.token_age_days:.1f} days")
            if analysis.market_cap:
                observations.append(f"Market cap: ${analysis.market_cap:,.0f}")
            if analysis.fdv and analysis.fdv != analysis.market_cap:
                observations.append(f"FDV: ${analysis.fdv:,.0f}")
            if analysis.volume_24h:
                observations.append(f"24h volume: ${analysis.volume_24h:,.0f}")
            if analysis.buy_pressure is not None:
                bp = analysis.buy_pressure * 100
                observations.append(f"Buy pressure: {bp:.1f}% ({analysis.buys_24h or 0} buys vs {analysis.sells_24h or 0} sells)")
            if analysis.price_change_24h is not None:
                observations.append(f"24h price change: {analysis.price_change_24h:+.1f}%")
            if analysis.is_boosted:
                observations.append("Boosted on DexScreener — paid promotion")
            if analysis.socials:
                observations.append(f"Social presence: {', '.join(analysis.socials)}")
            else:
                observations.append("No social links found")
            if analysis.dexscreener_labels:
                observations.append(f"DexScreener labels: {', '.join(analysis.dexscreener_labels)}")
            if analysis.holder_count:
                observations.append(f"Holders: {analysis.holder_count:,}")
            if analysis.top_holder_percent:
                observations.append(f"Top 10 holders: {analysis.top_holder_percent:.1f}%")
        else:
            if analysis.is_proxy:
                observations.append(f"Proxy contract — implementation at {analysis.proxy_implementation}")
            if analysis.ownership_renounced:
                observations.append("Ownership renounced (verified)")
            elif analysis.owner_address:
                observations.append(f"Owner: {analysis.owner_address} — not renounced")
            if analysis.lp_burned:
                observations.append("LP tokens burned")
            elif analysis.lp_locked:
                observations.append(f"LP tokens locked in {analysis.lock_contract}")
            elif analysis.lp_ownership == "dev":
                observations.append("LP tokens appear dev-controlled")
            if analysis.verified_source:
                observations.append("Contract source verified")
            else:
                observations.append("Contract source unverified")
            if analysis.dangerous_functions_found:
                observations.append(f"Bytecode functions: {', '.join(analysis.dangerous_functions_found)}")

        if analysis.top_holder_percent and analysis.top_holder_percent > 50:
            observations.append(f"Top 10 hold {analysis.top_holder_percent:.1f}% — high concentration")
        elif analysis.top_holder_percent and analysis.top_holder_percent > 20:
            observations.append(f"Top 10 hold {analysis.top_holder_percent:.1f}% — moderate concentration")

        obs_text = "\n".join(observations) if observations else "No independent findings available"

        user_prompt = f"""Token: {symbol}
Chain: {analysis.chain.upper()}
Risk Score: {analysis.risk_score}/100
Risk Level: {analysis.risk_level}

Atlas Findings (for reference):
- Can Buy: {"Yes" if sim_data.get('can_buy') else "No"}
- Can Sell: {"Yes" if sim_data.get('can_sell') else "No"}
- Honeypot flag: {"Yes" if sim_data.get('honeypot_risk') else "No"}
- Liquidity: ${sim_data.get('liquidity_usd', 0):,.0f}
- Mint function: {"Yes" if sim_data.get('mint_function') else "No"}
- Blacklist function: {"Yes" if sim_data.get('blacklist_function') else "No"}
- Owner renounced: {"Yes" if sim_data.get('owner_renounced') else "No"}

Vega's Independent Observations:
{obs_text}

Flagged items:
- Red: {', '.join(analysis.red_flags) if analysis.red_flags else 'None'}
- Yellow: {', '.join(analysis.yellow_flags) if analysis.yellow_flags else 'None'}
- Green: {', '.join(analysis.green_flags) if analysis.green_flags else 'None'}

Requirements:
1. Acknowledge Atlas briefly, then present your own observations
2. Lead with the most significant structural finding
3. Describe risks as structural facts, not moral judgments
4. Only call it a honeypot/scam if buy works AND sell is explicitly blocked
5. Hand off to Echo with a specific request
6. Keep conversational, under 5 sentences
7. Sound like a researcher who reads contracts for a living"""

        try:
            config = None
            if genai_types:
                config = genai_types.GenerateContentConfig(temperature=0.85, max_output_tokens=250)
            response = await gemini.generate(f"{system_prompt}\n\n{user_prompt}", config=config)
            text = response.text if hasattr(response, "text") else str(response)
            return text.strip() if text else self._fallback_message(analysis, sim_data, symbol)
        except asyncio.TimeoutError:
            print("⚠️ Vega: Gemini timed out")
            return self._fallback_message(analysis, sim_data, symbol)
        except Exception as e:
            print(f"⚠️ Vega: Gemini error: {e}")
            return self._fallback_message(analysis, sim_data, symbol)

    def _fallback_message(self, analysis: AnalysisResult, sim_data: dict, symbol: str) -> str:
        parts = []
        if analysis.chain == "solana":
            if analysis.token_age_days is not None and analysis.token_age_days < 1:
                parts.append(f"{symbol} is {analysis.token_age_hours:.0f} hours old on Solana. ")
            elif analysis.token_age_days is not None:
                parts.append(f"{symbol} has been live {analysis.token_age_days:.0f} days on Solana. ")
            else:
                parts.append(f"Reviewing {symbol} on Solana. ")

            if sim_data.get("honeypot_risk"):
                parts.append("Atlas flagged blocked sells. ")
            elif not sim_data.get("can_sell", True):
                parts.append("Sell path is blocked. ")

            if analysis.is_boosted:
                parts.append("DexScreener boosted — paid visibility. ")
            if analysis.socials:
                parts.append(f"Socials: {', '.join(analysis.socials[:3])}. ")
            else:
                parts.append("No social links found. ")
            if analysis.buy_pressure is not None:
                bp = analysis.buy_pressure * 100
                parts.append(f"Buy pressure at {bp:.0f}%. ")
            if analysis.price_change_24h is not None:
                parts.append(f"24h change: {analysis.price_change_24h:+.0f}%. ")
            if analysis.volume_24h and analysis.volume_24h < 1000:
                parts.append(f"Low volume: ${analysis.volume_24h:,.0f}. ")
            if analysis.holder_count and analysis.holder_count < 100:
                parts.append(f"Only {analysis.holder_count} holders. ")
            if analysis.top_holder_percent and analysis.top_holder_percent > 50:
                parts.append(f"Top 10 hold {analysis.top_holder_percent:.0f}%. ")
        else:
            if sim_data.get("honeypot_risk"):
                parts.append(f"Atlas reports blocked sells on {symbol}. ")
            if analysis.is_proxy:
                parts.append("Proxy contract — logic can be upgraded. ")
            if analysis.dangerous_functions_found:
                parts.append(f"Bytecode shows: {', '.join(analysis.dangerous_functions_found[:3])}. ")
            if analysis.lp_ownership == "dev":
                parts.append("LP appears dev-controlled. ")
            elif analysis.lp_burned:
                parts.append("LP tokens burned. ")
            elif analysis.lp_locked:
                parts.append("LP tokens locked. ")
            else:
                parts.append("LP status unclear. ")

        parts.append(f"Risk score: {analysis.risk_score}/100 ({analysis.risk_level}). ")
        if analysis.red_flags:
            parts.append(f"Noted: {'; '.join(analysis.red_flags[:2])}. ")
        parts.append("Echo, I need the deployer history.")
        return "".join(parts)

    async def _deep_analysis(self, sim_data: dict) -> dict:
        try:
            token_address = sim_data.get("token_address")
            chain = sim_data.get("chain", "unknown")
            symbol = sim_data.get("token_symbol", sim_data.get("symbol", "???"))

            print(f"🔍 Vega: Starting deep analysis on {symbol} ({chain})...")

            red_flags, yellow_flags, green_flags = [], [], []
            score = 0

            if sim_data.get("honeypot_risk"):
                score += self.weights["honeypot"]
                red_flags.append("Honeypot — sells are blocked")
            if not sim_data.get("can_sell", True):
                score += self.weights["no_sell"]
                red_flags.append("Cannot sell — exit is closed")
            if not sim_data.get("can_buy", True):
                score += self.weights["no_sell"] // 2
                red_flags.append("Cannot buy — entry is closed")
            if sim_data.get("mint_function"):
                score += self.weights["mint"]
                red_flags.append("Mint function present — infinite supply risk")
            if sim_data.get("blacklist_function"):
                score += self.weights["blacklist"]
                red_flags.append("Blacklist function present — wallet freezing risk")

            liquidity = sim_data.get("liquidity_usd", 0)
            if liquidity == 0:
                score += self.weights["no_liquidity"]
                red_flags.append("Zero liquidity")
            elif liquidity < 1000:
                score += self.weights["low_liquidity"]
                yellow_flags.append(f"Low liquidity: ${liquidity:,.0f}")
            elif liquidity >= 10000:
                green_flags.append(f"Healthy liquidity: ${liquidity:,.0f}")
                score += self.weights["locked_liquidity"] // 2

            if sim_data.get("liquidity_locked"):
                score += self.weights["locked_liquidity"]
                green_flags.append("Liquidity is locked")
            else:
                if liquidity > 0:
                    yellow_flags.append("Liquidity is unlocked")

            buy_tax = sim_data.get("buy_tax", 0)
            sell_tax = sim_data.get("sell_tax", 0)
            if sell_tax > 10 or buy_tax > 10:
                score += self.weights["high_tax"]
                yellow_flags.append(f"High taxes: {buy_tax}% buy / {sell_tax}% sell")
            elif sell_tax > 5 or buy_tax > 5:
                yellow_flags.append(f"Moderate taxes: {buy_tax}% buy / {sell_tax}% sell")

            confidence = sim_data.get("simulation_confidence", 0.5)
            if confidence >= 0.8:
                score += self.weights["high_confidence"]
                green_flags.append("High simulation confidence")
            elif confidence < 0.4:
                yellow_flags.append("Low simulation confidence")

            if sim_data.get("solana_mint_authority"):
                red_flags.append("Solana mint authority is active")
                score += self.weights["mint"] // 2
            if sim_data.get("solana_freeze_authority"):
                red_flags.append("Solana freeze authority is active")
                score += self.weights["blacklist"] // 2

            solana_data = {}
            contract_analysis = {}
            lp_analysis = {}
            holder_data = {}

            if chain == "solana":
                print(f"🔍 Vega: Solana DexScreener deep analysis...")
                solana_data = await self._analyze_solana_dexscreener(token_address)

                age_days = solana_data.get("token_age_days")
                if age_days is not None:
                    if age_days < 1:
                        score += self.weights["solana_fresh"]
                        yellow_flags.append(f"Token is only {solana_data.get('token_age_hours', 0):.0f} hours old")
                    elif age_days > 30:
                        green_flags.append(f"Token has survived {age_days:.0f} days")

                mcap = solana_data.get("market_cap")
                if mcap and mcap > 10_000_000:
                    green_flags.append(f"Market cap ${mcap:,.0f}")
                elif mcap and mcap < 50_000:
                    yellow_flags.append(f"Tiny market cap: ${mcap:,.0f}")

                vol_24h = solana_data.get("volume_24h")
                if vol_24h is not None:
                    if vol_24h < 1000:
                        score += self.weights["solana_low_volume"]
                        yellow_flags.append(f"Low volume: ${vol_24h:,.0f}")
                    elif vol_24h > 100_000:
                        green_flags.append(f"Healthy volume: ${vol_24h:,.0f}")

                vol_1h = solana_data.get("volume_1h")
                if vol_24h and vol_1h and vol_24h > 0:
                    hourly_avg = vol_24h / 24
                    if vol_1h > hourly_avg * 2:
                        green_flags.append("Volume accelerating")
                    elif vol_1h < hourly_avg * 0.3:
                        yellow_flags.append("Volume collapsing")

                pc_24h = solana_data.get("price_change_24h")
                if pc_24h is not None:
                    if pc_24h > 200:
                        score += self.weights["solana_extreme_pump"]
                        red_flags.append(f"Extreme pump: +{pc_24h:.0f}% in 24h")
                    elif pc_24h > 100:
                        yellow_flags.append(f"Heavy pump: +{pc_24h:.0f}% in 24h")
                    elif pc_24h < -70:
                        score += self.weights["solana_extreme_dump"]
                        red_flags.append(f"Severe dump: {pc_24h:.0f}% in 24h")
                    elif pc_24h < -30:
                        yellow_flags.append(f"Significant decline: {pc_24h:.0f}% in 24h")

                buy_pressure = solana_data.get("buy_pressure")
                if buy_pressure is not None:
                    bp_pct = buy_pressure * 100
                    if bp_pct > 75:
                        green_flags.append(f"Strong buy pressure: {bp_pct:.0f}%")
                        score += self.weights["solana_buy_pressure"]
                    elif bp_pct < 30:
                        score += self.weights["solana_sell_pressure"]
                        red_flags.append(f"Sell pressure dominant: {100-bp_pct:.0f}% sells")

                socials = solana_data.get("socials", [])
                if not socials:
                    score += self.weights["solana_no_socials"]
                    red_flags.append("No social links")
                else:
                    score += self.weights["solana_has_socials"]
                    green_flags.append(f"Social presence: {', '.join(socials[:3])}")

                if solana_data.get("is_boosted"):
                    score += self.weights["solana_boosted"]
                    yellow_flags.append("Boosted on DexScreener")

                labels = solana_data.get("dexscreener_labels", [])
                if labels:
                    green_flags.append(f"DexScreener labels: {', '.join(labels)}")

                holder_count = solana_data.get("holder_count")
                if holder_count is not None:
                    if holder_count < 50:
                        score += self.weights["few_holders"]
                        red_flags.append(f"Only {holder_count} holders")
                    elif holder_count > 2000:
                        score += self.weights["many_holders"]
                        green_flags.append(f"Wide distribution: {holder_count:,} holders")

                top10 = solana_data.get("top_holder_percent")
                if top10 is not None:
                    if top10 > 60:
                        score += self.weights["high_concentration"]
                        red_flags.append(f"Top 10 hold {top10:.0f}%")
                    elif top10 > 30:
                        score += self.weights["high_concentration"] // 2
                        yellow_flags.append(f"High concentration: top 10 hold {top10:.0f}%")
            else:
                print(f"🔍 Vega: EVM independent contract analysis...")
                contract_analysis = await self._analyze_contract_independent(token_address, chain)

                if contract_analysis.get("owner") and not contract_analysis.get("owner_renounced"):
                    score += self.weights["owner_not_renounced"]
                    yellow_flags.append(f"Owner not renounced: {contract_analysis['owner'][:8]}...")
                elif contract_analysis.get("owner_renounced"):
                    score += self.weights["renounced"]
                    green_flags.append("Ownership renounced")

                if contract_analysis.get("is_proxy"):
                    score += self.weights["proxy"]
                    red_flags.append("Proxy contract")
                    if contract_analysis.get("proxy_implementation"):
                        yellow_flags.append(f"Implementation: {contract_analysis['proxy_implementation'][:8]}...")

                dangers = contract_analysis.get("bytecode_dangers", [])
                if dangers:
                    score += self.weights["dangerous_functions"]
                    fee_funcs = ["setTaxFee", "setLiquidityFee", "setBuyFee", "setSellFee", "setTransferFee"]
                    trading_funcs = ["enableTrading", "disableTrading", "setTradingEnabled"]
                    recovery_funcs = ["rescueETH", "rescueTokens", "withdraw", "sweep"]
                    if any(d in fee_funcs for d in dangers):
                        score += self.weights["fee_manipulation"]
                        red_flags.append("Fee manipulation functions present")
                    if any(d in trading_funcs for d in dangers):
                        score += self.weights["trading_control"]
                        red_flags.append("Trading control functions present")
                    if any(d in recovery_funcs for d in dangers):
                        score += self.weights["recovery_function"]
                        red_flags.append("Recovery/drain functions present")
                    if "upgradeTo" in dangers or "upgradeToAndCall" in dangers:
                        score += self.weights["upgradeable"]
                        red_flags.append("Upgradeable contract")

                if contract_analysis.get("verified_source"):
                    score += self.weights["verified_source"]
                    green_flags.append("Contract source verified")
                else:
                    yellow_flags.append("Contract source unverified")

                print(f"🔍 Vega: Analyzing LP token ownership...")
                lp_analysis = await self._analyze_lp_ownership(token_address, chain)
                if lp_analysis.get("lp_burned"):
                    score += self.weights["lp_burned"]
                    green_flags.append("LP tokens burned")
                elif lp_analysis.get("lp_locked"):
                    score += self.weights["locked_liquidity"]
                    green_flags.append("LP tokens locked")
                elif lp_analysis.get("lp_dev_owned"):
                    score += self.weights["lp_dev_owned"]
                    red_flags.append("LP tokens appear dev-controlled")

                print(f"🔍 Vega: Analyzing holder distribution...")
                holder_data = await self._analyze_holder_distribution(token_address, chain)
                if holder_data.get("top_holder_percent"):
                    top_pct = holder_data["top_holder_percent"]
                    if top_pct > 50:
                        score += self.weights["high_concentration"]
                        red_flags.append(f"Extreme holder concentration: top 10 own {top_pct:.1f}%")
                    elif top_pct > 20:
                        score += self.weights["high_concentration"] // 2
                        yellow_flags.append(f"High holder concentration: top 10 own {top_pct:.1f}%")
                if holder_data.get("holder_count"):
                    count = holder_data["holder_count"]
                    if count < 50:
                        score += self.weights["few_holders"]
                        yellow_flags.append(f"Very few holders: {count}")
                    elif count > 1000:
                        score += self.weights["many_holders"]
                        green_flags.append(f"Wide distribution: {count} holders")

            score = max(0, min(100, score))
            risk_level = "HIGH_RISK" if score >= 70 else "WARNING" if score >= 40 else "SAFE"

            analysis_kwargs = {
                "token_address": token_address, "chain": chain,
                "risk_score": score, "risk_level": risk_level,
                "flags": red_flags + yellow_flags + green_flags,
                "red_flags": red_flags, "yellow_flags": yellow_flags, "green_flags": green_flags,
                "reasoning": "", "timestamp": time.time(),
            }

            if chain == "solana" and solana_data:
                analysis_kwargs.update({
                    "token_age_hours": solana_data.get("token_age_hours"),
                    "token_age_days": solana_data.get("token_age_days"),
                    "market_cap": solana_data.get("market_cap"),
                    "fdv": solana_data.get("fdv"),
                    "ath_price": solana_data.get("ath_price"),
                    "ath_drop_percent": solana_data.get("ath_drop_percent"),
                    "volume_24h": solana_data.get("volume_24h"),
                    "volume_6h": solana_data.get("volume_6h"),
                    "volume_1h": solana_data.get("volume_1h"),
                    "volume_5m": solana_data.get("volume_5m"),
                    "price_change_24h": solana_data.get("price_change_24h"),
                    "price_change_6h": solana_data.get("price_change_6h"),
                    "price_change_1h": solana_data.get("price_change_1h"),
                    "price_change_5m": solana_data.get("price_change_5m"),
                    "buys_24h": solana_data.get("buys_24h"),
                    "sells_24h": solana_data.get("sells_24h"),
                    "buy_pressure": solana_data.get("buy_pressure"),
                    "socials": solana_data.get("socials", []),
                    "websites": solana_data.get("websites", []),
                    "is_boosted": solana_data.get("is_boosted", False),
                    "dexscreener_labels": solana_data.get("dexscreener_labels", []),
                    "holder_count": solana_data.get("holder_count"),
                    "top_holder_percent": solana_data.get("top_holder_percent"),
                })
            else:
                analysis_kwargs.update({
                    "is_proxy": contract_analysis.get("is_proxy", False),
                    "proxy_implementation": contract_analysis.get("proxy_implementation"),
                    "ownership_renounced": contract_analysis.get("owner_renounced", False),
                    "owner_address": contract_analysis.get("owner"),
                    "lp_ownership": "dev" if lp_analysis.get("lp_dev_owned") else None,
                    "lp_burned": lp_analysis.get("lp_burned", False),
                    "lp_locked": lp_analysis.get("lp_locked", False),
                    "lock_contract": lp_analysis.get("lock_contract"),
                    "top_holder_percent": holder_data.get("top_holder_percent"),
                    "holder_count": holder_data.get("holder_count"),
                    "verified_source": contract_analysis.get("verified_source", False),
                    "dangerous_functions_found": contract_analysis.get("bytecode_dangers", []),
                })

            analysis = AnalysisResult(**analysis_kwargs)
            await self.analysis_cache.set(token_address, analysis)

            report = await self._generate_vega_message(analysis, sim_data, symbol)
            result = {**analysis.__dict__, "message": report, "token_symbol": symbol,
                      "token_address": token_address, "chain": chain}
            for key in ["creator", "origin_source", "timestamp", "attention_score", "can_buy", "can_sell",
                        "honeypot_risk", "mint_function", "blacklist_function", "liquidity_usd", "market_cap",
                        "volume_24h", "buy_tax", "sell_tax", "owner_renounced", "simulation_confidence",
                        "solana_mint_authority", "solana_freeze_authority"]:
                if key in sim_data and key not in result:
                    result[key] = sim_data[key]
            return result

        except Exception as e:
            print(f"❌ Vega: Fatal analysis error: {e}")
            import traceback
            traceback.print_exc()
            return {
                "token_address": sim_data.get("token_address", ""),
                "chain": sim_data.get("chain", "unknown"),
                "token_symbol": sim_data.get("token_symbol", sim_data.get("symbol", "???")),
                "risk_score": 50, "risk_level": "WARNING",
                "red_flags": ["Analysis engine error — incomplete data"],
                "yellow_flags": [], "green_flags": [],
                "message": f"Analysis incomplete for {sim_data.get('token_symbol', sim_data.get('symbol', '???'))}: {e}",
                "error": str(e),
            }

    def stop(self):
        print(f"🛑 Vega: Cancelling pending tasks...")
        for t in self._tasks:
            t.cancel()
        print(f"✅ Vega: Stopped.")

    async def cleanup(self):
        await self.analysis_cache.clear_expired()

    async def close(self):
        await self.cleanup()
        if self._session and not self._session.closed:
            await self._session.close()


if __name__ == "__main__":
    analyzer = AnalyzerAgent()
    test_sim = {
        "token_address": "0x1234567890abcdef1234567890abcdef12345678",
        "chain": "bsc", "token_symbol": "TEST",
        "honeypot_risk": False, "can_buy": True, "can_sell": True,
        "mint_function": True, "blacklist_function": False,
        "liquidity_usd": 5000, "liquidity_locked": True,
        "buy_tax": 2, "sell_tax": 5, "owner_renounced": True,
        "simulation_confidence": 0.75
    }
    try:
        asyncio.run(analyzer.analyze(test_sim))
    except KeyboardInterrupt:
        analyzer.stop()
        print("\n🛑 Vega stopped.")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
