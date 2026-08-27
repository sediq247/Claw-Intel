import asyncio
import json
import os
import time
from typing import Dict, List, Optional, Any
import aiohttp
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()
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

DEXSCREENER_BASE = "https://api.dexscreener.com"
DEXSCREENER_RATE_LIMIT = 300
DEXSCREENER_SLOW_LIMIT = 60

POPULAR_CHAINS = [
    "solana", "ethereum", "base", "bsc", "arbitrum", "optimism",
    "avalanche", "polygon_pos", "sonic", "sui"
]

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
    Pushes live updates via EventPublisher (DB persistence + optional WS broadcast).

    v4.1: Polls DB events for SIGNALs to build AI-verified list.
    """

    def __init__(
        self,
        publisher: Optional[Any] = None,
        server: Optional[Any] = None,
        db: Optional[Any] = None,
    ):
        """
        publisher: EventPublisher instance (v4.1 decoupled mode).
        server:    Legacy ClawIntelServer instance (backward compat).
        db:        Database instance for polling SIGNAL events.
        """
        self.publisher = publisher
        self.server = server
        self.db = db
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
        self._last_signal_ts = 0.0

    def on_ai_verdict(self, data: dict):
        """Handle AI verdict events from the Decision agent (Orion)."""
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

    async def _poll_signals(self):
        """Poll DB events for SIGNAL events to capture AI verdicts."""
        if not self.db or not hasattr(self.db, "get_recent_events"):
            return
        try:
            events = await self.db.get_recent_events(
                since=self._last_signal_ts, limit=50
            )
            for event in events:
                if event.get("event_type") == "SIGNAL":
                    payload = event.get("payload", {})
                    if payload.get("verdict", "").upper() == "SAFE":
                        self.on_ai_verdict(payload)
                ts = event.get("timestamp", 0)
                if ts > self._last_signal_ts:
                    self._last_signal_ts = ts
        except Exception as e:
            print(f"⚠️ {self.name}: Signal poll error: {e}")

    async def start(self):
        """Start the market engine background loop."""
        self.running = True
        self._last_signal_ts = time.time() - 300  # Look back 5 minutes on start

        connector = aiohttp.TCPConnector(limit=50, limit_per_host=30)
        self._session = aiohttp.ClientSession(
            connector=connector,
            headers={"Accept": "application/json"},
            timeout=aiohttp.ClientTimeout(total=20)
        )
        print(f"💰 {self.name}: Market engine ACTIVE (DexScreener-only).")

        while self.running:
            try:
                # Poll for AI verdicts from DB (decoupled architecture)
                await self._poll_signals()

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

        market_payload = {
            "trending": [t.to_dict() for t in self.trending_tokens[:20]],
            "gainers": [t.to_dict() for t in self.top_gainers[:20]],
            "losers": [t.to_dict() for t in self.top_losers[:20]],
            "ai_verified": [t.to_dict() for t in list(self.ai_verified_tokens.values())[:20]],
            "timestamp": time.time(),
        }

        if self.publisher is not None and hasattr(self.publisher, "market_update"):
            try:
                await self.publisher.market_update(market_payload)
                print(f"💰 {self.name}: MARKET_UPDATE persisted + broadcast")
            except Exception as e:
                print(f"⚠️ {self.name}: Publisher market_update failed: {e}")
        elif self.server is not None and hasattr(self.server, "broadcast"):
            try:
                await self.server.broadcast("MARKET_UPDATE", market_payload)
                print(f"💰 {self.name}: MARKET_UPDATE broadcast (legacy mode)")
            except Exception as e:
                print(f"⚠️ {self.name}: Server broadcast failed: {e}")
        else:
            print(f"⚠️ {self.name}: No publisher or server available — MARKET_UPDATE dropped")

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
