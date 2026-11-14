"""DexScreener market observation adapter and bounded autonomous investigation loop."""
import asyncio
import logging
import math
import random
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
import httpx
from .config import get_settings
from .database import SessionFactory
from .models import Evidence
from .models import Investigation
from sqlalchemy import select
from .orchestration import run_investigation

BASE = "https://api.dexscreener.com"
USER_AGENT = "ClawIntel/1.0 (+market evidence client)"
COINGECKO_PLATFORMS = {
    "ethereum": "ethereum",
    "bsc": "binance-smart-chain",
    "base": "base",
    "solana": "solana",
}
RPC_SETTINGS = {
    "ethereum": "eth_rpc_url",
    "bsc": "bsc_rpc_url",
    "base": "base_rpc_url",
    "solana": "solana_rpc_url",
}
logger = logging.getLogger(__name__)


def numeric(value):
    if value is None:
        return None
    try:
        number = Decimal(str(value))
        return str(number) if number.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _observation_from_pair(chain: str, address: str, pair: dict) -> dict:
    base_token = pair.get("baseToken") or {}
    quote_token = pair.get("quoteToken") or {}
    info = pair.get("info") or {}
    domains = []
    for website in (info.get("websites") or [])[:8]:
        if not isinstance(website, dict):
            continue
        try:
            host = urlsplit(str(website.get("url") or "")).hostname
        except ValueError:
            continue
        if host and re.fullmatch(r"[A-Za-z0-9.-]{1,253}", host):
            domains.append(host.lower())
    socials = []
    for social in (info.get("socials") or [])[:8]:
        if not isinstance(social, dict):
            continue
        platform = re.sub(r"[^A-Za-z0-9_-]", "", str(social.get("platform") or ""))[:32]
        handle = re.sub(r"[^A-Za-z0-9_@.-]", "", str(social.get("handle") or ""))[:80]
        if platform or handle:
            socials.append({"platform": platform, "handle": handle})
    created_ms = pair.get("pairCreatedAt")
    try:
        age_days = max(0, (datetime.now(timezone.utc).timestamp() - float(created_ms) / 1000) / 86400) if created_ms else None
    except (ValueError, TypeError, OverflowError):
        age_days = None
    return {
        "chain": chain,
        "token_address": address,
        "symbol": str(base_token.get("symbol") or "Unknown")[:48],
        "name": str(base_token.get("name") or "Unknown")[:96],
        "pair_address": pair.get("pairAddress"),
        "dex_id": pair.get("dexId"),
        "quote_symbol": quote_token.get("symbol"),
        "price_usd": numeric(pair.get("priceUsd")),
        "liquidity_usd": numeric((pair.get("liquidity") or {}).get("usd")),
        "fdv_usd": numeric(pair.get("fdv")),
        "market_cap_usd": numeric(pair.get("marketCap")),
        "volume_24h_usd": numeric((pair.get("volume") or {}).get("h24")),
        "price_change_24h_pct": numeric((pair.get("priceChange") or {}).get("h24")),
        "price_change_6h_pct": numeric((pair.get("priceChange") or {}).get("h6")),
        "price_change_1h_pct": numeric((pair.get("priceChange") or {}).get("h1")),
        "price_change_5m_pct": numeric((pair.get("priceChange") or {}).get("m5")),
        "buys_24h": (pair.get("txns") or {}).get("h24", {}).get("buys"),
        "sells_24h": (pair.get("txns") or {}).get("h24", {}).get("sells"),
        "buys_6h": (pair.get("txns") or {}).get("h6", {}).get("buys"),
        "sells_6h": (pair.get("txns") or {}).get("h6", {}).get("sells"),
        "buys_1h": (pair.get("txns") or {}).get("h1", {}).get("buys"),
        "sells_1h": (pair.get("txns") or {}).get("h1", {}).get("sells"),
        "buys_5m": (pair.get("txns") or {}).get("m5", {}).get("buys"),
        "sells_5m": (pair.get("txns") or {}).get("m5", {}).get("sells"),
        "pair_url": pair.get("url"),
        "provider_pair_created_at_ms": pair.get("pairCreatedAt"),
        "pair_age_days": round(age_days, 2) if age_days is not None else None,
        "website_domains": domains,
        "social_profiles": socials,
        "provider_retrieved_at": datetime.now(timezone.utc).isoformat(),
        "source": "DexScreener API",
        "data_kind": "live",
        "limitations": "Retrieved from the provider during this scan; upstream indexing delay is unspecified. Boost/profile placement may be promotional and is not proof of organic demand. Pair metrics do not verify source code, holder distribution, deployer history, or executable liquidity.",
    }
