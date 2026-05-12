#!/usr/bin/env python3
"""
💰 utils/marketEngine.py
The Data Aggregator.
Bridge between raw blockchain data and the UI.
Fetches from CoinGecko + DexScreener, calculates metrics,
normalizes multi-chain data, pushes live updates to markets.html.
"""

import asyncio
import json
import os
import time
from typing import Dict, List, Optional, Callable
import aiohttp
from dataclasses import dataclass, asdict, field
from dotenv import load_dotenv

from helpers import (
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
COINGECKO_RATE_LIMIT = 30 if COINGECKO_API_KEY else 10  # calls per minute
DEXSCREENER_RATE_LIMIT = 300  # calls per minute for pairs


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
        self.cache = SimpleCache(default_ttl=60)  # 60 second cache
        self.ai_verified_tokens: Dict[str, MarketToken] = {}
        self.trending_tokens: List[MarketToken] = []
        self.top_gainers: List[MarketToken] = []
        self.top_losers: List[MarketToken] = []
        self.running = False
        self.update_interval = 60  # seconds
        
        # Rate limiting trackers
        self.coingecko_calls = []
        self.dexscreener_calls = []
    
    async def start(self):
        """Start the market engine background loop."""
        self.running = True
        print(f"💰 {self.name}: Market engine ACTIVE.")
        
        # Subscribe to AI verification events
        # Note: In production, this would subscribe to eventBus
        # For now, we track manually
        
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
        
        # Fetch in parallel
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
        
        # Publish updates
        self.publish("MARKET_UPDATE", {
            "trending": [t.to_dict() for t in self.trending_tokens[:20]],
            "gainers": [t.to_dict() for t in self.top_gainers[:20]],
            "losers": [t.to_dict() for t in self.top_losers[:20]],
            "ai_verified": [t.to_dict() for t in self.ai_verified_tokens.values()],
            "timestamp": time.time(),
        })
        
        print(f"💰 {self.name}: Updated — {len(self.trending_tokens)} trending, "
              f"{len(self.top_gainers)} gainers, {len(self.top_losers)} losers, "
              f"{len(self.ai_verified_tokens)} AI verified")
    
    # ── CoinGecko API Calls ──
    
    async def _coingecko_request(self, endpoint: str, params: dict = None) -> dict:
        """Make rate-limited CoinGecko API request."""
        await self._enforce_coingecko_rate_limit()
        
        url = f"{COINGECKO_BASE}{endpoint}"
        headers = {}
        if COINGECKO_API_KEY:
            headers["x-cg-api-key"] = COINGECKO_API_KEY
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, timeout=15) as resp:
                if resp.status == 200:
                    return await resp.json()
                elif resp.status == 429:
                    print(f"⚠️ {self.name}: CoinGecko rate limited. Waiting...")
                    await asyncio.sleep(60)
                    return {}
                else:
                    print(f"⚠️ {self.name}: CoinGecko error {resp.status}")
                    return {}
    
    async def _enforce_coingecko_rate_limit(self):
        """Enforce CoinGecko rate limit."""
        now = time.time()
        window = 60  # 1 minute window
        self.coingecko_calls = [c for c in self.coingecko_calls if now - c < window]
        
        if len(self.coingecko_calls) >= COINGECKO_RATE_LIMIT:
            sleep_time = window - (now - self.coingecko_calls[0])
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
        
        self.coingecko_calls.append(time.time())
    
    async def _fetch_trending(self) -> List[MarketToken]:
        """Fetch trending tokens from CoinGecko."""
        cache_key = "coingecko_trending"
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        
        data = await self._coingecko_request("/search/trending")
        coins = data.get("coins", [])
        
        tokens = []
        for i, coin in enumerate(coins[:50]):
            item = coin.get("item", {})
            token = MarketToken(
                id=item.get("id", ""),
                symbol=normalize_symbol(item.get("symbol")),
                name=normalize_name(item.get("name")),
                chain="multi",
                price=float(item.get("data", {}).get("price", 0) or 0),
                price_change_24h=float(item.get("data", {}).get("price_change_percentage_24h", {}).get("usd", 0) or 0),
                price_change_7d=0.0,
                market_cap=float(item.get("data", {}).get("market_cap", 0) or 0),
                volume_24h=float(item.get("data", {}).get("total_volume", 0) or 0),
                liquidity=0.0,
                image=item.get("thumb"),
                rank=i + 1,
                last_updated=time.time(),
                source="coingecko",
            )
            tokens.append(token)
        
        self.cache.set(cache_key, tokens, ttl=120)
        return tokens
    
    async def _fetch_top_gainers(self) -> List[MarketToken]:
        """Fetch top gainers from CoinGecko."""
        cache_key = "coingecko_gainers"
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        
        params = {
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": 250,
            "page": 1,
            "sparkline": "false",
            "price_change_percentage": "24h",
        }
        
        data = await self._coingecko_request("/coins/markets", params)
        
        tokens = []
        for item in data:
            token = MarketToken(
                id=item.get("id", ""),
                symbol=normalize_symbol(item.get("symbol")),
                name=normalize_name(item.get("name")),
                chain="multi",
                price=float(item.get("current_price", 0) or 0),
                price_change_24h=float(item.get("price_change_percentage_24h", 0) or 0),
                price_change_7d=float(item.get("price_change_percentage_7d_in_currency", 0) or 0),
                market_cap=float(item.get("market_cap", 0) or 0),
                volume_24h=float(item.get("total_volume", 0) or 0),
                liquidity=0.0,
                image=item.get("image"),
                last_updated=time.time(),
                source="coingecko",
            )
            tokens.append(token)
        
        # Sort by 24h gain
        gainers = sorted([t for t in tokens if t.price_change_24h > 0], 
                        key=lambda x: x.price_change_24h, reverse=True)[:50]
        
        self.cache.set(cache_key, gainers, ttl=120)
        return gainers
    
    async def _fetch_top_losers(self) -> List[MarketToken]:
        """Fetch top losers from CoinGecko."""
        cache_key = "coingecko_losers"
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        
        # Reuse the same data as gainers but sort differently
        params = {
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": 250,
            "page": 1,
            "sparkline": "false",
            "price_change_percentage": "24h",
        }
        
        data = await self._coingecko_request("/coins/markets", params)
        
        tokens = []
        for item in data:
            token = MarketToken(
                id=item.get("id", ""),
                symbol=normalize_symbol(item.get("symbol")),
                name=normalize_name(item.get("name")),
                chain="multi",
                price=float(item.get("current_price", 0) or 0),
                price_change_24h=float(item.get("price_change_percentage_24h", 0) or 0),
                price_change_7d=float(item.get("price_change_percentage_7d_in_currency", 0) or 0),
                market_cap=float(item.get("market_cap", 0) or 0),
                volume_24h=float(item.get("total_volume", 0) or 0),
                liquidity=0.0,
                image=item.get("image"),
                last_updated=time.time(),
                source="coingecko",
            )
            tokens.append(token)
        
        # Sort by 24h loss (most negative first)
        losers = sorted([t for t in tokens if t.price_change_24h < 0], 
                       key=lambda x: x.price_change_24h)[:50]
        
        self.cache.set(cache_key, losers, ttl=120)
        return losers
    
    # ── DexScreener API Calls ──
    
    async def _dexscreener_request(self, endpoint: str) -> dict:
        """Make rate-limited DexScreener API request."""
        await self._enforce_dexscreener_rate_limit()
        
        url = f"{DEXSCREENER_BASE}{endpoint}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    print(f"⚠️ {self.name}: DexScreener error {resp.status}")
                    return {}
    
    async def _enforce_dexscreener_rate_limit(self):
        """Enforce DexScreener rate limit."""
        now = time.time()
        window = 60
        self.dexscreener_calls = [c for c in self.dexscreener_calls if now - c < window]
        
        if len(self.dexscreener_calls) >= DEXSCREENER_RATE_LIMIT:
            sleep_time = window - (now - self.dexscreener_calls[0])
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
        
        self.dexscreener_calls.append(time.time())
    
    async def fetch_token_by_address(self, token_address: str, chain: str) -> Optional[MarketToken]:
        """
        Fetch detailed token data by address from DexScreener.
        Used by Nova when investigating a specific token.
        """
        cache_key = f"dexscreener_token:{chain}:{token_address}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        
        # Try DexScreener token endpoint
        data = await self._dexscreener_request(f"/latest/dex/tokens/{token_address}")
        pairs = data.get("pairs", [])
        
        if not pairs:
            return None
        
        # Get the pair with highest liquidity
        best_pair = max(pairs, key=lambda x: x.get("liquidity", {}).get("usd", 0) or 0)
        normalized = normalize_dexscreener_token(best_pair)
        
        token = MarketToken(
            id=generate_token_id(token_address, chain),
            symbol=normalized.get("symbol", "???"),
            name=normalized.get("name", "Unknown"),
            chain=get_chain_display_name(normalized.get("chain", chain)),
            price=normalized.get("price", 0),
            price_change_24h=normalized.get("price_change_24h", 0),
            price_change_7d=0.0,
            market_cap=normalized.get("market_cap", 0),
            volume_24h=normalized.get("volume_24h", 0),
            liquidity=normalized.get("liquidity", 0),
            last_updated=time.time(),
            source="dexscreener",
        )
        
        self.cache.set(cache_key, token, ttl=60)
        return token
    
    async def fetch_token_profiles(self) -> List[MarketToken]:
        """Fetch latest token profiles from DexScreener."""
        cache_key = "dexscreener_profiles"
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        
        data = await self._dexscreener_request("/token-profiles/latest/v1")
        
        tokens = []
        for profile in data[:50]:
            normalized = normalize_dexscreener_token(profile)
            token = MarketToken(
                id=generate_token_id(normalized.get("address", ""), normalized.get("chain", "")),
                symbol=normalized.get("symbol", "???"),
                name=normalized.get("name", "Unknown"),
                chain=get_chain_display_name(normalized.get("chain", "unknown")),
                price=normalized.get("price", 0),
                price_change_24h=normalized.get("price_change_24h", 0),
                price_change_7d=0.0,
                market_cap=normalized.get("market_cap", 0),
                volume_24h=normalized.get("volume_24h", 0),
                liquidity=normalized.get("liquidity", 0),
                last_updated=time.time(),
                source="dexscreener",
            )
            tokens.append(token)
        
        self.cache.set(cache_key, tokens, ttl=60)
        return tokens
    
    # ── AI Verified Tokens ──
    
    def add_ai_verified_token(self, token_data: dict):
        """
        Add a token to the AI Verified list.
        Called when Orion approves a token as SAFE.
        """
        token_address = token_data.get("token", "")
        chain = token_data.get("chain", "unknown")
        
        token = MarketToken(
            id=generate_token_id(token_address, chain),
            symbol=token_data.get("symbol", "???"),
            name=token_data.get("name", "Unknown"),
            chain=get_chain_display_name(chain),
            price=0.0,
            price_change_24h=0.0,
            price_change_7d=0.0,
            market_cap=0.0,
            volume_24h=0.0,
            liquidity=0.0,
            ai_verified=True,
            ai_verdict=token_data.get("verdict", "SAFE"),
            ai_confidence=token_data.get("confidence", 0),
            last_updated=time.time(),
            source="ai_verified",
        )
        
        self.ai_verified_tokens[token_address] = token
        
        # Publish update
        self.publish("MARKET_UPDATE", {
            "ai_verified": [t.to_dict() for t in self.ai_verified_tokens.values()],
            "timestamp": time.time(),
        })
        
        print(f"✅ {self.name}: Added AI Verified token — {token.symbol}")
    
    def remove_ai_verified_token(self, token_address: str):
        """Remove a token from AI Verified list."""
        if token_address in self.ai_verified_tokens:
            del self.ai_verified_tokens[token_address]
            self.publish("MARKET_UPDATE", {
                "ai_verified": [t.to_dict() for t in self.ai_verified_tokens.values()],
                "timestamp": time.time(),
            })
    
    # ── Data Access ──
    
    def get_trending(self) -> List[dict]:
        """Get trending tokens as dicts."""
        return [t.to_dict() for t in self.trending_tokens[:20]]
    
    def get_gainers(self) -> List[dict]:
        """Get top gainers as dicts."""
        return [t.to_dict() for t in self.top_gainers[:20]]
    
    def get_losers(self) -> List[dict]:
        """Get top losers as dicts."""
        return [t.to_dict() for t in self.top_losers[:20]]
    
    def get_ai_verified(self) -> List[dict]:
        """Get AI verified tokens as dicts."""
        return [t.to_dict() for t in self.ai_verified_tokens.values()]
    
    def get_all(self) -> dict:
        """Get all market data."""
        return {
            "trending": self.get_trending(),
            "gainers": self.get_gainers(),
            "losers": self.get_losers(),
            "ai_verified": self.get_ai_verified(),
            "timestamp": time.time(),
        }
    
    def stop(self):
        """Stop the market engine."""
        self.running = False
        self.cache.clear()
        print(f"🛑 {self.name}: Market engine stopped.")


# Import here to avoid circular dependency
from helpers import generate_token_id


if __name__ == "__main__":
    def test_publish(event_type, data):
        print(f"\n📡 {event_type}: {json.dumps(data, indent=2, default=str)[:500]}")
    
    engine = MarketEngine(test_publish)
    
    async def test():
        await engine._update_all_markets()
        print("\n✅ Market data fetched successfully")
    
    asyncio.run(test())