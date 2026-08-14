#!/usr/bin/env python3
"""
💰 MARKET ENGINE — v4.0
The Data Aggregator. Fetches from DexScreener API, calculates metrics,
normalizes multi-chain data, pushes live updates via server.broadcast.

v4.0 CHANGES:
- Constructor accepts `server` instead of event_bus publish/subscribe
- Uses server.broadcast("MARKET_UPDATE", ...) for live updates
- on_ai_verdict is a public method called directly by orchestrator
- All original DexScreener logic preserved
- utils.helpers imports are optional with fallbacks
"""

import asyncio
import json
import os
import time
from typing import Dict, List, Optional, Any
import aiohttp
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────────
# Optional utils.helpers — fallbacks if not available
# ─────────────────────────────────────────────────────────────

try:
    from utils.helpers import (
        normalize_symbol, normalize_name, format_currency, format_percentage,
        format_price, format_large_number, unix_to_human, get_chain_display_name,
        SimpleCache
    )
    HAS_HELPERS = True
except ImportError:
    HAS_HELPERS = False
    print("⚠️ MarketEngine: utils.helpers not found. Using fallback implementations.")

    def normalize_symbol(s: str) -> str:
        return str(s).strip().upper() if s else "???"

    def normalize_name(s: str) -> str:
        return str(s).strip() if s else "Unknown"

    def format_currency(value: float) -> str:
        try:
            if value >= 1_000_000_000:
                return f"${value/1_000_000_000:.2f}B"
            if value >= 1_000_000:
                return f"${value/1_000_000:.2f}M"
            if value >= 1_000:
                return f"${value/1_000:.2f}K"
            return f"${value:,.2f}"
        except (TypeError, ValueError):
            return "$0"

    def format_percentage(value: float) -> str:
        try:
            return f"{value:+.2f}%"
        except (TypeError, ValueError):
            return "0%"

    def format_price(value: float) -> str:
        try:
            if value >= 1:
                return f"${value:,.4f}"
            return f"${value:.8f}"
        except (TypeError, ValueError):
            return "$0"

    def format_large_number(value: float) -> str:
        try:
            if value >= 1_000_000_000:
                return f"{value/1_000_000_000:.2f}B"
            if value >= 1_000_000:
                return f"{value/1_000_000:.2f}M"
            if value >= 1_000:
                return f"{value/1_000:.2f}K"
            return f"{value:,.0f}"
        except (TypeError, ValueError):
            return "0"

    def unix_to_human(ts: float) -> str:
        from datetime import datetime
        try:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            return "Unknown"

    def get_chain_display_name(chain: str) -> str:
        mapping = {
            "solana": "Solana", "ethereum": "Ethereum", "base": "Base",
            "bsc": "BSC", "arbitrum": "Arbitrum", "optimism": "Optimism",
            "avalanche": "Avalanche", "polygon_pos": "Polygon",
        }
        return mapping.get(chain.lower(), chain.upper())

    class SimpleCache:
        def __init__(self, default_ttl: int = 60):
            self._data: Dict[str, tuple] = {}
            self.default_ttl = default_ttl

        def get(self, key: str):
            if key not in self._data:
                return None
            value, expiry = self._data[key]
            if time.time() > expiry:
                del self._data[key]
                return None
            return value

        def set(self, key: str, value, ttl: Optional[int] = None):
            self._data[key] = (value, time.time() + (ttl or self.default_ttl))

        def clear(self):
            self._data.clear()


# ─────────────────────────────────────────────────────────────
# API Configuration — DexScreener only
# ─────────────────────────────────────────────────────────────

DEXSCREENER_BASE = "https://api.dexscreener.com"

# Rate limiting
DEXSCREENER_RATE_LIMIT = 300
DEXSCREENER_SLOW_LIMIT = 60

# Popular chains to scan for trending / gainers / losers
POPULAR_CHAINS = [
    "solana", "ethereum", "base", "bsc", "arbitrum", "optimism",
    "avalanche", "polygon_pos", "sonic", "sui"
]

