"""
"The Observer" — Multi-chain market surveillance. Spots tokens with traction,
scores them on market metrics, and queues them for the team's analysis.
"""

import asyncio
import json
import os
import time
import math
import random
from functools import partial
from dataclasses import dataclass, asdict
from typing import Optional

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
                    print(f"⚠️ Nova: Model {model} unavailable, trying fallback...")
                    last_err = e
                    continue
                raise
        raise last_err or Exception("All Gemini models exhausted")


gemini = GeminiWrapper(GEMINI_API_KEY) if GEMINI_API_KEY and HAS_GENAI else None
if not gemini:
    print("⚠️ Nova: Gemini unavailable. Running fallback mode.")


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
    attention_score: float = 0.0
    jupiter_failed: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)


class WatcherAgent:
    # Primary RPCs from .env (tried first), fallback pools used if env missing or fails
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
    }

    RAYDIUM_AMM_V4 = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
    SOLANA_DEX_SLUG = "solana"
    SOLANA_IGNORE_MINTS = {
        "So11111111111111111111111111111111111111112",
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
        "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    }

    MIN_LIQUIDITY_USD = 5000
    MIN_MARKET_CAP_USD = 2000
    MIN_VOLUME_24H_USD = 2000
    MAX_TOKEN_AGE_HOURS = 24
    DISCOVERY_COOLDOWN_SECONDS = 10

    JUPITER_QUOTE = "https://quote-api.jup.ag/v6"
    WSOL = "So11111111111111111111111111111111111111112"

    def __init__(self, db, server, publisher=None):
        self.db = db
        self.server = server
        self.publisher = publisher
        self.name = "Nova"

        self.web3_instances: dict[str, Web3] = {}
        self._active_rpc_urls: dict[str, str] = {}
        self.solana_rpc_url: Optional[str] = None
        self.running = False
        self._tasks: list[asyncio.Task] = []
        self._last_discovery_time: dict[str, float] = {}
        self._session: Optional[aiohttp.ClientSession] = None

        self._init_connections()

    def _init_connections(self):
        for chain, urls in self.RPC_POOLS.items():
            urls = [u for u in urls if u]
            if chain == "solana":
                self._init_solana(urls)
                continue
            for url in urls:
                try:
                    w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 15}))
                    if w3.is_connected() and w3.eth.block_number > 0:
                        self.web3_instances[chain] = w3
                        self._active_rpc_urls[chain] = url
                        host = url.split("/")[2]
                        print(f"✅ Nova: Connected to {chain} via {host}")
                        break
                except Exception as e:
                    host = url.split("/")[2]
                    print(f"⚠️ Nova: {chain} endpoint {host} failed: {e}")
            if chain not in self.web3_instances:
                print(f"❌ Nova: All RPC endpoints failed for {chain}")

    def _init_solana(self, urls: list[str]):
        for url in urls:
            try:
                import urllib.request
                req = urllib.request.Request(
                    url,
                    data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "getHealth"}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status == 200:
                        self.solana_rpc_url = url
                        print(f"✅ Nova: Connected to solana via {url.split('/')[2]}")
                        return
            except Exception as e:
                print(f"⚠️ Nova: Solana endpoint {url.split('/')[2]} failed: {e}")
        print(f"❌ Nova: All Solana RPC endpoints failed")

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(limit=20, limit_per_host=5),
                timeout=aiohttp.ClientTimeout(total=20),
            )
        return self._session

    async def _rotate_rpc(self, chain: str):
        current = self._active_rpc_urls.get(chain)
        urls = [u for u in self.RPC_POOLS.get(chain, []) if u]
        if not urls:
            return
        start = urls.index(current) + 1 if current in urls else 0
        for i in range(len(urls)):
            url = urls[(start + i) % len(urls)]
            try:
                w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 15}))
                if w3.is_connected() and w3.eth.block_number > 0:
                    self.web3_instances[chain] = w3
                    self._active_rpc_urls[chain] = url
                    print(f"✅ Nova: Rotated {chain} to {url.split('/')[2]}")
                    return
            except Exception:
                continue
        print(f"❌ Nova: All RPC endpoints failed for {chain}")

    async def _rpc_health_check(self):
        while self.running:
            try:
                for chain, w3 in list(self.web3_instances.items()):
                    try:
                        await asyncio.to_thread(lambda: w3.eth.block_number)
                    except Exception:
                        await self._rotate_rpc(chain)
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"⚠️ Nova: Health check error: {e}")
                await asyncio.sleep(60)

    def _calculate_attention(self, event: TokenEvent) -> float:
        liq = event.liquidity_usd or 0
        vol = event.volume_24h or 0
        mcap = event.market_cap or 0
        score = 0.0
        if liq > 0:
            score += min(math.log10(liq) * 15, 40)
        if vol > 0:
            score += min(math.log10(vol) * 15, 35)
        if mcap > 0:
            score += min(math.log10(mcap) * 10, 20)
        age_hours = (time.time() - event.timestamp) / 3600
        if age_hours < 2:
            score += 5
        return min(score, 100)

    def _check_rate_limit(self, chain: str) -> bool:
        now = time.time()
        last = self._last_discovery_time.get(chain, 0)
        if now - last < self.DISCOVERY_COOLDOWN_SECONDS:
            return False
        self._last_discovery_time[chain] = now
        return True

    async def _passes_quality_check(self, event: TokenEvent) -> bool:
        try:
            if event.liquidity_usd is not None and event.liquidity_usd < self.MIN_LIQUIDITY_USD:
                print(f"🚫 Nova: {event.token_symbol} rejected — liquidity ${event.liquidity_usd:,.0f}")
                return False
            if event.market_cap is not None and event.market_cap < self.MIN_MARKET_CAP_USD:
                print(f"🚫 Nova: {event.token_symbol} rejected — mcap ${event.market_cap:,.0f}")
                return False

            age_hours = (time.time() - event.timestamp) / 3600
            if age_hours > self.MAX_TOKEN_AGE_HOURS:
                print(f"🚫 Nova: {event.token_symbol} rejected — age {age_hours:.1f}h")
                return False

            dex_slug = self.CHAIN_CONFIG.get(event.chain, {}).get("dex_slug") or event.chain
            market_data = await self._fetch_dexscreener_token(event.token_address, dex_slug)

            if not isinstance(market_data, dict):
                market_data = {}

            liquidity = market_data.get("liquidity_usd") or 0
            mcap = market_data.get("market_cap") or 0
            volume = market_data.get("volume_24h") or 0

            if liquidity < self.MIN_LIQUIDITY_USD:
                print(f"🚫 Nova: {event.token_symbol} rejected — liquidity ${liquidity:,.0f}")
                return False
            if mcap < self.MIN_MARKET_CAP_USD:
                print(f"🚫 Nova: {event.token_symbol} rejected — mcap ${mcap:,.0f}")
                return False
            if volume < self.MIN_VOLUME_24H_USD:
                print(f"🚫 Nova: {event.token_symbol} rejected — volume ${volume:,.0f}")
                return False

            event.liquidity_usd = liquidity
            event.market_cap = mcap
            event.volume_24h = volume
            print(f"✅ Nova: {event.token_symbol} PASSED — liq: ${liquidity:,.0f}, mcap: ${mcap:,.0f}, vol: ${volume:,.0f}")
            return True

        except Exception as e:
            print(f"⚠️ Nova: Quality check error for {event.token_symbol}: {e}")
            return False

    async def _handle_discovery(self, event: TokenEvent):
        try:
            event.attention_score = self._calculate_attention(event)

            try:
                pending = await self.db.count_pending_tokens()
                if pending >= 100:
                    lowest = await self.db.get_lowest_attention_in_queue()
                    if lowest is not None and event.attention_score <= lowest:
                        print(f"🚫 Nova: {event.token_symbol} dropped — queue full, attention {event.attention_score:.1f} <= {lowest:.1f}")
                        return
            except Exception as e:
                print(f"⚠️ Nova: Queue cap check failed: {e}")

            try:
                existing = await self.db.get_token(event.token_address, event.chain)
                if existing and existing.get("status") in ("pending", "investigating", "completed"):
                    print(f"⏭️ Nova: {event.token_symbol} already {existing['status']}, skipping")
                    return
            except Exception:
                pass

            nova_msg = await self._generate_nova_message(event)

            discovered_doc = {
                "token_address": event.token_address,
                "chain": event.chain,
                "symbol": event.token_symbol,
                "name": event.token_name,
                "creator": event.creator,
                "liquidity_usd": event.liquidity_usd,
                "market_cap": event.market_cap,
                "volume_24h": event.volume_24h,
                "attention_score": event.attention_score,
                "status": "pending",
                "discovered_at": event.timestamp,
                "nova_message": nova_msg,
                "origin_source": event.origin_source,
                "raw_data": event.raw_data,
                "jupiter_failed": event.jupiter_failed,
            }

            try:
                await self.db.save_discovered_token(discovered_doc)
            except Exception as e:
                print(f"⚠️ Nova: Failed to save discovered token: {e}")
                return

            queue_doc = {
                "token_address": event.token_address,
                "chain": event.chain,
                "symbol": event.token_symbol,
                "name": event.token_name,
                "creator": event.creator,
                "liquidity_usd": event.liquidity_usd,
                "market_cap": event.market_cap,
                "volume_24h": event.volume_24h,
                "attention_score": event.attention_score,
                "status": "pending",
                "nova_message": nova_msg,
                "origin_source": event.origin_source,
                "timestamp": time.time(),
            }

            try:
                await self.db.add_token_to_queue(queue_doc)
            except Exception as e:
                print(f"⚠️ Nova: Failed to add token to queue: {e}")
                return

            try:
                await self.db.save_chat_message("Nova", nova_msg, "discovery")
            except Exception as e:
                print(f"⚠️ Nova: Chat save failed: {e}")

            print(f"🎯 Nova: {event.token_symbol} on {event.chain} saved (attention: {event.attention_score:.1f})")

        except Exception as e:
            print(f"❌ Nova: Discovery handling error: {e}")

    async def _generate_nova_message(self, event: TokenEvent) -> str:
        if not gemini:
            return self._fallback_message(event)

        creator_short = f"{event.creator[:8]}...{event.creator[-4:]}" if event.creator != "unknown" else "unknown"
        liq_text = f"${event.liquidity_usd:,.0f}" if event.liquidity_usd else "unknown"
        mcap_text = f"${event.market_cap:,.0f}" if event.market_cap else "unknown"
        vol_text = f"${event.volume_24h:,.0f}" if event.volume_24h else "unknown"

        system_prompt = (
            "You are Nova, a sharp crypto market observer in a team chat. "
            "You spot new tokens with early traction and report what you see — "
            "liquidity, volume, age, and anything that stands out. "
            "You are curious, not alarmist. You describe, you do not condemn. "
            "You never call a token a scam, rug, or honeypot. You simply say what the metrics show."
        )

        user_prompt = (
            f"Token: {event.token_symbol} ({event.token_name})\n"
            f"Chain: {event.chain.upper()}\n"
            f"Contract: {event.token_address[:8]}...{event.token_address[-4:]}\n"
            f"Creator: {creator_short}\n"
            f"Liquidity: {liq_text}\n"
            f"Market Cap: {mcap_text}\n"
            f"24h Volume: {vol_text}\n"
            f"Origin: {event.origin_source}\n\n"
            f"Requirements:\n"
            f"1. Open with a natural, concise discovery note\n"
            f"2. Mention chain, liquidity, and volume briefly\n"
            f"3. If metrics look thin, say so neutrally — no fear-mongering\n"
            f"4. Hand off to the team (Atlas, Vega) for deeper look\n"
            f"5. Keep it under 4 sentences\n"
            f"6. Sound like a calm trader who watches charts all day"
        )

        try:
            config = None
            if genai_types:
                config = genai_types.GenerateContentConfig(temperature=0.9, max_output_tokens=200)
            response = await gemini.generate(f"{system_prompt}\n\n{user_prompt}", config=config)
            text = response.text if hasattr(response, "text") else str(response)
            return text.strip() if text else self._fallback_message(event)
        except asyncio.TimeoutError:
            print("⚠️ Nova: Gemini timed out")
            return self._fallback_message(event)
        except Exception as e:
            print(f"⚠️ Nova: Gemini error: {e}")
            return self._fallback_message(event)

    def _fallback_message(self, event: TokenEvent) -> str:
        symbol = event.token_symbol
        chain = event.chain.upper()
        liq = event.liquidity_usd or 0
        mcap = event.market_cap or 0
        vol = event.volume_24h or 0

        parts = [f"Spotted {symbol} on {chain}. "]

        if mcap > 0:
            parts.append(f"Market cap around ${mcap:,.0f}. ")
        if liq > 0:
            parts.append(f"Liquidity at ${liq:,.0f}. ")
        if vol > 0:
            parts.append(f"${vol:,.0f} volume in 24h. ")

        parts.append("Atlas, Vega — take a look when you're free.")
        return "".join(parts)

    async def start(self):
        if self.running:
            return
        self.running = True
        print("🔭 Nova: Multi-chain surveillance ACTIVE.")
        self._tasks = []

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

        self._tasks.append(asyncio.create_task(self._rpc_health_check()))

        if not self._tasks:
            print("❌ Nova: No chains connected. Cannot start.")
            self.running = False
            return

        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def stop(self):
        self.running = False
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._session and not self._session.closed:
            await self._session.close()
        print("✅ Nova: Stopped.")

    async def _supervise(self, coro_fn, name: str):
        backoff = 1
        max_backoff = 60
        while self.running:
            try:
                await coro_fn()
                if not self.running:
                    break
                print(f"⚠️ Nova: {name} watcher exited. Restarting...")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"❌ Nova: {name} watcher crashed: {e}")
                if not self.running:
                    break
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    async def _watch_evm_chain(self, chain: str):
        w3 = self.web3_instances.get(chain)
        if not w3:
            await asyncio.sleep(300)
            return

        config = self.CHAIN_CONFIG[chain]
        factory = w3.eth.contract(
            address=Web3.to_checksum_address(config["factory"]),
            abi=[{
                "anonymous": False,
                "inputs": [
                    {"indexed": True, "name": "token0", "type": "address"},
                    {"indexed": True, "name": "token1", "type": "address"},
                    {"indexed": False, "name": "pair", "type": "address"},
                    {"indexed": False, "name": "", "type": "uint256"},
                ],
                "name": "PairCreated",
                "type": "event",
            }],
        )

        try:
            saved = await self.db.get_cursor(chain)
            from_block = saved if saved else max(await asyncio.to_thread(lambda: w3.eth.block_number) - 50, 0)
            print(f"🔍 Nova: Resuming {chain} from block {from_block}")
        except Exception:
            from_block = max(await asyncio.to_thread(lambda: w3.eth.block_number) - 50, 0)

        while self.running:
            try:
                if not self._check_rate_limit(chain):
                    await asyncio.sleep(2)
                    continue

                current = await asyncio.to_thread(lambda: w3.eth.block_number)
                if current < from_block:
                    await asyncio.sleep(3)
                    continue

                while from_block <= current and self.running:
                    chunk_end = min(current, from_block + 50)
                    events = await asyncio.to_thread(
                        lambda fb=from_block, tb=chunk_end: factory.events.PairCreated().get_logs(
                            from_block=fb, to_block=tb
                        )
                    )

                    for evt in events:
                        try:
                            token0 = evt.args.token0
                            token1 = evt.args.token1
                            pair = evt.args.pair
                            new_token = token1 if token0.lower() == config["w_native"].lower() else token0

                            info = await self._fetch_evm_token_info(w3, new_token)
                            token_event = TokenEvent(
                                event_type="NEW_TOKEN",
                                chain=chain,
                                token_address=new_token,
                                token_symbol=info.get("symbol", "UNKNOWN"),
                                token_name=info.get("name", "Unknown"),
                                creator=info.get("creator", "unknown"),
                                timestamp=time.time(),
                                block_number=chunk_end,
                                origin_source="uniswap" if chain != "bsc" else "pancakeswap",
                                raw_data={"pair": pair, "token0": token0, "token1": token1},
                            )

                            if await self._passes_quality_check(token_event):
                                await self._handle_discovery(token_event)

                        except Exception as inner:
                            print(f"⚠️ Nova: Event processing error: {inner}")

                    from_block = chunk_end + 1
                    try:
                        await self.db.save_cursor(chain, from_block)
                    except Exception as e:
                        print(f"⚠️ Nova: Cursor save failed: {e}")

                    await asyncio.sleep(3)

            except Exception as e:
                print(f"⚠️ Nova: {chain} watcher loop error: {e}")
                await asyncio.sleep(5)

    async def _fetch_evm_token_info(self, w3: Web3, token_address: str) -> dict:
        abi = [
            {"constant": True, "inputs": [], "name": "name", "outputs": [{"name": "", "type": "string"}], "type": "function"},
            {"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "type": "function"},
            {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
        ]
        try:
            token = w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=abi)
            name = await asyncio.to_thread(token.functions.name().call)
            symbol = await asyncio.to_thread(token.functions.symbol().call)
            decimals = await asyncio.to_thread(token.functions.decimals().call)
            return {"name": name, "symbol": symbol, "decimals": decimals, "creator": "unknown"}
        except Exception as e:
            print(f"⚠️ Nova: Token info fetch failed: {e}")
            return {"name": "Unknown", "symbol": "???", "decimals": 18, "creator": "unknown"}

    async def _watch_solana(self):
        if not self.solana_rpc_url:
            await asyncio.sleep(300)
            return

        rpc = self.solana_rpc_url
        headers = {"Content-Type": "application/json"}
        last_sig = None
        session = await self._get_session()

        while self.running:
            try:
                if not self._check_rate_limit("solana"):
                    await asyncio.sleep(2)
                    continue

                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getSignaturesForAddress",
                    "params": [self.RAYDIUM_AMM_V4, {"limit": 20}],
                }
                async with session.post(rpc, json=payload, headers=headers, timeout=15) as resp:
                    if resp.status != 200:
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
                            if not self.running:
                                break
                            await self._process_solana_tx(sig, rpc, headers, session)

                        last_sig = sigs[0]["signature"]

                    await asyncio.sleep(8)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"⚠️ Nova: Solana watcher error: {e}")
                await asyncio.sleep(10)

    async def _process_solana_tx(self, sig: str, rpc: str, headers: dict, session: aiohttp.ClientSession):
        tx_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTransaction",
            "params": [sig, {"encoding": "json", "maxSupportedTransactionVersion": 0}],
        }
        try:
            async with session.post(rpc, json=tx_payload, headers=headers, timeout=15) as resp:
                data = await resp.json()
                tx = data.get("result")
                if not tx:
                    return
                meta = tx.get("meta", {})
                balances = meta.get("postTokenBalances", [])
                found = set()
                for bal in balances:
                    mint = bal.get("mint")
                    if mint and mint not in self.SOLANA_IGNORE_MINTS:
                        found.add(mint)

                for mint in found:
                    supply_payload = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getTokenSupply",
                        "params": [mint],
                    }
                    try:
                        async with session.post(rpc, json=supply_payload, headers=headers, timeout=10) as sresp:
                            sdata = await sresp.json()
                            sinfo = sdata.get("result", {}).get("value", {})
                            if not sinfo or sinfo.get("uiAmount", 0) == 0:
                                continue
                    except Exception:
                        continue

                    info = await self._fetch_solana_token_info_rpc(mint, rpc, session)
                    event = TokenEvent(
                        event_type="NEW_TOKEN",
                        chain="solana",
                        token_address=mint,
                        token_symbol=info.get("symbol", "UNKNOWN"),
                        token_name=info.get("name", "Unknown"),
                        creator="unknown",
                        timestamp=time.time(),
                        origin_source="raydium",
                        raw_data={"signature": sig, "supply": sinfo.get("uiAmountString")},
                    )

                    if await self._passes_quality_check(event):
                        jupiter_ok = await self._check_jupiter_available(session, mint)
                        if not jupiter_ok:
                            event.jupiter_failed = True
                            print(f"⚠️ Nova: Jupiter unavailable for {event.token_symbol}")
                        await self._handle_discovery(event)

        except Exception as e:
            print(f"⚠️ Nova: Solana tx parse error: {e}")

    async def _check_jupiter_available(self, session: aiohttp.ClientSession, token_mint: str) -> bool:
        try:
            url = f"{self.JUPITER_QUOTE}/quote?inputMint={self.WSOL}&outputMint={token_mint}&amount=10000000&slippageBps=500&onlyDirectRoutes=false"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                return resp.status == 200
        except Exception:
            return False

    async def _fetch_solana_token_info_rpc(self, mint: str, rpc: str, session: aiohttp.ClientSession) -> dict:
        payload = {"jsonrpc": "2.0", "id": 1, "method": "getTokenSupply", "params": [mint]}
        try:
            async with session.post(rpc, json=payload, headers={"Content-Type": "application/json"}, timeout=10) as resp:
                data = await resp.json()
                value = data.get("result", {}).get("value", {})
                return {
                    "name": "Unknown",
                    "symbol": "???",
                    "decimals": value.get("decimals", 9),
                    "creator": "unknown",
                    "supply": value.get("uiAmountString", "0"),
                }
        except Exception as e:
            print(f"⚠️ Nova: Solana token info failed: {e}")
            return {"name": "Unknown", "symbol": "???", "decimals": 9, "creator": "unknown"}

    async def _fetch_dexscreener_token(self, token_address: str, chain_slug: str) -> dict:
        url = f"https://api.dexscreener.com/tokens/v1/{chain_slug}/{token_address}"
        try:
            session = await self._get_session()
            async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
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
                    "all_pairs": pairs,
                }
        except Exception as e:
            print(f"⚠️ Nova: DexScreener lookup failed: {e}")
            return {}

    async def search_token(self, token_address: str, chain: Optional[str] = None) -> Optional[TokenEvent]:
        token_address = token_address.strip()
        if chain is None:
            if token_address.startswith("0x") and len(token_address) == 42:
                chain = "ethereum"
            elif 32 <= len(token_address) <= 44 and not token_address.startswith("0x"):
                chain = "solana"
            else:
                return None
        else:
            chain = chain.lower()
            if chain == "eth":
                chain = "ethereum"
            elif chain == "bnb":
                chain = "bsc"

        if chain in self.CHAIN_CONFIG:
            if not Web3.is_address(token_address):
                return None
            token_address = Web3.to_checksum_address(token_address)
            w3 = self.web3_instances.get(chain)
            info = await self._fetch_evm_token_info(w3, token_address) if w3 else {"name": "Unknown", "symbol": "???", "creator": "unknown"}
        elif chain == "solana":
            if not self._is_solana_address(token_address):
                return None
            session = await self._get_session()
            info = await self._fetch_solana_token_info_rpc(token_address, self.solana_rpc_url, session)
        else:
            return None

        dex_slug = self.CHAIN_CONFIG.get(chain, {}).get("dex_slug", chain)
        market = await self._fetch_dexscreener_token(token_address, dex_slug)

        event = TokenEvent(
            event_type="USER_QUERY",
            chain=chain,
            token_address=token_address,
            token_symbol=info.get("symbol", "UNKNOWN"),
            token_name=info.get("name", "Unknown"),
            creator=info.get("creator", "unknown"),
            timestamp=time.time(),
            liquidity_usd=market.get("liquidity_usd"),
            market_cap=market.get("market_cap"),
            origin_source="user_query",
            raw_data={"token_info": info, "market": market},
        )
        event.attention_score = 100.0

        if await self._passes_quality_check(event):
            await self._handle_discovery(event)

        return event

    def _is_solana_address(self, addr: str) -> bool:
        if addr.startswith("0x") or len(addr) < 32 or len(addr) > 44:
            return False
        base58 = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")
        return all(c in base58 for c in addr)