async def fetch_latest_observation(client: httpx.AsyncClient):
    return choose_discovery_candidate(await fetch_discovery_candidates(client))


DISCOVERY_FEEDS = (
    ("latest_profile", "/token-profiles/latest/v1"),
    ("recent_profile", "/token-profiles/recent-updates/v1"),
    ("latest_boost", "/token-boosts/latest/v1"),
    ("top_boost", "/token-boosts/top/v1"),
)


def _candidate_weight(observation: dict) -> float:
    """Log-scaled attention signals prevent one huge volume number dominating selection."""
    fields = observation
    def metric(value):
        try:
            number = float(value or 0)
            return min(1e12, max(0.0, number)) if math.isfinite(number) else 0.0
        except (ValueError, TypeError, OverflowError):
            return 0.0
    volume = metric(fields.get("volume_24h_usd"))
    buys = sum(metric(fields.get(f"buys_{period}")) for period in ("24h", "6h", "1h", "5m"))
    sells = sum(metric(fields.get(f"sells_{period}")) for period in ("24h", "6h", "1h", "5m"))
    liquidity = metric(fields.get("liquidity_usd"))
    momentum = metric(fields.get("price_change_1h_pct"))
    feeds = set(fields.get("discovery_feeds") or [])
    return max(0.1, 1.0 + math.log1p(volume) + math.log1p(buys) + min(4.0, momentum / 25.0) + min(2, len(feeds) - 1) + min(3.0, math.log1p(liquidity) / 5.0) - math.log1p(sells) * 0.2)


def choose_discovery_candidate(candidates: list[dict]) -> dict | None:
    if not candidates:
        return None
    chosen = random.choices(candidates, weights=[_candidate_weight(row) for row in candidates], k=1)[0]
    chosen["attention_score"] = round(_candidate_weight(chosen), 3)
    chosen["discovery_reason"] = (
        f"Observed across {', '.join(chosen.get('discovery_feeds') or ['market feed'])}; "
        f"24h volume ${chosen.get('volume_24h_usd') or 'unavailable'}, "
        f"liquidity ${chosen.get('liquidity_usd') or 'unavailable'}, "
        f"1h price change {chosen.get('price_change_1h_pct') if chosen.get('price_change_1h_pct') is not None else 'unavailable'}%."
    )
    return chosen