# Search queries to discover active tokens across chains
TRENDING_SEARCH_QUERIES = [
    "SOL", "ETH", "BTC", "USDC", "USDT", "BONK", "PEPE", "SHIB",
    "WIF", "FLOKI", "DOGE", "JUP", "RAY", "BOME", "WETH", "WBTC"
]


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
    Fetches, normalizes, and caches market data from DexScreener API.
    Pushes live updates via server.broadcast.

    v4.0: Receives AI verdicts directly from orchestrator via on_ai_verdict().
    """

    def __init__(self, server: Optional[Any] = None):
        self.server = server
        self.name = "MarketEngine"
        self.cache = SimpleCache(default_ttl=60)
        self.ai_verified_tokens: Dict[str, MarketToken] = {}
        self.trending_tokens: List[MarketToken] = []
        self.top_gainers: List[MarketToken] = []
        self.top_losers: List[MarketToken] = []
        self.running = False
        self.update_interval = 60
        self.dexscreener_calls = []
        self._session: Optional[aiohttp.ClientSession] = None
        self._semaphore = asyncio.Semaphore(20)

    def on_ai_verdict(self, data: dict):
        """Handle AI verdict events from the Decision agent (Orion).
        Called directly by orchestrator — no event bus needed.

        Expected data format:
        {
            "token": "solana:So11111111111111111111111111111111111111112",
            "symbol": "SOL",
            "chain": "solana",
            "verdict": "SAFE",
            "confidence": 0.94,
            "timestamp": 1234567890
        }
        """
        try:
            verdict = data.get("verdict", "").upper()
            if verdict == "SAFE":
                self.add_ai_verified(data)
                print(f"✅ {self.name}: AI verified token added — {data.get('symbol', '???')} ({verdict})")
            elif verdict in ("UNSAFE", "WARNING", "HIGH_RISK"):
                token_id = data.get("token", "")
                if token_id in self.ai_verified_tokens:
                    del self.ai_verified_tokens[token_id]
                    print(f"🚫 {self.name}: AI verified token removed — {data.get('symbol', '???')} ({verdict})")
            else:
                print(f"⚠️ {self.name}: Unknown verdict '{verdict}', ignoring.")
        except Exception as e:
            print(f"⚠️ {self.name}: Error handling AI verdict: {e}")

    async def start(self):
        """Start the market engine background loop."""
        self.running = True

        connector = aiohttp.TCPConnector(limit=50, limit_per_host=30)
        self._session = aiohttp.ClientSession(
            connector=connector,
            headers={"Accept": "application/json"},
            timeout=aiohttp.ClientTimeout(total=20)
        )
        print(f"💰 {self.name}: Market engine ACTIVE (DexScreener-only).")

        while self.running:
            try:
                await self._update_all_markets()
                await asyncio.sleep(self.update_interval)
            except Exception as e:
                print(f"⚠️ {self.name}: Update error: {e}")
                await asyncio.sleep(10)

    async def _update_all_markets(self):
        """Update all market categories from DexScreener."""
        print(f"💰 {self.name}: Fetching market data from DexScreener...")

        results = await asyncio.gather(
            self._fetch_trending(),
            self._fetch_top_gainers(),
            self._fetch_top_losers(),
            return_exceptions=True
        )

        had_success = False
        if not isinstance(results[0], Exception):
            self.trending_tokens = results[0]
            had_success = True
        if not isinstance(results[1], Exception):
            self.top_gainers = results[1]
            had_success = True
        if not isinstance(results[2], Exception):
            self.top_losers = results[2]
            had_success = True

        if not had_success:
            print(f"⚠️ {self.name}: All fetch methods failed, skipping MARKET_UPDATE broadcast.")
            return

        # v4.0: Broadcast via server instead of event bus
        if self.server:
            await self.server.broadcast("MARKET_UPDATE", {
                "trending": [t.to_dict() for t in self.trending_tokens[:20]],
                "gainers": [t.to_dict() for t in self.top_gainers[:20]],
                "losers": [t.to_dict() for t in self.top_losers[:20]],
                "ai_verified": [t.to_dict() for t in list(self.ai_verified_tokens.values())[:20]],
                "timestamp": time.time(),
            })
        else:
            print(f"⚠️ {self.name}: No server available — MARKET_UPDATE not broadcast")

    # ───────────────────────────────────────────────
    # DexScreener: Trending
    # ───────────────────────────────────────────────
    async def _fetch_trending(self) -> List[MarketToken]:
        all_tokens: Dict[str, MarketToken] = {}

        try:
            boosted = await self._ds_get("/token-boosts/top/v1")
            if boosted:
                items = boosted if isinstance(boosted, list) else [boosted]
                for item in items[:20]:
                    token = await self._enrich_boosted_token(item)
                    if token:
                        all_tokens[token.id] = token
        except Exception as e:
            print(f"⚠️ {self.name}: Boosted fetch failed: {e}")

        search_tasks = [
            self._ds_search(q) for q in TRENDING_SEARCH_QUERIES[:6]
        ]
        search_results = await asyncio.gather(*search_tasks, return_exceptions=True)

        for result in search_results:
            if isinstance(result, Exception):
                continue
            for pair in result[:15]:
                token = self._ds_pair_to_token(pair, "trending")
                if token:
                    existing = all_tokens.get(token.id)
                    if not existing or token.liquidity > existing.liquidity:
                        all_tokens[token.id] = token

        tokens = list(all_tokens.values())
        tokens.sort(key=lambda t: (t.liquidity * t.volume_24h), reverse=True)
        for i, t in enumerate(tokens):
            t.rank = i + 1
        return tokens[:40]

    # ───────────────────────────────────────────────
    # DexScreener: Top Gainers
    # ───────────────────────────────────────────────
    async def _fetch_top_gainers(self) -> List[MarketToken]:
        all_pairs = []

        search_tasks = [
            self._ds_search(q) for q in TRENDING_SEARCH_QUERIES
        ]
        results = await asyncio.gather(*search_tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                continue
            all_pairs.extend(result)

        tokens = []
        seen = set()
        for pair in all_pairs:
            token = self._ds_pair_to_token(pair, "gainers")
            if token and token.id not in seen and token.price_change_24h > 0:
                seen.add(token.id)
                tokens.append(token)

        tokens.sort(key=lambda t: t.price_change_24h, reverse=True)
        for i, t in enumerate(tokens[:20]):
            t.rank = i + 1
        return tokens[:20]

    # ───────────────────────────────────────────────
    # DexScreener: Top Losers
    # ───────────────────────────────────────────────
    async def _fetch_top_losers(self) -> List[MarketToken]:
        all_pairs = []

        search_tasks = [
            self._ds_search(q) for q in TRENDING_SEARCH_QUERIES
        ]
        results = await asyncio.gather(*search_tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                continue
            all_pairs.extend(result)

        tokens = []
        seen = set()
        for pair in all_pairs:
            token = self._ds_pair_to_token(pair, "losers")
            if token and token.id not in seen and token.price_change_24h < 0:
                seen.add(token.id)
                tokens.append(token)

        tokens.sort(key=lambda t: t.price_change_24h)
        for i, t in enumerate(tokens[:20]):
            t.rank = i + 1
        return tokens[:20]

    # ───────────────────────────────────────────────
    # DexScreener HTTP helpers
    # ───────────────────────────────────────────────
    async def _ds_get(self, endpoint: str, params: dict = None):
        url = f"{DEXSCREENER_BASE}{endpoint}"
        async with self._semaphore:
            async with self._session.get(url, params=params) as resp:
                if resp.status == 200:
                    return await resp.json()
                elif resp.status == 429:
                    print(f"⚠️ {self.name}: Rate limited on {endpoint}, backing off...")
                    await asyncio.sleep(2)
                else:
                    print(f"⚠️ {self.name}: DS API {endpoint} returned {resp.status}")
                return None

    async def _ds_search(self, query: str) -> list:
        data = await self._ds_get("/latest/dex/search", params={"q": query})
        if data and isinstance(data, dict):
            return data.get("pairs", []) or []
        return []

    # ───────────────────────────────────────────────
    # Data normalizers
    # ───────────────────────────────────────────────
    def _ds_pair_to_token(self, pair: dict, source: str) -> Optional[MarketToken]:
        base = pair.get("baseToken", {})
        if not base:
            return None

        token_addr = base.get("address", "")
        symbol = normalize_symbol(base.get("symbol", "???"))
        name = normalize_name(base.get("name", symbol))
        chain = pair.get("chainId", "unknown")

        pair_addr = pair.get("pairAddress", "")
        if token_addr:
            token_id = f"{chain}:{token_addr}"
        elif pair_addr:
            token_id = f"{chain}:pair:{pair_addr}"
        else:
            token_id = f"{chain}:{symbol}:{int(time.time() * 1000)}"

        price_usd = self._safe_float(pair.get("priceUsd"), 0)
        price_change = pair.get("priceChange", {})
        change_24h = self._safe_float(price_change.get("h24"), 0)
        change_7d = 0.0

        volume = pair.get("volume", {})
        volume_24h = self._safe_float(volume.get("h24"), 0)

        liquidity_data = pair.get("liquidity", {})
        liquidity_usd = self._safe_float(liquidity_data.get("usd"), 0)

        market_cap = self._safe_float(pair.get("marketCap"), 0)
        if market_cap == 0:
            market_cap = self._safe_float(pair.get("fdv"), 0)

        info = pair.get("info", {})
        image = info.get("imageUrl")

        return MarketToken(
            id=token_id,
            symbol=symbol,
            name=name,
            chain=chain,
            price=price_usd,
            price_change_24h=change_24h,
            price_change_7d=change_7d,
            market_cap=market_cap,
            volume_24h=volume_24h,
            liquidity=liquidity_usd,
            image=image,
            rank=0,
            last_updated=time.time(),
            source=f"dexscreener:{source}"
        )

    async def _enrich_boosted_token(self, item: dict) -> Optional[MarketToken]:
        chain = item.get("chainId", "unknown")
        token_addr = item.get("tokenAddress", "")

        if not token_addr or not chain:
            return None

        token_id = f"{chain}:{token_addr}"
        symbol = "???"
        name = "???"
        price = 0.0
        change_24h = 0.0
        market_cap = 0.0
        volume_24h = 0.0
        liquidity_usd = 0.0
        image = item.get("icon") or item.get("header")

        try:
            pairs_data = await self._ds_get(f"/token-pairs/v1/{chain}/{token_addr}")
            if pairs_data and isinstance(pairs_data, list) and len(pairs_data) > 0:
                best_pair = max(pairs_data, key=lambda p: self._safe_float(
                    p.get("liquidity", {}).get("usd"), 0
                ))
                base = best_pair.get("baseToken", {})
                symbol = normalize_symbol(base.get("symbol", "???"))
                name = normalize_name(base.get("name", symbol))
                price = self._safe_float(best_pair.get("priceUsd"), 0)
                change_24h = self._safe_float(
                    best_pair.get("priceChange", {}).get("h24"), 0
                )
                market_cap = self._safe_float(best_pair.get("marketCap"), 0)
                if market_cap == 0:
                    market_cap = self._safe_float(best_pair.get("fdv"), 0)
                volume_24h = self._safe_float(
                    best_pair.get("volume", {}).get("h24"), 0
                )
                liquidity_usd = self._safe_float(
                    best_pair.get("liquidity", {}).get("usd"), 0
                )
                info = best_pair.get("info", {})
                if info.get("imageUrl"):
                    image = info.get("imageUrl")
        except Exception as e:
            print(f"⚠️ {self.name}: Failed to enrich boosted token {token_id}: {e}")

        return MarketToken(
            id=token_id,
            symbol=symbol,
            name=name,
            chain=chain,
            price=price,
            price_change_24h=change_24h,
            price_change_7d=0.0,
            market_cap=market_cap,
            volume_24h=volume_24h,
            liquidity=liquidity_usd,
            image=image,
            rank=0,
            last_updated=time.time(),
            source="dexscreener:boosted"
        )

    @staticmethod
    def _safe_float(value, default: float = 0.0) -> float:
        try:
            if value is None:
                return default
            return float(value)
        except (ValueError, TypeError):
            return default

    # ───────────────────────────────────────────────
    # AI Verified tokens
    # ───────────────────────────────────────────────
    def add_ai_verified(self, token_data: dict):
        """Add a token to the AI-verified list. Called internally on SAFE verdict."""
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

    # ───────────────────────────────────────────────
    # Public getters (unchanged interface)
    # ───────────────────────────────────────────────
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

    async def stop(self):
        """Gracefully stop the market engine."""
        self.running = False
        self.cache.clear()
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
        print(f"🛑 {self.name}: Market engine stopped.")
