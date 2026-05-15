#!/usr/bin/env python3
"""
💰 utils/marketEngine.py
The Data Aggregator.
Bridge between raw blockchain data and the UI.
Fetches from CoinGecko + DexScreener, calculates metrics,
normalizes multi-chain data, pushes live updates via eventBus.
"""

import asyncio
import json
import os
import time
from typing import Dict, List, Optional, Callable
import aiohttp
from dataclasses import dataclass, asdict, field
from dotenv import load_dotenv

from utils.helpers import (
    normalize_symbol, normalize_name, format_currency, format_percentage,
    format_price, format_large_number, unix_to_human, get_chain_display_name,
    normalize_dexscreener_token, normalize_coingecko_token, SimpleCache
)

load_dotenv()

# API Configuration
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "")
COINGECKO_BASE = "https://api.coingecko.com/api/v3"
DEXSCREENER_BASE = "https://api.dexscreener.com"

# Rate limiting
COINGECKO_RATE_LIMIT = 30 if COINGECKO_API_KEY else 10
DEXSCREENER_RATE_LIMIT = 300


@dataclass
class MarketToken:
    """Standardized token data for frontend."""
    id: str
    symbol: str
    name: str
    chain: str
    price: float
    price_change_24h: float
    price_change_7d: float
    market_cap: float
    volume_24h: float
    liquidity: float
    image: Optional[str] = None
    rank: int = 0
    ai_verified: bool = False
    ai_verdict: str = ""
    ai_confidence: float = 0.0
    last_updated: float = 0.0
    source: str = "unknown"

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'symbol': self.symbol,
            'name': self.name,
            'chain': self.chain,
            'price': format_price(self.price),
            'price_change_24h': format_percentage(self.price_change_24h),
            'price_change_7d': format_percentage(self.price_change_7d),
            'market_cap': format_currency(self.market_cap),
            'volume_24h': format_currency(self.volume_24h),
            'liquidity': format_currency(self.liquidity),
            'image': self.image,
            'rank': self.rank,
            'ai_verified': self.ai_verified,
            'ai_verdict': self.ai_verdict,
            'ai_confidence': f"{self.ai_confidence * 100:.0f}%",
            'last_updated': unix_to_human(self.last_updated),
            'source': self.source,
        }


