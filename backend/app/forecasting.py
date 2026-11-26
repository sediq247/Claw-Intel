"""Validate and version forecasts from transient market observations."""
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .evidence import Evidence
from .models import Investigation, MarketForecast
from .services import persist_event


class ScenarioProbabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bullish: float = Field(ge=0, le=1)
    bearish: float = Field(ge=0, le=1)
    neutral: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def total_one(self):
        if abs(self.bullish + self.bearish + self.neutral - 1.0) > 0.01:
            raise ValueError("Scenario probabilities must total 1.0")
        return self


class ForecastDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direction: Literal["bullish", "bearish", "neutral", "mixed", "uncertain"]
    horizon_days: int = Field(ge=1, le=3650)
    bullish_scenario: str = Field(min_length=15, max_length=1600)
    bearish_scenario: str = Field(min_length=15, max_length=1600)
    neutral_scenario: str = Field(min_length=15, max_length=1600)
    probabilities: ScenarioProbabilities | None = None
    probability_basis: str = Field(min_length=8, max_length=800)
    confidence: Literal["low", "medium", "high"]
    confidence_reason: str = Field(min_length=10, max_length=800)
    catalysts: list[str] = Field(max_length=8)
    key_risks: list[str] = Field(max_length=8)
    supporting_evidence_ids: list[str] = Field(max_length=12)
    contradicting_evidence_ids: list[str] = Field(max_length=12)
    missing_information: list[str] = Field(max_length=12)
    invalidation_conditions: list[str] = Field(min_length=1, max_length=8)


def parse_forecast(content: str, allowed_evidence_ids: set[str]) -> ForecastDocument:
    """Parse JSON and ensure the model only cites evidence supplied to it."""
    text_content = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", content or "", flags=re.IGNORECASE)
    start, end = text_content.find("{"), text_content.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Orion did not return a JSON forecast")
    try:
        document = ForecastDocument.model_validate_json(text_content[start:end + 1])
    except Exception as exc:
        raise ValueError("Orion returned a forecast that failed schema validation") from exc
    cited = set(document.supporting_evidence_ids + document.contradicting_evidence_ids)
    if not cited.issubset(allowed_evidence_ids):
        raise ValueError("Orion cited evidence that was not supplied to the forecast")
    probability_basis = document.probability_basis.lower()
    if document.probabilities is None and not any(
        probability_basis.startswith(marker)
        for marker in ("not estimated", "insufficient evidence", "not statistically supported", "uncalibrated")
    ):
        raise ValueError("A missing probability estimate must be explicitly marked unsupported")
    return document


async def persist_forecast(
    db: AsyncSession,
    investigation: Investigation,
    evidence: Evidence,
    document: ForecastDocument,
    provider: str,
    model: str,
) -> MarketForecast:
    if investigation.department != "autonomous" or evidence.department != "autonomous":
        raise ValueError("Only War Room forecasts can be published here")
    if evidence.data_kind != "live":
        raise ValueError("Forecasts require live provider evidence")

    chain = evidence.chain.strip().lower()
    address = evidence.token_address.strip().lower() if chain != "solana" else evidence.token_address.strip()
    asset_key = f"crypto:{chain}:{address}"
    # Serialize version allocation for one asset without blocking forecasts for other assets.
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:asset_key))"), {"asset_key": asset_key})
    previous = await db.scalar(
        select(MarketForecast).where(MarketForecast.asset_key == asset_key)
        .order_by(MarketForecast.version.desc()).limit(1)
    )
    fields = evidence.fields or {}
    symbol = str(fields.get("symbol") or "Unknown")[:64]
    row = MarketForecast(
        investigation_id=investigation.id,
        asset_class="crypto",
        asset_key=asset_key,
        symbol=symbol,
        version=(previous.version + 1) if previous else 1,
        provider=provider[:32],
        model=model[:160],
        forecast=document.model_dump(mode="json", exclude={
            "supporting_evidence_ids", "contradicting_evidence_ids",
        }),
        supersedes_id=previous.id if previous else None,
    )
    db.add(row)
    await db.flush()
    await persist_event(db, "autonomous", "FORECAST_PUBLISHED", {
        "forecast_id": str(row.id), "investigation_id": str(investigation.id),
        "asset_key": asset_key, "symbol": symbol,
        "version": row.version, "direction": document.direction,
        "horizon_days": document.horizon_days,
    }, agent_id="orion")
    return row


def forecast_json(row: MarketForecast, history_count: int | None = None) -> dict:
    result = {
        "id": str(row.id),
        "investigation_id": str(row.investigation_id),
        "asset_class": row.asset_class,
        "asset_key": row.asset_key,
        "symbol": row.symbol,
        "version": row.version,
        "provider": row.provider,
        "model": row.model,
        "forecast": row.forecast,
        "supersedes_id": str(row.supersedes_id) if row.supersedes_id else None,
        "created_at": row.created_at.isoformat(),
    }
    if history_count is not None:
        result["history_count"] = history_count
    return result
