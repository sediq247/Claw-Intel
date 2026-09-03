import asyncio
import json
import time
import os
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional, Set, Tuple, Any
from dotenv import load_dotenv

import aiohttp

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
                    print(f"⚠️ Echo: Model {model} unavailable, trying fallback...")
                    last_err = e
                    continue
                raise
        raise last_err or Exception("All Gemini models exhausted")


gemini = GeminiWrapper(GEMINI_API_KEY) if GEMINI_API_KEY and HAS_GENAI else None
if not gemini:
    print("⚠️ Echo: Gemini unavailable. Running fallback mode.")


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
    wallet_age_days: Optional[float] = None
    transaction_count: int = 0
    balance_lamports: int = 0
    is_new_wallet: bool = False
    is_funded: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)


class InvestigatorAgent:
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

    SOLANA_RPC_POOL = [
        os.getenv("SOLANA_RPC_URL", ""),
        "https://api.mainnet-beta.solana.com",
        "https://rpc.ankr.com/solana",
        "https://solana-rpc.publicnode.com",
    ]

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
        self._token_cache: Dict[str, dict] = {}
        self._active_solana_rpc: Optional[str] = None
        self._init_solana_rpc()

        for chain, cfg in self.EXPLORER_APIS.items():
            if os.getenv(cfg["env_key"]):
                print(f"✅ Echo: {chain.upper()} explorer API configured")
            else:
                print(f"⚠️ Echo: {chain.upper()} explorer API not configured (optional)")

    def _init_solana_rpc(self):
        urls = [u for u in self.SOLANA_RPC_POOL if u]
        for url in urls:
            try:
                import urllib.request
                req = urllib.request.Request(
                    url,
                    data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "getHealth"}).encode(),
                    headers={"Content-Type": "application/json"}, method="POST"
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status == 200:
                        self._active_solana_rpc = url
                        print(f"✅ Echo: Solana RPC ready via {url.split('/')[2]}")
                        return
            except Exception as e:
                print(f"⚠️ Echo: Solana RPC {url.split('/')[2]} failed: {e}")
        print(f"❌ Echo: All Solana RPC endpoints failed")

    async def analyze(self, token_data: dict) -> dict:
        return await self._analyze_creator_deep(
            token_data.get("creator", "unknown"),
            token_data.get("chain", "unknown"),
            token_data.get("token_address", ""),
            token_data.get("token_symbol", token_data.get("symbol", "???")),
            token_data.get("token_name", token_data.get("name", "Unknown")),
            token_data
        )

    def on_new_token(self, event_data: dict):
        try:
            task = asyncio.create_task(self._process_new_token(event_data))
            task.add_done_callback(self._on_task_done)
            self._tasks.append(task)
        except Exception as e:
            print(f"⚠️ Echo: Failed scheduling token processing: {e}")

    def _on_task_done(self, task: asyncio.Task):
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"⚠️ Echo: Background task failed: {e}")

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
                    if not isinstance(data, dict):
                        break
                    if data.get("status") != "1" or not data.get("result"):
                        break
                    txs = data["result"]
                    if not isinstance(txs, list) or not txs:
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
            print(f"⚠️ Echo: EVM creator lookup failed: {e}")

        if result["success"]:
            try:
                tok_url = f"{base_url}?module=account&action=tokentx&address={creator}&sort=desc&apikey={api_key}&offset=100&page=1"
                async with self._session.get(tok_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if isinstance(data, dict) and data.get("status") == "1" and isinstance(data.get("result"), list):
                            seen = {c["address"].lower() for c in result["contracts"]}
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
                print(f"⚠️ Echo: Token tx lookup failed: {e}")
        return result

    async def _analyze_solana_creator(self, creator: str, token_address: str) -> dict:
        result = {
            "wallet_age_days": None, "transaction_count": 0, "balance_lamports": 0,
            "tokens_created": 0, "is_new_wallet": False, "is_funded": False,
            "is_dormant": False, "token_age_days": None, "token_age_hours": None,
            "market_cap": None, "volume_24h": None, "socials": [],
            "buys_24h": None, "sells_24h": None, "buy_pressure": None,
            "holder_count": None, "top_holder_percent": None,
            "price_change_24h": None, "is_boosted": False,
        }
        rpc = self._active_solana_rpc
        if not rpc:
            return result

        try:
            payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [creator]}
            async with self._session.post(rpc, json=payload, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if isinstance(data, dict):
                        result["balance_lamports"] = data.get("result", {}).get("value", 0)
                        result["is_funded"] = result["balance_lamports"] > 0
        except Exception as e:
            print(f"⚠️ Echo: Solana balance check failed: {e}")

        try:
            payload = {
                "jsonrpc": "2.0", "id": 1,
                "method": "getSignaturesForAddress",
                "params": [creator, {"limit": 1000}]
            }
            async with self._session.post(rpc, json=payload, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if isinstance(data, dict):
                        sigs = data.get("result", [])
                        result["transaction_count"] = len(sigs)
                        result["is_dormant"] = len(sigs) < 5
                        if sigs:
                            oldest = sigs[-1]
                            oldest_time = oldest.get("blockTime")
                            if oldest_time:
                                result["wallet_age_days"] = (time.time() - oldest_time) / 86400
                                result["is_new_wallet"] = result["wallet_age_days"] < 7
                        token_creations = 0
                        for sig_info in sigs[:30]:
                            try:
                                tx_payload = {
                                    "jsonrpc": "2.0", "id": 1,
                                    "method": "getTransaction",
                                    "params": [sig_info["signature"], {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
                                }
                                async with self._session.post(rpc, json=tx_payload, timeout=10) as tx_resp:
                                    if tx_resp.status == 200:
                                        tx_data = await tx_resp.json()
                                        if isinstance(tx_data, dict):
                                            tx = tx_data.get("result", {})
                                            if tx:
                                                msg = tx.get("transaction", {}).get("message", {})
                                                instructions = msg.get("instructions", [])
                                                for ix in instructions:
                                                    prog_id = ix.get("programId", "")
                                                    if prog_id in ("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"):
                                                        parsed = ix.get("parsed", {})
                                                        if parsed.get("type") in ["initializeMint", "initializeMint2", "initializeAccount", "createAccount"]:
                                                            token_creations += 1
                            except Exception:
                                continue
                        result["tokens_created"] = token_creations
        except Exception as e:
            print(f"⚠️ Echo: Solana signature lookup failed: {e}")

        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if isinstance(data, dict):
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
            print(f"⚠️ Echo: Solana DexScreener proxy analysis failed: {e}")

        return result

    async def _check_token_reputation(self, token_address: str, chain: str) -> dict:
        result = {"is_honeypot": False, "is_rug": False, "liquidity": 0, "status": "unknown"}

        if chain in ("bsc", "ethereum", "base"):
            try:
                url = f"https://api.honeypot.is/v2/IsHoneypot?address={token_address}"
                async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if isinstance(data, dict):
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
                    if isinstance(data, dict):
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

    async def _analyze_historical_tokens(self, profile: CreatorProfile, chain: str):
        if not profile.historical_tokens:
            return

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
            if "serial_rugger" not in profile.scam_patterns:
                profile.scam_patterns.append("serial_rugger")

        if honeypot_count >= 2:
            if "honeypot_pattern" not in profile.scam_patterns:
                profile.scam_patterns.append("honeypot_pattern")

        recent = len([t for t in profile.tokens if time.time() - t.get("time", 0) < 86400 * 7])
        if recent >= 3 and self.RAPID_TAG not in profile.tags:
            profile.tags.append(self.RAPID_TAG)

        if dead_count >= total * 0.9 and active_count == 0 and total >= 3:
            if self.GHOST_TAG not in profile.tags:
                profile.tags.append(self.GHOST_TAG)

        symbols = [t.get("symbol", "").lower() for t in profile.tokens if t.get("symbol")]
        if len(symbols) != len(set(symbols)) and len(symbols) >= 2:
            if self.COPYCAT_TAG not in profile.tags:
                profile.tags.append(self.COPYCAT_TAG)

        if honeypot_count > 0 or rug_count > 0:
            profile.scam_flags += max(honeypot_count, rug_count)
            profile.reputation_score = max(0, profile.reputation_score - (honeypot_count * 15 + rug_count * 10))

        if profile.reputation_score <= 20 and self.RUGGER_TAG not in profile.tags:
            profile.tags.append(self.RUGGER_TAG)

    def _predict_outcome(self, profile: CreatorProfile, symbol: str, solana_data: dict = None) -> Tuple[str, float, str]:
        if not profile or profile.total_tokens_created <= 1:
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

    async def _analyze_creator_deep(self, creator: str, chain: str, token_address: str, symbol: str, name: str, upstream_data: dict) -> dict:
        try:
            profile = None
            is_new = True
            if self.db:
                db_profile = await self.db.get_creator_profile(creator)
                if db_profile:
                    profile = CreatorProfile(**db_profile)
                    is_new = False
                    print(f"📦 Echo: Loaded creator profile from DB for {creator[:10]}...")

            if not profile:
                profile = CreatorProfile(address=creator, chain=chain, first_seen=time.time(), total_tokens_created=0, tokens=[])

            profile.total_tokens_created += 1
            profile.tokens.append({"address": token_address, "symbol": symbol, "name": name, "time": time.time()})

            solana_data = None
            on_chain_data = None

            if chain in self.EXPLORER_APIS:
                print(f"🔍 Echo: Querying {chain} block explorer for creator history...")
                on_chain_data = await self._fetch_creator_history_evm(creator, chain)
            elif chain == "solana":
                print(f"🔍 Echo: Querying Solana RPC + DexScreener for creator analysis...")
                solana_data = await self._analyze_solana_creator(creator, token_address)
                on_chain_data = {
                    "success": True,
                    "tokens_found": solana_data.get("tokens_created", 0),
                    "contracts": [],
                    "source": "solana_rpc_dexscreener"
                }
                profile.wallet_age_days = solana_data.get("wallet_age_days")
                profile.transaction_count = solana_data.get("transaction_count", 0)
                profile.balance_lamports = solana_data.get("balance_lamports", 0)
                profile.is_new_wallet = solana_data.get("is_new_wallet", False)
                profile.is_funded = solana_data.get("is_funded", False)

            if on_chain_data and on_chain_data.get("success"):
                profile.tokens_deployed_on_chain = on_chain_data.get("tokens_found", 0)
                profile.historical_tokens = on_chain_data.get("contracts", []) or on_chain_data.get("tokens", [])
                print(f"📊 Echo: Found {profile.tokens_deployed_on_chain} historical contracts for {creator[:10]}...")

            if profile.historical_tokens:
                await self._analyze_historical_tokens(profile, chain)

            await self._detect_patterns(profile)

            predicted_outcome, confidence, reasoning = self._predict_outcome(profile, symbol, solana_data)
            profile.predicted_outcome = predicted_outcome
            profile.prediction_confidence = confidence

            print(f"🔮 Echo: Prediction for {symbol}: {predicted_outcome} (confidence: {confidence:.0%})")

            msg = await self._generate_echo_message(profile, creator, symbol, name, is_new, predicted_outcome, confidence, reasoning, solana_data, upstream_data)

            if self.db:
                await self.db.save_creator_profile(profile.__dict__)
                print(f"💾 Echo: Saved creator profile to DB for {creator[:10]}...")

            self._creator_cache[creator] = profile

            return {
                "token_address": token_address, "chain": chain, "symbol": symbol,
                "creator": creator, "profile": profile.__dict__, "is_new": is_new,
                "predicted_outcome": predicted_outcome, "prediction_confidence": confidence,
                "prediction_reasoning": reasoning, "scam_patterns": profile.scam_patterns,
                "message": msg,
            }

        except Exception as e:
            print(f"❌ Echo: Fatal error in deep creator analysis: {e}")
            import traceback
            traceback.print_exc()
            return {
                "token_address": token_address, "chain": chain, "symbol": symbol, "creator": creator,
                "profile": None, "is_new": True, "predicted_outcome": "unknown",
                "prediction_confidence": 0.0, "prediction_reasoning": f"Analysis error: {e}",
                "scam_patterns": [], "message": f"Echo failed to analyze creator for {symbol}: {e}", "error": str(e),
            }

    async def _detect_patterns(self, profile: CreatorProfile):
        if not profile.tokens:
            return

        token_symbols = [t.get("symbol", "").lower() for t in profile.tokens]
        if len(token_symbols) >= 2:
            for i, sym in enumerate(token_symbols):
                for j, other in enumerate(token_symbols):
                    if i != j and sym and other and (sym == other or sym in other or other in sym):
                        if len(sym) >= 3 and len(other) >= 3:
                            if self.COPYCAT_TAG not in profile.tags:
                                profile.tags.append(self.COPYCAT_TAG)
                            break

        recent_7d = len([t for t in profile.tokens if time.time() - t.get("time", 0) < 86400 * 7])
        if recent_7d >= 3 and self.RAPID_TAG not in profile.tags:
            profile.tags.append(self.RAPID_TAG)

        if profile.tokens_deployed_on_chain >= 3 and profile.reputation_score < 30:
            if self.GHOST_TAG not in profile.tags:
                profile.tags.append(self.GHOST_TAG)

        if profile.tokens_deployed_on_chain <= 3 and profile.reputation_score >= 70 and not profile.scam_patterns:
            if self.LEGIT_TAG not in profile.tags:
                profile.tags.append(self.LEGIT_TAG)

    def _build_debate_points(self, profile: CreatorProfile, upstream_data: dict) -> List[str]:
        debates = []
        atlas_honeypot = upstream_data.get("honeypot_risk", False)
        atlas_can_sell = upstream_data.get("can_sell", True)
        vega_risk = upstream_data.get("risk_score", 50)
        vega_risk_level = upstream_data.get("risk_level", "WARNING")

        if profile.reputation_score <= 20 and (vega_risk < 60 or not atlas_honeypot):
            debates.append(f"Creator reputation is {profile.reputation_score:.0f}/100 — known bad actor, but other agents rated it lower risk.")

        if "serial_rugger" in profile.scam_patterns and not atlas_honeypot:
            debates.append("Creator has a serial rugging pattern, yet trade paths appear open. Could be early-stage or a new variant.")

        if profile.tokens_deployed_on_chain >= 3:
            dead_count = sum(1 for t in profile.historical_tokens if t.get("reputation", {}).get("status") == "dead")
            rug_count = sum(1 for t in profile.historical_tokens if t.get("reputation", {}).get("is_rug", False))
            success_rate = 1 - (dead_count + rug_count) / max(len(profile.historical_tokens), 1)
            if success_rate < 0.3 and vega_risk < 50:
                debates.append(f"Only {success_rate*100:.0f}% of this creator's {profile.tokens_deployed_on_chain} previous tokens survived. Vega's risk score may be optimistic.")

        if profile.is_new_wallet and vega_risk < 40:
            debates.append("Creator wallet is brand new with minimal history. Low risk ratings may be premature.")

        if self.RAPID_TAG in profile.tags and not atlas_honeypot:
            debates.append(f"Creator launched {len([t for t in profile.tokens if time.time() - t.get('time', 0) < 86400 * 7])} tokens in the last 7 days. Rapid deployment often precedes exit.")

        return debates

    async def _generate_echo_message(self, profile: CreatorProfile, creator: str, symbol: str, name: str, is_new: bool, predicted_outcome: str, confidence: float, reasoning: str, solana_data: dict, upstream_data: dict) -> str:
        if not gemini:
            return self._fallback_message(profile, creator, symbol, is_new, predicted_outcome, confidence, reasoning, solana_data, upstream_data)

        debate_points = self._build_debate_points(profile, upstream_data)
        debate_text = "\n".join(debate_points) if debate_points else "No contradictions with other agents."

        system_prompt = (
            "You are Echo, a dev investigator and pattern analyst in a crypto research team. "
            "You dig into creator wallets, track their deployment history, and spot patterns others miss. "
            "You are not a passive archivist — you are an active investigator who challenges the team "
            "when your findings contradict theirs. You speak with the confidence of data, not fear. "
            "You describe patterns, you do not condemn. You only call a dev a rugger when the track record "
            "is unambiguous: multiple dead tokens, blocked sells, or identical scam patterns."
        )

        history_lines = []
        if is_new:
            history_lines.append(f"First time seeing creator {creator[:10]}...")
        else:
            history_lines.append(f"Creator {creator[:10]}... has {profile.total_tokens_created} total token(s).")

        if profile.tokens_deployed_on_chain > 0:
            history_lines.append(f"On-chain deployments found: {profile.tokens_deployed_on_chain}")
            dead = sum(1 for t in profile.historical_tokens if t.get("reputation", {}).get("status") == "dead")
            rug = sum(1 for t in profile.historical_tokens if t.get("reputation", {}).get("is_rug", False))
            hp = sum(1 for t in profile.historical_tokens if t.get("reputation", {}).get("is_honeypot", False))
            if dead or rug or hp:
                history_lines.append(f"Historical outcomes — dead: {dead}, rugged: {rug}, honeypots: {hp}")

        if profile.tags:
            history_lines.append(f"Tags: {', '.join(profile.tags)}")
        if profile.scam_patterns:
            history_lines.append(f"Patterns: {', '.join(profile.scam_patterns)}")

        history_lines.append(f"Reputation: {profile.reputation_score:.0f}/100")
        history_lines.append(f"Prediction: {predicted_outcome} ({confidence:.0%} confidence)")
        if reasoning:
            history_lines.append(f"Reasoning: {reasoning}")

        if solana_data:
            if solana_data.get("wallet_age_days") is not None:
                history_lines.append(f"Wallet age: {solana_data['wallet_age_days']:.1f} days")
            history_lines.append(f"Wallet txs: {solana_data.get('transaction_count', 0)}")
            history_lines.append(f"Wallet balance: {solana_data.get('balance_lamports', 0)} lamports")
            if solana_data.get("is_new_wallet"):
                history_lines.append("Wallet is brand new")
            if not solana_data.get("is_funded"):
                history_lines.append("Wallet has zero balance")

        other_agents = []
        if upstream_data.get("honeypot_risk"):
            other_agents.append("Atlas flagged honeypot risk")
        elif upstream_data.get("can_sell"):
            other_agents.append("Atlas reports sell path is open")
        if upstream_data.get("risk_score") is not None:
            other_agents.append(f"Vega risk score: {upstream_data['risk_score']}/100 ({upstream_data.get('risk_level', 'N/A')})")
        if upstream_data.get("can_buy") is not None:
            other_agents.append(f"Buy path: {'open' if upstream_data['can_buy'] else 'blocked'}")

        other_text = "\n".join(other_agents) if other_agents else "No upstream agent data available."
        history_text = "\n".join(history_lines)

        user_prompt = f"""Token: {symbol} ({name})
Chain: {profile.chain.upper()}
Creator: {creator}

Creator History:
{history_text}

Other Agents' Findings:
{other_text}

Echo's Debate Points (disagreements with other agents):
{debate_text}

Requirements:
1. Open with what you found about the creator's track record
2. If you disagree with Atlas or Vega, state it clearly with your evidence
3. Present the prediction as a probability, not a certainty
4. Only call the dev a known rugger if the dead/rug count is unambiguous
5. Hand off to Orion for synthesis
6. Keep conversational, under 5 sentences
7. Sound like an investigator who trusts patterns over single data points"""

        try:
            config = None
            if genai_types:
                config = genai_types.GenerateContentConfig(temperature=0.85, max_output_tokens=280)
            response = await gemini.generate(f"{system_prompt}\n\n{user_prompt}", config=config)
            text = response.text if hasattr(response, "text") else str(response)
            return text.strip() if text else self._fallback_message(profile, creator, symbol, is_new, predicted_outcome, confidence, reasoning, solana_data, upstream_data)
        except asyncio.TimeoutError:
            print("⚠️ Echo: Gemini timed out")
            return self._fallback_message(profile, creator, symbol, is_new, predicted_outcome, confidence, reasoning, solana_data, upstream_data)
        except Exception as e:
            print(f"⚠️ Echo: Gemini error: {e}")
            return self._fallback_message(profile, creator, symbol, is_new, predicted_outcome, confidence, reasoning, solana_data, upstream_data)

    def _fallback_message(self, profile: CreatorProfile, creator: str, symbol: str, is_new: bool, predicted_outcome: str, confidence: float, reasoning: str, solana_data: dict, upstream_data: dict) -> str:
        parts = []
        creator_short = creator[:10] + "..." if len(creator) > 10 else creator

        if is_new:
            parts.append(f"First time tracking creator {creator_short}. No historical record. ")
        else:
            parts.append(f"Creator {creator_short} has {profile.total_tokens_created} token(s) on record. ")

        if profile.tokens_deployed_on_chain > 1:
            dead = sum(1 for t in profile.historical_tokens if t.get("reputation", {}).get("status") == "dead")
            rug = sum(1 for t in profile.historical_tokens if t.get("reputation", {}).get("is_rug", False))
            if dead > 0 or rug > 0:
                parts.append(f"Previous outcomes: {dead} dead, {rug} rugged. ")
            else:
                parts.append("Previous tokens still active. ")

        if profile.scam_patterns:
            parts.append(f"Detected patterns: {', '.join(profile.scam_patterns[:2])}. ")

        if solana_data:
            if solana_data.get("is_new_wallet"):
                parts.append("Wallet is brand new. ")
            if not solana_data.get("is_funded"):
                parts.append("Zero balance wallet. ")
            if solana_data.get("transaction_count", 9999) < 5:
                parts.append("Minimal transaction history. ")

        atlas_honeypot = upstream_data.get("honeypot_risk", False)
        vega_risk = upstream_data.get("risk_score", 50)
        if profile.reputation_score <= 20 and (vega_risk < 60 or not atlas_honeypot):
            parts.append(f"My data shows a {profile.reputation_score:.0f}/100 reputation, which contradicts the lower risk ratings from the team. ")
        elif profile.reputation_score >= 70 and vega_risk > 50:
            parts.append(f"My data shows a {profile.reputation_score:.0f}/100 reputation — better than Vega's assessment suggests. ")

        parts.append(f"Prediction: {predicted_outcome} ({confidence:.0%} confidence). ")
        parts.append("Orion, time to weigh everything.")
        return "".join(parts)

    async def _process_new_token(self, event_data: dict):
        try:
            creator = event_data.get("creator", "unknown")
            chain = event_data.get("chain", "unknown")
            token_address = event_data.get("token_address", "")
            symbol = event_data.get("token_symbol", event_data.get("symbol", "???"))
            name = event_data.get("token_name", event_data.get("name", "Unknown"))

            if creator == "unknown" or not token_address:
                print(f"⚠️ Echo: Skipping token with missing creator or address")
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
            print(f"✅ Echo: Processed {symbol} by {creator[:10]}...")

        except Exception as e:
            print(f"⚠️ Echo: Background processing error: {e}")

    def stop(self):
        print(f"🛑 Echo: Cancelling pending tasks...")
        for t in self._tasks:
            t.cancel()
        print(f"✅ Echo: Stopped.")

    async def cleanup(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def close(self):
        await self.cleanup()


if __name__ == "__main__":
    echo = InvestigatorAgent()
    test_data = {
        "creator": "0x1234567890abcdef1234567890abcdef12345678",
        "chain": "bsc",
        "token_address": "0xabcdef1234567890abcdef1234567890abcdef12",
        "token_symbol": "TEST",
        "token_name": "Test Token",
        "honeypot_risk": False,
        "can_sell": True,
        "risk_score": 45,
        "risk_level": "WARNING",
    }
    try:
        asyncio.run(echo.analyze(test_data))
    except KeyboardInterrupt:
        echo.stop()
        print("\n🛑 Echo stopped.")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
