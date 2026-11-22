"""Single-leader PostgreSQL worker for wallet-owned price alerts."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID

import httpx
from sqlalchemy import select, text

from .config import get_settings
from .database import SessionFactory, engine
from .market_data import fetch_token_observation
from .models import PriceAlert, PriceAlertEvent
from .telegram import queue_price_alert

logger = logging.getLogger(__name__)
_WORKER_LOCK_ID = 713042110812
_BATCH_LIMIT = 25


def alert_matches(condition: str, threshold: Decimal, price: Decimal) -> bool:
    if condition == "above":
        return price >= threshold
    if condition == "below":
        return price <= threshold
    raise ValueError("Unsupported price alert condition")


async def _sleep_or_stop(stop: asyncio.Event, seconds: int) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass


async def _check_alert(alert_id: UUID, settings, client: httpx.AsyncClient) -> None:
    async with SessionFactory() as db:
        alert = await db.get(PriceAlert, alert_id)
        if alert is None or not alert.enabled:
            return
        chain, address = alert.chain, alert.token_address

    try:
        observation = await fetch_token_observation(client, address, settings, chain)
        if not observation or str(observation.get("chain", "")).lower() != chain.lower():
            await _mark_check(alert_id)
            return
        price = Decimal(str(observation.get("price_usd")))
        observed_at = datetime.fromisoformat(str(observation["provider_retrieved_at"]).replace("Z", "+00:00"))
        if not price.is_finite() or price <= 0 or observed_at.tzinfo is None:
            return
        now = datetime.now(timezone.utc)
        if observed_at > now + timedelta(seconds=30) or now - observed_at > timedelta(minutes=10):
            await _mark_check(alert_id)
            return
    except (httpx.HTTPError, InvalidOperation, KeyError, ValueError, TypeError, ArithmeticError) as exc:
        logger.info("Price alert observation unavailable (%s)", type(exc).__name__)
        await _mark_check(alert_id)
        return

    async with SessionFactory() as db:
        current = await db.scalar(select(PriceAlert).where(PriceAlert.id == alert_id).with_for_update())
        if current is None or not current.enabled:
            return
        current.last_observed_price_usd = price
        current.last_checked_at = datetime.now(timezone.utc)
        triggered = alert_matches(current.condition, Decimal(current.threshold_usd), price)
        if triggered and not current.is_triggered:
            db.add(PriceAlertEvent(
                alert_id=current.id, user_id=current.user_id, observed_price_usd=price,
                source=str(observation.get("source") or "DexScreener API")[:128], observed_at=observed_at,
            ))
            await queue_price_alert(
                db, current.user_id, str(price), current.chain, current.token_address,
                current.condition, str(current.threshold_usd),
            )
            current.is_triggered = True
        elif not triggered:
            # Re-arm when price returns across the threshold; the next crossing
            # produces a new durable in-app alert event.
            current.is_triggered = False
        await db.commit()


async def _mark_check(alert_id: UUID) -> None:
    async with SessionFactory() as db:
        current = await db.get(PriceAlert, alert_id)
        if current is not None:
            current.last_checked_at = datetime.now(timezone.utc)
            await db.commit()


async def _run_leader(stop: asyncio.Event) -> None:
    settings = get_settings()
    semaphore = asyncio.Semaphore(5)
    while not stop.is_set():
        try:
            async with SessionFactory() as db:
                alert_ids = list((await db.scalars(
                    select(PriceAlert.id).where(PriceAlert.enabled.is_(True))
                    .order_by(PriceAlert.last_checked_at.asc().nullsfirst(), PriceAlert.created_at)
                    .limit(_BATCH_LIMIT)
                )).all())
            async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=5)) as client:
                async def bounded(alert_id):
                    async with semaphore:
                        await _check_alert(alert_id, settings, client)
                await asyncio.gather(*(bounded(alert_id) for alert_id in alert_ids))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Price alert worker cycle failed (%s)", type(exc).__name__)
        await _sleep_or_stop(stop, settings.price_alert_check_interval_seconds)


async def price_alert_loop(stop: asyncio.Event) -> None:
    """Run one polling worker across API replicas using a session advisory lock."""
    while not stop.is_set():
        connection = None
        acquired = False
        try:
            connection = await engine.connect()
            acquired = bool(await connection.scalar(text("SELECT pg_try_advisory_lock(:lock_id)"), {"lock_id": _WORKER_LOCK_ID}))
            if acquired:
                logger.info("Price alert worker leadership acquired")
                try:
                    await _run_leader(stop)
                finally:
                    await connection.execute(text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": _WORKER_LOCK_ID})
                    await connection.commit()
                return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Price alert worker waiting for PostgreSQL (%s)", type(exc).__name__)
        finally:
            if connection is not None:
                await connection.close()
        await _sleep_or_stop(stop, 15 if not acquired else 1)
