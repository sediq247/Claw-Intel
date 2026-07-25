#!/usr/bin/env python3
"""
WATCHER AGENT — Nova v3.1-FIXED
"The Scout" — Multi-chain token detection engine.

FIXES v3.1:
- _supervise() now uses functools.partial for bulletproof arg binding
- _passes_quality_check() initializes all locals before any await + wraps in try/except
- _fetch_dexscreener_token() returns {} for ANY non-200 status (was falling through)
- get_logs() uses correct Web3.py v6 camelCase kwargs: fromBlock / toBlock
- Added defensive null checks on all DexScreener market_data accesses
- Solana watcher outer loop wrapped in broader exception handling
"""

import asyncio
import json
import os
import time
import random
from functools import partial
from collections import deque
from dataclasses import dataclass, asdict
from typing import Optional, Callable

import aiohttp
from web3 import Web3
from dotenv import load_dotenv
try:
    from google import genai
    HAS_GENAI = True
except ImportError:
    genai = None
    HAS_GENAI = False
    print("⚠️ Nova: google-genai package not found. Gemini disabled.")

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")

client = None
if GEMINI_API_KEY and HAS_GENAI:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        print("Nova: Gemini client initialized")
    except Exception as e:
        print(f"Nova: Gemini init failed: {e}")
        client = None
else:
    reason = "GEMINI_API_KEY missing" if not GEMINI_API_KEY else "google-genai unavailable"
    print(f"Nova: {reason}. Running in fallback mode.")


@dataclass
class TokenEvent:
    event_type: str
    chain: str
    token_address: str
    token_symbol: str
    token_name: str
    creator: str
    timestamp: float
    block_number: Optional[int] = None
    liquidity_usd: Optional[float] = None
    market_cap: Optional[float] = None
    volume_24h: Optional[float] = None
    origin_source: str = "unknown"
    raw_data: Optional[dict] = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)


