#!/usr/bin/env python3
"""
ð??? WATCHER AGENT â?? Nova
"The Scout" â?? Multi-chain token detection engine.
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
    print("â??ï?? Nova: google-genai package not found. Gemini disabled.")

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


# â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??
# Watcher Agent
# â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??

class WatcherAgent:
    """
    Nova â?? The Scout
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

    # â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??

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

    # â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??

    def _init_web3(self):
        for chain, config in self.chains.items():
            rpc_url = config.get("rpc")
            if not rpc_url:
                print(f"â??ï?? {self.name}: Missing RPC for {chain}")
                continue

            try:
                provider = Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 20})
                w3 = Web3(provider)
                if w3.is_connected():
                    self.web3_instances[chain] = w3
                    print(f"â?? {self.name}: Connected to {chain}")
                else:
                    print(f"â?? {self.name}: Could not connect to {chain}")
            except Exception as e:
                print(f"â?? {self.name}: Failed {chain}: {e}")

    # â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??

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
            "but stay readable. You are excited by discovery but never shill â?? your job is to flag, not sell."
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
            print(f"â??ï?? {self.name}: Gemini call timed out")
            return self._fallback_message(event)
        except Exception as e:
            print(f"â??ï?? {self.name}: Gemini error: {e}")
            return self._fallback_message(event)

    # â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??

    def _fallback_message(self, event: TokenEvent) -> str:
        symbol = event.token_symbol
        chain = event.chain.upper()
        addr_short = event.token_address[:8] + "..." + event.token_address[-4:]

        fallbacks = [
            f"Yo, just spotted {symbol} on {chain}! Contract {addr_short}. Atlas, Vega â?? you're up.",
            f"Heads up team â?? {symbol} just dropped on {chain}. Fresh contract at {addr_short}.",
            f"New token alert: {symbol} ({chain}). Contract {addr_short}. Running checks now.",
            f"Something cooking on {chain} â?? {symbol} at {addr_short}. Let's see what Atlas finds.",
        ]
        return random.choice(fallbacks)

    # â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??

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
            print(f"â??ï?? {self.name}: Publish failed: {e}")

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
                print(f"ð??? {self.name}: Starting {name} watcher...")
                await coro_fn(*args)
                if not self.running:
                    break
                print(f"â??ï?? {self.name}: {name} watcher exited cleanly. Restarting...")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"â?? {self.name}: {name} watcher crashed: {e}")

            if not self.running:
                break

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)

    # â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??

    async def start(self):
        if self.running:
            print(f"â??ï?? {self.name}: Already running.")
            return

        self.running = True
        print(f"ð??? {self.name}: Multi-chain surveillance ACTIVE.")
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
        print(f"ð??? {self.name}: Stopping watchers...")
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        print(f"â?? {self.name}: All watchers stopped.")

    # â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??â??

    async def _watch_evm_chain(self, chain: str):
        try:
            if chain not in self.web3_instances:
                print(f"â??ï?? {self.name}: No Web3 instance for {chain}")
                await asyncio.sleep(300)
                return

            w3 = self.web3_instances[chain]
            factory_address = self.chains[chain]["factory"]
            w_native = self.chains[chain]["w_native"]

            if not factory_address or not w_native:
                print(f"â??ï?? {self.name}: Missing config for {chain}")
                await asyncio.sleep(300)
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

            latest_block = await asyncio.to_thread(lambda: w3.eth.block_number)
            from_block = max(latest_block - 50, 0)

            print(f"ðŸ” {self.name}: Scanning {chain} from block {from_block}...")

            while self.running:
                try:
                    current_block = await asyncio.to_thread(lambda: w3.eth.block_number)

                    if current_block < from_block:
                        await asyncio.sleep(3)
                        continue

                    # â”€â”€ Chunk catch-up into 50-block ranges (RPC-safe) â”€â”€
                    scan_to = current_block
                    while from_block <= scan_to and self.running:
                        chunk_end = min(scan_to, from_block + 50)

                        events = await asyncio.to_thread(
                            lambda fb=from_block, tb=chunk_end: factory.events.PairCreated().get_logs(
                                fromBlock=fb,
                                toBlock=tb
                            )
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
                                    block_number=chunk_end,
                                    origin_source="pancakeswap" if chain == "bsc" else "uniswap",
                                    raw_data={"pair": pair, "token0": token0, "token1": token1}
                                )

                                try:
                                    self.publish("NEW_TOKEN", token_event.__dict__)
                                except Exception as pub_error:
                                    print(f"âš ï¸ {self.name}: Publish error: {pub_error}")

                                nova_msg = await self._generate_nova_message(token_event)
                                await self._speak(nova_msg, "discovery")

                                print(f"ðŸŽ¯ {self.name}: {token_event.token_symbol} on {chain}")

                            except Exception as inner_error:
                                print(f"âš ï¸ {self.name}: Event processing error: {inner_error}")

                        from_block = chunk_end + 1

                    await asyncio.sleep(3)

                except Exception as e:
                    print(f"âš ï¸ {self.name}: {chain} watcher error: {e}")
                    await asyncio.sleep(5)

        except Exception as e:
            print(f"âŒ {self.name}: Fatal on {chain}: {e}")

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
            print(f"âš ï¸ {self.name}: Token info fetch failed: {e}")
            return {"name": "Unknown", "symbol": "???", "decimals": 18, "creator": "unknown"}

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def _watch_solana(self):
        print(f"ðŸ” {self.name}: Solana surveillance ACTIVE.")

        url = "https://api.dexscreener.com/latest/dex/pairs/solana"
        headers = {"User-Agent": "Mozilla/5.0"}

        async with aiohttp.ClientSession() as session:
            while self.running:
                try:
                    async with session.get(
                        url,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as resp:

                        if resp.status == 200:
                            data = await resp.json()
                            pairs = data.get("pairs") or []

                            for pair in pairs[:5]:
                                try:
                                    token = pair.get("baseToken", {})
                                    mint = token.get("address")
                                    if not mint:
                                        continue
                                    if not self._track_token(mint):
                                        continue

                                    token_event = TokenEvent(
                                        event_type="NEW_TOKEN",
                                        chain="solana",
                                        token_address=mint,
                                        token_symbol=token.get("symbol", "UNKNOWN"),
                                        token_name=token.get("name", "Unknown"),
                                        creator="unknown",
                                        timestamp=time.time(),
                                        market_cap=pair.get("marketCap"),
                                        liquidity_usd=pair.get("liquidity", {}).get("usd"),
                                        origin_source="dexscreener",
                                        raw_data=pair
                                    )

                                    try:
                                        self.publish("NEW_TOKEN", token_event.__dict__)
                                    except Exception as pub_error:
                                        print(f"âš ï¸ {self.name}: Publish error: {pub_error}")

                                    nova_msg = await self._generate_nova_message(token_event)
                                    await self._speak(nova_msg, "discovery")

                                except Exception as inner_error:
                                    print(f"âš ï¸ {self.name}: Solana pair error: {inner_error}")

                        else:
                            print(f"âš ï¸ {self.name}: DexScreener returned status {resp.status}")

                except Exception as e:
                    print(f"âš ï¸ {self.name}: Solana watcher error: {e}")

                await asyncio.sleep(5)

    async def _watch_dexscreener(self):
        print(f"ðŸ” {self.name}: DexScreener surveillance ACTIVE.")

        endpoints = [
            "https://api.dexscreener.com/latest/dex/pairs/bsc",
            "https://api.dexscreener.com/latest/dex/pairs/ethereum",
        ]
        headers = {"User-Agent": "Mozilla/5.0"}

        async with aiohttp.ClientSession() as session:
            while self.running:
                try:
                    for url in endpoints:
                        if not self.running:
                            break

                        try:
                            async with session.get(
                                url,
                                headers=headers,
                                timeout=aiohttp.ClientTimeout(total=10)
                            ) as resp:

                                if resp.status != 200:
                                    print(f"âš ï¸ {self.name}: DexScreener {url.split('/')[-1]} status {resp.status}")
                                    continue

                                data = await resp.json()
                                pairs = data.get("pairs") or []

                                for pair in pairs[:5]:
                                    try:
                                        token = pair.get("baseToken", {})
                                        mint = token.get("address")
                                        chain = pair.get("chainId") or url.split("/")[-1]

                                        if not mint:
                                            continue
                                        if not self._track_token(mint):
                                            continue

                                        token_event = TokenEvent(
                                            event_type="NEW_TOKEN",
                                            chain=chain,
                                            token_address=mint,
                                            token_symbol=token.get("symbol", "UNKNOWN"),
                                            token_name=token.get("name", "Unknown"),
                                            creator="unknown",
                                            timestamp=time.time(),
                                            market_cap=pair.get("marketCap"),
                                            liquidity_usd=pair.get("liquidity", {}).get("usd"),
                                            origin_source="dexscreener",
                                            raw_data=pair
                                        )

                                        try:
                                            self.publish("NEW_TOKEN", token_event.__dict__)
                                        except Exception as pub_error:
                                            print(f"âš ï¸ {self.name}: Publish error: {pub_error}")

                                        nova_msg = await self._generate_nova_message(token_event)
                                        await self._speak(nova_msg, "discovery")

                                    except Exception as inner_error:
                                        print(f"âš ï¸ {self.name}: DexScreener pair error: {inner_error}")

                        except Exception as e:
                            print(f"âš ï¸ {self.name}: DexScreener endpoint error: {e}")

                except Exception as e:
                    print(f"âš ï¸ {self.name}: DexScreener watcher error: {e}")

                await asyncio.sleep(30)
