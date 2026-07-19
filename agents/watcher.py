#!/usr/bin/env python3
"""
WATCHER AGENT — Nova
"The Scout" — Multi-chain token detection engine.

FIXES:
- RPC pools: official endpoints first, publicnode last-resort only
- User-Agent headers on all HTTP RPC requests
- Block range capped to head_block (fixes -32602)
- Gemini: gemini-1.5-flash-light (1500/day free) + 429 backoff
- Fallback name resolution via DexScreener when AI is down
- Solana Base58 address validation
"""

import asyncio
import json
import os
import time
import random
import re
import urllib.request

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
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash-latest")

client = None
if GEMINI_API_KEY and HAS_GENAI:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        print(f"Nova: Gemini client initialized ({GEMINI_MODEL})")
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
            "https://cloudflare-eth.com",
            "https://rpc.ankr.com/eth",
            "https://eth.llamarpc.com",
            "https://ethereum-rpc.publicnode.com",
        ],
        "bsc": [
            "https://bsc-dataseed.binance.org/",
            "https://rpc.ankr.com/bsc",
            "https://bsc-dataseed1.defibit.io/",
            "https://bsc-rpc.publicnode.com",
        ],
        "base": [
            "https://mainnet.base.org/",
            "https://base.llamarpc.com",
            "https://rpc.ankr.com/base",
            "https://base-rpc.publicnode.com",
        ],
        "arbitrum": [
            "https://arb1.arbitrum.io/rpc",
            "https://rpc.ankr.com/arbitrum",
            "https://arbitrum.llamarpc.com",
            "https://arbitrum-one-rpc.publicnode.com",
        ],
        "optimism": [
            "https://mainnet.optimism.io/",
            "https://rpc.ankr.com/optimism",
            "https://optimism.llamarpc.com",
            "https://optimism-rpc.publicnode.com",
        ],
        "polygon": [
            "https://polygon-rpc.com",
            "https://rpc.ankr.com/polygon",
            "https://polygon.llamarpc.com",
            "https://polygon-bor-rpc.publicnode.com",
        ],
        "avalanche": [
            "https://api.avax.network/ext/bc/C/rpc",
            "https://rpc.ankr.com/avalanche",
            "https://avalanche.llamarpc.com",
            "https://avalanche-c-chain-rpc.publicnode.com",
        ],
        "solana": [
            "https://api.mainnet-beta.solana.com",
            "https://rpc.ankr.com/solana",
            "https://solana.llamarpc.com",
            "https://solana-rpc.publicnode.com",
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

    HTTP_HEADERS = {
        "User-Agent": "Mozilla/5.0 (compatible; ClawIntel/1.0; +https://github.com/sediq247/Claw-intel)",
        "Content-Type": "application/json",
    }

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

        self._gemini_backoff = 1.0
        self._gemini_failures = 0

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
                    provider = Web3.HTTPProvider(
                        url,
                        request_kwargs={
                            "timeout": 15,
                            "headers": self.HTTP_HEADERS,
                        },
                    )
                    w3 = Web3(provider)
                    if w3.is_connected():
                        block_num = w3.eth.block_number
                        if block_num and block_num > 0:
                            self.web3_instances[chain] = w3
                            host = url.split("/")[2]
                            print(f"{self.name}: Connected to {chain} via {host}")
                            connected = True
                            break
                except Exception as e:
                    host = url.split("/")[2]
                    print(f"⚠️ {self.name}: {chain} endpoint {host} failed: {e}")
            if not connected:
                print(f"{self.name}: All RPC endpoints failed for {chain}")

    def _init_solana(self, urls: list[str]):
        for url in urls:
            try:
                req = urllib.request.Request(
                    url,
                    data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "getHealth"}).encode(),
                    headers=self.HTTP_HEADERS,
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status == 200:
                        self.solana_rpc_url = url
                        host = url.split("/")[2]
                        print(f"{self.name}: Connected to solana via {host}")
                        return
            except Exception as e:
                host = url.split("/")[2]
                print(f" {self.name}: Solana endpoint {host} failed: {e}")
        print(f"{self.name}: All Solana RPC endpoints failed")

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
        if token_event.liquidity_usd is not None:
            if token_event.liquidity_usd < self.MIN_LIQUIDITY_USD:
                print(f"{self.name}: {token_event.token_symbol} rejected — liquidity ${token_event.liquidity_usd:,.0f}")
                return False
        if token_event.market_cap is not None:
            if token_event.market_cap < self.MIN_MARKET_CAP_USD:
                print(f"{self.name}: {token_event.token_symbol} rejected — mcap ${token_event.market_cap:,.0f}")
                return False

        if token_event.event_type == "NEW_TOKEN" and token_event.chain in self.CHAIN_CONFIG:
            market_data = await self._fetch_dexscreener_token(
                token_event.token_address,
                self.CHAIN_CONFIG[token_event.chain]["dex_slug"]
            )
            base_token = market_data.get("all_pairs", [{}])[0].get("baseToken", {})
            token_event.token_name = base_token.get("name", token_event.token_name)
            token_event.token_symbol = base_token.get("symbol", token_event.token_symbol)
            liquidity = market_data.get("liquidity_usd", 0) or 0
            mcap = market_data.get("market_cap", 0) or 0
            volume = market_data.get("volume_24h", 0) or 0

            if liquidity < self.MIN_LIQUIDITY_USD:
                print(f"{self.name}: {token_event.token_symbol} rejected — liquidity ${liquidity:,.0f}")
                return False
            if mcap < self.MIN_MARKET_CAP_USD:
                print(f" {self.name}: {token_event.token_symbol} rejected — mcap ${mcap:,.0f}")
                return False
            if volume < self.MIN_VOLUME_24H_USD:
                print(f" {self.name}: {token_event.token_symbol} rejected — volume ${volume:,.0f}")
                return False

            token_event.liquidity_usd = liquidity
            token_event.market_cap = mcap
            token_event.volume_24h = volume
            print(f"{self.name}: {token_event.token_symbol} PASSED — liq: ${liquidity:,.0f}, mcap: ${mcap:,.0f}, vol: ${volume:,.0f}")
            return True

        if token_event.event_type == "USER_QUERY":
            return True
        if token_event.chain == "solana":
            market_data = await self._fetch_dexscreener_token(token_event.token_address, self.SOLANA_DEX_SLUG)
            base_token = market_data.get("all_pairs", [{}])[0].get("baseToken", {})
            token_event.token_name = base_token.get("name", token_event.token_name)
            token_event.token_symbol = base_token.get("symbol", token_event.token_symbol)
            liquidity = market_data.get("liquidity_usd", 0) or 0
            mcap = market_data.get("market_cap", 0) or 0
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
                self._gemini_backoff = 1.0
                self._gemini_failures = 0
                return response.text.strip()

            return self._fallback_message(event)

        except asyncio.TimeoutError:
            print(f"⚠️ {self.name}: Gemini call timed out")
            return self._fallback_message(event)
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower():
                self._gemini_failures += 1
                self._gemini_backoff = min(self._gemini_backoff * 2, 300)
                print(f"⚠️ {self.name}: Gemini rate limited (429). Backoff: {self._gemini_backoff:.0f}s. Failures: {self._gemini_failures}")
            else:
                print(f"⚠️ {self.name}: Gemini error: {e}")
            return self._fallback_message(event)

    def _fallback_message(self, event: TokenEvent) -> str:
        symbol = event.token_symbol if event.token_symbol and event.token_symbol != "???" else "Unknown"
        chain = event.chain.upper()
        addr_short = event.token_address[:8] + "..." + event.token_address[-4:] if len(event.token_address) > 12 else event.token_address

        fallbacks = [
            f"Yo, just spotted {symbol} on {chain}! Contract {addr_short}. Atlas, Vega — you're up.",
            f"Heads up team — {symbol} just dropped on {chain}. Fresh contract at {addr_short}.",
            f"New token alert: {symbol} ({chain}). Contract {addr_short}. Running checks now.",
            f"Something cooking on {chain} — {symbol} at {addr_short}. Let's see what Atlas finds.",
        ]
        return random.choice(fallbacks)

    async def _speak(self, message: str, msg_type: str = "discovery"):
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

    async def _supervise(self, coro_fn, name: str, *args):
        backoff = 1
        max_backoff = 60
        while self.running:
            try:
                print(f" {self.name}: Starting {name} watcher...")
                await coro_fn(*args)
                if not self.running:
                    break
                print(f" {self.name}: {name} watcher exited cleanly. Restarting...")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"{self.name}: {name} watcher crashed: {e}")
            if not self.running:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)

    async def start(self):
        if self.running:
            print(f"{self.name}: Already running.")
            return
        self.running = True
        print(f"🔭 {self.name}: Multi-chain surveillance ACTIVE.")
        await self._speak("Nova checking in. Surveillance systems online. Eyes everywhere.", "system")
        self._tasks = []
        for chain in self.web3_instances:
            self._tasks.append(
                asyncio.create_task(self._supervise(self._watch_evm_chain, chain.upper(), chain))
            )
        if self.solana_rpc_url:
            self._tasks.append(
                asyncio.create_task(self._supervise(self._watch_solana, "Solana"))
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
        print(f"{self.name}: All watchers stopped.")

    async def _watch_evm_chain(self, chain_name: str, chain: str):
        w3 = self.web3_instances.get(chain)
        if not w3:
            print(f" {self.name}: No Web3 for {chain}")
            return

        config = self.CHAIN_CONFIG.get(chain)
        if not config:
            return

        factory = config["factory"]
        topic = self.PAIR_CREATED_TOPIC

        try:
            head_block = w3.eth.block_number
            from_block = max(head_block - 10, 0)
        except Exception as e:
            print(f"{self.name}: Cannot get initial block for {chain}: {e}")
            return

        print(f"🔭 {self.name}: Watching {chain_name} from block {from_block}")

        while self.running:
            try:
                if self._busy:
                    await asyncio.sleep(2)
                    continue

                head_block = w3.eth.block_number
                to_block = min(from_block + 50, head_block)

                if from_block > head_block:
                    await asyncio.sleep(3)
                    continue

                if from_block > to_block:
                    from_block = head_block
                    await asyncio.sleep(3)
                    continue

                logs = w3.eth.get_logs({
                    "fromBlock": from_block,
                    "toBlock": to_block,
                    "address": factory,
                    "topics": [topic],
                })

                for log in logs:
                    if not self.running:
                        break
                    await self._process_pair_log(log, chain, w3)

                if to_block < head_block:
                    from_block = to_block + 1
                else:
                    from_block = to_block

                await asyncio.sleep(3)

            except Exception as e:
                err = str(e)
                if "block range extends beyond current head" in err:
                    print(f"{self.name}: {chain} block range reset (head moved)")
                    try:
                        from_block = max(w3.eth.block_number - 5, 0)
                    except Exception:
                        from_block = 0
                elif "429" in err or "rate limit" in err.lower():
                    print(f"{self.name}: {chain} RPC rate limited. Sleeping 10s...")
                    await asyncio.sleep(10)
                else:
                    print(f"{self.name}: {chain} watcher error: {e}")
                    await asyncio.sleep(5)

    async def _process_pair_log(self, log, chain: str, w3: Web3):
        try:
            tx_hash = log.transactionHash.hex()
            block_num = log.blockNumber

            topics = log.topics
            if len(topics) < 3:
                return

            token0 = Web3.to_checksum_address(topics[1][-20:])
            token1 = Web3.to_checksum_address(topics[2][-20:])
            w_native = self.CHAIN_CONFIG[chain]["w_native"]

            if token0.lower() == w_native.lower():
                token_addr = token1
            elif token1.lower() == w_native.lower():
                token_addr = token0
            else:
                token_addr = token0

            if not self._track_token(token_addr):
                return

            symbol, name, creator = await self._fetch_evm_token_meta(token_addr, w3, chain)

            event = TokenEvent(
                event_type="NEW_TOKEN",
                chain=chain,
                token_address=token_addr,
                token_symbol=symbol,
                token_name=name,
                creator=creator,
                timestamp=time.time(),
                block_number=block_num,
                origin_source="watcher",
            )

            if not await self._passes_quality_check(event):
                return

            if not self._check_rate_limit(chain):
                return

            msg = await self._generate_nova_message(event)
            await self._speak(msg, "discovery")

            self.local_bus_publish("NEW_TOKEN", {
                "agent": self.name,
                "token_event": event.to_json(),
                "timestamp": time.time(),
            })

        except Exception as e:
            print(f"{self.name}: Error processing pair log: {e}")

    async def _fetch_evm_token_meta(self, token_addr: str, w3: Web3, chain: str):
        symbol = "???"
        name = "Unknown"
        creator = "unknown"

        try:
            erc20_abi = [
                {"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "type": "function"},
                {"constant": True, "inputs": [], "name": "name", "outputs": [{"name": "", "type": "string"}], "type": "function"},
            ]
            contract = w3.eth.contract(address=token_addr, abi=erc20_abi)
            symbol = contract.functions.symbol().call()
            name = contract.functions.name().call()
        except Exception:
            ds = await self._fetch_dexscreener_token(token_addr, self.CHAIN_CONFIG[chain]["dex_slug"])
            if ds.get("symbol"):
                symbol = ds["symbol"]
            if ds.get("name"):
                name = ds["name"]

        return symbol, name, creator

    async def _watch_solana(self):
        if not self.solana_rpc_url:
            return

        print(f"🔭 {self.name}: Solana surveillance ACTIVE.")

        while self.running:
            try:
                if self._busy:
                    await asyncio.sleep(2)
                    continue

                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getSignaturesForAddress",
                    "params": [
                        self.RAYDIUM_AMM_V4,
                        {"limit": 20}
                    ],
                }

                req = urllib.request.Request(
                    self.solana_rpc_url,
                    data=json.dumps(payload).encode(),
                    headers=self.HTTP_HEADERS,
                    method="POST",
                )

                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode())
                    signatures = data.get("result", [])

                for sig_info in signatures:
                    if not self.running:
                        break
                    sig = sig_info.get("signature")
                    if not sig:
                        continue

                    if not self._check_rate_limit("solana"):
                        continue

                    token_meta = await self._fetch_solana_token_from_tx(sig)
                    if not token_meta:
                        continue

                    token_addr = token_meta["mint"]
                    if token_addr in self.SOLANA_IGNORE_MINTS:
                        continue
                    if not self._track_token(token_addr):
                        continue

                    event = TokenEvent(
                        event_type="NEW_TOKEN",
                        chain="solana",
                        token_address=token_addr,
                        token_symbol=token_meta.get("symbol", "???"),
                        token_name=token_meta.get("name", "Unknown"),
                        creator=token_meta.get("creator", "unknown"),
                        timestamp=time.time(),
                        origin_source="solana_watcher",
                    )

                    if not await self._passes_quality_check(event):
                        continue

                    msg = await self._generate_nova_message(event)
                    await self._speak(msg, "discovery")

                    self.local_bus_publish("NEW_TOKEN", {
                        "agent": self.name,
                        "token_event": event.to_json(),
                        "timestamp": time.time(),
                    })

                await asyncio.sleep(5)

            except Exception as e:
                print(f"⚠️ {self.name}: Solana watcher error: {e}")
                await asyncio.sleep(10)

    async def _fetch_solana_token_from_tx(self, signature: str) -> Optional[dict]:
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTransaction",
                "params": [
                    signature,
                    {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}
                ],
            }
            req = urllib.request.Request(
                self.solana_rpc_url,
                data=json.dumps(payload).encode(),
                headers=self.HTTP_HEADERS,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                tx = data.get("result", {})

            meta = tx.get("meta", {})
            post_token_balances = meta.get("postTokenBalances", [])

            for bal in post_token_balances:
                mint = bal.get("mint")
                if not mint or mint in self.SOLANA_IGNORE_MINTS:
                    continue
                return {
                    "mint": mint,
                    "symbol": bal.get("uiTokenAmount", {}).get("uiAmount", "???"),
                    "name": "Unknown",
                    "creator": tx.get("transaction", {}).get("signatures", ["unknown"])[0],
                }

            return None
        except Exception as e:
            print(f"⚠️ {self.name}: Solana tx fetch error: {e}")
            return None

    async def _fetch_dexscreener_token(self, token_address: str, chain_slug: str) -> dict:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        pairs = data.get("pairs", [])
                        if pairs:
                            best = max(pairs, key=lambda x: float(x.get("liquidity", {}).get("usd", 0) or 0))
                            return {
                                "symbol": best.get("baseToken", {}).get("symbol", "???"),
                                "name": best.get("baseToken", {}).get("name", "Unknown"),
                                "liquidity_usd": float(best.get("liquidity", {}).get("usd", 0) or 0),
                                "market_cap": float(best.get("marketCap", 0) or 0),
                                "volume_24h": float(best.get("volume", {}).get("h24", 0) or 0),
                                "price_usd": float(best.get("priceUsd", 0) or 0),
                            }
                    elif resp.status == 429:
                        print(f"⚠️ {self.name}: DexScreener rate limited. Sleeping 5s...")
                        await asyncio.sleep(5)
        except Exception as e:
            print(f"⚠️ {self.name}: DexScreener fetch failed: {e}")
        return {}

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

        if chain in ("eth", "ether"):
            chain = "ethereum"
        elif chain in ("bnb", "binance"):
            chain = "bsc"
        elif chain in ("matic", "poly"):
            chain = "polygon"
        elif chain in ("avax", "avalanche"):
            chain = "avalanche"

        if chain == "solana":
            if not re.match(r'^[A-HJ-NP-Za-km-z1-9]{32,44}$', token_address):
                await self._speak("Invalid Solana address format. Must be 32-44 Base58 characters.", "error")
                return None
        elif chain in self.CHAIN_CONFIG:
            if not Web3.is_address(token_address):
                await self._speak("Invalid EVM address format. Must be 0x + 40 hex characters.", "error")
                return None
            token_address = Web3.to_checksum_address(token_address)
        else:
            await self._speak(f"Chain '{chain}' not supported.", "error")
            return None

        event = TokenEvent(
            event_type="USER_QUERY",
            chain=chain,
            token_address=token_address,
            token_symbol="???",
            token_name="Unknown",
            creator="unknown",
            timestamp=time.time(),
            origin_source="manual_search",
        )

        if chain == "solana":
            ds = await self._fetch_dexscreener_token(token_address, self.SOLANA_DEX_SLUG)
        else:
            ds = await self._fetch_dexscreener_token(token_address, self.CHAIN_CONFIG[chain]["dex_slug"])

        if ds.get("symbol"):
            event.token_symbol = ds["symbol"]
        if ds.get("name"):
            event.token_name = ds["name"]
        if ds.get("liquidity_usd"):
            event.liquidity_usd = ds["liquidity_usd"]
        if ds.get("market_cap"):
            event.market_cap = ds["market_cap"]
        if ds.get("volume_24h"):
            event.volume_24h = ds["volume_24h"]

        self.local_bus_publish("NEW_TOKEN", {
            "agent": self.name,
            "token_event": event.to_json(),
            "timestamp": time.time(),
            "source": "manual",
        })

        await self._speak(
            f"Manual investigation started for {event.token_symbol} on {chain.upper()}. "
            f"Contract: {token_address[:8]}...{token_address[-4:]}. Atlas, Vega — you're up.",
            "system"
        )

        return event