async def fetch_discovery_candidates(client: httpx.AsyncClient, per_feed: int = 6) -> list[dict]:
    """Collect a bounded, de-duplicated candidate set from documented attention feeds."""
    async def load_feed(feed: str, path: str):
        try:
            response = await client.get(f"{BASE}{path}", headers={"User-Agent": USER_AGENT})
            response.raise_for_status()
            body = response.json()
            return feed, body if isinstance(body, list) else [body] if isinstance(body, dict) else []
        except Exception as exc:
            logger.info("DEX Screener feed %s unavailable: %s", feed, type(exc).__name__)
            return feed, []

    feeds = await asyncio.gather(*(load_feed(feed, path) for feed, path in DISCOVERY_FEEDS))
    discovered: dict[tuple[str, str], set[str]] = {}
    for feed, rows in feeds:
        added = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            chain, address = row.get("chainId"), row.get("tokenAddress")
            if not isinstance(chain, str) or not isinstance(address, str) or not address.strip():
                continue
            discovered.setdefault((chain, address), set()).add(feed)
            added += 1
            if added >= per_feed:
                break

    candidates = []
    for (chain, address), sources in list(discovered.items())[:24]:
        try:
            response = await client.get(f"{BASE}/tokens/v1/{chain}/{address}", headers={"User-Agent": USER_AGENT})
            response.raise_for_status()
            pairs = response.json()
        except Exception as exc:
            logger.info("DEX pair lookup unavailable for candidate: %s", type(exc).__name__)
            continue
        valid = [pair for pair in pairs if isinstance(pair, dict)
                 and isinstance(pair.get("liquidity"), dict)
                 and str((pair.get("baseToken") or {}).get("address", "")).lower() == address.lower()] if isinstance(pairs, list) else []
        if not valid:
            continue
        valid.sort(key=lambda pair: float(numeric((pair.get("liquidity") or {}).get("usd")) or 0), reverse=True)
        observation = _observation_from_pair(chain, address, valid[0])
        observation["discovery_feeds"] = sorted(sources)
        candidates.append(observation)
    return candidates


async def fetch_token_observation(client: httpx.AsyncClient, address: str, settings) -> dict | None:
    """Find the exact base-token pair for a user-submitted address and enrich it."""
    response = await client.get(f"{BASE}/latest/dex/search", params={"q": address}, headers={"User-Agent": USER_AGENT})
    if response.status_code == 429:
        return None
    response.raise_for_status()
    pairs = response.json().get("pairs") or []
    def address_matches(pair: dict) -> bool:
        candidate = str((pair.get("baseToken") or {}).get("address") or "")
        chain = str(pair.get("chainId") or "").lower()
        # EVM addresses are case-insensitive; Solana/Base58 addresses are case-sensitive.
        return candidate == address if chain == "solana" else candidate.lower() == address.lower()

    exact = [pair for pair in pairs if isinstance(pair, dict) and address_matches(pair)]
    exact = [pair for pair in exact if isinstance(pair.get("liquidity"), dict)]
    if not exact:
        return None
    exact.sort(key=lambda item: Decimal(numeric((item.get("liquidity") or {}).get("usd")) or "0"), reverse=True)
    observation = _observation_from_pair(str(exact[0].get("chainId") or "unknown"), address, exact[0])
    return await enrich_observation(client, observation, settings)


async def enrich_observation(client: httpx.AsyncClient, observation: dict, settings) -> dict:
    enrichments = await asyncio.gather(
        fetch_coingecko_observation(client, observation["chain"], observation["token_address"], settings),
        fetch_chain_observation(client, observation["chain"], observation["token_address"], settings),
        return_exceptions=True,
    )
    for key, result in zip(("coingecko_status", "chain_rpc_status"), enrichments):
        observation.update({key: f"unavailable:{type(result).__name__}"} if isinstance(result, Exception) else result)
    sources = ["DexScreener API"]
    if observation.get("coingecko_status") == "listed":
        sources.append("CoinGecko API")
    if observation.get("chain_rpc_status") == "read":
        sources.append(observation.get("chain_rpc_source", "chain JSON-RPC"))
    observation["source"] = " + ".join(sources)
    observation["limitations"] += " CoinGecko may not index new or unlisted tokens. RPC results only confirm queried account/code metadata; they are not a contract audit, holder analysis, or proof of safe trading."
    return observation