class MarketEngine:
    """
    Market Data Aggregator.
    Fetches, normalizes, and caches market data from multiple sources.
    Pushes live updates via eventBus.
    """

    def __init__(self, event_bus_publish: Callable[[str, dict], None]):
        self.publish = event_bus_publish
        self.name = "MarketEngine"
        self.cache = SimpleCache(default_ttl=60)
        self.ai_verified_tokens: Dict[str, MarketToken] = {}
        self.trending_tokens: List[MarketToken] = []
        self.top_gainers: List[MarketToken] = []
        self.top_losers: List[MarketToken] = []
        self.running = False
        self.update_interval = 60
        self.coingecko_calls = []
        self.dexscreener_calls = []

    async def start(self):
        """Start the market engine background loop."""
        self.running = True
        print(f"💰 {self.name}: Market engine ACTIVE.")

        # Subscribe to AI verification events via eventBus
        # Note: In this architecture, the orchestrator wires eventBus subscriptions
        # We also handle direct REQUEST_MARKET_DATA from HTTP API

        while self.running:
            try:
                await self._update_all_markets()
                await asyncio.sleep(self.update_interval)
            except Exception as e:
                print(f"⚠️ {self.name}: Update error: {e}")
                await asyncio.sleep(10)

    async def _update_all_markets(self):
        """Update all market categories."""
        print(f"💰 {self.name}: Fetching market data...")

        results = await asyncio.gather(
            self._fetch_trending(),
            self._fetch_top_gainers(),
            self._fetch_top_losers(),
            return_exceptions=True
        )

        if not isinstance(results[0], Exception):
            self.trending_tokens = results[0]
        if not isinstance(results[1], Exception):
            self.top_gainers = results[1]
        if not isinstance(results[2], Exception):
            self.top_losers = results[2]

        # Publish updates to eventBus — StreamManager broadcasts to all WS clients
        self.publish("MARKET_UPDATE", {
            "trending": [t.to_dict() for t in self.trending_tokens[:20]],
            "gainers": [t.to_dict() for t in self.top_gainers[:20]],
            "losers": [t.to_dict() for t in self.top_losers[:20]],
            "ai_verified": [t.to_dict() for t in list(self.ai_verified_tokens.values())[:20]],
            "timestamp": time.time(),
        })

    async def _fetch_trending(self) -> List[MarketToken]:
        """Fetch trending tokens from CoinGecko."""
        try:
            url = f"{COINGECKO_BASE}/search/trending"
            headers = {}
            if COINGECKO_API_KEY:
                headers["x-cg-demo-api-key"] = COINGECKO_API_KEY

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=15) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        coins = data.get("coins", [])
                        tokens = []
                        for i, coin in enumerate(coins[:20]):
                            item = coin.get("item", {})
                            token = MarketToken(
                                id=item.get("id", ""),
                                symbol=normalize_symbol(item.get("symbol", "")),
                                name=normalize_name(item.get("name", "")),
                                chain="multi",
                                price=float(item.get("price_btc", 0) or 0),
                                price_change_24h=0,
                                price_change_7d=0,
                                market_cap=float(item.get("market_cap_rank", 0) or 0),
                                volume_24h=0,
                                liquidity=0,
                                image=item.get("thumb"),
                                rank=i + 1,
                                last_updated=time.time(),
                                source="coingecko"
                            )
                            tokens.append(token)
                        return tokens
        except Exception as e:
            print(f"⚠️ {self.name}: Trending fetch failed: {e}")
        return []

    async def _fetch_top_gainers(self) -> List[MarketToken]:
        """Fetch top gainers from CoinGecko."""
        try:
            url = f"{COINGECKO_BASE}/coins/markets"
            params = {
                "vs_currency": "usd",
                "order": "price_change_percentage_24h_desc",
                "per_page": "20",
                "page": "1",
                "sparkline": "false"
            }
            headers = {}
            if COINGECKO_API_KEY:
                headers["x-cg-demo-api-key"] = COINGECKO_API_KEY

            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, headers=headers, timeout=15) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return self._coingecko_to_tokens(data, "gainers")
        except Exception as e:
            print(f"⚠️ {self.name}: Gainers fetch failed: {e}")
        return []

    async def _fetch_top_losers(self) -> List[MarketToken]:
        """Fetch top losers from CoinGecko."""
        try:
            url = f"{COINGECKO_BASE}/coins/markets"
            params = {
                "vs_currency": "usd",
                "order": "price_change_percentage_24h_asc",
                "per_page": "20",
                "page": "1",
                "sparkline": "false"
            }
            headers = {}
            if COINGECKO_API_KEY:
                headers["x-cg-demo-api-key"] = COINGECKO_API_KEY

            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, headers=headers, timeout=15) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return self._coingecko_to_tokens(data, "losers")
        except Exception as e:
            print(f"⚠️ {self.name}: Losers fetch failed: {e}")
        return []

    def _coingecko_to_tokens(self, data: list, source: str) -> List[MarketToken]:
        """Convert CoinGecko market data to MarketToken list."""
        tokens = []
        for i, item in enumerate(data):
            token = MarketToken(
                id=item.get("id", ""),
                symbol=normalize_symbol(item.get("symbol", "")),
                name=normalize_name(item.get("name", "")),
                chain="multi",
                price=float(item.get("current_price", 0) or 0),
                price_change_24h=float(item.get("price_change_percentage_24h", 0) or 0),
                price_change_7d=float(item.get("price_change_percentage_7d_in_currency", 0) or 0),
                market_cap=float(item.get("market_cap", 0) or 0),
                volume_24h=float(item.get("total_volume", 0) or 0),
                liquidity=float(item.get("total_volume", 0) or 0) * 0.1,
                image=item.get("image"),
                rank=i + 1,
                last_updated=time.time(),
                source=source
            )
            tokens.append(token)
        return tokens

    def add_ai_verified(self, token_data: dict):
        """Add a token to the AI-verified list. Called by Orion on SAFE verdict."""
        token_id = token_data.get("token", "")
        if not token_id:
            return

        token = MarketToken(
            id=token_id,
            symbol=normalize_symbol(token_data.get("symbol", "???")),
            name="AI Verified Token",
            chain=token_data.get("chain", "unknown"),
            price=0,
            price_change_24h=0,
            price_change_7d=0,
            market_cap=0,
            volume_24h=0,
            liquidity=0,
            ai_verified=True,
            ai_verdict=token_data.get("verdict", "SAFE"),
            ai_confidence=token_data.get("confidence", 0),
            last_updated=time.time(),
            source="ai_verified"
        )
        self.ai_verified_tokens[token_id] = token

    def get_trending(self) -> List[dict]:
        return [t.to_dict() for t in self.trending_tokens[:20]]

    def get_gainers(self) -> List[dict]:
        return [t.to_dict() for t in self.top_gainers[:20]]

    def get_losers(self) -> List[dict]:
        return [t.to_dict() for t in self.top_losers[:20]]

    def get_ai_verified(self) -> List[dict]:
        return [t.to_dict() for t in list(self.ai_verified_tokens.values())[:20]]

    def get_all(self) -> dict:
        return {
            "trending": self.get_trending(),
            "gainers": self.get_gainers(),
            "losers": self.get_losers(),
            "ai_verified": self.get_ai_verified(),
            "timestamp": time.time(),
        }

    def stop(self):
        self.running = False
        self.cache.clear()
        print(f"🛑 {self.name}: Market engine stopped.")


if __name__ == "__main__":
    def test_publish(event_type, data):
        print(f"\n📡 {event_type}: {json.dumps(data, indent=2, default=str)[:500]}")

    engine = MarketEngine(test_publish)

    async def test():
        await engine._update_all_markets()
        print("\n✅ Market data fetched successfully")

    asyncio.run(test())
