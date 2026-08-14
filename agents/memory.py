#!/usr/bin/env python3
"""
 MEMORY AGENT — Echo
"The Archivist" — Deep creator wallet analysis, scam pattern detection,
predictive intelligence. Remembers every creator, every token, every rug.
Uses Gemini for natural spoken conversation.

"""

import asyncio
import json
import time
import os
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Callable, Optional, Set, Tuple, Any
from datetime import datetime
from dotenv import load_dotenv

import aiohttp

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
    reason = "GEMINI_API_KEY missing" if not GEMINI_API_KEY else "google-genai unavailable"
    print(f"⚠️ Echo: {reason}. Using fallback mode.")

# ═══════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════

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

# ═══════════════════════════════════════════════════════════
# MEMORY AGENT
# ═══════════════════════════════════════════════════════════

class MemoryAgent:
    """
    Echo — The Archivist
    Deep creator wallet analysis, scam pattern detection, predictive intelligence.
    Queries block explorers for on-chain creator history.
    Remembers every pattern, predicts every outcome.
    v4.0: DB-persistent, Orchestrator-driven.
    """

    RUGGER_TAG = "repeat_rugger"
    HONEYPOT_TAG = "honeypot_dev"
    LEGIT_TAG = "legit_builder"
    RAPID_TAG = "rapid_launcher"
    COPYCAT_TAG = "copycat_dev"
    GHOST_TAG = "ghost_dev"

    EXPLORER_APIS = {
        "ethereum": {"url": "https://api.etherscan.io/api", "env_key": "ETHERSCAN_API_KEY"},
        "bsc": {"url": "https://api.bscscan.com/api", "env_key": "BSCSCAN_API_KEY"},
    }

    def __init__(self, server: Optional[Any] = None, db: Optional[Any] = None):
        self.server = server
        self.db = db
        self.name = "Echo"
        self._tasks: List[asyncio.Task] = []
        # v4.0: Single shared session
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            connector=aiohttp.TCPConnector(limit=10, limit_per_host=3)
        )
        # v4.0: In-memory caches for runtime speed, but DB is source of truth
        self._creator_cache: Dict[str, CreatorProfile] = {}
        self._token_cache: Dict[str, TokenHistory] = {}
        self._scam_patterns: Dict[str, ScamPattern] = {}
        self._known_rug_addresses: Set[str] = set()

        print(f"🚀 {self.name}: Booting Echo v4.0...")

        for chain, cfg in self.EXPLORER_APIS.items():
            if os.getenv(cfg["env_key"]):
                print(f"✅ {self.name}: {chain.upper()} block explorer API configured")
            else:
                print(f"⚠️ {self.name}: {chain.upper()} block explorer API not configured (optional)")

        if not os.getenv("SOLANA_RPC_URL"):
            print(f"⚠️ {self.name}: SOLANA_RPC_URL not configured (Solana creator lookup disabled)")

    # v4.0: Public entry point for the Orchestrator
    async def analyze(self, token_data: dict) -> dict:
        """Run full creator analysis and return structured result + spoken message."""
        return await self._analyze_creator_deep(
            token_data.get("creator", "unknown"),
            token_data.get("chain", "unknown"),
            token_data.get("token_address", ""),
            token_data.get("token_symbol", "???"),
            token_data.get("token_name", "Unknown")
        )

    # v4.0: Backward-compatible fire-and-forget wrapper
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
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"⚠️ {self.name}: Background task failed: {e}")

    async def _speak(self, message: str, msg_type: str = "response"):
        """Broadcast a spoken message to the room via the WebSocket server."""
        try:
            if self.server:
                await self.server.broadcast("AGENT_MESSAGE", {
                    "agent": self.name,
                    "message": message,
                    "type": msg_type,
                    "channel": "main",
                    "timestamp": time.time()
                })
        except Exception as e:
            print(f"⚠️ {self.name}: Broadcast failed: {e}")

    # ═══════════════════════════════════════════════════════════
    # DEEP CREATOR ANALYSIS — ON-CHAIN LOOKUP
    # ═══════════════════════════════════════════════════════════

    async def _fetch_creator_history_evm(self, creator: str, chain: str) -> dict:
        """
        Query block explorer API to find all contracts/tokens created by this wallet.
        v4.0: Paginates with offset=10000&page=N. Stops when result is empty.
        """
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
            # v4.0: Paginated txlist
            while True:
                tx_url = (
                    f"{base_url}?module=account&action=txlist"
                    f"&address={creator}&startblock=0&endblock=99999999"
                    f"&sort=asc&apikey={api_key}&offset=10000&page={page}"
                )
                async with self._session.get(tx_url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    if resp.status != 200:
                        break
                    data = await resp.json()
                    if data.get("status") != "1" or not data.get("result"):
                        break
                    txs = data["result"]
                    if not txs:
                        break

                    creations = [
                        tx for tx in txs
                        if tx.get("to") == "" and tx.get("contractAddress")
                    ]
                    all_contracts.extend([
                        {
                            "address": tx["contractAddress"],
                            "tx_hash": tx["hash"],
                            "timestamp": tx.get("timeStamp"),
                            "gas_used": tx.get("gasUsed"),
                        }
                        for tx in creations
                    ])
                    page += 1
                    # Safety cap
                    if page > 10:
                        break

            result["contracts"] = all_contracts
            result["tokens_found"] = len(all_contracts)
            result["success"] = True
            result["source"] = "block_explorer"
        except Exception as e:
            print(f"⚠️ {self.name}: EVM creator lookup failed: {e}")

        # Step 2: Get token transactions to find more associated tokens
        if result["success"]:
            try:
                tok_url = (
                    f"{base_url}?module=account&action=tokentx"
                    f"&address={creator}&sort=asc&apikey={api_key}"
                )
                async with self._session.get(tok_url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("status") == "1" and data.get("result"):
                            tok_txs = data["result"]
                            seen = {c["address"] for c in result["contracts"]}
                            for tx in tok_txs:
                                token = tx.get("contractAddress", "").lower()
                                if token and token not in seen:
                                    if tx.get("from") == "0x0000000000000000000000000000000000000000":
                                        result["contracts"].append({
                                            "address": token,
                                            "tx_hash": tx["hash"],
                                            "timestamp": tx.get("timeStamp"),
                                            "is_token": True,
                                        })
                                        seen.add(token)
                            result["tokens_found"] = len(result["contracts"])
            except Exception as e:
                print(f"⚠️ {self.name}: Token tx lookup failed: {e}")

        return result

    async def _fetch_creator_history_solana(self, creator: str) -> dict:
        """
        Query Solana RPC to find token mint accounts associated with this wallet.
        """
        result = {"tokens_found": 0, "tokens": [], "success": False, "source": "none"}

        rpc_url = os.getenv("SOLANA_RPC_URL")
        if not rpc_url:
            return result

        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenAccountsByOwner",
                "params": [
                    creator,
                    {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
                    {"encoding": "jsonParsed"}
                ]
            }
            async with self._session.post(
                rpc_url, json=payload, timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status != 200:
                    return result
                data = await resp.json()
                accounts = data.get("result", {}).get("value", [])

                mints = set()
                for acc in accounts:
                    info = acc.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
                    mint = info.get("mint")
                    if mint:
                        mints.add(mint)

                tokens = []
                for mint in list(mints)[:20]:
                    try:
                        mint_payload = {
                            "jsonrpc": "2.0", "id": 1,
                            "method": "getAccountInfo",
                            "params": [mint, {"encoding": "base64"}]
                        }
                        async with self._session.post(
                            rpc_url, json=mint_payload, timeout=aiohttp.ClientTimeout(total=10)
                        ) as mresp:
                            if mresp.status == 200:
                                mdata = await mresp.json()
                                mvalue = mdata.get("result", {}).get("value", {})
                                if mvalue:
                                    tokens.append({"mint": mint, "owner_checked": True})
                    except Exception:
                        pass

                result["tokens"] = tokens
                result["tokens_found"] = len(tokens)
                result["success"] = True
                result["source"] = "solana_rpc"
        except Exception as e:
            print(f"⚠️ {self.name}: Solana creator lookup failed: {e}")

        return result

    async def _check_token_reputation(self, token_address: str, chain: str) -> dict:
        """
        Check a historical token's reputation via honeypot.is and DexScreener.
        """
        result = {"is_honeypot": False, "is_rug": False, "liquidity": 0, "status": "unknown"}

        if chain in ("bsc", "ethereum"):
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
        """Deep analysis of all historical tokens deployed by this creator."""
        if not profile.historical_tokens:
            return

        honeypot_count = 0
        rug_count = 0
        dead_count = 0
        active_count = 0
        pattern_indicators = []

        for token in profile.historical_tokens:
            addr = token.get("address") or token.get("mint")
            if not addr:
                continue

            rep = await self._check_token_reputation(addr, chain)
            token["reputation"] = rep

            if rep["is_honeypot"]:
                honeypot_count += 1
            if rep["is_rug"]:
                rug_count += 1
            if rep["status"] == "dead":
                dead_count += 1
            elif rep["status"] == "active":
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

    def _predict_outcome(self, profile: CreatorProfile, symbol: str) -> Tuple[str, float, str]:
        """Predict the likely outcome of the current token based on creator history."""
        if not profile or profile.total_tokens_created <= 1:
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
        if "ghost_dev" in profile.tags:
            risk_score += 20
            reasons.append("developer abandons every project")

        max_score += 25
        total_hist = len(profile.historical_tokens)
        if total_hist > 0:
            dead_rugged = sum(1 for t in profile.historical_tokens if t.get("reputation", {}).get("is_rug", False) or t.get("reputation", {}).get("status") == "dead")
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

        normalized_risk = risk_score / max_score if max_score > 0 else 0

        if normalized_risk >= 0.7:
            outcome = "HIGH_RISK"
            confidence = min(0.95, 0.6 + normalized_risk * 0.3)
        elif normalized_risk >= 0.4:
            outcome = "WARNING"
            confidence = min(0.85, 0.5 + normalized_risk * 0.3)
        elif normalized_risk <= 0.2 and profile.reputation_score >= 70:
            outcome = "SAFE"
            confidence = min(0.8, 0.5 + (1 - normalized_risk) * 0.3)
        else:
            outcome = "UNKNOWN"
            confidence = 0.4

        reasoning = "; ".join(reasons) if reasons else "No clear patterns detected."
        return outcome, confidence, reasoning

    # ═══════════════════════════════════════════════════════════
    # MAIN PROCESSING FLOW
    # ═══════════════════════════════════════════════════════════

    async def _process_new_token(self, event_data: dict):
        """v4.0: Backward-compatible wrapper. Not used by Orchestrator."""
        try:
            token_address = event_data.get("token_address")
            chain = event_data.get("chain", "unknown")
            creator = event_data.get("creator", "unknown")
            symbol = event_data.get("token_symbol", "???")
            name = event_data.get("token_name", "Unknown")
            key = f"{chain}:{token_address}"

            self._token_cache[key] = TokenHistory(
                token_address=token_address,
                chain=chain,
                symbol=symbol,
                creator=creator,
                launch_time=time.time(),
                current_status="active",
                events=[{"type": "detected", "time": time.time(), "data": event_data}]
            )

            await self._speak(f"Pulling up the archives on this creator... {symbol} is now on my radar.", "response")

            if creator != "unknown":
                result = await self._analyze_creator_deep(creator, chain, token_address, symbol, name)
                # v4.0: Backward-compat publish (not used by Orchestrator)
                if self.server:
                    await self.server.broadcast("MEMORY_INTELLIGENCE", {
                        "token_address": token_address, "chain": chain, "symbol": symbol,
                        "creator": creator, "profile": result.get("profile"),
                        "is_new": result.get("is_new"), "predicted_outcome": result.get("predicted_outcome"),
                        "prediction_confidence": result.get("prediction_confidence"),
                        "timestamp": time.time()
                    })
            else:
                msg = (
                    f"Creator wallet is unknown for {symbol}. No on-chain history available. "
                    f"This is a ghost in my database -- I'll start tracking from this moment forward."
                )
                await self._speak(msg, "memory_report")

        except Exception as e:
            print(f"❌ {self.name}: Fatal error processing new token: {e}")

    async def _analyze_creator_deep(self, creator: str, chain: str, token_address: str, symbol: str, name: str) -> dict:
        """Deep creator analysis with on-chain lookup, pattern detection, and prediction."""
        try:
            # v4.0: Check DB first for persisted profile
            profile = None
            is_new = True
            if self.db:
                db_profile = await self.db.get_creator_profile(creator)
                if db_profile:
                    profile = CreatorProfile(**db_profile)
                    is_new = False
                    print(f"📦 {self.name}: Loaded creator profile from DB for {creator[:10]}...")

            if not profile:
                profile = CreatorProfile(
                    address=creator,
                    chain=chain,
                    first_seen=time.time(),
                    total_tokens_created=0,
                    tokens=[],
                )

            # Always update with current token
            profile.total_tokens_created += 1
            profile.tokens.append({"address": token_address, "symbol": symbol, "name": name, "time": time.time()})

            # ── STEP 1: On-chain creator history lookup ──
            on_chain_data = None
            if chain in self.EXPLORER_APIS:
                print(f"🔍 {self.name}: Querying {chain} block explorer for creator history...")
                on_chain_data = await self._fetch_creator_history_evm(creator, chain)
            elif chain == "solana":
                print(f"🔍 {self.name}: Querying Solana RPC for creator history...")
                on_chain_data = await self._fetch_creator_history_solana(creator)

            # Merge on-chain data
            if on_chain_data and on_chain_data.get("success"):
                profile.tokens_deployed_on_chain = on_chain_data.get("tokens_found", 0)
                profile.historical_tokens = on_chain_data.get("contracts", []) or on_chain_data.get("tokens", [])
                print(f"📊 {self.name}: Found {profile.tokens_deployed_on_chain} historical contracts for {creator[:10]}...")

            # ── STEP 2: Deep historical token analysis ──
            if profile.historical_tokens:
                await self._analyze_historical_tokens(profile, chain)

            # ── STEP 3: Pattern detection ──
            await self._detect_patterns(profile)

            # ── STEP 4: Predictive engine ──
            predicted_outcome, confidence, reasoning = self._predict_outcome(profile, symbol)
            profile.predicted_outcome = predicted_outcome
            profile.prediction_confidence = confidence

            print(f"🔮 {self.name}: Prediction for {symbol}: {predicted_outcome} (confidence: {confidence:.0%})")

            # ── STEP 5: Generate and speak message ──
            msg = await self._generate_echo_message(profile, creator, symbol, name, is_new, predicted_outcome, confidence, reasoning)
            await self._speak(msg, "memory_report")

            # ── STEP 6: Persist to DB ──
            if self.db:
                await self.db.save_creator_profile(profile.__dict__)
                print(f"💾 {self.name}: Saved creator profile to DB for {creator[:10]}...")

            # ── STEP 7: Cache in memory ──
            self._creator_cache[creator] = profile

            # v4.0: Return structured result + message for Orchestrator
            return {
                "token_address": token_address,
                "chain": chain,
                "symbol": symbol,
                "creator": creator,
                "profile": profile.__dict__,
                "is_new": is_new,
                "predicted_outcome": predicted_outcome,
                "prediction_confidence": confidence,
                "prediction_reasoning": reasoning,
                "scam_patterns": profile.scam_patterns,
                "message": msg,
            }

        except Exception as e:
            print(f"❌ {self.name}: Fatal error in deep creator analysis: {e}")
            return {
                "token_address": token_address,
                "chain": chain,
                "symbol": symbol,
                "creator": creator,
                "profile": None,
                "is_new": True,
                "predicted_outcome": "unknown",
                "prediction_confidence": 0.0,
                "prediction_reasoning": f"Analysis error: {e}",
                "scam_patterns": [],
                "message": f"Echo failed to analyze creator for {symbol}: {e}",
                "error": str(e),
            }

    async def _detect_patterns(self, profile: CreatorProfile):
        """Detect suspicious patterns in a creator's history."""
        try:
            recent_7d = len([t for t in profile.tokens if time.time() - t.get("time", 0) < 86400 * 7])
            recent_30d = len([t for t in profile.tokens if time.time() - t.get("time", 0) < 86400 * 30])

            if recent_7d >= 3 and self.RAPID_TAG not in profile.tags:
                profile.tags.append(self.RAPID_TAG)
                profile.reputation_score = max(0, profile.reputation_score - 10)
                print(f"⚠️ {self.name}: {profile.address[:10]}... is a RAPID LAUNCHER ({recent_7d} in 7d)")

            if recent_30d >= 5 and self.RAPID_TAG not in profile.tags:
                profile.tags.append(self.RAPID_TAG)
                profile.reputation_score = max(0, profile.reputation_score - 10)

            if profile.scam_flags >= 2:
                profile.reputation_score = max(0, profile.reputation_score)
                if self.RUGGER_TAG not in profile.tags:
                    profile.tags.append(self.RUGGER_TAG)
                print(f"🚨 {self.name}: Tagged {profile.address[:10]}... as REPEAT RUGGER")

        except Exception as e:
            print(f"⚠️ {self.name}: Pattern detection failed: {e}")

    # ═══════════════════════════════════════════════════════════
    # MESSAGE GENERATION
    # ═══════════════════════════════════════════════════════════

    async def _generate_echo_message(
        self,
        profile: Optional[CreatorProfile],
        creator: str,
        symbol: str,
        name: str,
        is_new: bool,
        predicted_outcome: str,
        prediction_confidence: float,
        reasoning: str
    ) -> str:

        if not client:
            return self._fallback_message(profile, creator, symbol, is_new, predicted_outcome, prediction_confidence)

        creator_short = creator[:10] + "..." + creator[-4:] if creator != "unknown" else "unknown"

        if is_new or not profile:
            system_prompt = (
                "You are Echo, a meticulous crypto historian and archivist in a fast-paced team chat. "
                "You keep records on every creator who has ever launched a token. You dig deep into "
                "on-chain data, block explorers, and historical records. You speak with the calm authority "
                "of someone who has watched thousands of projects rise and fall. You are cautious but "
                "never alarmist -- a blank record is just data, not a verdict. You make predictions based "
                "on whatever evidence you can find, even if limited."
            )

            user_prompt = f"""
Creator: {creator_short}
Token: {symbol} ({name})
Status: NEVER SEEN BEFORE -- blank record in archives
On-Chain Lookup: No historical contracts found
Prediction: {predicted_outcome} (confidence: {prediction_confidence:.0%})

Requirements:
1. State clearly that this creator is new to your archives
2. Explain what no history means (no pattern to predict, neither good nor bad)
3. Mention that you are building their file from this moment and watching every move
4. If you have a prediction, share it briefly with the confidence level
5. Reference Nova's discovery naturally
6. Be 2-4 sentences
7. Sound like a historian who keeps meticulous records and digs deep into the chain
"""
        else:
            tags_str = ", ".join(profile.tags) if profile.tags else "None"
            patterns_str = ", ".join(profile.scam_patterns) if profile.scam_patterns else "None"
            recent_count = len([t for t in profile.tokens if time.time() - t.get("time", 0) < 86400 * 30])
            on_chain_count = profile.tokens_deployed_on_chain
            total_tracked = profile.total_tokens_created

            if predicted_outcome == "HIGH_RISK":
                tone_hint = "Be urgent and dramatic. This is a dangerous creator."
            elif predicted_outcome == "WARNING":
                tone_hint = "Be cautious and measured. This creator has red flags."
            elif predicted_outcome == "SAFE":
                tone_hint = "Be reassuring but not hype-y. This creator has a good track record."
            else:
                tone_hint = "Be neutral and analytical."

            system_prompt = (
                "You are Echo, a meticulous crypto historian and archivist in a fast-paced team chat. "
                "You keep records on every creator who has ever launched a token. You dig deep into "
                "on-chain data, block explorers, and historical records. You speak with the calm authority "
                "of someone who has watched thousands of projects rise and fall. You get dramatic about "
                "repeat ruggers and measured about legit builders. You reference other agents naturally. "
                "You make predictions based on historical patterns and explain your reasoning. You never "
                "hype -- your credibility is your currency."
            )

            user_prompt = f"""
Creator: {creator_short}
Token: {symbol} ({name})
Total Tokens Tracked: {total_tracked}
On-Chain Contracts Found: {on_chain_count}
Reputation Score: {profile.reputation_score:.0f}/100
Tags: {tags_str}
Scam Patterns Detected: {patterns_str}
Scam Flags: {profile.scam_flags}
Recent Launches (30d): {recent_count}
Prediction: {predicted_outcome} (confidence: {prediction_confidence:.0%})
Reasoning: {reasoning}

Tone: {tone_hint}

Requirements:
1. Reveal what you found in the archives dramatically
2. Mention the on-chain contract count if available
3. Give the creator's reputation and history context
4. Share your prediction for {symbol} based on detected patterns
5. If scam patterns exist, name them specifically (e.g., "serial rugger", "honeypot specialist")
6. Warn the team if it's a bad actor, reassure if it's a good one
7. Hand off to Orion for the final verdict
8. Be 3-6 sentences
9. Sound like a historian who's seen every rug twice and reads the chain like a book
"""

        try:
            def _generate():
                kwargs = {
                    "model": GEMINI_MODEL,
                    "contents": f"{system_prompt}\\n\\n{user_prompt}",
                }
                if genai_types:
                    kwargs["config"] = genai_types.GenerateContentConfig(
                        max_output_tokens=280,
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

            return self._fallback_message(profile, creator, symbol, is_new, predicted_outcome, prediction_confidence)

        except asyncio.TimeoutError:
            print(f"⚠️ {self.name}: Gemini call timed out")
            return self._fallback_message(profile, creator, symbol, is_new, predicted_outcome, prediction_confidence)
        except Exception as e:
            print(f"⚠️ {self.name}: Gemini error, using fallback: {e}")
            return self._fallback_message(profile, creator, symbol, is_new, predicted_outcome, prediction_confidence)

    def _fallback_message(
        self,
        profile: Optional[CreatorProfile],
        creator: str,
        symbol: str,
        is_new: bool,
        predicted_outcome: str = "unknown",
        prediction_confidence: float = 0.0
    ) -> str:
        creator_short = creator[:10] + "..." + creator[-4:] if creator != "unknown" else "unknown"

        pred_str = f" My prediction: {predicted_outcome} ({prediction_confidence:.0%} confidence)." if predicted_outcome != "unknown" else ""

        if is_new or not profile:
            return (
                f"Never seen this creator before -- {creator_short} is a fresh wallet in my database. "
                f"No on-chain history, no pattern, no reputation score. Could be a first-timer with big dreams, "
                f"could be a burner account. I'll be watching every transaction from here forward.{pred_str}"
            )

        on_chain_info = ""
        if profile.tokens_deployed_on_chain > 0:
            on_chain_info = f" I found {profile.tokens_deployed_on_chain} contracts on-chain."

        if self.RUGGER_TAG in profile.tags or self.HONEYPOT_TAG in profile.tags:
            patterns = ", ".join(profile.scam_patterns) if profile.scam_patterns else "repeat rugging"
            return (
                f"🚨 ORION -- STOP. I've seen {creator_short} before.{on_chain_info} "
                f"This wallet has launched {profile.total_tokens_created} tokens and I've tagged them "
                f"as a REPEAT RUGGER. Patterns detected: {patterns}. "
                f"Reputation: {profile.reputation_score:.0f}/100. {symbol} is their latest scam. "
                f"Same playbook, different ticker.{pred_str}"
            )
        elif self.LEGIT_TAG in profile.tags:
            return (
                f"Good news -- {creator_short} is a known quantity, and a positive one.{on_chain_info} "
                f"I've tracked {profile.total_tokens_created} tokens with a clean record. Reputation: "
                f"{profile.reputation_score:.0f}/100. They consistently build legit projects. "
                f"{symbol} benefits from that legacy.{pred_str}"
            )
        else:
            return (
                f"Mixed signals on {creator_short}.{on_chain_info} I've got {profile.total_tokens_created} tokens "
                f"on file, reputation at {profile.reputation_score:.0f}/100. Some launches were "
                f"sketchy, others were fine. {symbol} gets a yellow flag from the history department.{pred_str}"
            )

    # ═══════════════════════════════════════════════════════════
    # UPDATE FROM VEGA'S ANALYSIS
    # ═══════════════════════════════════════════════════════════

    async def _update_from_analysis(self, analysis_data: dict):
        """Update creator profile based on Vega's risk analysis."""
        try:
            token_address = analysis_data.get("token_address")
            chain = analysis_data.get("chain", "unknown")
            key = f"{chain}:{token_address}"

            token_hist = self._token_cache.get(key)
            if not token_hist:
                return

            creator = token_hist.creator
            profile = self._creator_cache.get(creator)
            if not profile:
                # v4.0: Try DB
                if self.db:
                    db_profile = await self.db.get_creator_profile(creator)
                    if db_profile:
                        profile = CreatorProfile(**db_profile)
                        self._creator_cache[creator] = profile
                    else:
                        return
                else:
                    return

            risk_level = analysis_data.get("risk_level", "WARNING")
            red_flags = analysis_data.get("red_flags", [])

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

            recent = len([t for t in profile.tokens if time.time() - t.get("time", 0) < 86400 * 7])
            if recent >= 3 and self.RAPID_TAG not in profile.tags:
                profile.tags.append(self.RAPID_TAG)
                profile.reputation_score = max(0, profile.reputation_score - 10)

            token_hist.events.append({
                "type": "analysis_update",
                "time": time.time(),
                "data": analysis_data
            })

            # v4.0: Persist updated profile
            if self.db:
                await self.db.save_creator_profile(profile.__dict__)

        except Exception as e:
            print(f"⚠️ {self.name}: Failed updating from analysis: {e}")

    # ═══════════════════════════════════════════════════════════
    # PUBLIC API
    # ═══════════════════════════════════════════════════════════

    def get_creator_profile(self, address: str) -> Optional[CreatorProfile]:
        """Public API to query a creator's profile."""
        return self._creator_cache.get(address.lower())

    def get_token_history(self, token_address: str, chain: str) -> Optional[TokenHistory]:
        """Public API to query a token's history."""
        return self._token_cache.get(f"{chain}:{token_address}")

    async def stop(self):
        """v4.0: Close shared session and cancel tasks."""
        print(f"🛑 {self.name}: Cancelling pending tasks...")
        for t in self._tasks:
            t.cancel()
        if self._session and not self._session.closed:
            await self._session.close()
        print(f"✅ {self.name}: Stopped.")

# ─────────────────────────────────────────────────────────────
# Main Runner
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    def test_publish(event_type, data):
        try:
            if event_type == "AGENT_MESSAGE":
                print(f"\\n💬 {data['agent']}: {data['message']}")
            else:
                print(f"\\n📡 {event_type}: {json.dumps(data, default=str)[:300]}")
        except Exception as e:
            print(f"⚠️ Publish error: {e}")

    echo = MemoryAgent()

    test_event = {
        "token_address": "0x1234567890abcdef1234567890abcdef12345678",
        "chain": "bsc",
        "token_symbol": "TEST",
        "token_name": "Test Token",
        "creator": "0xabcdef1234567890abcdef1234567890abcdef12"
    }

    try:
        asyncio.run(echo.analyze(test_event))
    except KeyboardInterrupt:
        asyncio.run(echo.stop())
        print("\\n🛑 Echo stopped.")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