async def fetch_coingecko_observation(client: httpx.AsyncClient, chain: str, address: str, settings) -> dict:
    """Enrich a live pair with CoinGecko market data when the configured key can resolve it."""
    api_key = getattr(settings, "coingecko_api_key", None)
    platform = COINGECKO_PLATFORMS.get(chain.lower())
    if not api_key:
        return {"coingecko_status": "not_configured"}
    if not platform:
        return {"coingecko_status": "unsupported_chain"}

    # Demo and Pro keys use different host/header pairs. Try the matching API tiers
    # without ever putting the key in a URL, application log, or agent prompt.
    for base_url, header in (
        ("https://api.coingecko.com/api/v3", "x-cg-demo-api-key"),
        ("https://pro-api.coingecko.com/api/v3", "x-cg-pro-api-key"),
    ):
        response = await client.get(
            f"{base_url}/coins/{platform}/contract/{address}",
            headers={"User-Agent": USER_AGENT, header: api_key},
            params={"localization": "false", "tickers": "false", "market_data": "true",
                    "community_data": "false", "developer_data": "false"},
        )
        if response.status_code in {401, 403}:
            continue
        if response.status_code == 404:
            return {"coingecko_status": "not_listed"}
        if response.status_code == 429:
            return {"coingecko_status": "rate_limited"}
        response.raise_for_status()
        body = response.json()
        market = body.get("market_data") or {}
        current = market.get("current_price") or {}
        cap = market.get("market_cap") or {}
        volume = market.get("total_volume") or {}
        ath = market.get("ath") or {}
        ath_change = market.get("ath_change_percentage") or {}
        return {
            "coingecko_status": "listed",
            "coingecko_id": str(body.get("id") or "")[:100] or None,
            "coingecko_price_usd": numeric(current.get("usd")),
            "coingecko_market_cap_usd": numeric(cap.get("usd")),
            "coingecko_volume_24h_usd": numeric(volume.get("usd")),
            "coingecko_ath_usd": numeric(ath.get("usd")),
            "coingecko_ath_change_pct": numeric(ath_change.get("usd")),
            "coingecko_market_cap_rank": market.get("market_cap_rank"),
            "coingecko_retrieved_at": datetime.now(timezone.utc).isoformat(),
        }
    return {"coingecko_status": "key_rejected"}


