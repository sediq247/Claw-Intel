"""Twelve evidence-first analytical capabilities routed through one registry."""
from decimal import Decimal, InvalidOperation
import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .tool_registry import ToolDefinition, ToolExecutionFailed, ToolRegistry


class CapabilityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: str = Field(min_length=1, max_length=64)
    source: str = Field(min_length=1, max_length=128)
    observed_at: str | None = Field(default=None, max_length=64)
    fields: dict[str, Any]


class CapabilityOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capability: str
    status: str
    facts: dict[str, Any]
    missing_inputs: list[str]
    limitations: list[str]
    evidence_id: str
    source: str
    observed_at: str | None


def _finite_number(value: Any) -> float | None:
    """Provider adapters persist exact decimals as JSON strings; parse them safely."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(Decimal(str(value)))
        return number if math.isfinite(number) and abs(number) <= 1e100 else None
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        return None


def _tool(capability: str, required: tuple[str, ...], *, facts=None, missing=None,
          limitations=(), transform=None):
    async def run(payload: CapabilityInput):
        available = {key: payload.fields[key] for key in required if payload.fields.get(key) is not None}
        absent = [key for key in required if payload.fields.get(key) is None]
        if transform:
            derived, derived_missing, extra_limitations = transform(payload.fields)
            available.update(derived)
            absent = sorted(set(absent + derived_missing))
            current_limitations = list(limitations) + extra_limitations
        else:
            current_limitations = list(limitations)
        if facts:
            available.update({key: payload.fields[key] for key in facts if payload.fields.get(key) is not None})
        return CapabilityOutput(
            capability=capability,
            status="unavailable" if not available else ("partial" if absent else "available"),
            facts=available,
            missing_inputs=absent if missing is None else sorted(set(absent + list(missing))),
            limitations=current_limitations,
            evidence_id=payload.evidence_id,
            source=payload.source,
            observed_at=payload.observed_at,
        )
    return run


def _technical(fields):
    windows = {key: value for key in (
        "price_change_5m_pct", "price_change_1h_pct", "price_change_6h_pct", "price_change_24h_pct",
    ) if (value := _finite_number(fields.get(key))) is not None}
    ordered = list(windows.values())
    direction = "mixed or insufficient windows"
    if len(ordered) >= 2 and all(value > 0 for value in ordered):
        direction = "positive across observed windows"
    elif len(ordered) >= 2 and all(value < 0 for value in ordered):
        direction = "negative across observed windows"
    elif len(ordered) >= 2:
        direction = "mixed across observed windows"
    return {"observed_price_change_windows_pct": windows, "window_direction": direction}, [
        "historical_candles", "support_resistance", "rsi", "macd",
    ], ["Directional labels summarize provider-reported windows; no candlestick series was supplied."]


def _quantitative(fields):
    changes = [value for key in ("price_change_5m_pct", "price_change_1h_pct", "price_change_6h_pct", "price_change_24h_pct")
               if (value := _finite_number(fields.get(key))) is not None]
    result = {}
    if changes:
        result["observed_window_count"] = len(changes)
        result["mean_reported_change_pct"] = round(sum(changes) / len(changes), 6)
        result["window_dispersion_pct"] = round(max(changes) - min(changes), 6)
    return result, ["historical_returns", "realized_volatility", "correlation_series", "sample_size"], [
        "Statistics are calculated only from the price-change windows supplied by the source; they are not a backtest or forecast calibration.",
    ]


def _liquidity(fields):
    liquidity = fields.get("liquidity_usd")
    volume = fields.get("volume_24h_usd")
    facts = {}
    missing = []
    liquidity_number, volume_number = _finite_number(liquidity), _finite_number(volume)
    if liquidity_number is not None and liquidity_number > 0 and volume_number is not None:
        facts["volume_to_liquidity_24h"] = round(volume_number / liquidity_number, 6)
    else:
        missing.extend([key for key, value in (("liquidity_usd", liquidity), ("volume_24h_usd", volume)) if value is None])
    missing.append("executable_quote_and_price_impact")
    return facts, missing, ["The ratio is a descriptive market metric, not executable depth or a guaranteed exit estimate."]


def _market_structure(fields):
    facts = {}
    missing = []
    for period in ("5m", "1h", "24h"):
        buys, sells = fields.get(f"buys_{period}"), fields.get(f"sells_{period}")
        if isinstance(buys, int) and isinstance(sells, int) and buys + sells > 0:
            facts[f"{period}_buy_share"] = round(buys / (buys + sells), 6)
            facts[f"{period}_transaction_count"] = buys + sells
        else:
            missing.extend([f"buys_{period}", f"sells_{period}"])
    return facts, missing, ["Transaction counts do not reveal order size, trader identity, or organic demand."]


def _tokenomics(fields):
    known = {key: fields.get(key) for key in (
        "evm_token_total_supply", "solana_token_supply", "solana_mint_authority",
        "solana_freeze_authority", "solana_largest_account_supply_pct", "solana_top20_account_supply_pct",
    ) if fields.get(key) is not None}
    missing = [key for key in ("holder_distribution", "vesting_schedule", "unlock_schedule") if fields.get(key) is None]
    return known, missing, ["Unavailable holder and vesting data must not be inferred from supply metadata."]


def _contract_risk(fields):
    known = {key: fields.get(key) for key in (
        "chain_contract_code_present", "chain_contract_code_bytes", "evm_token_metadata_status",
        "eip1967_proxy_indicator", "eip1967_slots_status", "solana_mint_authority", "solana_freeze_authority",
    ) if fields.get(key) is not None}
    missing = [key for key in ("verified_source_code", "complete_permission_scan", "independent_audit") if fields.get(key) is None]
    return known, missing, ["RPC facts and proxy-slot checks are partial; absence of a detected indicator does not prove safety."]


registry = ToolRegistry()


def _register(name, description, agents, required, *, transform=None, limitations=()):
    registry.register(ToolDefinition(
        name=f"intelligence.{name}", description=description, provider="Zecto deterministic analysis",
        operation=name, allowed_agents=frozenset(agents), required_permissions=frozenset({"read:market_evidence"}),
        input_schema=CapabilityInput, output_schema=CapabilityOutput,
        handler=_tool(name, required, transform=transform, limitations=limitations),
        timeout_seconds=2, cache_seconds=15,
    ))


_register("fundamental_analysis", "Summarizes supplied project and protocol fundamentals, leaving unsupported facts unavailable.",
          ("nova", "vega", "orion"), ("market_cap_usd", "fdv_usd", "coingecko_market_cap_rank"),
          limitations=("Adoption, revenue, governance, and project quality require separate verified sources.",))
_register("technical_analysis", "Summarizes observed price-change windows and explicitly reports missing technical series.",
          ("nova", "atlas", "orion"), (), transform=_technical)
_register("onchain_analysis", "Reports supplied RPC and holder observations without inferring wallet relationships.",
          ("echo", "vega", "orion"), ("chain_rpc_status", "chain_contract_code_present", "chain_account_owner"))
_register("sentiment_analysis", "Reports whether public sentiment inputs were supplied; does not infer sentiment from token metadata.",
          ("nova", "echo", "orion"), ("sentiment_score", "sentiment_source_count", "sentiment_observed_at"),
          limitations=("No social sentiment provider is currently connected to the evidence pipeline.",))
_register("quantitative_analysis", "Calculates bounded descriptive statistics from provider-reported return windows.",
          ("atlas", "orion", "makto"), (), transform=_quantitative)
_register("liquidity_analysis", "Calculates a descriptive turnover-to-liquidity ratio when supplied metrics are available.",
          ("atlas", "makto", "orion"), (), transform=_liquidity)
_register("derivatives_analysis", "Reports the availability of derivatives-market evidence.",
          ("atlas", "orion", "makto"), ("funding_rate", "open_interest", "liquidation_volume"),
          limitations=("No derivatives provider is connected to this evidence pipeline.",))
_register("tokenomics_analysis", "Summarizes available supply and concentration fields and lists missing vesting data.",
          ("vega", "orion"), (), transform=_tokenomics)
_register("market_structure_analysis", "Calculates buy share and transaction counts from supplied provider windows.",
          ("atlas", "orion"), (), transform=_market_structure)
_register("macroeconomic_analysis", "Reports availability of timestamped macroeconomic evidence.",
          ("nova", "orion"), ("macro_indicator", "macro_value", "macro_observed_at"),
          limitations=("No macroeconomic provider is connected to this evidence pipeline.",))
_register("security_risk_analysis", "Summarizes supplied contract and RPC checks without certifying asset safety.",
          ("vega", "orion"), (), transform=_contract_risk)
_register("narrative_sector_analysis", "Reports supplied public project links and narrative metadata without asserting popularity.",
          ("nova", "echo", "orion"), ("website_domains", "social_profiles", "narrative_tags"),
          limitations=("A website or social handle is not proof of community adoption or authenticity.",))


async def analyze_for_agent(agent_id: str, evidence_id: str, source: str,
                            observed_at: str | None, fields: dict[str, Any]) -> list[dict[str, Any]]:
    """Run only tools authorized for this internal agent and evidence scope."""
    input_value = {"evidence_id": evidence_id, "source": source, "observed_at": observed_at, "fields": fields}
    results = []
    for item in registry.catalog(agent_id):
        try:
            results.append(await registry.execute(
                item["name"], agent_id, input_value, permissions={"read:market_evidence"},
            ))
        except ToolExecutionFailed:
            results.append({"capability": item["operation"], "status": "unavailable",
                            "facts": {}, "missing_inputs": ["tool_execution"],
                            "limitations": ["Capability execution failed; no result was inferred."],
                            "evidence_id": evidence_id, "source": source, "observed_at": observed_at})
    return results
