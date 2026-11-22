"""Atomic PostgreSQL-backed fixed-window rate limits shared by app replicas."""
from datetime import datetime, timezone
import hashlib
import hmac

from sqlalchemy import text


UPSERT_RATE_LIMIT = text(
    """
    INSERT INTO rate_limit_buckets (route, client_key, window_start, hits)
    VALUES (:route, :client_key, :window_start, 1)
    ON CONFLICT (route, client_key, window_start)
    DO UPDATE SET hits = LEAST(rate_limit_buckets.hits + 1, :cap)
    RETURNING hits
    """
)


def client_key(remote_host: str, secret: str | None = None) -> str:
    """Store a stable pseudonymous client key instead of a raw network address."""
    normalized = (remote_host or "unknown").strip().lower()
    key = (secret or "ClawIntel development-only rate-limit key").encode("utf-8")
    return hmac.new(key, normalized.encode("utf-8"), hashlib.sha256).hexdigest()


def window_start(now: datetime) -> datetime:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    epoch = int(now.timestamp())
    return datetime.fromtimestamp(epoch - epoch % 60, tz=timezone.utc)


async def consume_rate_limit(connection, route: str, remote_host: str, limit: int, now: datetime,
                             secret: str | None = None) -> int:
    """Atomically increment and return the request count for this client/route/minute."""
    result = await connection.execute(
        UPSERT_RATE_LIMIT,
        {
            "route": route,
            "client_key": client_key(remote_host, secret),
            "window_start": window_start(now),
            "cap": limit + 1,
        },
    )
    return int(result.scalar_one())
