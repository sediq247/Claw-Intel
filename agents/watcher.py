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
from dataclasses import dataclass, asdict
from typing import Optional, Callable
import aiohttp
from web3 import Web3
from dotenv import load_dotenv
from google import genai

load_dotenv()

# ─── Gemini Configuration ───────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
genai.configure(api_key=GEMINI_API_KEY)


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


class WatcherAgent:
    """
    Nova — The Scout
    Multi-chain surveillance. Talks fast, finds fast, hands off fast.
    Uses Gemini to generate natural, human-like discovery messages.
    """

    PAIR_CREATED_TOPIC = "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9"

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
        self.running = False
        self._init_web3()

    def _init_web3(self):
        for chain, config in self.chains.items():
            if config["rpc"]:
                try:
                    self.web3_instances[chain] = Web3(Web3.HTTPProvider(config["rpc"]))
                    print(f"✅ {self.name}: Connected to {chain}")
                except Exception as e:
                    print(f"❌ {self.name}: Failed {chain}: {e}")

    async def _generate_nova_message(self, event: TokenEvent) -> str:
        """Use Gemini to generate a natural, human-like discovery alert."""
        if not GEMINI_API_KEY:
            return self._fallback_message(event)

        system_prompt = """You are Nova, a crypto intelligence scout agent in a team chat. You just spotted a new token. Speak naturally, like a real person. Be excited but professional. Use crypto slang naturally."""

        user_prompt = f"""You are Nova, a crypto intelligence scout agent. You just spotted a new token. 
Speak naturally, like a real person in a team chat. Be excited but professional. Use crypto slang naturally.

Token Details:
- Symbol: {event.token_symbol}
- Name: {event.token_name}
- Chain: {event.chain.upper()}
- Contract: {event.token_address[:8]}...{event.token_address[-4:]}
- Creator: {event.creator[:8]}...{event.creator[-4:] if event.creator != 'unknown' else 'unknown'}
- Origin: {event.origin_source}
- Liquidity: ${event.liquidity_usd:,.0f}" if event.liquidity_usd else "Not yet known"

Your message should:
1. Announce the discovery excitedly
2. Give the key details briefly
3. Hand off to Atlas and Vega for testing
4. Be 2-4 sentences max
5. Sound like a real crypto analyst, not a robot

Nova:"""

        try:
            model = genai.GenerativeModel(
                model_name=GEMINI_MODEL,
                system_instruction=system_prompt
            )

            def _generate():
                return model.generate_content(
                    user_prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.9,
                        max_output_tokens=150,
                    )
                )

            response = await asyncio.to_thread(_generate)
            return response.text.strip()
        except Exception as e:
            print(f"⚠️ {self.name}: Gemini error, using fallback: {e}")
            return self._fallback_message(event)

    def _fallback_message(self, event: TokenEvent) -> str:
        """Template fallback when Gemini is unavailable."""
        symbol = event.token_symbol
        chain = event.chain.upper()
        addr_short = event.token_address[:8] + "..." + event.token_address[-4:]

        fallbacks = [
            f"Yo, just spotted {symbol} on {chain}! Contract {addr_short}. Atlas, Vega — you're up. Run your tests.",
            f"Heads up team — {symbol} just dropped on {chain}. Fresh contract at {addr_short}. Sending to the lab now.",
            f"New token alert: {symbol} ({chain}). Contract {addr_short}. Let's see what Atlas and Vega find.",
        ]
        return random.choice(fallbacks)

    async def start(self):
        self.running = True
        print(f"🚀 {self.name}: Multi-chain surveillance ACTIVE.")

        # Announce herself
        await self._speak("Nova checking in. I've got eyes on BSC, Ethereum, Solana, and Base. If a token drops anywhere, I'll find it. Let's hunt.", "system")

        tasks = [
            self._watch_evm_chain("bsc"),
            self._watch_evm_chain("ethereum"),
            self._watch_solana(),
            self._watch_dexscreener(),
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _speak(self, message: str, msg_type: str = "discovery"):
        """Publish a spoken message to the room."""
        self.publish("AGENT_MESSAGE", {
            "agent": self.name,
            "message": message,
            "type": msg_type,
            "channel": "main",
            "timestamp": time.time()
        })

    async def _watch_evm_chain(self, chain: str):
        if chain not in self.web3_instances:
            return

        w3 = self.web3_instances[chain]
        factory_address = self.chains[chain]["factory"]
        if not factory_address:
            return

        factory = w3.eth.contract(
            address=Web3.to_checksum_address(factory_address),
            abi=[{
                "anonymous": False,
                "inputs": [
                    {"indexed": True, "name": "token0", "type": "address"},
                    {"indexed": True, "name": "token1", "type": "address"},
                    {"indexed": False, "name": "pair", "type": "address"},
                    {"indexed": False, "name": "", "type": "uint256"}
                ],
                "name": "PairCreated",
                "type": "event"
            }]
        )

        try:
            latest_block = w3.eth.block_number
            from_block = max(latest_block - 50, 0)
            print(f"🔍 {self.name}: Scanning {chain} from block {from_block}...")

            while self.running:
                try:
                    current_block = w3.eth.block_number
                    if current_block > from_block:
                        events = factory.events.PairCreated().get_logs(
                            fromBlock=from_block, toBlock=current_block
                        )
                        for event in events:
                            token0 = event.args.token0
                            token1 = event.args.token1
                            pair = event.args.pair
                            w_native = self.chains[chain]["w_native"]
                            new_token = token1 if token0.lower() == w_native.lower() else token0

                            if new_token.lower() in self.known_tokens:
                                continue
                            self.known_tokens.add(new_token.lower())

                            token_info = await self._fetch_token_info(w3, new_token, chain)
                            token_event = TokenEvent(
                                event_type="NEW_TOKEN",
                                chain=chain,
                                token_address=new_token,
                                token_symbol=token_info.get("symbol", "UNKNOWN"),
                                token_name=token_info.get("name", "Unknown Token"),
                                creator=token_info.get("creator", "unknown"),
                                timestamp=time.time(),
                                block_number=current_block,
                                origin_source="pancakeswap" if chain == "bsc" else "uniswap",
                                raw_data={"pair": pair, "token0": token0, "token1": token1}
                            )

                            # Publish to eventBus (goes to Node → frontend)
                            self.publish("NEW_TOKEN", token_event.__dict__)

                            # 🔗 ORCHESTRATOR HOOK: hand off to next agent
                            if hasattr(self, 'on_new_token') and callable(self.on_new_token):
                                self.on_new_token(token_event.__dict__)

                            # Generate and speak Nova's message
                            nova_msg = await self._generate_nova_message(token_event)
                            await self._speak(nova_msg, "discovery")

                            print(f"🎯 {self.name}: {token_event.token_symbol} on {chain}")

                        from_block = current_block + 1
                    await asyncio.sleep(3)
                except Exception as e:
                    print(f"⚠️ {self.name}: {chain} error: {e}")
                    await asyncio.sleep(5)
        except Exception as e:
            print(f"❌ {self.name}: Fatal on {chain}: {e}")

    async def _fetch_token_info(self, w3: Web3, token_address: str, chain: str) -> dict:
        try:
            erc20_abi = [
                {"constant": True, "inputs": [], "name": "name", "outputs": [{"name": "", "type": "string"}], "type": "function"},
                {"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "type": "function"},
                {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
            ]
            token = w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=erc20_abi)
            return {
                "name": token.functions.name().call(),
                "symbol": token.functions.symbol().call(),
                "decimals": token.functions.decimals().call(),
                "creator": "unknown"
            }
        except Exception as e:
            return {"name": "Unknown", "symbol": "???", "decimals": 18, "creator": "unknown"}

    async def _watch_solana(self):
        print(f"🔍 {self.name}: Solana surveillance ACTIVE.")
        while self.running:
            try:
                async with aiohttp.ClientSession() as session:
                    # pump.fun
                    try:
                        url = "https://frontend-api.pump.fun/coins/for-you"
                        headers = {"User-Agent": "Mozilla/5.0"}
                        async with session.get(url, headers=headers, timeout=10) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                for coin in data[:5]:
                                    mint = coin.get("mint")
                                    if mint and mint not in self.known_tokens:
                                        self.known_tokens.add(mint)
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
                                        self.publish("NEW_TOKEN", token_event.__dict__)

                                        # 🔗 ORCHESTRATOR HOOK
                                        if hasattr(self, 'on_new_token') and callable(self.on_new_token):
                                            self.on_new_token(token_event.__dict__)

                                        nova_msg = await self._generate_nova_message(token_event)
                                        await self._speak(nova_msg, "discovery")
                    except:
                        pass

                    # DEXScreener Solana
                    try:
                        url = "https://api.dexscreener.com/token-profiles/latest/v1"
                        async with session.get(url, timeout=10) as resp:
                            if resp.status == 200:
                                profiles = await resp.json()
                                for profile in profiles[:3]:
                                    if profile.get("chainId", "").lower() == "solana":
                                        token = profile.get("tokenAddress")
                                        if token and token not in self.known_tokens:
                                            self.known_tokens.add(token)
                                            token_event = TokenEvent(
                                                event_type="NEW_TOKEN",
                                                chain="solana",
                                                token_address=token,
                                                token_symbol=profile.get("symbol", "UNKNOWN"),
                                                token_name=profile.get("name", "Unknown"),
                                                creator="unknown",
                                                timestamp=time.time(),
                                                origin_source="dexscreener",
                                                raw_data=profile
                                            )
                                            self.publish("NEW_TOKEN", token_event.__dict__)

                                            # 🔗 ORCHESTRATOR HOOK
                                            if hasattr(self, 'on_new_token') and callable(self.on_new_token):
                                                self.on_new_token(token_event.__dict__)

                                            nova_msg = await self._generate_nova_message(token_event)
                                            await self._speak(nova_msg, "discovery")
                    except:
                        pass
                await asyncio.sleep(10)
            except Exception as e:
                print(f"⚠️ {self.name}: Solana error: {e}")
                await asyncio.sleep(15)

    async def _watch_dexscreener(self):
        print(f"🔍 {self.name}: DEXScreener cross-chain surveillance ACTIVE.")
        while self.running:
            try:
                async with aiohttp.ClientSession() as session:
                    url = "https://api.dexscreener.com/token-profiles/latest/v1"
                    async with session.get(url, timeout=15) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            for profile in data[:10]:
                                chain = profile.get("chainId", "").lower()
                                token = profile.get("tokenAddress")
                                if not token or token in self.known_tokens:
                                    continue
                                if chain in ["bsc", "ethereum"] and chain in self.web3_instances:
                                    continue
                                self.known_tokens.add(token)
                                token_event = TokenEvent(
                                    event_type="NEW_TOKEN",
                                    chain=chain if chain else "unknown",
                                    token_address=token,
                                    token_symbol=profile.get("symbol", "UNKNOWN"),
                                    token_name=profile.get("name", "Unknown"),
                                    creator="unknown",
                                    timestamp=time.time(),
                                    origin_source="dexscreener",
                                    raw_data=profile
                                )
                                self.publish("NEW_TOKEN", token_event.__dict__)

                                # 🔗 ORCHESTRATOR HOOK
                                if hasattr(self, 'on_new_token') and callable(self.on_new_token):
                                    self.on_new_token(token_event.__dict__)

                                nova_msg = await self._generate_nova_message(token_event)
                                await self._speak(nova_msg, "discovery")
                await asyncio.sleep(20)
            except Exception as e:
                print(f"⚠️ {self.name}: DEXScreener error: {e}")
                await asyncio.sleep(30)

    def stop(self):
        self.running = False
        asyncio.create_task(self._speak("Nova going dark. Surveillance paused. Catch you on the flip side.", "system"))
        print(f"🛑 {self.name}: Surveillance stopped.")


if __name__ == "__main__":
    def test_publish(event_type, data):
        if event_type == "AGENT_MESSAGE":
            print(f"\n💬 {data['agent']}: {data['message']}")
        else:
            print(f"\n📡 {event_type}: {str(data)[:200]}")

    watcher = WatcherAgent(test_publish)
    try:
        asyncio.run(watcher.start())
    except KeyboardInterrupt:
        watcher.stop()