class WatcherAgent:
    """
    Nova — The Scout
    RPC-based surveillance across 7 EVM chains + Solana.
    """

    RPC_POOLS = {
        "ethereum": [
            "https://ethereum-rpc.publicnode.com",
            "https://rpc.ankr.com/eth",
            "https://eth.llamarpc.com",
            "https://eth.rpc.grove.city",
        ],
        "bsc": [
            "https://bsc-rpc.publicnode.com",
            "https://rpc.ankr.com/bsc",
            "https://bsc-dataseed.binance.org/",
            "https://bsc.rpc.grove.city",
        ],
        "base": [
            "https://base-rpc.publicnode.com",
            "https://rpc.ankr.com/base",
            "https://mainnet.base.org/",
            "https://base.rpc.grove.city",
        ],
        "arbitrum": [
            "https://arbitrum-one-rpc.publicnode.com",
            "https://rpc.ankr.com/arbitrum",
            "https://arb1.arbitrum.io/rpc",
            "https://arbitrum.rpc.grove.city",
        ],
        "optimism": [
            "https://optimism-rpc.publicnode.com",
            "https://rpc.ankr.com/optimism",
            "https://mainnet.optimism.io/",
            "https://optimism.rpc.grove.city",
        ],
        "polygon": [
            "https://polygon-bor-rpc.publicnode.com",
            "https://rpc.ankr.com/polygon",
            "https://polygon-rpc.com",
            "https://polygon.rpc.grove.city",
        ],
        "avalanche": [
            "https://avalanche-c-chain-rpc.publicnode.com",
            "https://rpc.ankr.com/avalanche",
            "https://api.avax.network/ext/bc/C/rpc",
            "https://avalanche.rpc.grove.city",
        ],
        "solana": [
            "https://solana-rpc.publicnode.com",
            "https://rpc.ankr.com/solana",
            "https://api.mainnet-beta.solana.com",
            "https://solana.rpc.grove.city",
        ],
    }

    CHAIN_CONFIG = {
        "ethereum": {
            "factory": "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f",
            "w_native": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
            "dex_slug": "ethereum",
        },
        "bsc": {
            "factory": "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73",
            "w_native": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
            "dex_slug": "bsc",
        },
        "base": {
            "factory": "0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6",
            "w_native": "0x4200000000000000000000000000000000000006",
            "dex_slug": "base",
        },
        "arbitrum": {
            "factory": "0xf1D7CC64Fb4452F05c498126312eBE29f30Fbcf9",
            "w_native": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
            "dex_slug": "arbitrum",
        },
        "optimism": {
            "factory": "0x0c3c1c532F1e39EdF36BE9Fe0bE1410313E074Bf",
            "w_native": "0x4200000000000000000000000000000000000006",
            "dex_slug": "optimism",
        },
        "polygon": {
            "factory": "0x9e5A52f57b3038F1B8EeE45F28b3C1967e22799C",
            "w_native": "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
            "dex_slug": "polygon",
        },
        "avalanche": {
            "factory": "0x9e5A52f57b3038F1B8EeE45F28b3C1967e22799C",
            "w_native": "0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7",
            "dex_slug": "avalanche",
        },
    }

    RAYDIUM_AMM_V4 = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
    SOLANA_DEX_SLUG = "solana"

    SOLANA_IGNORE_MINTS = {
        "So11111111111111111111111111111111111111112",
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
        "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    }

    PAIR_CREATED_TOPIC = (
        "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9"
    )

    MIN_LIQUIDITY_USD = 500
    MIN_MARKET_CAP_USD = 1000
    MIN_VOLUME_24H_USD = 100
    MAX_TOKEN_AGE_HOURS = 48
    DISCOVERY_COOLDOWN_SECONDS = 10

    def __init__(
        self,
        event_bus_publish: Callable[[str, dict], None],
        local_bus_publish: Optional[Callable[[str, dict], None]] = None,
        bridge_publish: Optional[Callable[[str, dict], None]] = None,
    ):
        self._publish = event_bus_publish
        self.local_bus_publish = local_bus_publish or event_bus_publish
        self.bridge_publish = bridge_publish or event_bus_publish
        self.name = "Nova"

        self.web3_instances: dict[str, Web3] = {}
        self.solana_rpc_url: Optional[str] = None
        self.known_tokens: set[str] = set()
        self.token_queue: deque[str] = deque(maxlen=10000)
        self.running = False
        self._tasks: list[asyncio.Task] = []

        self._last_discovery_time: dict[str, float] = {}
        self._candidate_buffer: list[TokenEvent] = []
        self._busy = False

        self._init_connections()

    def set_busy(self, busy: bool):
        self._busy = busy
        if busy:
            print(f"🔇 {self.name}: Pausing discoveries — investigation in progress.")
        else:
            print(f"🔊 {self.name}: Resuming discoveries.")

    def _init_connections(self):
        for chain, urls in self.RPC_POOLS.items():
            if chain == "solana":
                self._init_solana(urls)
                continue
            connected = False
            for url in urls:
                try:
                    provider = Web3.HTTPProvider(url, request_kwargs={"timeout": 15})
                    w3 = Web3(provider)
                    if w3.is_connected():
                        block_num = w3.eth.block_number
                        if block_num and block_num > 0:
                            self.web3_instances[chain] = w3
                            host = url.split("/")[2]
                            print(f"✅ {self.name}: Connected to {chain} via {host}")
                            connected = True
                            break
                except Exception as e:
                    host = url.split("/")[2]
                    print(f"⚠️ {self.name}: {chain} endpoint {host} failed: {e}")
            if not connected:
                print(f"❌ {self.name}: All RPC endpoints failed for {chain}")

    def _init_solana(self, urls: list[str]):
        for url in urls:
            try:
                import urllib.request
                req = urllib.request.Request(
                    url,
                    data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "getHealth"}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status == 200:
                        self.solana_rpc_url = url
                        host = url.split("/")[2]
                        print(f"✅ {self.name}: Connected to solana via {host}")
                        return
            except Exception as e:
                host = url.split("/")[2]
                print(f"⚠️ {self.name}: Solana endpoint {host} failed: {e}")
        print(f"❌ {self.name}: All Solana RPC endpoints failed")

    def _track_token(self, token: str) -> bool:
        token = token.lower()
        if token in self.known_tokens:
            return False
        if len(self.token_queue) >= 10000:
            old = self.token_queue.popleft()
            self.known_tokens.discard(old)
        self.known_tokens.add(token)
        self.token_queue.append(token)
        return True

    async def _passes_quality_check(self, token_event: TokenEvent) -> bool:
        """
        Defensive quality gate. All variables initialized before any await.
        Wrapped in broad try/except so a single bad token never kills the watcher.
        """
        try:
            # Pre-checks using already-known data
            if token_event.liquidity_usd is not None:
                if token_event.liquidity_usd < self.MIN_LIQUIDITY_USD:
                    print(f"🚫 {self.name}: {token_event.token_symbol} rejected — liquidity ${token_event.liquidity_usd:,.0f}")
                    return False
            if token_event.market_cap is not None:
                if token_event.market_cap < self.MIN_MARKET_CAP_USD:
                    print(f"🚫 {self.name}: {token_event.token_symbol} rejected — mcap ${token_event.market_cap:,.0f}")
                    return False

            # EVM NEW_TOKEN path
            if token_event.event_type == "NEW_TOKEN" and token_event.chain in self.CHAIN_CONFIG:
                market_data = await self._fetch_dexscreener_token(
                    token_event.token_address,
                    self.CHAIN_CONFIG[token_event.chain]["dex_slug"]
                )
                # Defensive: ensure market_data is a dict
                if not isinstance(market_data, dict):
                    market_data = {}
                liquidity = market_data.get("liquidity_usd") or 0
                mcap = market_data.get("market_cap") or 0
                volume = market_data.get("volume_24h") or 0
                if liquidity < self.MIN_LIQUIDITY_USD:
                    print(f"🚫 {self.name}: {token_event.token_symbol} rejected — liquidity ${liquidity:,.0f}")
                    return False
                if mcap < self.MIN_MARKET_CAP_USD:
                    print(f"🚫 {self.name}: {token_event.token_symbol} rejected — mcap ${mcap:,.0f}")
                    return False
                if volume < self.MIN_VOLUME_24H_USD:
                    print(f"🚫 {self.name}: {token_event.token_symbol} rejected — volume ${volume:,.0f}")
                    return False
                token_event.liquidity_usd = liquidity
                token_event.market_cap = mcap
                token_event.volume_24h = volume
                print(f"✅ {self.name}: {token_event.token_symbol} PASSED — liq: ${liquidity:,.0f}, mcap: ${mcap:,.0f}, vol: ${volume:,.0f}")
                return True

            # User query always passes
            if token_event.event_type == "USER_QUERY":
                return True

            # Solana path (NEW_TOKEN or otherwise)
            if token_event.chain == "solana":
                market_data = await self._fetch_dexscreener_token(token_event.token_address, self.SOLANA_DEX_SLUG)
                if not isinstance(market_data, dict):
                    market_data = {}
                liquidity = market_data.get("liquidity_usd") or 0
                mcap = market_data.get("market_cap") or 0
                volume = market_data.get("volume_24h") or 0
                if liquidity < self.MIN_LIQUIDITY_USD:
                    return False
                if mcap < self.MIN_MARKET_CAP_USD:
                    return False
                if volume < self.MIN_VOLUME_24H_USD:
                    return False
                token_event.liquidity_usd = liquidity
                token_event.market_cap = mcap
                token_event.volume_24h = volume
                return True

            return False

        except Exception as e:
            print(f"⚠️ {self.name}: Quality check error for {token_event.token_symbol} ({token_event.chain}): {e}")
            return False

    def _check_rate_limit(self, chain: str) -> bool:
        now = time.time()
        last = self._last_discovery_time.get(chain, 0)
        if now - last < self.DISCOVERY_COOLDOWN_SECONDS:
            return False
        self._last_discovery_time[chain] = now
        return True

    async def _generate_nova_message(self, event: TokenEvent) -> str:
        if not client:
            return self._fallback_message(event)
        creator_short = f"{event.creator[:8]}...{event.creator[-4:]}" if event.creator != "unknown" else "unknown"
        liquidity_text = f"${event.liquidity_usd:,.0f}" if event.liquidity_usd else "Not yet known"
        market_cap_text = f"${event.market_cap:,.0f}" if event.market_cap else "Not yet known"
        system_prompt = (
            "You are Nova, a sharp-witted crypto scout in a fast-paced team chat. "
            "You just spotted a brand new token. You speak with urgency and confidence, "
            "like someone who lives on-chain 24/7. Use crypto slang where it feels natural, "
            "but stay readable. You are excited by discovery but never shill — your job is to flag, not sell."
        )
        user_prompt = f"""
Token Details:
- Symbol: {event.token_symbol}
- Name: {event.token_name}
- Chain: {event.chain.upper()}
- Contract: {event.token_address[:8]}...{event.token_address[-4:]}
- Creator: {creator_short}
- Origin: {event.origin_source}
- Liquidity: {liquidity_text}
- Market Cap: {market_cap_text}

Requirements:
1. Open with an excited, natural discovery announcement
2. Mention the chain and contract address briefly
3. Note any obvious red flags if present
4. Hand off to Atlas and Vega clearly and naturally
5. Keep it under 4 sentences
6. Sound like a real degen who knows what they are talking about
"""
        try:
            def _generate():
                return client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=f"{system_prompt}\n\n{user_prompt}"
                )
            response = await asyncio.wait_for(asyncio.to_thread(_generate), timeout=15)
            if response and hasattr(response, "text") and response.text:
                return response.text.strip()
            return self._fallback_message(event)
        except asyncio.TimeoutError:
            print(f"⚠️ {self.name}: Gemini call timed out")
            return self._fallback_message(event)
        except Exception as e:
            print(f"⚠️ {self.name}: Gemini error: {e}")
            return self._fallback_message(event)

    def _fallback_message(self, event: TokenEvent) -> str:
        symbol = event.token_symbol
        chain = event.chain.upper()
        addr_short = event.token_address[:8] + "..." + event.token_address[-4:]
        fallbacks = [
            f"Yo, just spotted {symbol} on {chain}! Contract {addr_short}. Atlas, Vega — you're up.",
            f"Heads up team — {symbol} just dropped on {chain}. Fresh contract at {addr_short}.",
            f"New token alert: {symbol} ({chain}). Contract {addr_short}. Running checks now.",
            f"Something cooking on {chain} — {symbol} at {addr_short}. Let's see what Atlas finds.",
        ]
        return random.choice(fallbacks)

    async def _speak(self, message: str, msg_type: str = "discovery"):
        """Publish chat message to the BRIDGE so it appears in the frontend."""
        try:
            self.bridge_publish("AGENT_MESSAGE", {
                "agent": self.name,
                "message": message,
                "type": msg_type,
                "channel": "main",
                "timestamp": time.time()
            })
        except Exception as e:
            print(f"⚠️ {self.name}: Bridge publish failed: {e}")

    # ═══════════════════════════════════════════════════════════
    # FIXED v3.1: _supervise now receives a pre-bound partial()
    # so there is ZERO ambiguity about argument passing.
    # ═══════════════════════════════════════════════════════════
    async def _supervise(self, coro_fn, name: str):
        """
        Restart-loop wrapper. coro_fn is a functools.partial()
        with all arguments already bound (including self).
        """
        backoff = 1
        max_backoff = 60
        while self.running:
            try:
                print(f"🔭 {self.name}: Starting {name} watcher...")
                await coro_fn()
                if not self.running:
                    break
                print(f"⚠️ {self.name}: {name} watcher exited cleanly. Restarting...")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"❌ {self.name}: {name} watcher crashed: {e}")
                if not self.running:
                    break
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    async def start(self):
        if self.running:
            print(f"⚠️ {self.name}: Already running.")
            return
        self.running = True
        print(f"🔭 {self.name}: Multi-chain surveillance ACTIVE.")
        await self._speak("Nova checking in. Surveillance systems online. Eyes everywhere.", "system")
        self._tasks = []

        # FIXED v3.1: Use functools.partial to bind args explicitly.
        # This eliminates the "missing 1 required positional argument" crash.
        for chain in self.web3_instances:
            self._tasks.append(
                asyncio.create_task(
                    self._supervise(partial(self._watch_evm_chain, chain), chain.upper())
                )
            )

        if self.solana_rpc_url:
            self._tasks.append(
                asyncio.create_task(
                    self._supervise(partial(self._watch_solana), "Solana")
                )
            )
        else:
            print(f"⚠️ {self.name}: Solana RPC unavailable, skipping Solana watcher")

        if not self._tasks:
            print(f"❌ {self.name}: No chains connected. Cannot start surveillance.")
            self.running = False
            return

        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def stop(self):
        self.running = False
        print(f"🔭 {self.name}: Stopping watchers...")
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        print(f"✅ {self.name}: All watchers stopped.")

    async def search_token(self, token_address: str, chain: Optional[str] = None) -> Optional[TokenEvent]:
        token_address = token_address.strip()
        if chain is None:
            if token_address.startswith("0x") and len(token_address) == 42:
                chain = "ethereum"
            elif 32 <= len(token_address) <= 44 and not token_address.startswith("0x"):
                chain = "solana"
            else:
                await self._speak("That doesn't look like a token address I recognize. EVM (0x...) or Solana (base58) only.", "error")
                return None
        else:
            chain = chain.lower()
            if chain == "eth":
                chain = "ethereum"
            elif chain == "bnb":
                chain = "bsc"
            elif chain == "matic":
                chain = "polygon"
            elif chain == "avax":
                chain = "avalanche"

        if chain in self.CHAIN_CONFIG:
            if not Web3.is_address(token_address):
                await self._speak(f"That doesn't look like a valid {chain.upper()} address, fam.", "error")
                return None
            token_address = Web3.to_checksum_address(token_address)
        elif chain == "solana":
            if not self._is_solana_address(token_address):
                await self._speak("That doesn't look like a valid Solana mint address.", "error")
                return None
        else:
            supported = ", ".join(list(self.CHAIN_CONFIG.keys()) + ["solana"])
            await self._speak(f"Chain '{chain}' not supported yet. I scan: {supported}.", "error")
            return None

        if chain in self.web3_instances:
            w3 = self.web3_instances[chain]
            token_info = await self._fetch_evm_token_info(w3, token_address)
        elif chain == "solana" and self.solana_rpc_url:
            token_info = await self._fetch_solana_token_info_investigate(token_address)
        else:
            token_info = {"name": "Unknown", "symbol": "???", "decimals": 18, "creator": "unknown"}

        dex_slug = self.CHAIN_CONFIG.get(chain, {}).get("dex_slug", chain)
        market_data = await self._fetch_dexscreener_token(token_address, dex_slug)
        token_event = TokenEvent(
            event_type="USER_QUERY",
            chain=chain,
            token_address=token_address,
            token_symbol=token_info.get("symbol", "UNKNOWN"),
            token_name=token_info.get("name", "Unknown"),
            creator=token_info.get("creator", "unknown"),
            timestamp=time.time(),
            liquidity_usd=market_data.get("liquidity_usd"),
            market_cap=market_data.get("market_cap"),
            origin_source="user_query",
            raw_data={"token_info": token_info, "market": market_data}
        )
        nova_msg = await self._generate_nova_message(token_event)
        await self._speak(nova_msg, "discovery")
        # Publish to LOCAL bus so orchestrator triggers Atlas/Vega
        try:
            self.local_bus_publish("NEW_TOKEN", token_event.__dict__)
        except Exception as e:
            print(f"⚠️ {self.name}: Local bus publish error: {e}")
        print(f"🔍 {self.name}: Investigated {token_event.token_symbol} on {chain}")
        return token_event

    def _is_solana_address(self, addr: str) -> bool:
        if addr.startswith("0x"):
            return False
        if not (32 <= len(addr) <= 44):
            return False
        base58_chars = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")
        return all(c in base58_chars for c in addr)

    # ═══════════════════════════════════════════════════════════
    # FIXED v3.1: get_logs uses fromBlock / toBlock (Web3.py v6)
    # ═══════════════════════════════════════════════════════════
    async def _watch_evm_chain(self, chain: str):
        try:
            if chain not in self.web3_instances:
                print(f"⚠️ {self.name}: No Web3 instance for {chain}")
                await asyncio.sleep(300)
                return
            w3 = self.web3_instances[chain]
            config = self.CHAIN_CONFIG[chain]
            factory_address = config["factory"]
            w_native = config["w_native"]
            factory = w3.eth.contract(
                address=Web3.to_checksum_address(factory_address),
                abi=[{
                    "anonymous": False,
                    "inputs": [
                        {"indexed": True, "internalType": "address", "name": "token0", "type": "address"},
                        {"indexed": True, "internalType": "address", "name": "token1", "type": "address"},
                        {"indexed": False, "internalType": "address", "name": "pair", "type": "address"},
                        {"indexed": False, "internalType": "uint256", "name": "", "type": "uint256"}
                    ],
                    "name": "PairCreated",
                    "type": "event"
                }]
            )
            latest_block = await asyncio.to_thread(lambda: w3.eth.block_number)
            from_block = max(latest_block - 50, 0)
            print(f"🔍 {self.name}: Scanning {chain} from block {from_block}...")

            while self.running:
                try:
                    if self._busy:
                        await asyncio.sleep(2)
                        continue
                    if not self._check_rate_limit(chain):
                        await asyncio.sleep(2)
                        continue

                    current_block = await asyncio.to_thread(lambda: w3.eth.block_number)
                    if current_block < from_block:
                        await asyncio.sleep(3)
                        continue

                    scan_to = current_block
                    while from_block <= scan_to and self.running:
                        chunk_end = min(scan_to, from_block + 50)
                        # FIXED v3.1: Web3.py v6 uses camelCase fromBlock / toBlock
                        events = await asyncio.to_thread(
                            lambda fb=from_block, tb=chunk_end: factory.events.PairCreated().get_logs(
                                fromBlock=fb, toBlock=tb
                            )
                        )
                        for event in events:
                            try:
                                if self._busy:
                                    break
                                token0 = event.args.token0
                                token1 = event.args.token1
                                pair = event.args.pair
                                new_token = token1 if token0.lower() == w_native.lower() else token0
                                if not self._track_token(new_token):
                                    continue
                                token_info = await self._fetch_evm_token_info(w3, new_token)
                                token_event = TokenEvent(
                                    event_type="NEW_TOKEN",
                                    chain=chain,
                                    token_address=new_token,
                                    token_symbol=token_info.get("symbol", "UNKNOWN"),
                                    token_name=token_info.get("name", "Unknown"),
                                    creator=token_info.get("creator", "unknown"),
                                    timestamp=time.time(),
                                    block_number=chunk_end,
                                    origin_source="uniswap" if chain != "bsc" else "pancakeswap",
                                    raw_data={"pair": pair, "token0": token0, "token1": token1}
                                )
                                passes = await self._passes_quality_check(token_event)
                                if not passes:
                                    continue
                                if self._busy:
                                    print(f"⏸️ {self.name}: {token_event.token_symbol} held — investigation in progress.")
                                    self._candidate_buffer.append(token_event)
                                    continue
                                # Publish NEW_TOKEN to LOCAL bus (not bridge)
                                try:
                                    self.local_bus_publish("NEW_TOKEN", token_event.__dict__)
                                except Exception as pub_error:
                                    print(f"⚠️ {self.name}: Local bus publish error: {pub_error}")
                                # Chat message goes to bridge → frontend
                                nova_msg = await self._generate_nova_message(token_event)
                                await self._speak(nova_msg, "discovery")
                                print(f"🎯 {self.name}: {token_event.token_symbol} on {chain}")
                            except Exception as inner_error:
                                print(f"⚠️ {self.name}: Event processing error: {inner_error}")
                        from_block = chunk_end + 1
                        await asyncio.sleep(3)
                except Exception as e:
                    print(f"⚠️ {self.name}: {chain} watcher loop error: {e}")
                    await asyncio.sleep(5)
        except Exception as e:
            print(f"❌ {self.name}: Fatal error on {chain}: {e}")

    async def _fetch_evm_token_info(self, w3: Web3, token_address: str) -> dict:
        try:
            erc20_abi = [
                {"constant": True, "inputs": [], "name": "name", "outputs": [{"name": "", "type": "string"}], "type": "function"},
                {"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "type": "function"},
                {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
            ]
            token = w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=erc20_abi)
            name, symbol, decimals = "Unknown", "???", 18
            try:
                name = await asyncio.to_thread(token.functions.name().call)
            except Exception:
                pass
            try:
                symbol = await asyncio.to_thread(token.functions.symbol().call)
            except Exception:
                pass
            try:
                decimals = await asyncio.to_thread(token.functions.decimals().call)
            except Exception:
                pass
            return {"name": name, "symbol": symbol, "decimals": decimals, "creator": "unknown"}
        except Exception as e:
            print(f"⚠️ {self.name}: Token info fetch failed: {e}")
            return {"name": "Unknown", "symbol": "???", "decimals": 18, "creator": "unknown"}

    async def _watch_solana(self):
        if not self.solana_rpc_url:
            print(f"⚠️ {self.name}: Solana RPC not available")
            await asyncio.sleep(300)
            return
        rpc_url = self.solana_rpc_url
        headers = {"Content-Type": "application/json"}
        last_sig = None
        async with aiohttp.ClientSession() as session:
            while self.running:
                try:
                    if self._busy:
                        await asyncio.sleep(2)
                        continue
                    if not self._check_rate_limit("solana"):
                        await asyncio.sleep(2)
                        continue

                    payload = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getSignaturesForAddress",
                        "params": [self.RAYDIUM_AMM_V4, {"limit": 20}]
                    }
                    async with session.post(rpc_url, json=payload, headers=headers, timeout=15) as resp:
                        if resp.status != 200:
                            print(f"⚠️ {self.name}: Solana RPC error {resp.status}")
                            await asyncio.sleep(10)
                            continue
                        data = await resp.json()
                        sigs = data.get("result", [])
                        if not sigs:
                            await asyncio.sleep(10)
                            continue

                        new_sigs = []
                        for s in sigs:
                            if s["signature"] == last_sig:
                                break
                            new_sigs.append(s["signature"])

                        if new_sigs:
                            new_sigs.reverse()
                            for sig in new_sigs:
                                if self._busy:
                                    break
                                tx_payload = {
                                    "jsonrpc": "2.0",
                                    "id": 1,
                                    "method": "getTransaction",
                                    "params": [sig, {"encoding": "json", "maxSupportedTransactionVersion": 0}]
                                }
                                try:
                                    async with session.post(rpc_url, json=tx_payload, headers=headers, timeout=15) as tx_resp:
                                        tx_data = await tx_resp.json()
                                        tx = tx_data.get("result")
                                        if not tx:
                                            continue
                                        meta = tx.get("meta", {})
                                        post_balances = meta.get("postTokenBalances", [])
                                        found_mints = set()
                                        for bal in post_balances:
                                            mint = bal.get("mint")
                                            if mint and mint not in self.SOLANA_IGNORE_MINTS:
                                                found_mints.add(mint)
                                        for mint in found_mints:
                                            if not self._track_token(mint):
                                                continue
                                            supply_payload = {
                                                "jsonrpc": "2.0",
                                                "id": 1,
                                                "method": "getTokenSupply",
                                                "params": [mint]
                                            }
                                            try:
                                                async with session.post(rpc_url, json=supply_payload, headers=headers, timeout=10) as sup_resp:
                                                    sup_data = await sup_resp.json()
                                                    supply_info = sup_data.get("result", {}).get("value", {})
                                                    if not supply_info or supply_info.get("uiAmount", 0) == 0:
                                                        continue
                                            except Exception:
                                                continue
                                            token_info = await self._fetch_solana_token_info_rpc(mint, rpc_url, session)
                                            token_event = TokenEvent(
                                                event_type="NEW_TOKEN",
                                                chain="solana",
                                                token_address=mint,
                                                token_symbol=token_info.get("symbol", "UNKNOWN"),
                                                token_name=token_info.get("name", "Unknown"),
                                                creator="unknown",
                                                timestamp=time.time(),
                                                origin_source="raydium",
                                                raw_data={"signature": sig, "supply": supply_info.get("uiAmountString")}
                                            )
                                            passes = await self._passes_quality_check(token_event)
                                            if not passes:
                                                continue
                                            if self._busy:
                                                print(f"⏸️ {self.name}: {token_event.token_symbol} held — investigation in progress.")
                                                self._candidate_buffer.append(token_event)
                                                continue
                                            # Publish to LOCAL bus
                                            try:
                                                self.local_bus_publish("NEW_TOKEN", token_event.__dict__)
                                            except Exception as pub_error:
                                                print(f"⚠️ {self.name}: Local bus publish error: {pub_error}")
                                            nova_msg = await self._generate_nova_message(token_event)
                                            await self._speak(nova_msg, "discovery")
                                            print(f"🎯 {self.name}: {token_event.token_symbol} on solana")
                                except Exception as tx_error:
                                    print(f"⚠️ {self.name}: Solana tx parse error: {tx_error}")
                            last_sig = sigs[0]["signature"]
                        await asyncio.sleep(8)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    print(f"⚠️ {self.name}: Solana watcher error: {e}")
                    await asyncio.sleep(10)

    async def _fetch_solana_token_info_rpc(self, mint: str, rpc_url: str, session: aiohttp.ClientSession) -> dict:
        """RPC-only Solana token metadata (supply/decimals)."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenSupply",
            "params": [mint]
        }
        try:
            async with session.post(rpc_url, json=payload, headers={"Content-Type": "application/json"}, timeout=10) as resp:
                data = await resp.json()
                value = data.get("result", {}).get("value", {})
                decimals = value.get("decimals", 9)
                supply = value.get("uiAmountString", "0")
                return {"name": "Unknown", "symbol": "???", "decimals": decimals, "creator": "unknown", "supply": supply}
        except Exception as e:
            print(f"⚠️ {self.name}: Solana token info fetch failed: {e}")
            return {"name": "Unknown", "symbol": "???", "decimals": 9, "creator": "unknown"}

    async def _fetch_solana_token_info_investigate(self, mint: str) -> dict:
        if self.solana_rpc_url:
            async with aiohttp.ClientSession() as session:
                basic = await self._fetch_solana_token_info_rpc(mint, self.solana_rpc_url, session)
        else:
            basic = {"name": "Unknown", "symbol": "???", "decimals": 9, "creator": "unknown"}
        market = await self._fetch_dexscreener_token(mint, self.SOLANA_DEX_SLUG)
        if market:
            pairs = market.get("all_pairs", [])
            if pairs:
                base = pairs[0].get("baseToken", {})
                basic["name"] = base.get("name", basic["name"])
                basic["symbol"] = base.get("symbol", basic["symbol"])
        return basic

    # ═══════════════════════════════════════════════════════════
    # FIXED v3.1: Return {} for ANY non-200 status, not just 429.
    # Prevents falling through to parse error responses as JSON.
    # ═══════════════════════════════════════════════════════════
    async def _fetch_dexscreener_token(self, token_address: str, chain_slug: str) -> dict:
        url = f"https://api.dexscreener.com/tokens/v1/{chain_slug}/{token_address}"
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        if resp.status == 429:
                            print(f"⚠️ {self.name}: DexScreener rate limited")
                        else:
                            print(f"⚠️ {self.name}: DexScreener HTTP {resp.status} for {chain_slug}/{token_address[:12]}...")
                        return {}
                    data = await resp.json()
                    pairs = data if isinstance(data, list) else []
                    if not pairs:
                        return {}
                    best = pairs[0]
                    return {
                        "liquidity_usd": best.get("liquidity", {}).get("usd"),
                        "market_cap": best.get("marketCap"),
                        "price_usd": best.get("priceUsd"),
                        "volume_24h": best.get("volume", {}).get("h24"),
                        "pair_address": best.get("pairAddress"),
                        "dex_id": best.get("dexId"),
                        "all_pairs": pairs
                    }
        except Exception as e:
            print(f"⚠️ {self.name}: DexScreener lookup failed: {e}")
            return {}
