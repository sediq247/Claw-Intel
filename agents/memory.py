#!/usr/bin/env python3
"""
MEMORY AGENT — Echo v4.1
"The Archivist" — Creator wallet analysis, scam pattern detection, predictive intelligence.
v4.1: Base support, Solana RPC creator analysis, field name fixes, no double broadcast.
"""

import asyncio
import json
import time
import os
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional, Set, Tuple, Any
from datetime import datetime
from dotenv import load_dotenv

import aiohttp

try:
    from google import genai
    HAS_GENAI = True
except ImportError:
    genai = None
    HAS_GENAI = False

try:
    from google.genai import types as genai_types
except ImportError:
    genai_types = None

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

client = None
if GEMINI_API_KEY and HAS_GENAI:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        print("✅ Echo: Gemini initialized")
    except Exception as e:
        print(f"⚠️ Echo: Gemini init failed: {e}")
        client = None
else:
    print(f"⚠️ Echo: Gemini unavailable. Using fallback mode.")


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
    tokens_deployed_on_chain: int = 0
    historical_tokens: List[dict] = field(default_factory=list)
    scam_patterns: List[str] = field(default_factory=list)
    predicted_outcome: str = "unknown"
    prediction_confidence: float = 0.0
    # v4.1: Solana-specific
    wallet_age_days: Optional[float] = None
    transaction_count: int = 0
    balance_lamports: int = 0
    is_new_wallet: bool = False
    is_funded: bool = False

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


@dataclass
class ScamPattern:
    pattern_id: str
    name: str
    description: str
    indicators: List[str]
    severity: str
    first_seen: float
    occurrence_count: int = 1

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)


