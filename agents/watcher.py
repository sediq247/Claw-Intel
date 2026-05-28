#!/usr/bin/env python3
"""
👁 WATCHER AGENT — Nova
"The Scout" — Multi-chain token detection engine.
Detects newly created tokens, shouts to the room, hands off to the team.
Uses Gemini for natural spoken alerts.
"""

import asyncio
import json
import os
import time
import random

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
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

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
    origin_source: str = "unknown"
    raw_data: Optional[dict] = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)


# ─────────────────────────────────────────────────────────────
# Watcher Agent
# ─────────────────────────────────────────────────────────────

class WatcherAgent:
    """
    Nova — The Scout
    Multi-chain surveillance. Talks fast, finds fast, hands off fast.
    """

    PAIR_CREATED_TOPIC = (
        "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9"
    )

    def __init__(self, event_bus_publish: Callable[[str, dict], None]):
        self.publish = event_bus_publish
        self.name = "Nova"

        self.chains = {
            "bsc": {
                "rpc": os.getenv("BSC_RPC_URL"),
                "factory": os.getenv("PANCAKE_FACTORY"),
                "w_native": os.getenv("WBNB_ADDRESS"),
            },
            "ethereum": {
                "rpc": os.getenv("ETH_RPC_URL"),
                "factory": os.getenv("UNISWAP_FACTORY"),
                "w_native": os.getenv("WETH_ADDRESS"),
            }
        }

        self.web3_instances = {}
        self.known_tokens = set()
        self.token_queue = deque(maxlen=10000)
        self.running = False
        self._tasks = []

        self._init_web3()

    # ─────────────────────────────────────────────────────────

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

    # ─────────────────────────────────────────────────────────

    def _init_web3(self):
        for chain, config in self.chains.items():
            rpc_url = config.get("rpc")
            if not rpc_url:
                print(f"⚠️ {self.name}: Missing RPC for {chain}")
                continue

            try:
                provider = Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 20})
                w3 = Web3(provider)
                if w3.is_connected():
                    self.web3_instances[chain] = w3
                    print(f"✅ {self.name}: Connected to {chain}")
                else:
                    print(f"❌ {self.name}: Could not connect to {chain}")
            except Exception as e:
                print(f"❌ {self.name}: Failed {chain}: {e}")

    # ─────────────────────────────────────────────────────────

    async def _generate_nova_message(self, event: TokenEvent) -> str:
        if not client:
            return self._fallback_message(event)

        creator_short = (
            f"{event.creator[:8]}...{event.creator[-4:]}"
            if event.creator != "unknown"
            else "unknown"
        )

        liquidity_text = (
            f"${event.liquidity_usd:,.0f}"
            if event.liquidity_usd
            else "Not yet known"
        )

        market_cap_text = (
            f"${event.market_cap:,.0f}"
            if event.market_cap
            else "Not yet known"
        )

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
3. Note any obvious red flags if present (unknown creator, zero liquidity, etc.)
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

            response = await asyncio.wait_for(
                asyncio.to_thread(_generate),
                timeout=15
            )

            if response and hasattr(response, "text") and response.text:
                return response.text.strip()

            return self._fallback_message(event)

        except asyncio.TimeoutError:
            print(f"⚠️ {self.name}: Gemini call timed out")
            return self._fallback_message(event)
        except Exception as e:
            print(f"⚠️ {self.name}: Gemini error: {e}")
            return self._fallback_message(event)

    # ─────────────────────────────────────────────────────────

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

    # ─────────────────────────────────────────────────────────

    async def _speak(self, message: str, msg_type: str = "discovery"):
        try:
            self.publish("AGENT_MESSAGE", {
                "agent": self.name,
                "message": message,
                "type": msg_type,
                "channel": "main",
                "timestamp": time.time()
            })
        except Exception as e:
            print(f"⚠️ {self.name}: Publish failed: {e}")

    async def _supervise(self, coro_fn, name: str, *args):
        """
        If a watcher crashes, log it, back off, and restart it.
        Prevents one broken chain from killing the whole agent.
        Stops cleanly when self.running becomes False.
        """
        backoff = 1
        max_backoff = 60
        while self.running:
            try:
                print(f"🔄 {self.name}: Starting {name} watcher...")
                await coro_fn(*args)
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

    # ─────────────────────────────────────────────────────────

    async def start(self):
        if self.running:
            print(f"⚠️ {self.name}: Already running.")
            return

        self.running = True
        print(f"🚀 {self.name}: Multi-chain surveillance ACTIVE.")
        await self._speak("Nova checking in. Surveillance systems online. Eyes everywhere.", "system")

        self._tasks = [
            asyncio.create_task(self._supervise(self._watch_evm_chain, "BSC", "bsc")),
            asyncio.create_task(self._supervise(self._watch_evm_chain, "ETH", "ethereum")),
            asyncio.create_task(self._supervise(self._watch_solana, "Solana")),
            asyncio.create_task(self._supervise(self._watch_dexscreener, "DexScreener")),
        ]

        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def stop(self):
        """Graceful shutdown."""
        self.running = False
        print(f"🛑 {self.name}: Stopping watchers...")
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        print(f"✅ {self.name}: All watchers stopped.")

    # ─────────────────────────────────────────────────────────

    async def _watch_evm_chain(self, chain: str):
        try:
            if chain not in self.web3_instances:
                print(f"⚠️ {self.name}: No Web3 instance for {chain}")
                return

            w3 = self.web3_instances[chain]
            factory_address = self.chains[chain]["factory"]
            w_native = self.chains[chain]["w_native"]

            if not factory_address or not w_native:
                print(f"⚠️ {self.name}: Missing config for {chain}")
                return

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

            latest_block = w3.eth.block_number
            from_block = max(latest_block - 50, 0)

            print(f"🔍 {self.name}: Scanning {chain}...")

            while self.running:
                try:
                    current_block = w3.eth.block_number

                    # Guard against RPC lag / re-orgs causing invalid ranges
                    if current_block <= from_block:
                        await asyncio.sleep(3)
                        continue

                    events = factory.events.PairCreated().get_logs(
                        fromBlock=from_block,
                        toBlock=current_block
                    )

                    for event in events:
                        try:
                            token0 = event.args.token0
                            token1 = event.args.token1
                            pair = event.args.pair

                            new_token = token1 if token0.lower() == w_native.lower() else token0

                            if not self._track_token(new_token):
                                continue

                            token_info = await self._fetch_token_info(w3, new_token, chain)

                            token_event = TokenEvent(
                                event_type="NEW_TOKEN",
                                chain=chain,
                                token_address=new_token,
                                token_symbol=token_info.get("symbol", "UNKNOWN"),
                                token_name=token_info.get("name", "Unknown"),
                                creator=token_info.get("creator", "unknown"),
                                timestamp=time.time(),
                                block_number=current_block,
                                origin_source="pancakeswap" if chain == "bsc" else "uniswap",
                                raw_data={"pair": pair, "token0": token0, "token1": token1}
                            )

                            try:
                                self.publish("NEW_TOKEN", token_event.__dict__)
                            except Exception as pub_error:
                                print(f"⚠️ {self.name}: Publish error: {pub_error}")

                            nova_msg = await self._generate_nova_message(token_event)
                            await self._speak(nova_msg, "discovery")

                            print(f"🎯 {self.name}: {token_event.token_symbol} on {chain}")

                        except Exception as inner_error:
                            print(f"⚠️ {self.name}: Event processing error: {inner_error}")

                    from_block = current_block + 1
                    await asyncio.sleep(3)

                except Exception as e:
                    print(f"⚠️ {self.name}: {chain} watcher error: {e}")
                    await asyncio.sleep(5)

        except Exception as e:
            print(f"❌ {self.name}: Fatal on {chain}: {e}")

    # ─────────────────────────────────────────────────────────

    async def _fetch_token_info(self, w3: Web3, token_address: str, chain: str) -> dict:
        try:
            erc20_abi = [
                {"constant": True, "inputs": [], "name": "name", "outputs": [{"name": "", "type": "string"}], "type": "function"},
                {"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "type": "function"},
                {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
            ]

            token = w3.eth.contract(
                address=Web3.to_checksum_address(token_address),
                abi=erc20_abi
            )

            name, symbol, decimals = "Unknown", "???", 18

            try:
                name = token.functions.name().call()
            except Exception:
                pass
            try:
                symbol = token.functions.symbol().call()
            except Exception:
                pass
            try:
                decimals = token.functions.decimals().call()
            except Exception:
                pass

            return {"name": name, "symbol": symbol, "decimals": decimals, "creator": "unknown"}

        except Exception as e:
            print(f"⚠️ {self.name}: Token info fetch failed: {e}")
            return {"name": "Unknown", "symbol": "???", "decimals": 18, "creator": "unknown"}

    # ─────────────────────────────────────────────────────────

    async def _watch_solana(self):
        print(f"🔍 {self.name}: Solana surveillance ACTIVE.")

        while self.running:
            try:
                async with aiohttp.ClientSession() as session:
                    url = "https://frontend-api.pump.fun/coins/for-you"
                    headers = {"User-Agent": "Mozilla/5.0"}

                    async with session.get(
                        url,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as resp:

                        if resp.status == 200:
                            data = await resp.json()

                            for coin in data[:5]:
                                try:
                                    mint = coin.get("mint")
                                    if not mint:
                                        continue
                                    if not self._track_token(mint):
                                        continue

                                    token_event = TokenEvent(
                                        event_type="NEW_TOKEN",
                                        chain="solana",
                                        token_address=mint,
                                        token_symbol=coin.get("symbol", "UNKNOWN"),
                                        token_name=coin.get("name", "Unknown"),
                                        creator=coin.get("creator", "unknown"),
                                        timestamp=time.time(),
                                        market_cap=coin.get("usd_market_cap"),
                                        origin_source="pump.fun",
                                        raw_data=coin
                                    )

                                    try:
                                        self.publish("NEW_TOKEN", token_event.__dict__)
                                    except Exception as pub_error:
                                        print(f"⚠️ {self.name}: Publish error: {pub_error}")

                                    nova_msg = await self._generate_nova_message(token_event)
                                    await self._speak(nova_msg, "discovery")

                                except Exception as inner_error:
                                    print(f"⚠️ {self.name}: Solana coin error: {inner_error}")

                        else:
                            print(f"⚠️ {self.name}: Pump.fun returned status {resp.status}")

            except Exception as e:
                print(f"⚠️ {self.name}: Solana watcher error: {e}")

            await asyncio.sleep(5)

    async def _watch_dexscreener(self):
        print(f"🔍 {self.name}: DexScreener surveillance ACTIVE.")
        while self.running:
            try:
                # TODO: Implement DexScreener polling / WebSocket logic
                await asyncio.sleep(30)
            except Exception as e:
                print(f"⚠️ {self.name}: DexScreener error: {e}")
                await asyncio.sleep(5)
