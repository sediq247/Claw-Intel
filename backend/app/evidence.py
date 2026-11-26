"""Short-lived market evidence passed between providers and the analysis workflow.

Instances are intentionally plain in-memory values, never SQLAlchemy entities.
The database stores resulting analysis, not the underlying provider evidence.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Evidence:
    department: str
    chain: str
    token_address: str
    source: str
    data_kind: str
    fields: dict = field(default_factory=dict)
    limitations: str | None = None
    id: UUID = field(default_factory=uuid4)
    observed_at: datetime = field(default_factory=now_utc)
    session_id: UUID | None = None
    investigation_id: UUID | None = None