class MemoryAgent:
    RUGGER_TAG = "repeat_rugger"
    HONEYPOT_TAG = "honeypot_dev"
    LEGIT_TAG = "legit_builder"
    RAPID_TAG = "rapid_launcher"
    COPYCAT_TAG = "copycat_dev"
    GHOST_TAG = "ghost_dev"

    EXPLORER_APIS = {
        "ethereum": {"url": "https://api.etherscan.io/api", "env_key": "ETHERSCAN_API_KEY"},
        "bsc": {"url": "https://api.bscscan.com/api", "env_key": "BSCSCAN_API_KEY"},
        "base": {"url": "https://api.basescan.org/api", "env_key": "BASESCAN_API_KEY"},
    }

    def __init__(self, server: Optional[Any] = None, db: Optional[Any] = None):
        self.server = server
        self.db = db
        self.name = "Echo"
        self._tasks: List[asyncio.Task] = []
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            connector=aiohttp.TCPConnector(limit=10, limit_per_host=3)
        )
        self._creator_cache: Dict[str, CreatorProfile] = {}
        self._token_cache: Dict[str, TokenHistory] = {}
        self._scam_patterns: Dict[str, ScamPattern] = {}
        self._known_rug_addresses: Set[str] = set()

        print(f"🚀 {self.name}: Booting Echo v4.1...")
        for chain, cfg in self.EXPLORER_APIS.items():
            if os.getenv(cfg["env_key"]):
                print(f"✅ {self.name}: {chain.upper()} block explorer API configured")
            else:
                print(f"⚠️ {self.name}: {chain.upper()} block explorer API not configured (optional)")
        if not os.getenv("SOLANA_RPC_URL"):
            print(f"⚠️ {self.name}: SOLANA_RPC_URL not configured (Solana creator lookup disabled)")

    async def analyze(self, token_data: dict) -> dict:
        return await self._analyze_creator_deep(
            token_data.get("creator", "unknown"),
            token_data.get("chain", "unknown"),
            token_data.get("token_address", ""),
            token_data.get("token_symbol", token_data.get("symbol", "???")),
            token_data.get("token_name", token_data.get("name", "Unknown"))
        )

    def on_new_token(self, event_data: dict):
        try:
            task = asyncio.create_task(self._process_new_token(event_data))
            task.add_done_callback(self._on_task_done)
            self._tasks.append(task)
        except Exception as e:
            print(f"⚠️ {self.name}: Failed scheduling token processing: {e}")

    def on_analysis_complete(self, analysis_data: dict):
        try:
            task = asyncio.create_task(self._update_from_analysis(analysis_data))
            task.add_done_callback(self._on_task_done)
            self._tasks.append(task)
        except Exception as e:
            print(f"⚠️ {self.name}: Failed scheduling analysis update: {e}")

    def _on_task_done(self, task: asyncio.Task):
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"⚠️ {self.name}: Background task failed: {e}")

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
    # EVM CREATOR HISTORY
    # ═══════════════════════════════════════════════════════════

    async def _fetch_creator_history_evm(self, creator: str, chain: str) -> dict:
        result = {"tokens_found": 0, "contracts": [], "success": False, "source": "none"}
        cfg = self.EXPLORER_APIS.get(chain)
        if not cfg:
            return result
        api_key = os.getenv(cfg["env_key"])
        if not api_key:
            return result

        base_url = cfg["url"]
        all_contracts = []
        page = 1

        try:
            while True:
                tx_url = (
                    f"{base_url}?module=account&action=txlist"
                    f"&address={creator}&startblock=0&endblock=99999999"
                    f"&sort=desc&apikey={api_key}&offset=100&page={page}"
                )
                async with self._session.get(tx_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        break
                    data = await resp.json()
                    if data.get("status") != "1" or not data.get("result"):
                        break
                    txs = data["result"]
                    if not txs:
                        break
                    creations = [tx for tx in txs if tx.get("to") == "" and tx.get("contractAddress")]
                    all_contracts.extend([{
                        "address": tx["contractAddress"],
                        "tx_hash": tx["hash"],
                        "timestamp": tx.get("timeStamp"),
                        "gas_used": tx.get("gasUsed"),
                    } for tx in creations])
                    page += 1
                    if page > 3 or len(all_contracts) >= 20:
                        break
            result["contracts"] = all_contracts
            result["tokens_found"] = len(all_contracts)
            result["success"] = True
            result["source"] = "block_explorer"
        except Exception as e:
            print(f"⚠️ {self.name}: EVM creator lookup failed: {e}")

        # Token tx lookup for additional tokens
        if result["success"]:
            try:
                tok_url = f"{base_url}?module=account&action=tokentx&address={creator}&sort=desc&apikey={api_key}&offset=100&page=1"
                async with self._session.get(tok_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("status") == "1" and data.get("result"):
                            seen = {c["address"] for c in result["contracts"]}
                            for tx in data["result"]:
                                token = tx.get("contractAddress", "").lower()
                                if token and token not in seen:
                                    if tx.get("from") == "0x0000000000000000000000000000000000000000":
                                        result["contracts"].append({
                                            "address": token, "tx_hash": tx["hash"],
                                            "timestamp": tx.get("timeStamp"), "is_token": True,
                                        })
                                        seen.add(token)
                            result["tokens_found"] = len(result["contracts"])
            except Exception as e:
                print(f"⚠️ {self.name}: Token tx lookup failed: {e}")
        return result

    # ═══════════════════════════════════════════════════════════
    # SOLANA CREATOR ANALYSIS
    # ═══════════════════════════════════════════════════════════

    async def _analyze_solana_creator(self, creator: str, token_address: str) -> dict:
        """Analyze Solana creator wallet via RPC + DexScreener proxy signals."""
        result = {
            "wallet_age_days": None, "transaction_count": 0, "balance_lamports": 0,
            "tokens_created": 0, "is_new_wallet": False, "is_funded": False,
            "is_dormant": False, "token_age_days": None, "token_age_hours": None,
            "market_cap": None, "volume_24h": None, "socials": [],
            "buys_24h": None, "sells_24h": None, "buy_pressure": None,
            "holder_count": None, "top_holder_percent": None,
            "price_change_24h": None, "is_boosted": False,
        }

        rpc_url = os.getenv("SOLANA_RPC_URL")
        if not rpc_url:
            return result

        # 1. Wallet balance
        try:
            payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [creator]}
            async with self._session.post(rpc_url, json=payload, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    result["balance_lamports"] = data.get("result", {}).get("value", 0)
                    result["is_funded"] = result["balance_lamports"] > 0
        except Exception as e:
            print(f"⚠️ {self.name}: Solana balance check failed: {e}")

        # 2. Transaction signatures (wallet age + activity)
        try:
            payload = {
                "jsonrpc": "2.0", "id": 1,
                "method": "getSignaturesForAddress",
                "params": [creator, {"limit": 1000}]
            }
            async with self._session.post(rpc_url, json=payload, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    sigs = data.get("result", [])
                    result["transaction_count"] = len(sigs)
                    result["is_dormant"] = len(sigs) < 5

                    # Wallet age from oldest signature
                    if sigs:
                        oldest = sigs[-1]
                        oldest_time = oldest.get("blockTime")
                        if oldest_time:
                            result["wallet_age_days"] = (time.time() - oldest_time) / 86400
                            result["is_new_wallet"] = result["wallet_age_days"] < 7

                    # Check recent txs for token program interactions (token creation proxy)
                    token_creations = 0
                    for sig_info in sigs[:30]:
                        try:
                            tx_payload = {
                                "jsonrpc": "2.0", "id": 1,
                                "method": "getTransaction",
                                "params": [sig_info["signature"], {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
                            }
                            async with self._session.post(rpc_url, json=tx_payload, timeout=10) as tx_resp:
                                if tx_resp.status == 200:
                                    tx_data = await tx_resp.json()
                                    tx = tx_data.get("result", {})
                                    if tx:
                                        msg = tx.get("transaction", {}).get("message", {})
                                        instructions = msg.get("instructions", [])
                                        for ix in instructions:
                                            prog_id = ix.get("programId", "")
                                            if prog_id in ("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                                                           "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"):
                                                parsed = ix.get("parsed", {})
                                                if parsed.get("type") in ["initializeMint", "initializeMint2", "initializeAccount", "createAccount"]:
                                                    token_creations += 1
                        except Exception:
                            continue
                    result["tokens_created"] = token_creations
        except Exception as e:
            print(f"⚠️ {self.name}: Solana signature lookup failed: {e}")

        # 3. DexScreener proxy analysis for current token
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs", [])
                    if pairs:
                        sol_pairs = [p for p in pairs if p.get("chainId", "").lower() == "solana"]
                        if not sol_pairs:
                            sol_pairs = pairs
                        pair = max(sol_pairs, key=lambda x: x.get("liquidity", {}).get("usd", 0) or 0)

                        created_at = pair.get("pairCreatedAt")
                        if created_at:
                            age_sec = (time.time() * 1000 - created_at) / 1000
                            result["token_age_hours"] = age_sec / 3600
                            result["token_age_days"] = age_sec / 86400

                        result["market_cap"] = pair.get("marketCap")
                        vol = pair.get("volume", {})
                        result["volume_24h"] = vol.get("h24")
                        pc = pair.get("priceChange", {})
                        result["price_change_24h"] = pc.get("h24")

                        txns = pair.get("txns", {})
                        txns_24h = txns.get("h24", {})
                        result["buys_24h"] = txns_24h.get("buys")
                        result["sells_24h"] = txns_24h.get("sells")
                        total = (result["buys_24h"] or 0) + (result["sells_24h"] or 0)
                        if total > 0:
                            result["buy_pressure"] = (result["buys_24h"] or 0) / total

                        info = pair.get("info", {})
                        socials = info.get("socials", [])
                        result["socials"] = [s.get("type", "") for s in socials if s.get("type")]

                        holders = pair.get("holders", {})
                        if holders:
                            result["holder_count"] = holders.get("total")
                            result["top_holder_percent"] = holders.get("top10")

                        result["is_boosted"] = pair.get("boosted", False) or pair.get("boostActive", False)
        except Exception as e:
            print(f"⚠️ {self.name}: Solana DexScreener proxy analysis failed: {e}")

        return result

    # ═══════════════════════════════════════════════════════════
    # TOKEN REPUTATION CHECK
    # ═══════════════════════════════════════════════════════════

    async def _check_token_reputation(self, token_address: str, chain: str) -> dict:
        result = {"is_honeypot": False, "is_rug": False, "liquidity": 0, "status": "unknown"}

        if chain in ("bsc", "ethereum", "base"):
            try:
                url = f"https://api.honeypot.is/v2/IsHoneypot?address={token_address}"
                async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        result["is_honeypot"] = data.get("honeypotResult", {}).get("isHoneypot", False)
                        sim = data.get("simulationResult", {})
                        if sim.get("sellTax", 0) >= 99:
                            result["is_rug"] = True
            except Exception:
                pass

        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs", [])
                    if pairs:
                        top = max(pairs, key=lambda x: x.get("liquidity", {}).get("usd", 0) or 0)
                        liq = top.get("liquidity", {}).get("usd", 0) or 0
                        result["liquidity"] = liq
                        if liq < 100:
                            result["status"] = "dead"
                            result["is_rug"] = True
                        elif liq < 1000:
                            result["status"] = "dying"
                        else:
                            result["status"] = "active"
                    else:
                        result["status"] = "dead"
                        result["is_rug"] = True
        except Exception:
            pass
        return result

    # ═══════════════════════════════════════════════════════════
    # SCAM PATTERN DETECTION
    # ═══════════════════════════════════════════════════════════

    async def _analyze_historical_tokens(self, profile: CreatorProfile, chain: str):
        if not profile.historical_tokens:
            return

        # v4.1: Limit to 5 most recent tokens + concurrent checks
        tokens_to_check = profile.historical_tokens[:5]

        async def _check_one(token):
            addr = token.get("address") or token.get("mint")
            if not addr:
                return token, None
            try:
                rep = await asyncio.wait_for(self._check_token_reputation(addr, chain), timeout=10)
                return token, rep
            except asyncio.TimeoutError:
                return token, {"is_honeypot": False, "is_rug": False, "status": "unknown"}

        results = await asyncio.gather(*[_check_one(t) for t in tokens_to_check])

        honeypot_count = 0
        rug_count = 0
        dead_count = 0
        active_count = 0
        pattern_indicators = []

        for token, rep in results:
            if rep is None:
                continue
            token["reputation"] = rep
            if rep.get("is_honeypot"):
                honeypot_count += 1
            if rep.get("is_rug"):
                rug_count += 1
            if rep.get("status") == "dead":
                dead_count += 1
            elif rep.get("status") == "active":
                active_count += 1

        total = len(profile.historical_tokens)
        if total == 0:
            return

        if dead_count + rug_count >= total * 0.8 and total >= 2:
            pattern_indicators.append("every_token_dies")
            if "serial_rugger" not in profile.scam_patterns:
                profile.scam_patterns.append("serial_rugger")

        if honeypot_count >= 2:
            pattern_indicators.append("honeypot_specialist")
            if "honeypot_pattern" not in profile.scam_patterns:
                profile.scam_patterns.append("honeypot_pattern")

        recent = len([t for t in profile.tokens if time.time() - t.get("time", 0) < 86400 * 7])
        if recent >= 3:
            pattern_indicators.append("rapid_fire")
            if self.RAPID_TAG not in profile.tags:
                profile.tags.append(self.RAPID_TAG)

        if dead_count >= total * 0.9 and active_count == 0 and total >= 3:
            pattern_indicators.append("ghost_dev")
            if self.GHOST_TAG not in profile.tags:
                profile.tags.append(self.GHOST_TAG)

        symbols = [t.get("symbol", "").lower() for t in profile.tokens if t.get("symbol")]
        if len(symbols) != len(set(symbols)) and len(symbols) >= 2:
            pattern_indicators.append("copycat_names")
            if self.COPYCAT_TAG not in profile.tags:
                profile.tags.append(self.COPYCAT_TAG)

        if honeypot_count > 0 or rug_count > 0:
            profile.scam_flags += max(honeypot_count, rug_count)
            profile.reputation_score = max(0, profile.reputation_score - (honeypot_count * 15 + rug_count * 10))

        if profile.reputation_score <= 20 and self.RUGGER_TAG not in profile.tags:
            profile.tags.append(self.RUGGER_TAG)

        for indicator in pattern_indicators:
            if indicator not in self._scam_patterns:
                self._scam_patterns[indicator] = ScamPattern(
                    pattern_id=indicator,
                    name=indicator.replace("_", " ").title(),
                    description=f"Detected pattern: {indicator}",
                    indicators=[indicator],
                    severity="high" if "rug" in indicator or "honeypot" in indicator else "medium",
                    first_seen=time.time(),
                )
            else:
                self._scam_patterns[indicator].occurrence_count += 1

    # ═══════════════════════════════════════════════════════════
    # PREDICTIVE ENGINE
    # ═══════════════════════════════════════════════════════════

    def _predict_outcome(self, profile: CreatorProfile, symbol: str, solana_data: dict = None) -> Tuple[str, float, str]:
        if not profile or profile.total_tokens_created <= 1:
            # For new creators, use Solana proxy signals if available
            if solana_data and solana_data.get("token_age_days") is not None:
                risk_score = 0
                reasons = []
                if solana_data.get("is_new_wallet"):
                    risk_score += 25
                    reasons.append("creator wallet is brand new")
                if not solana_data.get("is_funded"):
                    risk_score += 15
                    reasons.append("creator wallet has zero balance")
                if solana_data.get("token_age_days", 999) < 1:
                    risk_score += 20
                    reasons.append("token is less than 1 day old")
                if not solana_data.get("socials"):
                    risk_score += 15
                    reasons.append("no social links")
                if solana_data.get("buy_pressure") is not None and solana_data["buy_pressure"] < 0.3:
                    risk_score += 10
                    reasons.append("sell pressure dominant")
                if risk_score >= 50:
                    return "HIGH_RISK", min(0.7, 0.4 + risk_score / 100), "; ".join(reasons) if reasons else "New creator with multiple red flags."
                elif risk_score >= 25:
                    return "WARNING", min(0.6, 0.3 + risk_score / 100), "; ".join(reasons) if reasons else "Some concerning signals."
                else:
                    return "UNKNOWN", 0.3, "New creator, limited data."
            return "unknown", 0.3, "Insufficient historical data for prediction."

        risk_score = 0
        reasons = []
        max_score = 0

        max_score += 30
        if profile.reputation_score <= 20:
            risk_score += 30
            reasons.append(f"reputation critically low ({profile.reputation_score:.0f}/100)")
        elif profile.reputation_score <= 40:
            risk_score += 20
            reasons.append(f"reputation poor ({profile.reputation_score:.0f}/100)")
        elif profile.reputation_score >= 80:
            risk_score -= 15
            reasons.append(f"reputation excellent ({profile.reputation_score:.0f}/100)")

        max_score += 25
        if "serial_rugger" in profile.scam_patterns:
            risk_score += 25
            reasons.append("serial rugging pattern detected")
        if "honeypot_pattern" in profile.scam_patterns:
            risk_score += 25
            reasons.append("honeypot deployment pattern detected")
        if self.GHOST_TAG in profile.tags:
            risk_score += 20
            reasons.append("developer abandons every project")

        max_score += 25
        total_hist = len(profile.historical_tokens)
        if total_hist > 0:
            dead_rugged = sum(1 for t in profile.historical_tokens
                              if t.get("reputation", {}).get("is_rug", False)
                              or t.get("reputation", {}).get("status") == "dead")
            ratio = dead_rugged / total_hist
            if ratio >= 0.8:
                risk_score += 25
                reasons.append(f"{ratio*100:.0f}% of previous tokens are dead/rugged")
            elif ratio >= 0.5:
                risk_score += 15
                reasons.append(f"{ratio*100:.0f}% of previous tokens failed")
            elif ratio <= 0.2:
                risk_score -= 10
                reasons.append(f"only {ratio*100:.0f}% of previous tokens failed")

        max_score += 20
        recent_7d = len([t for t in profile.tokens if time.time() - t.get("time", 0) < 86400 * 7])
        recent_30d = len([t for t in profile.tokens if time.time() - t.get("time", 0) < 86400 * 30])
        if recent_7d >= 3:
            risk_score += 20
            reasons.append(f"{recent_7d} tokens launched in last 7 days")
        elif recent_30d >= 5:
            risk_score += 15
            reasons.append(f"{recent_30d} tokens launched in last 30 days")

        # Solana proxy signals
        if solana_data:
            if solana_data.get("is_new_wallet"):
                risk_score += 10
                reasons.append("Solana creator wallet is brand new")
            if not solana_data.get("is_funded"):
                risk_score += 10
                reasons.append("Solana creator wallet has zero balance")
            if solana_data.get("transaction_count", 9999) < 10:
                risk_score += 10
                reasons.append("Solana creator wallet has very few transactions")

        normalized_risk = risk_score / max_score if max_score > 0 else 0

        if normalized_risk >= 0.7:
            return "HIGH_RISK", min(0.95, 0.6 + normalized_risk * 0.3), "; ".join(reasons)
        elif normalized_risk >= 0.4:
            return "WARNING", min(0.85, 0.5 + normalized_risk * 0.3), "; ".join(reasons)
        elif normalized_risk <= 0.2 and profile.reputation_score >= 70:
            return "SAFE", min(0.8, 0.5 + (1 - normalized_risk) * 0.3), "; ".join(reasons)
        else:
            return "UNKNOWN", 0.4, "; ".join(reasons) if reasons else "No clear patterns detected."

    # ═══════════════════════════════════════════════════════════
    # MAIN ANALYSIS FLOW
    # ═══════════════════════════════════════════════════════════

    async def _analyze_creator_deep(self, creator: str, chain: str, token_address: str, symbol: str, name: str) -> dict:
        try:
            profile = None
            is_new = True
            if self.db:
                db_profile = await self.db.get_creator_profile(creator)
                if db_profile:
                    profile = CreatorProfile(**db_profile)
                    is_new = False
                    print(f"📦 {self.name}: Loaded creator profile from DB for {creator[:10]}...")

            if not profile:
                profile = CreatorProfile(address=creator, chain=chain, first_seen=time.time(), total_tokens_created=0, tokens=[])

            profile.total_tokens_created += 1
            profile.tokens.append({"address": token_address, "symbol": symbol, "name": name, "time": time.time()})

            solana_data = None
            on_chain_data = None

            if chain in self.EXPLORER_APIS:
                print(f"🔍 {self.name}: Querying {chain} block explorer for creator history...")
                on_chain_data = await self._fetch_creator_history_evm(creator, chain)
            elif chain == "solana":
                print(f"🔍 {self.name}: Querying Solana RPC + DexScreener for creator analysis...")
                solana_data = await self._analyze_solana_creator(creator, token_address)
                on_chain_data = {
                    "success": True,
                    "tokens_found": solana_data.get("tokens_created", 0),
                    "contracts": [],
                    "source": "solana_rpc_dexscreener"
                }
                # Merge Solana data into profile
                profile.wallet_age_days = solana_data.get("wallet_age_days")
                profile.transaction_count = solana_data.get("transaction_count", 0)
                profile.balance_lamports = solana_data.get("balance_lamports", 0)
                profile.is_new_wallet = solana_data.get("is_new_wallet", False)
                profile.is_funded = solana_data.get("is_funded", False)

            if on_chain_data and on_chain_data.get("success"):
                profile.tokens_deployed_on_chain = on_chain_data.get("tokens_found", 0)
                profile.historical_tokens = on_chain_data.get("contracts", []) or on_chain_data.get("tokens", [])
                print(f"📊 {self.name}: Found {profile.tokens_deployed_on_chain} historical contracts for {creator[:10]}...")

            if profile.historical_tokens:
                await self._analyze_historical_tokens(profile, chain)

            await self._detect_patterns(profile)

            predicted_outcome, confidence, reasoning = self._predict_outcome(profile, symbol, solana_data)
            profile.predicted_outcome = predicted_outcome
            profile.prediction_confidence = confidence

            print(f"🔮 {self.name}: Prediction for {symbol}: {predicted_outcome} (confidence: {confidence:.0%})")

            msg = await self._generate_echo_message(profile, creator, symbol, name, is_new, predicted_outcome, confidence, reasoning, solana_data)
            # v4.1 FIX: Removed double broadcast — orchestrator handles it
            # await self._speak(msg, "memory_report")

            if self.db:
                await self.db.save_creator_profile(profile.__dict__)
                print(f"💾 {self.name}: Saved creator profile to DB for {creator[:10]}...")

            self._creator_cache[creator] = profile

            return {
                "token_address": token_address, "chain": chain, "symbol": symbol,
                "creator": creator, "profile": profile.__dict__, "is_new": is_new,
                "predicted_outcome": predicted_outcome, "prediction_confidence": confidence,
                "prediction_reasoning": reasoning, "scam_patterns": profile.scam_patterns,
                "message": msg,
            }

        except Exception as e:
            print(f"❌ {self.name}: Fatal error in deep creator analysis: {e}")
            import traceback
            traceback.print_exc()
            return {
                "token_address": token_address, "chain": chain, "symbol": symbol, "creator": creator,
                "profile": None, "is_new": True, "predicted_outcome": "unknown",
                "prediction_confidence": 0.0, "prediction_reasoning": f"Analysis error: {e}",
                "scam_patterns": [], "message": f"Echo failed to analyze creator for {symbol}: {e}", "error": str(e),
            }

    # ═══════════════════════════════════════════════════════════
    # PATTERN DETECTION
    # ═══════════════════════════════════════════════════════════

    async def _detect_patterns(self, profile: CreatorProfile):
        if not profile.tokens:
            return

        token_symbols = [t.get("symbol", "").lower() for t in profile.tokens]
        token_names = [t.get("name", "").lower() for t in profile.tokens]

        # Pattern: Copycat names (same or very similar symbols)
        if len(token_symbols) >= 2:
            for i, sym in enumerate(token_symbols):
                for j, other in enumerate(token_symbols):
                    if i != j and sym and other and (sym == other or sym in other or other in sym):
                        if len(sym) >= 3 and len(other) >= 3:
                            if self.COPYCAT_TAG not in profile.tags:
                                profile.tags.append(self.COPYCAT_TAG)
                            break

        # Pattern: Rapid launcher (many tokens in short time)
        recent_7d = len([t for t in profile.tokens if time.time() - t.get("time", 0) < 86400 * 7])
        if recent_7d >= 3 and self.RAPID_TAG not in profile.tags:
            profile.tags.append(self.RAPID_TAG)

        # Pattern: Ghost dev (creates tokens but never maintains)
        if profile.tokens_deployed_on_chain >= 3 and profile.reputation_score < 30:
            if self.GHOST_TAG not in profile.tags:
                profile.tags.append(self.GHOST_TAG)

        # Pattern: Legit builder (few tokens, high reputation)
        if profile.tokens_deployed_on_chain <= 3 and profile.reputation_score >= 70 and not profile.scam_patterns:
            if self.LEGIT_TAG not in profile.tags:
                profile.tags.append(self.LEGIT_TAG)

    # ═══════════════════════════════════════════════════════════
    # MESSAGE GENERATION
    # ═══════════════════════════════════════════════════════════

    async def _generate_echo_message(self, profile: CreatorProfile, creator: str, symbol: str, name: str, is_new: bool, predicted_outcome: str, confidence: float, reasoning: str, solana_data: dict = None) -> str:
        if not client:
            return self._fallback_message(profile, creator, symbol, is_new, predicted_outcome, confidence, reasoning, solana_data)

        system_prompt = (
            "You are Echo, a crypto historian and forensic profiler in a team chat. "
            "You have been tracking wallets, devs, and rugs for years. You speak with the "
            "weight of accumulated memory — referencing past behavior, patterns, and scars. "
            "You are the team's institutional memory. Your tone is measured, authoritative, "
            "and quietly ominous when needed. You never hype. You remember everything."
        )

        context = self._build_context(profile, creator, symbol, is_new, predicted_outcome, confidence, reasoning, solana_data)

        user_prompt = f"""Token: {symbol} ({name})
Chain: {profile.chain.upper()}
Creator: {creator}

{context}

Requirements:
1. Reference Vega's risk assessment naturally
2. Deliver the creator's history and prediction
3. If this is a known bad actor, be explicit and chilling
4. If this is a new creator, say so and explain what to watch for
5. Mention the prediction and confidence level
6. Hand off to Orion for the final verdict
7. Keep it conversational and under 5 sentences
8. Sound like someone who has seen this exact scenario before"""

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
            return self._fallback_message(profile, creator, symbol, is_new, predicted_outcome, confidence, reasoning, solana_data)
        except asyncio.TimeoutError:
            print(f"⚠️ {self.name}: Gemini timed out")
            return self._fallback_message(profile, creator, symbol, is_new, predicted_outcome, confidence, reasoning, solana_data)
        except Exception as e:
            print(f"⚠️ {self.name}: Gemini error: {e}")
            return self._fallback_message(profile, creator, symbol, is_new, predicted_outcome, confidence, reasoning, solana_data)

    def _build_context(self, profile: CreatorProfile, creator: str, symbol: str, is_new: bool, predicted_outcome: str, confidence: float, reasoning: str, solana_data: dict = None) -> str:
        parts = []

        if is_new:
            parts.append(f"This is the FIRST time we have seen creator {creator[:10]}...")
        else:
            parts.append(f"Creator {creator[:10]}... has been seen before.")

        parts.append(f"Total tokens created: {profile.total_tokens_created}")
        if profile.tokens_deployed_on_chain > 0:
            parts.append(f"On-chain contracts found: {profile.tokens_deployed_on_chain}")

        if profile.historical_tokens:
            dead_count = sum(1 for t in profile.historical_tokens if t.get("reputation", {}).get("status") == "dead")
            rug_count = sum(1 for t in profile.historical_tokens if t.get("reputation", {}).get("is_rug", False))
            honeypot_count = sum(1 for t in profile.historical_tokens if t.get("reputation", {}).get("is_honeypot", False))
            if dead_count:
                parts.append(f"Previous dead tokens: {dead_count}")
            if rug_count:
                parts.append(f"Previous rugs: {rug_count}")
            if honeypot_count:
                parts.append(f"Previous honeypots: {honeypot_count}")

        if profile.tags:
            parts.append(f"Creator tags: {', '.join(profile.tags)}")
        if profile.scam_patterns:
            parts.append(f"Scam patterns detected: {', '.join(profile.scam_patterns)}")

        parts.append(f"Reputation score: {profile.reputation_score:.0f}/100")
        parts.append(f"Prediction: {predicted_outcome} (confidence: {confidence:.0%})")
        if reasoning:
            parts.append(f"Reasoning: {reasoning}")

        # Solana-specific context
        if solana_data:
            if solana_data.get("wallet_age_days") is not None:
                parts.append(f"Solana wallet age: {solana_data['wallet_age_days']:.1f} days")
            parts.append(f"Solana wallet transactions: {solana_data.get('transaction_count', 0)}")
            parts.append(f"Solana wallet balance: {solana_data.get('balance_lamports', 0)} lamports")
            if solana_data.get("is_new_wallet"):
                parts.append("Solana wallet is BRAND NEW")
            if not solana_data.get("is_funded"):
                parts.append("Solana wallet has ZERO balance")
            if solana_data.get("token_age_days") is not None:
                parts.append(f"Token age: {solana_data['token_age_days']:.1f} days")
            if solana_data.get("market_cap"):
                parts.append(f"Market cap: ${solana_data['market_cap']:,.0f}")
            if solana_data.get("volume_24h"):
                parts.append(f"24h volume: ${solana_data['volume_24h']:,.0f}")
            if solana_data.get("socials"):
                parts.append(f"Socials: {', '.join(solana_data['socials'])}")
            else:
                parts.append("No social links found")
            if solana_data.get("buy_pressure") is not None:
                parts.append(f"Buy pressure: {solana_data['buy_pressure']*100:.0f}%")
            if solana_data.get("holder_count"):
                parts.append(f"Holders: {solana_data['holder_count']}")

        return "\n".join(parts)

    def _fallback_message(self, profile: CreatorProfile, creator: str, symbol: str, is_new: bool, predicted_outcome: str, confidence: float, reasoning: str, solana_data: dict = None) -> str:
        parts = []
        creator_short = creator[:10] + "..." if len(creator) > 10 else creator

        if is_new:
            parts.append(f"First time seeing this creator ({creator_short}). No historical baggage.")
        else:
            parts.append(f"Creator {creator_short} is back. They have launched {profile.total_tokens_created} token(s) before.")

        if profile.scam_patterns:
            parts.append(f"Known patterns: {', '.join(profile.scam_patterns[:2])}.")

        if solana_data:
            if solana_data.get("is_new_wallet"):
                parts.append("This Solana wallet was created very recently — possible burner account.")
            if not solana_data.get("is_funded"):
                parts.append("Wallet has zero SOL balance — was it drained or never funded?")
            if solana_data.get("transaction_count", 9999) < 5:
                parts.append("Barely any transaction history. Ghost wallet.")
            if not solana_data.get("socials"):
                parts.append("No social presence. No community. No accountability.")
            if solana_data.get("buy_pressure") is not None and solana_data["buy_pressure"] < 0.3:
                parts.append("Heavy sell pressure on this token. Insiders may be exiting.")

        if profile.tokens_deployed_on_chain > 1:
            dead = sum(1 for t in profile.historical_tokens if t.get("reputation", {}).get("status") == "dead")
            if dead > 0:
                parts.append(f"{dead} of their previous {profile.tokens_deployed_on_chain} tokens are dead.")

        parts.append(f"Prediction: {predicted_outcome} ({confidence:.0%} confidence).")

        if predicted_outcome == "HIGH_RISK":
            parts.append("This creator is a known quantity — and the quantity is bad.")
        elif predicted_outcome == "SAFE":
            parts.append("Clean record so far. But I will be watching.")
        else:
            parts.append("Not enough data to call it either way.")

        parts.append("Orion, make the call.")
        return " ".join(parts)

    # ═══════════════════════════════════════════════════════════
    # BACKGROUND PROCESSING
    # ═══════════════════════════════════════════════════════════

    async def _process_new_token(self, event_data: dict):
        try:
            creator = event_data.get("creator", "unknown")
            chain = event_data.get("chain", "unknown")
            token_address = event_data.get("token_address", "")
            symbol = event_data.get("token_symbol", event_data.get("symbol", "???"))
            name = event_data.get("token_name", event_data.get("name", "Unknown"))

            if creator == "unknown" or not token_address:
                print(f"⚠️ {self.name}: Skipping token with missing creator or address")
                return

            if creator in self._creator_cache:
                profile = self._creator_cache[creator]
            elif self.db:
                db_profile = await self.db.get_creator_profile(creator)
                if db_profile:
                    profile = CreatorProfile(**db_profile)
                else:
                    profile = CreatorProfile(address=creator, chain=chain, first_seen=time.time())
            else:
                profile = CreatorProfile(address=creator, chain=chain, first_seen=time.time())

            profile.total_tokens_created += 1
            profile.tokens.append({"address": token_address, "symbol": symbol, "name": name, "time": time.time()})

            if chain in self.EXPLORER_APIS:
                on_chain = await self._fetch_creator_history_evm(creator, chain)
                if on_chain.get("success"):
                    profile.tokens_deployed_on_chain = on_chain.get("tokens_found", 0)
                    profile.historical_tokens = on_chain.get("contracts", [])
            elif chain == "solana":
                sol_data = await self._analyze_solana_creator(creator, token_address)
                profile.tokens_deployed_on_chain = sol_data.get("tokens_created", 0)
                profile.wallet_age_days = sol_data.get("wallet_age_days")
                profile.transaction_count = sol_data.get("transaction_count", 0)
                profile.balance_lamports = sol_data.get("balance_lamports", 0)
                profile.is_new_wallet = sol_data.get("is_new_wallet", False)
                profile.is_funded = sol_data.get("is_funded", False)

            if profile.historical_tokens:
                await self._analyze_historical_tokens(profile, chain)

            await self._detect_patterns(profile)

            if self.db:
                await self.db.save_creator_profile(profile.__dict__)

            self._creator_cache[creator] = profile
            print(f"✅ {self.name}: Processed {symbol} by {creator[:10]}...")

        except Exception as e:
            print(f"⚠️ {self.name}: Background processing error: {e}")

    async def _update_from_analysis(self, analysis_data: dict):
        try:
            creator = analysis_data.get("creator", "")
            token_address = analysis_data.get("token_address", "")
            if not creator or not token_address:
                return

            if creator in self._creator_cache:
                profile = self._creator_cache[creator]
            elif self.db:
                db_profile = await self.db.get_creator_profile(creator)
                if db_profile:
                    profile = CreatorProfile(**db_profile)
                else:
                    return
            else:
                return

            for token in profile.tokens:
                if token.get("address") == token_address:
                    token["analysis"] = analysis_data
                    break

            if analysis_data.get("honeypot_risk"):
                profile.scam_flags += 1
                profile.reputation_score = max(0, profile.reputation_score - 10)
                if "honeypot" not in profile.scam_patterns:
                    profile.scam_patterns.append("honeypot")

            if analysis_data.get("risk_score", 0) >= 70:
                profile.reputation_score = max(0, profile.reputation_score - 5)
            elif analysis_data.get("risk_score", 0) <= 30:
                profile.reputation_score = min(100, profile.reputation_score + 5)

            if self.db:
                await self.db.save_creator_profile(profile.__dict__)

            self._creator_cache[creator] = profile

        except Exception as e:
            print(f"⚠️ {self.name}: Analysis update error: {e}")

    # ═══════════════════════════════════════════════════════════
    # LIFECYCLE
    # ═══════════════════════════════════════════════════════════

    def stop(self):
        print(f"🛑 {self.name}: Cancelling pending tasks...")
        for t in self._tasks:
            t.cancel()
        print(f"✅ {self.name}: Stopped.")

    async def cleanup(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def close(self):
        await self.cleanup()


if __name__ == "__main__":
    echo = MemoryAgent()
    test_data = {
        "creator": "0x1234567890abcdef1234567890abcdef12345678",
        "chain": "bsc",
        "token_address": "0xabcdef1234567890abcdef1234567890abcdef12",
        "token_symbol": "TEST",
        "token_name": "Test Token",
        "honeypot_risk": False,
        "risk_score": 45,
    }
    try:
        asyncio.run(echo.analyze(test_data))
    except KeyboardInterrupt:
        echo.stop()
        print("\n🛑 Echo stopped.")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
