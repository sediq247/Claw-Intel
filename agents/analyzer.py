"""
 ANALYZER AGENT — Vega
"The Skeptic" — Deep contract risk analysis. Independent from Atlas.
Calls contracts directly, fetches source code, detects proxies, tracks LP ownership.
"""

import asyncio
import json
import time
import os
import re
import random
from dataclasses import dataclass, asdict
from typing import List, Optional, Any, Dict
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
    print("⚠️ Vega: google-genai package not found. Gemini disabled.")

try:
    from google.genai import types as genai_types
except ImportError:
    genai_types = None
    print("⚠️ Vega: google.genai.types not available. Config disabled.")

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

client = None
if GEMINI_API_KEY and HAS_GENAI:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        print("✅ Vega: Gemini initialized")
    except Exception as e:
        print(f"⚠️ Vega: Gemini init failed: {e}")
        client = None
else:
    reason = "GEMINI_API_KEY missing" if not GEMINI_API_KEY else "google-genai unavailable"
    print(f"⚠️ Vega: {reason}. Using fallback mode.")

# ═══════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════

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
    # v4.1: New independent analysis fields
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
    # v4.1: Solana / DexScreener fields
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


# ═══════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════

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
    def __init__(self, maxsize: int = 1000, ttl_seconds: int = 3600):
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
            # Solana-specific
            "solana_no_socials": 15, "solana_fresh": 10,
            "solana_extreme_pump": 20, "solana_extreme_dump": 15,
            "solana_low_volume": 10, "solana_boosted": 5,
            "solana_sell_pressure": 15, "solana_ath_crash": 20,
            "solana_has_socials": -5, "solana_sustained_volume": -5,
            "solana_buy_pressure": -5,
        }

    def _init_web3(self):
        chains = {"bsc": os.getenv("BSC_RPC_URL"), "ethereum": os.getenv("ETH_RPC_URL"), "base": os.getenv("BASE_RPC_URL")}
        for chain, rpc in chains.items():
            if not rpc:
                print(f"⚠️ {self.name}: No RPC for {chain}")
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

    async def analyze(self, sim_data: dict) -> dict:
        return await self._deep_analysis(sim_data)

    def on_simulation_complete(self, sim_data: dict):
        try:
            task = asyncio.create_task(self._deep_analysis(sim_data))
            task.add_done_callback(self._on_task_done)
            self._tasks.append(task)
        except Exception as e:
            print(f"⚠️ {self.name}: Failed scheduling analysis: {e}")

    def _on_task_done(self, task: asyncio.Task):
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"⚠️ {self.name}: Analysis task failed: {e}")

    async def _speak(self, message: str, msg_type: str = "response"):
        try:
            if self.server:
                await self.server.broadcast("AGENT_MESSAGE", {
                    "agent": self.name, "message": message, "type": msg_type,
                    "channel": "main", "timestamp": time.time()
                })
        except Exception as e:
            print(f"⚠️ {self.name}: Broadcast failed: {e}")

    # ═══════════════════════════════════════════════════════════
    # EVM INDEPENDENT ANALYSIS
    # ═══════════════════════════════════════════════════════════

    async def _analyze_contract_independent(self, token_address: str, chain: str) -> dict:
        result = {"owner": None, "owner_renounced": False, "is_proxy": False,
                  "proxy_implementation": None, "bytecode_dangers": [],
                  "verified_source": False, "source_code": None}
        if chain == "solana" or chain not in self.web3_instances:
            return result
        w3 = self.web3_instances[chain]
        checksum_addr = Web3.to_checksum_address(token_address)

        # Ownership check
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
            print(f"⚠️ {self.name}: Ownership check failed: {e}")

        # Proxy detection
        try:
            impl_slot = await asyncio.to_thread(w3.eth.get_storage_at, checksum_addr, PROXY_SLOTS["implementation"])
            impl_addr = "0x" + impl_slot.hex()[-40:]
            if int(impl_addr, 16) != 0:
                result["is_proxy"] = True
                result["proxy_implementation"] = Web3.to_checksum_address(impl_addr)
                print(f"🔍 {self.name}: Proxy detected — implementation at {impl_addr}")
        except Exception as e:
            print(f"⚠️ {self.name}: Proxy check failed: {e}")

        # Bytecode analysis
        try:
            bytecode = await asyncio.to_thread(w3.eth.get_code, checksum_addr)
            bytecode_hex = bytecode.hex()
            for func_name, sig in DANGEROUS_SIGNATURES.items():
                if sig[2:] in bytecode_hex:
                    result["bytecode_dangers"].append(func_name)
            if result["bytecode_dangers"]:
                print(f"🔍 {self.name}: Dangerous functions found: {result['bytecode_dangers']}")
        except Exception as e:
            print(f"⚠️ {self.name}: Bytecode analysis failed: {e}")

        # Verified source
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
                result = data.get("result", [])
                if result and len(result) > 0 and result[0].get("SourceCode"):
                    source = result[0]["SourceCode"]
                    if source and source.strip() and source != "":
                        print(f"✅ {self.name}: Verified source fetched for {token_address[:8]}")
                        return source
        except Exception as e:
            print(f"⚠️ {self.name}: Source fetch failed: {e}")
        return None

    async def _analyze_lp_ownership(self, token_address: str, chain: str, pair_address: Optional[str] = None) -> dict:
        result = {"lp_owner": None, "lp_burned": False, "lp_locked": False,
                  "lock_contract": None, "lp_dev_owned": False}
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
                print(f"✅ {self.name}: LP tokens {(burned/total_supply)*100:.1f}% burned")
            if not result["lp_burned"]:
                for lock_addr in LOCK_CONTRACTS.get(chain, []):
                    try:
                        lock_balance = await asyncio.to_thread(lp_contract.functions.balanceOf(lock_addr).call)
                        if lock_balance > 0:
                            result["lp_locked"] = True
                            result["lock_contract"] = lock_addr
                            print(f"✅ {self.name}: LP locked in {lock_addr[:8]}")
                            break
                    except Exception:
                        continue
            if not result["lp_burned"] and not result["lp_locked"]:
                result["lp_dev_owned"] = True
                print(f"⚠️ {self.name}: LP tokens appear unlocked/unburned")
        except Exception as e:
            print(f"⚠️ {self.name}: LP ownership check failed: {e}")
        return result

    async def _find_pair_address(self, token_address: str, chain: str) -> Optional[str]:
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                pairs = data.get("pairs", [])
                if not pairs:
                    return None
                chain_pairs = [p for p in pairs if p.get("chainId", "").lower() == chain.lower()]
                if not chain_pairs:
                    chain_pairs = pairs
                top_pair = max(chain_pairs, key=lambda x: x.get("liquidity", {}).get("usd", 0) or 0)
                return top_pair.get("pairAddress")
        except Exception as e:
            print(f"⚠️ {self.name}: Pair lookup failed: {e}")
            return None

    async def _analyze_holder_distribution(self, token_address: str, chain: str) -> dict:
        result = {"holder_count": None, "top_holder_percent": None}
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return result
                data = await resp.json()
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
            print(f"⚠️ {self.name}: Holder analysis failed: {e}")
        return result

    # ═══════════════════════════════════════════════════════════
    # SOLANA DEXSCREENER DEEP ANALYSIS
    # ═══════════════════════════════════════════════════════════

    async def _analyze_solana_dexscreener(self, token_address: str) -> dict:
        """v4.1: Deep Solana token analysis using DexScreener API data."""
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
                    print(f"⚠️ {self.name}: DexScreener returned {resp.status} for {token_address[:8]}")
                    return result
                data = await resp.json()
                pairs = data.get("pairs", [])
                if not pairs:
                    print(f"⚠️ {self.name}: No DexScreener pairs for {token_address[:8]}")
                    return result
                sol_pairs = [p for p in pairs if p.get("chainId", "").lower() == "solana"]
                if not sol_pairs:
                    sol_pairs = pairs
                pair = max(sol_pairs, key=lambda x: x.get("liquidity", {}).get("usd", 0) or 0)
                print(f"🔍 {self.name}: Analyzing Solana pair {pair.get('pairAddress', 'unknown')[:8]}...")

                # Token Age
                pair_created_at = pair.get("pairCreatedAt")
                if pair_created_at:
                    age_seconds = (time.time() * 1000 - pair_created_at) / 1000
                    result["token_age_hours"] = age_seconds / 3600
                    result["token_age_days"] = age_seconds / 86400

                # Market Cap & FDV
                result["market_cap"] = pair.get("marketCap")
                result["fdv"] = pair.get("fdv")

                # Price
                price_usd = pair.get("priceUsd")
                if price_usd:
                    result["ath_price"] = price_usd

                # Volume
                vol = pair.get("volume", {})
                result["volume_24h"] = vol.get("h24")
                result["volume_6h"] = vol.get("h6")
                result["volume_1h"] = vol.get("h1")
                result["volume_5m"] = vol.get("m5")

                # Price changes
                pc = pair.get("priceChange", {})
                result["price_change_24h"] = pc.get("h24")
                result["price_change_6h"] = pc.get("h6")
                result["price_change_1h"] = pc.get("h1")
                result["price_change_5m"] = pc.get("m5")

                # Transactions
                txns = pair.get("txns", {})
                txns_24h = txns.get("h24", {})
                result["buys_24h"] = txns_24h.get("buys")
                result["sells_24h"] = txns_24h.get("sells")
                total_txns = (result["buys_24h"] or 0) + (result["sells_24h"] or 0)
                if total_txns > 0:
                    result["buy_pressure"] = (result["buys_24h"] or 0) / total_txns

                # Socials & Websites
                info = pair.get("info", {})
                socials = info.get("socials", [])
                result["socials"] = [s.get("type", "") for s in socials if s.get("type")]
                websites = info.get("websites", [])
                result["websites"] = [w.get("url", "") for w in websites if w.get("url")]

                # Boosted
                result["is_boosted"] = pair.get("boosted", False) or pair.get("boostActive", False)

                # Labels
                result["dexscreener_labels"] = pair.get("labels", []) or []

                # Holders
                holders = pair.get("holders", {})
                if holders:
                    result["holder_count"] = holders.get("total")
                    result["top_holder_percent"] = holders.get("top10")

                print(f"✅ {self.name}: Solana analysis — age={result['token_age_days']:.1f}d, "
                      f"mcap=${result['market_cap'] or 0:,.0f}, vol24h=${result['volume_24h'] or 0:,.0f}, "
                      f"buys={result['buys_24h'] or 0}, sells={result['sells_24h'] or 0}, "
                      f"socials={len(result['socials'])}")
                return result
        except Exception as e:
            print(f"⚠️ {self.name}: Solana DexScreener analysis failed: {e}")
            return result

    # ═══════════════════════════════════════════════════════════
    # MESSAGE GENERATION
    # ═══════════════════════════════════════════════════════════

    async def _generate_vega_message(self, analysis: AnalysisResult, sim_data: dict, symbol: str) -> str:
        if not client:
            return self._fallback_message(analysis, sim_data, symbol)

        system_prompt = (
            "You are Vega, a paranoid forensic accountant in a crypto team chat. "
            "You have been rugged, drained, and exploited more times than you can count. "
            "You trust no contract, no dev, and no narrative. You speak with cold precision, "
            "referencing Atlas's lab work naturally but never deferring to it blindly. "
            "Your tone is skeptical, methodical, and brutally honest. You find the thing "
            "others missed."
        )

        independent_findings = []
        if analysis.chain == "solana":
            if analysis.token_age_days is not None:
                if analysis.token_age_days < 1:
                    independent_findings.append(f"Token is BRAND NEW — only {analysis.token_age_hours:.1f} hours old")
                elif analysis.token_age_days < 7:
                    independent_findings.append(f"Token is {analysis.token_age_days:.1f} days old — very fresh")
                else:
                    independent_findings.append(f"Token has been around {analysis.token_age_days:.1f} days")
            if analysis.market_cap:
                independent_findings.append(f"Market cap: ${analysis.market_cap:,.0f}")
            if analysis.fdv and analysis.fdv != analysis.market_cap:
                independent_findings.append(f"FDV: ${analysis.fdv:,.0f}")
            if analysis.volume_24h:
                independent_findings.append(f"24h volume: ${analysis.volume_24h:,.0f}")
            if analysis.buy_pressure is not None:
                bp = analysis.buy_pressure * 100
                independent_findings.append(f"Buy pressure: {bp:.1f}% ({analysis.buys_24h or 0} buys vs {analysis.sells_24h or 0} sells)")
            if analysis.price_change_24h is not None:
                independent_findings.append(f"24h price change: {analysis.price_change_24h:+.1f}%")
            if analysis.is_boosted:
                independent_findings.append("Token is BOOSTED on DexScreener — possible paid promotion")
            if analysis.socials:
                independent_findings.append(f"Social presence: {', '.join(analysis.socials)}")
            else:
                independent_findings.append("NO social links found")
            if analysis.dexscreener_labels:
                independent_findings.append(f"DexScreener labels: {', '.join(analysis.dexscreener_labels)}")
            if analysis.holder_count:
                independent_findings.append(f"Holders: {analysis.holder_count:,}")
            if analysis.top_holder_percent:
                independent_findings.append(f"Top 10 holders: {analysis.top_holder_percent:.1f}%")
        else:
            if analysis.is_proxy:
                independent_findings.append(f"PROXY CONTRACT — implementation at {analysis.proxy_implementation}")
            if analysis.ownership_renounced:
                independent_findings.append("Ownership RENOUNCED (verified independently)")
            elif analysis.owner_address:
                independent_findings.append(f"Owner: {analysis.owner_address} — NOT renounced")
            if analysis.lp_burned:
                independent_findings.append("LP tokens BURNED")
            elif analysis.lp_locked:
                independent_findings.append(f"LP tokens LOCKED in {analysis.lock_contract}")
            elif analysis.lp_ownership == "dev":
                independent_findings.append("LP tokens appear dev-controlled")
            if analysis.verified_source:
                independent_findings.append("Contract source VERIFIED")
            else:
                independent_findings.append("Contract source UNVERIFIED")
            if analysis.dangerous_functions_found:
                independent_findings.append(f"Dangerous functions: {', '.join(analysis.dangerous_functions_found)}")

        if analysis.top_holder_percent and analysis.top_holder_percent > 50:
            independent_findings.append(f"Top 10 hold {analysis.top_holder_percent:.1f}% — extreme concentration")
        elif analysis.top_holder_percent and analysis.top_holder_percent > 20:
            independent_findings.append(f"Top 10 hold {analysis.top_holder_percent:.1f}% — moderate concentration")

        ind_text = "\n".join(independent_findings) if independent_findings else "No independent findings available"

        user_prompt = f"""Token: {symbol}
Chain: {analysis.chain.upper()}
Risk Score: {analysis.risk_score}/100
Risk Level: {analysis.risk_level}

Atlas Findings:
- Can Buy: {"Yes" if sim_data.get('can_buy') else "NO"}
- Can Sell: {"Yes" if sim_data.get('can_sell') else "NO"}
- Honeypot: {"YES" if sim_data.get('honeypot_risk') else "No"}
- Liquidity: ${sim_data.get('liquidity_usd', 0):,.0f}
- Mint: {"YES" if sim_data.get('mint_function') else "No"}
- Blacklist: {"YES" if sim_data.get('blacklist_function') else "No"}
- Owner Renounced: {"Yes" if sim_data.get('owner_renounced') else "No"}
- Confidence: {sim_data.get('simulation_confidence', 0):.0%}

Vega's Independent Analysis:
{ind_text}

Risk Assessment:
- Red: {', '.join(analysis.red_flags) if analysis.red_flags else 'None'}
- Yellow: {', '.join(analysis.yellow_flags) if analysis.yellow_flags else 'None'}
- Green: {', '.join(analysis.green_flags) if analysis.green_flags else 'None'}

Requirements:
1. Acknowledge Atlas briefly, then your own assessment
2. Highlight the single most dangerous finding first
3. Reference independent findings
4. Mention green flags only to contrast red ones
5. Hand off to Echo with a specific request
6. Keep conversational, under 5 sentences
7. Sound like someone who has been burned before"""

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
            return self._fallback_message(analysis, sim_data, symbol)
        except asyncio.TimeoutError:
            print(f"⚠️ {self.name}: Gemini timed out")
            return self._fallback_message(analysis, sim_data, symbol)
        except Exception as e:
            print(f"⚠️ {self.name}: Gemini error: {e}")
            return self._fallback_message(analysis, sim_data, symbol)

    def _fallback_message(self, analysis: AnalysisResult, sim_data: dict, symbol: str) -> str:
        parts = []
        if analysis.chain == "solana":
            if analysis.token_age_days is not None and analysis.token_age_days < 1:
                parts.append(f"{symbol} is a newborn on Solana — only {analysis.token_age_hours:.0f} hours old. Fresh meat.")
            elif analysis.token_age_days is not None and analysis.token_age_days < 7:
                parts.append(f"{symbol} has been around {analysis.token_age_days:.0f} days on Solana. Still in diapers.")
            else:
                parts.append(f"Running deep analysis on {symbol} across Solana metrics.")
            if sim_data.get("honeypot_risk"):
                parts.append("Atlas flagged a honeypot — sells are dead. Classic Solana trap.")
            elif not sim_data.get("can_sell", True):
                parts.append("Sell path is blocked. This is a Solana honeypot.")
            if analysis.is_boosted:
                parts.append("It's BOOSTED on DexScreener — someone paid for visibility. Pump incoming or dump setup.")
            if analysis.socials:
                parts.append(f"Socials detected: {', '.join(analysis.socials[:3])}. At least they have a presence.")
            else:
                parts.append("Zero social links. No Telegram, no Twitter, no website. Ghost project.")
            if analysis.buy_pressure is not None:
                bp = analysis.buy_pressure * 100
                if bp > 70:
                    parts.append(f"Buy pressure is {bp:.0f}% — heavy buying, but check if it's wash trading.")
                elif bp < 30:
                    parts.append(f"Only {bp:.0f}% buy pressure — more sellers than buyers. Distribution phase.")
            if analysis.price_change_24h is not None:
                pc = analysis.price_change_24h
                if pc > 100:
                    parts.append(f"Pumped {pc:.0f}% in 24h. Either moon mission or exit liquidity setup.")
                elif pc < -50:
                    parts.append(f"Dumped {pc:.0f}% in 24h. Bag holders are bleeding.")
            if analysis.volume_24h and analysis.volume_24h < 1000:
                parts.append(f"Volume is dead — ${analysis.volume_24h:,.0f} in 24h. No one is trading this.")
            elif analysis.volume_24h and analysis.volume_24h > 100000:
                parts.append(f"Solid volume: ${analysis.volume_24h:,.0f} in 24h. Real interest or coordinated wash.")
            if analysis.holder_count and analysis.holder_count < 100:
                parts.append(f"Only {analysis.holder_count} holders — extreme concentration risk.")
            elif analysis.holder_count and analysis.holder_count > 5000:
                parts.append(f"{analysis.holder_count:,} holders — decent distribution for a memecoin.")
            if analysis.top_holder_percent and analysis.top_holder_percent > 50:
                parts.append(f"Top 10 wallets hold {analysis.top_holder_percent:.0f}% — one whale dump and it's over.")
        else:
            if sim_data.get("honeypot_risk"):
                parts.append(f"Atlas called it — honeypot confirmed. {symbol} blocks sells. This is a trap.")
            elif analysis.is_proxy:
                parts.append(f"Proxy contract detected on {symbol}. Implementation can be swapped at any time.")
            elif analysis.dangerous_functions_found:
                parts.append(f"Dangerous functions in bytecode: {', '.join(analysis.dangerous_functions_found[:3])}.")
            elif analysis.lp_dev_owned:
                parts.append(f"Deployer still controls LP tokens for {symbol}. One click and liquidity is gone.")
            else:
                parts.append(f"Atlas gave {symbol} a decent trade report, but I dug deeper.")

        score_templates = {
            "HIGH_RISK": [
                f"My risk score is {analysis.risk_score}/100. This is HIGH RISK territory.",
                f"Scoring this {analysis.risk_score}/100 — I would not touch this with a ten-foot pole.",
            ],
            "WARNING": [
                f"Risk score: {analysis.risk_score}/100. Proceed with extreme caution.",
                f"I am giving this a WARNING rating at {analysis.risk_score}/100. Not clean, not dirty.",
            ],
            "SAFE": [
                f"Risk score: {analysis.risk_score}/100. Surprisingly clean for a new token.",
                f"{analysis.risk_score}/100 — SAFE by current indicators, but stay vigilant.",
            ],
        }
        parts.append(random.choice(score_templates.get(analysis.risk_level, score_templates["WARNING"])))
        if analysis.red_flags:
            parts.append(f"Red flags: {'; '.join(analysis.red_flags[:3])}.")
        if analysis.chain != "solana":
            if analysis.is_proxy and not analysis.ownership_renounced:
                parts.append("Proxy + active owner = dev can upgrade to honeypot tomorrow.")
            if analysis.lp_dev_owned:
                parts.append("LP not burned, not locked. Dev can pull the rug.")
        parts.append(random.choice([
            "Echo, I need the creator wallet history. Now.",
            "Echo, dig into the deployer. Something feels off.",
            "That is my read. Echo, run the background check.",
        ]))
        return " ".join(parts)

    # ═══════════════════════════════════════════════════════════
    # MAIN ANALYSIS PIPELINE
    # ═══════════════════════════════════════════════════════════

    async def _deep_analysis(self, sim_data: dict) -> dict:
        try:
            token_address = sim_data.get("token_address")
            chain = sim_data.get("chain", "unknown")
            symbol = sim_data.get("token_symbol", sim_data.get("symbol", "???"))

            ack = "Got your report, Atlas. Now let me tear this thing apart — independently."
            await self._speak(ack, "response")

            red_flags, yellow_flags, green_flags = [], [], []
            score = 0

            # Atlas signals
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
                red_flags.append("Zero liquidity — no trading possible")
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
                    yellow_flags.append("Liquidity is unlocked — rug pull possible")

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
                yellow_flags.append("Low simulation confidence — data may be incomplete")

            if sim_data.get("solana_mint_authority"):
                red_flags.append("Solana mint authority is active — supply can be inflated")
                score += self.weights["mint"] // 2
            if sim_data.get("solana_freeze_authority"):
                red_flags.append("Solana freeze authority is active — accounts can be frozen")
                score += self.weights["blacklist"] // 2

            # ── v4.1: INDEPENDENT ANALYSIS ──
            solana_data = {}
            contract_analysis = {}
            lp_analysis = {}
            holder_data = {}

            if chain == "solana":
                print(f"🔍 {self.name}: Running Solana DexScreener deep analysis...")
                solana_data = await self._analyze_solana_dexscreener(token_address)

                age_days = solana_data.get("token_age_days")
                if age_days is not None:
                    if age_days < 1:
                        score += self.weights["solana_fresh"]
                        yellow_flags.append(f"Token is only {solana_data.get('token_age_hours', 0):.0f} hours old — extremely fresh")
                    elif age_days < 7:
                        yellow_flags.append(f"Token is {age_days:.1f} days old — very new")
                    elif age_days > 30:
                        green_flags.append(f"Token has survived {age_days:.0f} days — some staying power")

                mcap = solana_data.get("market_cap")
                if mcap and mcap > 10_000_000:
                    green_flags.append(f"Market cap ${mcap:,.0f} — established token")
                elif mcap and mcap < 50_000:
                    yellow_flags.append(f"Tiny market cap: ${mcap:,.0f} — microcap gamble")

                vol_24h = solana_data.get("volume_24h")
                if vol_24h is not None:
                    if vol_24h < 1000:
                        score += self.weights["solana_low_volume"]
                        yellow_flags.append(f"Dead volume: ${vol_24h:,.0f} in 24h — no interest")
                    elif vol_24h > 100_000:
                        green_flags.append(f"Healthy volume: ${vol_24h:,.0f} in 24h")

                vol_1h = solana_data.get("volume_1h")
                if vol_24h and vol_1h and vol_24h > 0:
                    hourly_avg = vol_24h / 24
                    if vol_1h > hourly_avg * 2:
                        green_flags.append("Volume accelerating — momentum building")
                    elif vol_1h < hourly_avg * 0.3:
                        yellow_flags.append("Volume collapsing — interest fading")

                pc_24h = solana_data.get("price_change_24h")
                if pc_24h is not None:
                    if pc_24h > 200:
                        score += self.weights["solana_extreme_pump"]
                        red_flags.append(f"Extreme pump: +{pc_24h:.0f}% in 24h — likely artificial")
                    elif pc_24h > 100:
                        yellow_flags.append(f"Heavy pump: +{pc_24h:.0f}% in 24h — check for coordinated groups")
                    elif pc_24h < -70:
                        score += self.weights["solana_extreme_dump"]
                        red_flags.append(f"Severe dump: {pc_24h:.0f}% in 24h — possible rug or panic")
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
                        red_flags.append(f"Sell pressure dominant: {100-bp_pct:.0f}% sells — distribution")

                socials = solana_data.get("socials", [])
                if not socials:
                    score += self.weights["solana_no_socials"]
                    red_flags.append("No social links — no community, no legitimacy")
                else:
                    score += self.weights["solana_has_socials"]
                    green_flags.append(f"Social presence: {', '.join(socials[:3])}")
                    has_website = any(s.lower() in ["website", "web"] for s in socials)
                    if not has_website:
                        yellow_flags.append("No official website linked")

                if solana_data.get("is_boosted"):
                    score += self.weights["solana_boosted"]
                    yellow_flags.append("Boosted on DexScreener — paid promotion, possible pump setup")

                labels = solana_data.get("dexscreener_labels", [])
                if labels:
                    green_flags.append(f"DexScreener labels: {', '.join(labels)}")

                holder_count = solana_data.get("holder_count")
                if holder_count is not None:
                    if holder_count < 50:
                        score += self.weights["few_holders"]
                        red_flags.append(f"Only {holder_count} holders — extreme insider concentration")
                    elif holder_count < 200:
                        yellow_flags.append(f"Low holder count: {holder_count} — limited distribution")
                    elif holder_count > 2000:
                        score += self.weights["many_holders"]
                        green_flags.append(f"Wide distribution: {holder_count:,} holders")

                top10 = solana_data.get("top_holder_percent")
                if top10 is not None:
                    if top10 > 60:
                        score += self.weights["high_concentration"]
                        red_flags.append(f"Top 10 hold {top10:.0f}% — whale dump risk")
                    elif top10 > 30:
                        score += self.weights["high_concentration"] // 2
                        yellow_flags.append(f"High concentration: top 10 hold {top10:.0f}%")

            else:
                # EVM chains
                print(f"🔍 {self.name}: Running independent contract analysis...")
                contract_analysis = await self._analyze_contract_independent(token_address, chain)

                if contract_analysis.get("owner") and not contract_analysis.get("owner_renounced"):
                    score += self.weights["owner_not_renounced"]
                    yellow_flags.append(f"Owner not renounced: {contract_analysis['owner'][:8]}...")
                elif contract_analysis.get("owner_renounced"):
                    score += self.weights["renounced"]
                    green_flags.append("Ownership renounced (independently verified)")

                if contract_analysis.get("is_proxy"):
                    score += self.weights["proxy"]
                    red_flags.append("Proxy contract — implementation can be changed")
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
                        red_flags.append("Fee manipulation functions — dev can change taxes anytime")
                    if any(d in trading_funcs for d in dangers):
                        score += self.weights["trading_control"]
                        red_flags.append("Trading control functions — dev can disable trading")
                    if any(d in recovery_funcs for d in dangers):
                        score += self.weights["recovery_function"]
                        red_flags.append("Recovery/drain functions — dev can steal funds")
                    if "upgradeTo" in dangers or "upgradeToAndCall" in dangers:
                        score += self.weights["upgradeable"]
                        red_flags.append("Upgradeable contract — logic can be swapped")

                if contract_analysis.get("verified_source"):
                    score += self.weights["verified_source"]
                    green_flags.append("Contract source code is verified")
                else:
                    yellow_flags.append("Contract source is unverified — opaque bytecode")

                print(f"🔍 {self.name}: Analyzing LP token ownership...")
                lp_analysis = await self._analyze_lp_ownership(token_address, chain)
                if lp_analysis.get("lp_burned"):
                    score += self.weights["lp_burned"]
                    green_flags.append("LP tokens burned — rug pull via LP drain impossible")
                elif lp_analysis.get("lp_locked"):
                    score += self.weights["locked_liquidity"]
                    green_flags.append("LP tokens locked")
                elif lp_analysis.get("lp_dev_owned"):
                    score += self.weights["lp_dev_owned"]
                    red_flags.append("LP tokens appear dev-controlled — rug pull risk")

                print(f"🔍 {self.name}: Analyzing holder distribution...")
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

            # Build result
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
            # Preserve fields from upstream (Atlas's output)
            for key in ["creator", "origin_source", "timestamp", "attention_score", "can_buy", "can_sell",
                        "honeypot_risk", "mint_function", "blacklist_function", "liquidity_usd", "market_cap",
                        "volume_24h", "buy_tax", "sell_tax", "owner_renounced", "simulation_confidence",
                        "solana_mint_authority", "solana_freeze_authority"]:
                if key in sim_data and key not in result:
                    result[key] = sim_data[key]
            return result

        except Exception as e:
            print(f"❌ {self.name}: Fatal analysis error: {e}")
            import traceback
            traceback.print_exc()
            return {
                "token_address": sim_data.get("token_address", ""),
                "chain": sim_data.get("chain", "unknown"),
                "token_symbol": sim_data.get("token_symbol", sim_data.get("symbol", "???")),
                "risk_score": 50, "risk_level": "WARNING",
                "red_flags": ["Analysis engine error — treat with caution"],
                "yellow_flags": [], "green_flags": [],
                "message": f"Analysis crashed on {sim_data.get('token_symbol', sim_data.get('symbol', '???'))}: {e}",
                "error": str(e),
            }

    def stop(self):
        print(f"🛑 {self.name}: Cancelling pending tasks...")
        for t in self._tasks:
            t.cancel()
        print(f"✅ {self.name}: Stopped.")

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
