"""Alpha Vantage daily OHLCV adapter. This feed is historical/daily, not real-time."""
import re
import threading
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .models import ProviderDailyBudget


SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.^_-]{0,14}$")
ENDPOINT = "https://www.alphavantage.co/query"
SERIES_KEY = "Time Series (Daily)"
DAILY_CACHE_TTL_SECONDS = 20 * 60 * 60
_CACHE_GUARD = threading.Lock()
_PROCESS_CACHE: dict[str, tuple[datetime, list["DailyBar"]]] = {}


@dataclass(frozen=True)
class DailyBar:
    symbol: str
    market_date: date
    open_usd: Decimal
    high_usd: Decimal
    low_usd: Decimal
    close_usd: Decimal
    volume: Decimal
    source: str
    retrieved_at: datetime


def validate_symbol(symbol: str) -> str:
    value = symbol.strip().upper()
    if not SYMBOL_RE.fullmatch(value):
        raise ValueError("Use a supported stock ticker symbol")
    return value


def _decimal(value: object, *, integer: bool = False) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Provider returned an invalid numeric field") from None
    if not result.is_finite() or result < 0 or (integer and result != result.to_integral_value()):
        raise ValueError("Provider returned an out-of-range numeric field")
    return result


def normalize_daily(symbol: str, body: object) -> list[dict]:
    symbol = validate_symbol(symbol)
    if not isinstance(body, dict):
        raise ValueError("Provider returned an invalid response")
    series = body.get(SERIES_KEY)
    if not isinstance(series, dict):
        # Do not surface provider messages which can contain user supplied input.
        raise ValueError("Daily market data is unavailable for this symbol or provider quota")
    observations = []
    for raw_date, raw in sorted(series.items(), reverse=True)[:100]:
        if not isinstance(raw, dict):
            continue
        try:
            market_date = date.fromisoformat(raw_date)
            opened = _decimal(raw.get("1. open"))
            high = _decimal(raw.get("2. high"))
            low = _decimal(raw.get("3. low"))
            close = _decimal(raw.get("4. close"))
            volume = _decimal(raw.get("5. volume"), integer=True)
        except (ValueError, TypeError):
            continue
        if min(opened, high, low, close) <= 0 or high < max(opened, close, low) or low > min(opened, close):
            continue
        observations.append({"symbol": symbol, "market_date": market_date, "open_usd": opened,
                             "high_usd": high, "low_usd": low, "close_usd": close, "volume": volume,
                             "source": "Alpha Vantage TIME_SERIES_DAILY"})
    if not observations:
        raise ValueError("Provider returned no valid daily observations")
    return observations


async def fetch_daily(client: httpx.AsyncClient, symbol: str, api_key: str) -> list[dict]:
    symbol = validate_symbol(symbol)
    response = await client.get(ENDPOINT, params={
        "function": "TIME_SERIES_DAILY", "symbol": symbol,
        "outputsize": "compact", "apikey": api_key,
    })
    response.raise_for_status()
    return normalize_daily(symbol, response.json())


async def load_or_fetch_daily(db, symbol: str, settings, *, now: datetime | None = None) -> list[DailyBar]:
    """Use a process-local cache; persist only the shared provider-call counter."""
    symbol = validate_symbol(symbol)
    now = now or datetime.now(timezone.utc)

    if settings.alpha_vantage_license_status == "disabled":
        raise PermissionError("Alpha Vantage use is disabled until provider terms are reviewed")
    with _CACHE_GUARD:
        cached = _PROCESS_CACHE.get(symbol)
        if cached and (now - cached[0]).total_seconds() < DAILY_CACHE_TTL_SECONDS:
            return list(cached[1])
    if not settings.alpha_vantage_api_key:
        raise RuntimeError("Alpha Vantage API key is not configured")

    budget = pg_insert(ProviderDailyBudget).values(
        provider="alpha_vantage", budget_date=now.date(), request_count=1, updated_at=now,
    )
    statement = budget.on_conflict_do_update(
        index_elements=["provider", "budget_date"],
        set_={"request_count": ProviderDailyBudget.request_count + 1, "updated_at": now},
        where=ProviderDailyBudget.request_count < settings.alpha_vantage_daily_call_budget,
    ).returning(ProviderDailyBudget.request_count)
    if await db.scalar(statement) is None:
        raise OverflowError("Alpha Vantage daily request budget has been reached")
    # Count every paid attempt, including failed upstream requests.
    await db.commit()

    async with httpx.AsyncClient(timeout=httpx.Timeout(12, connect=4), follow_redirects=False,
                                 trust_env=False) as client:
        observations = await fetch_daily(client, symbol, settings.alpha_vantage_api_key)
    retrieved_at = datetime.now(timezone.utc)
    rows = [DailyBar(**item, retrieved_at=retrieved_at) for item in observations]
    with _CACHE_GUARD:
        _PROCESS_CACHE[symbol] = (retrieved_at, rows)
    return list(rows)