async def fetch_chain_observation(client: httpx.AsyncClient, chain: str, address: str, settings) -> dict:
    """Read standard token metadata without signing or broadcasting transactions."""
    setting_name = RPC_SETTINGS.get(chain.lower())
    endpoint = getattr(settings, setting_name, None) if setting_name else None
    if not endpoint:
        return {"chain_rpc_status": "not_configured"}

    async def rpc(method: str, params: list):
        response = await client.post(endpoint, json={"jsonrpc": "2.0", "id": method, "method": method, "params": params},
                                     headers={"Content-Type": "application/json"})
        if response.status_code == 429:
            return {"error": "rate_limited"}
        response.raise_for_status()
        body = response.json()
        return {"error": "rpc_error"} if body.get("error") else {"result": body.get("result")}

    if chain.lower() == "solana":
        info, supply, largest = await asyncio.gather(
            rpc("getAccountInfo", [address, {"encoding": "jsonParsed", "commitment": "confirmed"}]),
            rpc("getTokenSupply", [address, {"commitment": "confirmed"}]),
            rpc("getTokenLargestAccounts", [address, {"commitment": "confirmed"}]),
            return_exceptions=True,
        )
        if isinstance(info, Exception) or not isinstance(info, dict) or info.get("error"):
            return {"chain_rpc_status": info.get("error", "rpc_error") if isinstance(info, dict) else "rpc_error"}
        account = (info.get("result") or {}).get("value")
        if account is None:
            return {"chain_rpc_status": "account_not_found"}
        parsed = ((account.get("data") or {}).get("parsed") or {})
        mint = parsed.get("info") or {}
        if parsed.get("type") != "mint":
            return {"chain_rpc_status": "read", "solana_account_type": str(parsed.get("type") or "unparsed"),
                    "chain_rpc_source": "Solana JSON-RPC",
                    "chain_rpc_retrieved_at": datetime.now(timezone.utc).isoformat()}
        result = {
            "chain_rpc_status": "read",
            "chain_rpc_source": "Solana JSON-RPC",
            "solana_account_type": "mint",
            "solana_token_decimals": mint.get("decimals"),
            "solana_token_supply": numeric(mint.get("supply")),
            "solana_mint_authority": mint.get("mintAuthority"),
            "solana_freeze_authority": mint.get("freezeAuthority"),
            "chain_rpc_retrieved_at": datetime.now(timezone.utc).isoformat(),
        }
        if isinstance(supply, dict) and not supply.get("error"):
            supply_info = ((supply.get("result") or {}).get("value") or {})
            result["solana_token_supply"] = numeric(supply_info.get("amount"))
            result["solana_token_decimals"] = supply_info.get("decimals", result["solana_token_decimals"])
        if isinstance(largest, dict) and not largest.get("error"):
            accounts = ((largest.get("result") or {}).get("value") or [])
            total = Decimal(result["solana_token_supply"]) if result.get("solana_token_supply") else Decimal(0)
            amounts = [Decimal(str(item.get("amount"))) for item in accounts if numeric(item.get("amount")) is not None]
            if total > 0 and amounts:
                # Keep concentration values consistently readable in the API and chat.
                result["solana_largest_account_supply_pct"] = str((amounts[0] * 100 / total).quantize(Decimal("0.1")))
                result["solana_top20_account_supply_pct"] = str((sum(amounts) * 100 / total).quantize(Decimal("0.1")))
            result["solana_largest_accounts_count"] = len(accounts)
            result["solana_holder_limitations"] = "Largest token accounts are not consolidated wallet owners; exchange pools and related accounts may affect concentration."
        return result

    else:
        if len(address) != 42 or not address.startswith("0x"):
            return {"chain_rpc_status": "invalid_address"}
        eip1967_slots = {
            "implementation": "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc",
            "admin": "0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103",
            "beacon": "0xa3f0ad74e5423aebfd80d3ef4346578335a9a72aeaee59ff6cb3582b35133d50",
        }
        responses = await asyncio.gather(
            rpc("eth_getCode", [address, "latest"]),
            rpc("eth_call", [{"to": address, "data": "0x06fdde03"}, "latest"]),
            rpc("eth_call", [{"to": address, "data": "0x95d89b41"}, "latest"]),
            rpc("eth_call", [{"to": address, "data": "0x313ce567"}, "latest"]),
            rpc("eth_call", [{"to": address, "data": "0x18160ddd"}, "latest"]),
            *(rpc("eth_getStorageAt", [address, slot, "latest"]) for slot in eip1967_slots.values()),
            return_exceptions=True,
        )
        code_result = responses[0]
        if isinstance(code_result, Exception) or code_result.get("error"):
            return {"chain_rpc_status": code_result.get("error", "rpc_error") if isinstance(code_result, dict) else "rpc_error"}
        code = code_result.get("result")
        if not isinstance(code, str) or not code.startswith("0x"):
            return {"chain_rpc_status": "invalid_response"}
        output = {
        "chain_rpc_status": "read",
        "chain_rpc_source": "EVM JSON-RPC",
        "chain_contract_code_present": code not in {"0x", "0x0", "0x00"},
        "chain_contract_code_bytes": max(0, (len(code) - 2) // 2),
        "chain_rpc_retrieved_at": datetime.now(timezone.utc).isoformat(),
        }
        def decode_text(raw):
            if not isinstance(raw, str) or not raw.startswith("0x") or len(raw) < 66:
                return None
            try:
                data = bytes.fromhex(raw[2:])
                if len(data) == 32:
                    return data.rstrip(b"\0").decode("utf-8", "replace") or None
                offset = int.from_bytes(data[:32], "big")
                size = int.from_bytes(data[offset:offset + 32], "big")
                return data[offset + 32:offset + 32 + min(size, 256)].decode("utf-8", "replace") or None
            except (ValueError, IndexError, OverflowError):
                return None
        metadata = {}
        keys = ("name", "symbol", "decimals", "total_supply")
        for key, response in zip(keys, responses[1:]):
            if isinstance(response, dict) and not response.get("error"):
                raw = response.get("result")
                if key in {"name", "symbol"}:
                    metadata[f"evm_token_{key}"] = decode_text(raw)
                elif isinstance(raw, str) and raw.startswith("0x"):
                    try:
                        value = int(raw, 16)
                        metadata[f"evm_token_{key}"] = value if key == "decimals" else str(value)
                    except ValueError:
                        metadata[f"evm_token_{key}"] = None
            else:
                metadata[f"evm_token_{key}"] = None
        metadata["evm_token_metadata_status"] = "read" if metadata.get("evm_token_symbol") or metadata.get("evm_token_name") else "unavailable"
        eip_results = responses[5:]
        proxy_addresses = {}
        for (slot_name, _slot), response in zip(eip1967_slots.items(), eip_results):
            raw = response.get("result") if isinstance(response, dict) and not response.get("error") else None
            if isinstance(raw, str) and re.fullmatch(r"0x[0-9a-fA-F]{64}", raw):
                candidate = "0x" + raw[-40:]
                if int(candidate[2:], 16):
                    proxy_addresses[f"eip1967_{slot_name}_address"] = candidate
        metadata["eip1967_proxy_indicator"] = bool(proxy_addresses)
        metadata["eip1967_slots_status"] = "read" if all(isinstance(row, dict) and not row.get("error") for row in eip_results) else "partial"
        metadata.update(proxy_addresses)
        return output | metadata


async def run_one_cycle():
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5)) as client:
            candidates = await fetch_discovery_candidates(client)
            if not candidates:
                return "no pair evidence available from discovery feeds"
            async with SessionFactory() as db:
                cutoff = datetime.now(timezone.utc) - timedelta(hours=4)
                recent = (await db.execute(select(Investigation.chain, Investigation.token_address).where(
                    Investigation.department == "autonomous",
                    Investigation.updated_at >= cutoff,
                ))).all()
                already_active = {(chain.lower(), address.lower()) for chain, address in recent}
                eligible = [row for row in candidates
                            if (row["chain"].lower(), row["token_address"].lower()) not in already_active]
                observation = choose_discovery_candidate(eligible)
                if observation is None:
                    return "no fresh candidate; all eligible tokens were investigated recently"
                observation = await enrich_observation(client, observation, settings)
                fields = {key: value for key, value in observation.items() if key not in {"source", "data_kind", "limitations"}}
                evidence = Evidence(
                    department="autonomous",
                    chain=observation["chain"],
                    token_address=observation["token_address"],
                    source=observation["source"],
                    data_kind=observation["data_kind"],
                    fields=fields,
                    limitations=observation["limitations"],
                )
                result = await run_investigation(
                    db,
                    evidence,
                    title=f"{observation['symbol']} market investigation",
                    user_request=f"Nova selected this candidate for observed market attention: {observation['discovery_reason']}",
                    simulated=False,
                )
    except Exception as exc:
        return f"market provider unavailable: {type(exc).__name__}"
    if result["status"] != "completed":
        return f"{result['status']}: live evidence retained; agent conclusions unavailable"
    return f"completed: {observation['symbol']} ({observation['chain']})"


async def autonomous_loop(stop: asyncio.Event):
    settings = get_settings()
    while not stop.is_set():
        try:
            outcome = await run_one_cycle()
            logger.info("Autonomous live-data cycle: %s", outcome)
        except Exception as exc:
            logger.error("Autonomous cycle stopped: %s", type(exc).__name__)
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.auto_scan_interval_seconds)
        except asyncio.TimeoutError:
            pass
