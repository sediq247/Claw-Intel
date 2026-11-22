"""DexScreener market observation adapter and bounded autonomous investigation loop."""
import asyncio
import json
import logging
import math
import random
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
import httpx
from .config import get_settings
from .database import SessionFactory, engine
from .models import AgentJob, AutonomousSchedule, ConversationMessage, Evidence, LLMUsage
from .models import Investigation
from sqlalchemy import func, select, text, tuple_
from .agent_jobs import _reclaim_expired_jobs, auto_scan_dedupe_key, enqueue_investigation_job
from .services import ProviderUnavailable, generate

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


def _reported_usage_cost(metadata: dict) -> Decimal | None:
    usage = metadata.get("usage") or {}
    raw = usage.get("cost_usd", usage.get("cost", usage.get("total_cost")))
    try:
        value = Decimal(str(raw))
        return value if raw is not None and value.is_finite() and value >= 0 else None
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
    logo_url = info.get("imageUrl") if isinstance(info.get("imageUrl"), str) else None
    try:
        parsed_logo = urlsplit(logo_url or "")
        if parsed_logo.scheme != "https" or not parsed_logo.hostname or len(logo_url or "") > 1000:
            logo_url = None
    except ValueError:
        logo_url = None
    return {
        "chain": chain,
        "token_address": address,
        "symbol": str(base_token.get("symbol") or "Unknown")[:48],
        "name": str(base_token.get("name") or "Unknown")[:96],
        "logo_url": logo_url,
        "pair_address": pair.get("pairAddress"),
        "dex_id": pair.get("dexId"),
        "quote_symbol": quote_token.get("symbol"),
        "price_usd": numeric(pair.get("priceUsd")),
        "liquidity_usd": numeric((pair.get("liquidity") or {}).get("usd")),
        "fdv_usd": numeric(pair.get("fdv")),
        "market_cap_usd": numeric(pair.get("marketCap")),
        "volume_24h_usd": numeric((pair.get("volume") or {}).get("h24")),
        "volume_1h_usd": numeric((pair.get("volume") or {}).get("h1")),
        "volume_5m_usd": numeric((pair.get("volume") or {}).get("m5")),
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

# War Room discovery is deliberately narrower than DexScreener's overall chain
# coverage. Keep the upstream IDs here so unrelated ecosystems never enter the
# autonomous pipeline by accident.
WAR_ROOM_CHAIN_IDS = frozenset({"solana", "bsc", "base", "ethereum"})


def _candidate_weight(observation: dict) -> float:
    """Rank observable recent market activity; promotional feed placement is not demand."""
    fields = observation
    def metric(value):
        try:
            number = float(value or 0)
            return min(1e12, max(0.0, number)) if math.isfinite(number) else 0.0
        except (ValueError, TypeError, OverflowError):
            return 0.0
    volume = metric(fields.get("volume_1h_usd"))
    buys = sum(metric(fields.get(f"buys_{period}")) for period in ("1h", "5m"))
    sells = sum(metric(fields.get(f"sells_{period}")) for period in ("1h", "5m"))
    liquidity = metric(fields.get("liquidity_usd"))
    momentum = metric(fields.get("price_change_1h_pct"))
    recent_txns = buys + sells
    if recent_txns < 3 or volume <= 0 or liquidity <= 0:
        return 0.0
    return math.log1p(volume) + math.log1p(recent_txns) + min(2.0, max(-2.0, momentum / 20.0)) + math.log1p(liquidity) / 8


def choose_discovery_candidate(candidates: list[dict]) -> dict | None:
    if not candidates:
        return None
    ranked = [( _candidate_weight(row), row) for row in candidates]
    ranked = [(score, row) for score, row in ranked if score > 0]
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    score, chosen = ranked[0]
    chosen["attention_score"] = round(score, 3)
    chosen["discovery_reason"] = (
        f"Observed recent activity: {int(chosen.get('buys_1h') or 0) + int(chosen.get('sells_1h') or 0)} trades in 1h, "
        f"1h volume ${chosen.get('volume_1h_usd') or 'unavailable'}, "
        f"liquidity ${chosen.get('liquidity_usd') or 'unavailable'}, "
        f"1h price change {chosen.get('price_change_1h_pct') if chosen.get('price_change_1h_pct') is not None else 'unavailable'}%. Promotional profile/boost placement is excluded from the attention score."
    )
    return chosen


async def _nova_select_candidate(candidates: list[dict]) -> tuple[dict, dict]:
    """Ask Nova to choose only from measured, currently eligible attention candidates."""
    ranked = sorted(candidates, key=_candidate_weight, reverse=True)[:6]
    bounded = [{key: row.get(key) for key in (
        "chain", "token_address", "symbol", "name", "price_usd", "volume_1h_usd",
        "buys_1h", "sells_1h", "liquidity_usd", "price_change_1h_pct", "discovery_reason",
    )} for row in ranked]
    prompt = (
        "Choose the next token for a live War Room investigation. Select only a candidate with measured recent trade activity, "
        "nonzero live volume and liquidity. Ignore paid boosts and profile placement. Do not invent facts or predict a return. "
        "Return exactly one JSON object {\"chain\": ..., \"token_address\": ..., \"reason\": ...} using an exact chain and address below. "
        "If none merits analysis, return {\"chain\": null, \"token_address\": null, \"reason\": ...}. Candidate evidence: "
        + json.dumps(bounded, ensure_ascii=True, separators=(",", ":"))
    )
    answer, metadata = await generate("autonomous", "nova", prompt, max_output_tokens=180, natural_chat=False)
    try:
        start, end = answer.find("{"), answer.rfind("}")
        choice = json.loads(answer[start:end + 1]) if start >= 0 and end > start else {}
    except (json.JSONDecodeError, TypeError):
        choice = {}
    def exact_candidate(row: dict) -> bool:
        chain = str(row.get("chain", "")).lower()
        if chain != str(choice.get("chain", "")).lower():
            return False
        address, chosen_address = str(row.get("token_address", "")), str(choice.get("token_address", ""))
        return address == chosen_address if chain == "solana" else address.lower() == chosen_address.lower()
    selected = next((row for row in ranked if exact_candidate(row)), None)
    if not selected:
        raise ValueError("Nova did not return one exact eligible token candidate")
    selected["nova_selection_reason"] = str(choice.get("reason") or "Nova selected this measured attention candidate")[:500]
    return selected, metadata


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
            if chain.lower() not in WAR_ROOM_CHAIN_IDS:
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


async def fetch_token_observation(client: httpx.AsyncClient, address: str, settings, chain: str | None = None) -> dict | None:
    """Find an exact token pair, scoped to a chain when the caller supplied one."""
    requested_chain = chain.lower() if chain else None
    if requested_chain:
        response = await client.get(f"{BASE}/tokens/v1/{requested_chain}/{address}", headers={"User-Agent": USER_AGENT})
    else:
        response = await client.get(f"{BASE}/latest/dex/search", params={"q": address}, headers={"User-Agent": USER_AGENT})
    if response.status_code in {400, 404, 429}:
        return None
    response.raise_for_status()
    payload = response.json()
    pairs = payload if isinstance(payload, list) else payload.get("pairs") or []
    def address_matches(pair: dict) -> bool:
        candidate = str((pair.get("baseToken") or {}).get("address") or "")
        pair_chain = str(pair.get("chainId") or "").lower()
        # EVM addresses are case-insensitive; Solana/Base58 addresses are case-sensitive.
        if requested_chain and pair_chain != requested_chain:
            return False
        return candidate == address if pair_chain == "solana" else candidate.lower() == address.lower()

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
        ath_date = market.get("ath_date") or {}
        ath_change = market.get("ath_change_percentage") or {}
        return {
            "coingecko_status": "listed",
            "coingecko_id": str(body.get("id") or "")[:100] or None,
            "coingecko_price_usd": numeric(current.get("usd")),
            "coingecko_market_cap_usd": numeric(cap.get("usd")),
            "coingecko_volume_24h_usd": numeric(volume.get("usd")),
            "coingecko_ath_usd": numeric(ath.get("usd")),
            "coingecko_ath_date": ath_date.get("usd"),
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
                candidate_keys = {(row["chain"].lower(), row["token_address"].lower()) for row in candidates}
                previous_rows = (await db.scalars(select(Evidence).where(
                    Evidence.department == "autonomous",
                    tuple_(Evidence.chain, Evidence.token_address).in_(candidate_keys),
                ).order_by(Evidence.observed_at.desc()))).all()
                latest_by_token: dict[tuple[str, str], Evidence] = {}
                for previous in previous_rows:
                    latest_by_token.setdefault((previous.chain.lower(), previous.token_address.lower()), previous)
                now = datetime.now(timezone.utc)
                cooldown = timedelta(seconds=settings.auto_scan_min_revisit_seconds)
                eligible = []
                for candidate in candidates:
                    key = (candidate["chain"].lower(), candidate["token_address"].lower())
                    previous = latest_by_token.get(key)
                    if previous is None:
                        candidate["_last_observed_at"] = None
                        eligible.append(candidate)
                        continue
                    if previous.observed_at and now - previous.observed_at < cooldown:
                        continue
                    if _material_market_change(previous.fields or {}, candidate,
                                              settings.auto_scan_revisit_change_pct):
                        candidate["_last_observed_at"] = previous.observed_at
                        eligible.append(candidate)
                eligible.sort(key=lambda row: (
                    -_candidate_weight(row),
                    row.get("_last_observed_at") or datetime.min.replace(tzinfo=timezone.utc),
                ))
                if not eligible:
                    return "no new candidate or material market change after the configured revisit cooldown"
                observation, nova_usage = await _nova_select_candidate(eligible)
                counts = nova_usage.get("usage") or {}
                def usage_count(*keys):
                    return next((int(counts[key]) for key in keys if isinstance(counts.get(key), int) and counts[key] >= 0), None)
                db.add(LLMUsage(
                    department="autonomous", agent_id="nova", provider=nova_usage["provider"],
                    model=nova_usage["model"], input_tokens=usage_count("promptTokenCount", "prompt_tokens", "input_tokens"),
                    output_tokens=usage_count("candidatesTokenCount", "completion_tokens", "output_tokens"),
                    cost_usd=_reported_usage_cost(nova_usage),
                ))
                observation.pop("_last_observed_at", None)
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
                db.add(evidence)
                await db.flush()
                job = await enqueue_investigation_job(
                    db,
                    evidence,
                    title=f"{observation['symbol']} market investigation",
                    user_request=(f"Nova selected this candidate for measured market attention: {observation['nova_selection_reason']}. "
                                  f"Observed data: {observation['discovery_reason']}"),
                    dedupe_key=auto_scan_dedupe_key(
                        observation["chain"], observation["token_address"],
                        int(now.timestamp() // max(60, settings.auto_scan_min_revisit_seconds)),
                    ),
                )
                return f"queued: {observation['symbol']} ({observation['chain']}) job {str(job.id)[:8]}"
    except Exception as exc:
        if isinstance(exc, ProviderUnavailable):
            return "Nova model unavailable; no token was selected or queued"
        if isinstance(exc, ValueError):
            return "Nova did not return an exact live candidate; no token was queued"
        return f"market provider unavailable: {type(exc).__name__}"


def _material_market_change(previous: dict, current: dict, threshold_pct: float) -> bool:
    """Return true only when a comparable market field moved beyond the configured threshold."""
    for key in ("price_usd", "liquidity_usd", "volume_24h_usd"):
        try:
            before = Decimal(str(previous.get(key)))
            after = Decimal(str(current.get(key)))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if not before.is_finite() or not after.is_finite() or before < 0 or after < 0:
            continue
        if before == 0:
            if after > 0:
                return True
            continue
        change_pct = abs((after - before) / before) * Decimal("100")
        if change_pct >= Decimal(str(threshold_pct)):
            return True
    return False


AMBIENT_TOPICS = (
    '"climate change" OR "extreme weather"',
    'economy OR inflation OR recession OR "cost of living"',
    'election OR diplomacy OR parliament OR government',
    'culture OR science OR technology OR health',
)
TRUSTED_NEWS_HOSTS = (
    "reuters.com", "apnews.com", "bbc.com", "bbc.co.uk", "ft.com", "npr.org",
    "pbs.org", "dw.com", "aljazeera.com", "theguardian.com", "france24.com",
)
SCHEDULE_LOCK_KEY = 1129070935


def _trusted_article_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        return parsed.scheme == "https" and any(host == trusted or host.endswith("." + trusted)
                                                for trusted in TRUSTED_NEWS_HOSTS)
    except ValueError:
        return False


async def _ambient_article(client: httpx.AsyncClient, previous_url: str | None) -> dict | None:
    for topic in random.sample(AMBIENT_TOPICS, k=len(AMBIENT_TOPICS)):
        try:
            response = await client.get("https://api.gdeltproject.org/api/v2/doc/doc", params={
                "query": f"({topic}) sourcelang:english", "mode": "artlist", "format": "json",
                "timespan": "24h", "maxrecords": 50, "sort": "datedesc",
            })
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            # A single failed topic must not prevent the remaining live-news queries.
            logger.info("GDELT ambient topic unavailable (%s)", type(exc).__name__)
            continue
        for item in body.get("articles", []) if isinstance(body, dict) else []:
            if not isinstance(item, dict):
                continue
            title, url = item.get("title"), item.get("url")
            if not isinstance(title, str) or len(title.strip()) < 12 or not isinstance(url, str) or not _trusted_article_url(url):
                continue
            if url == previous_url:
                continue
            return {"title": title.strip()[:500], "url": url, "date": str(item.get("seendate") or "")[:40],
                    "source": urlsplit(url).hostname}
    return None


async def _append_autonomous_message(db, agent_id: str, content: str, attachments: list | None = None):
    row = ConversationMessage(department="autonomous", agent_id=agent_id, role="assistant",
                              content=content[:6000], attachments=attachments or [], simulated=False)
    db.add(row)
    return row


async def _ambient_discussion(article: dict | None) -> int:
    agents = ("nova", "atlas", "echo")
    async with SessionFactory() as db:
        previous = (await db.scalars(select(ConversationMessage).where(
            ConversationMessage.department == "autonomous",
        ).order_by(ConversationMessage.created_at.desc()).limit(6))).all()
        history = [{"role": "assistant", "content": f"{row.agent_id}: {row.content}"}
                   for row in reversed(previous)]
        turns = []
        for agent_id in agents:
            if article:
                prompt = (
                    "Have a brief, natural off-topic team conversation about this current world-news headline. "
                    "The source is a headline index, not the article body: do not infer details beyond the headline, "
                    "do not repeat allegations as fact, and do not gossip about private people. You may respectfully "
                    "disagree or show emotion. Keep it to 1-3 conversational sentences and explicitly distinguish "
                    "headline from confirmed facts. Mention the date only if supplied.\n"
                    f"Headline: {article['title']}\nPublished/indexed: {article['date'] or 'date not supplied'}\n"
                    f"Publisher domain: {article['source']}\nSource URL: {article['url']}"
                )
            else:
                prompt = (
                    "Continue a brief, natural conversation among teammates at the market desk. This cycle found no "
                    "fresh headline from the configured source list. Do not invent current news, prices, market moves, "
                    "or personal experiences. You may discuss how the team should verify evidence, ask a teammate a "
                    "thoughtful question, or react to the recent conversation. Keep it warm, specific to the prior "
                    "messages, and to 1-3 conversational sentences. Make clear when a fact has not been checked."
                )
            try:
                content, metadata = await generate("autonomous", agent_id, prompt, history + turns,
                                                   max_output_tokens=180, natural_chat=True)
            except ProviderUnavailable as exc:
                logger.warning("Autonomous agent discussion unavailable: %s", str(exc)[:600])
                break
            turns.append({"role": "assistant", "content": f"{agent_id}: {content}"})
            attachments = ([{
                "name": f"Source: {article['source']}", "url": article["url"],
                "title": article["title"], "source_kind": "world-news-headline",
            }] if article else [])
            await _append_autonomous_message(db, agent_id, content, attachments)
            counts = (metadata.get("usage") or {})
            def usage_value(*keys):
                return next((int(counts[k]) for k in keys if isinstance(counts.get(k), int) and counts[k] >= 0), None)
            db.add(LLMUsage(department="autonomous", agent_id=agent_id, provider=metadata["provider"],
                            model=metadata["model"],
                            input_tokens=usage_value("promptTokenCount", "prompt_tokens", "input_tokens"),
                            output_tokens=usage_value("candidatesTokenCount", "completion_tokens", "output_tokens"),
                            cost_usd=_reported_usage_cost(metadata)))
        await db.commit()
        return len(turns)


async def _schedule_transition(phase: str) -> None:
    agents = ("nova", "atlas", "orion")
    intent = "Wrap up the current work session and say a warm, concise goodnight to the team; the agents are entering a scheduled software pause." if phase == "resting" else "Welcome the team back from its scheduled software pause and naturally pick up the market desk conversation."
    async with SessionFactory() as db:
        history_rows = (await db.scalars(select(ConversationMessage).where(
            ConversationMessage.department == "autonomous",
        ).order_by(ConversationMessage.created_at.desc()).limit(5))).all()
        history = [{"role": "assistant", "content": f"{row.agent_id}: {row.content}"}
                   for row in reversed(history_rows)]
        for agent_id in agents:
            try:
                content, metadata = await generate("autonomous", agent_id, intent, history,
                                                   max_output_tokens=100, natural_chat=True)
            except ProviderUnavailable:
                break
            await _append_autonomous_message(db, agent_id, content, [{"name": "Scheduled pause" if phase == "resting" else "Work resumed",
                                                                       "source_kind": "schedule"}])
            history.append({"role": "assistant", "content": f"{agent_id}: {content}"})
            counts = metadata.get("usage") or {}
            inp = next((counts[k] for k in ("promptTokenCount", "prompt_tokens", "input_tokens") if isinstance(counts.get(k), int)), None)
            out = next((counts[k] for k in ("candidatesTokenCount", "completion_tokens", "output_tokens") if isinstance(counts.get(k), int)), None)
            db.add(LLMUsage(department="autonomous", agent_id=agent_id, provider=metadata["provider"],
                            model=metadata["model"], input_tokens=inp, output_tokens=out,
                            cost_usd=_reported_usage_cost(metadata)))
        await db.commit()


async def _get_or_create_schedule(db, now: datetime) -> AutonomousSchedule:
    schedule = await db.scalar(select(AutonomousSchedule).where(AutonomousSchedule.id == 1).with_for_update())
    if schedule is None:
        schedule = AutonomousSchedule(id=1, phase="working", phase_started_at=now,
                                      phase_ends_at=now + timedelta(seconds=random.randint(7200, 10800)),
                                      next_scan_at=now, next_ambient_at=now + timedelta(seconds=random.randint(20, 45)))
        db.add(schedule)
        await db.commit()
        await db.refresh(schedule)
    return schedule


async def _run_scheduler_as_leader(stop: asyncio.Event) -> None:
    settings = get_settings()
    async with engine.connect() as leader_connection:
        locked = await leader_connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": SCHEDULE_LOCK_KEY})
        if not locked:
            await leader_connection.commit()
            try:
                await asyncio.wait_for(stop.wait(), timeout=20)
            except asyncio.TimeoutError:
                pass
            return
        await leader_connection.commit()
        try:
            while not stop.is_set():
                now = datetime.now(timezone.utc)
                transitioned = None
                ambient_due = False
                previous_news_url = None
                should_scan = False
                async with SessionFactory() as db:
                    schedule = await _get_or_create_schedule(db, now)
                    if now >= schedule.phase_ends_at:
                        if schedule.phase == "working":
                            schedule.phase = "draining"
                            schedule.phase_started_at = now
                            schedule.phase_ends_at = now + timedelta(seconds=20)
                            transitioned = "draining"
                        else:
                            if schedule.phase == "draining":
                                await _reclaim_expired_jobs(db, now)
                            active_jobs = int(await db.scalar(select(func.count(AgentJob.id)).where(
                                AgentJob.status == "processing",
                            )) or 0)
                            if active_jobs == 0:
                                if schedule.phase == "draining":
                                    schedule.phase = "resting"
                                    schedule.phase_started_at = now
                                    schedule.phase_ends_at = now + timedelta(seconds=random.randint(1800, 2100))
                                    transitioned = "resting"
                                else:
                                    schedule.phase = "working"
                                    schedule.phase_started_at = now
                                    schedule.phase_ends_at = now + timedelta(seconds=random.randint(7200, 10800))
                                    schedule.next_scan_at = now
                                    schedule.next_ambient_at = now + timedelta(minutes=random.randint(10, 20))
                                    transitioned = "working"
                            else:
                                schedule.phase_ends_at = now + timedelta(seconds=20)
                    if schedule.phase == "working":
                        # Bring forward legacy 30–60 minute ambient timers once
                        # after upgrading, while leaving the new 10–20 minute
                        # cadence untouched on subsequent scheduler passes.
                        if schedule.next_ambient_at > now + timedelta(minutes=20):
                            schedule.next_ambient_at = now + timedelta(seconds=random.randint(20, 45))
                        if settings.auto_scan_enabled and now >= schedule.next_scan_at:
                            should_scan = True
                            schedule.next_scan_at = now + timedelta(seconds=settings.auto_scan_interval_seconds)
                        if now >= schedule.next_ambient_at:
                            schedule.next_ambient_at = now + timedelta(minutes=random.randint(10, 20))
                            previous_news_url = schedule.last_news_url
                            ambient_due = True
                    schedule.updated_at = now
                    await db.commit()
                if transitioned and transitioned != "draining":
                    await _schedule_transition(transitioned)
                if should_scan:
                    try:
                        logger.info("Autonomous live-data cycle: %s", await run_one_cycle())
                    except Exception as exc:
                        logger.error("Autonomous cycle stopped: %s", type(exc).__name__)
                if ambient_due:
                    try:
                        async with httpx.AsyncClient(timeout=httpx.Timeout(12, connect=4)) as client:
                            article = await _ambient_article(client, previous_news_url)
                        if article is None:
                            logger.info("No fresh headline from the trusted publisher list; starting a source-free desk discussion")
                        posted = await _ambient_discussion(article)
                        async with SessionFactory() as db:
                            schedule = await db.get(AutonomousSchedule, 1)
                            if schedule and posted:
                                if article:
                                    schedule.last_news_url = article["url"]
                                schedule.updated_at = datetime.now(timezone.utc)
                                await db.commit()
                            elif schedule:
                                schedule.next_ambient_at = datetime.now(timezone.utc) + timedelta(minutes=2)
                                await db.commit()
                    except Exception as exc:
                        logger.warning("Ambient discussion cycle failed (%s)", type(exc).__name__)
                        async with SessionFactory() as db:
                            schedule = await db.get(AutonomousSchedule, 1)
                            if schedule:
                                schedule.next_ambient_at = datetime.now(timezone.utc) + timedelta(minutes=3)
                                await db.commit()
                # Recheck ownership without holding an idle-in-transaction connection.
                owned = await leader_connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": SCHEDULE_LOCK_KEY})
                await leader_connection.commit()
                if not owned:
                    logger.warning("Autonomous scheduler lost its database leader lock")
                    break
                await leader_connection.scalar(text("SELECT pg_advisory_unlock(:key)"), {"key": SCHEDULE_LOCK_KEY})
                await leader_connection.commit()
                try:
                    await asyncio.wait_for(stop.wait(), timeout=20)
                except asyncio.TimeoutError:
                    pass
        finally:
            await leader_connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": SCHEDULE_LOCK_KEY})
            await leader_connection.commit()


async def autonomous_loop(stop: asyncio.Event):
    while not stop.is_set():
        try:
            await _run_scheduler_as_leader(stop)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Autonomous scheduler unavailable (%s)", type(exc).__name__)
            try:
                await asyncio.wait_for(stop.wait(), timeout=10)
            except asyncio.TimeoutError:
                pass
