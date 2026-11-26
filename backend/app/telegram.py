"""Telegram webhook, wallet-account linking, and durable message delivery."""
import asyncio
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select, text

from .config import get_settings
from .database import SessionFactory, engine
from .models import TelegramAccount, TelegramLinkChallenge, TelegramOutbox

logger = logging.getLogger(__name__)
_DELIVERY_LOCK_ID = 713042110813
_POLLING_LOCK_ID = 713042110814
_MAX_ATTEMPTS = 8


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def telegram_api(client: httpx.AsyncClient, method: str, payload: dict | None = None):
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("Telegram bot is not configured")
    response = await client.post(
        f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}", json=payload or {}
    )
    response.raise_for_status()
    body = response.json()
    if not body.get("ok"):
        raise RuntimeError(f"Telegram API rejected {method}")
    return body.get("result")


async def configure_webhook(client: httpx.AsyncClient) -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        return
    base = settings.public_base_url.strip().rstrip("/")
    secret = settings.telegram_webhook_secret or ""
    if not base:
        logger.info("Telegram local mode selected; use long polling because PUBLIC_BASE_URL is empty")
        return
    if not base.startswith("https://") or len(secret) < 32:
        logger.error("Telegram webhook not configured: set PUBLIC_BASE_URL (HTTPS) and a 32+ character TELEGRAM_WEBHOOK_SECRET")
        return
    await telegram_api(client, "setWebhook", {
        "url": f"{base}/api/telegram/webhook",
        "secret_token": secret,
        "allowed_updates": ["message"],
        "drop_pending_updates": False,
    })
    logger.info("Telegram webhook configured")


async def handle_update(update: dict, client: httpx.AsyncClient) -> None:
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text_value = message.get("text")
    if not isinstance(chat_id, (int, str)) or not isinstance(text_value, str):
        return
    words = text_value.strip().split()
    if words and words[0].split("@", 1)[0] == "/start" and len(words) == 1:
        await telegram_api(client, "sendMessage", {"chat_id": str(chat_id), "text": "To link this chat, create a one-time Telegram link from Zecto Settings."})
        return
    if len(words) != 2 or words[0].split("@", 1)[0] != "/start":
        return
    raw_token = words[1]
    if len(raw_token) > 128:
        return
    async with SessionFactory() as db:
        now = datetime.now(timezone.utc)
        challenge = await db.scalar(select(TelegramLinkChallenge).where(
            TelegramLinkChallenge.token_hash == token_digest(raw_token),
            TelegramLinkChallenge.used_at.is_(None),
            TelegramLinkChallenge.expires_at > now,
        ).with_for_update())
        if challenge is None:
            owner = await db.scalar(select(TelegramAccount).where(TelegramAccount.chat_id == str(chat_id)))
            response = ("This Telegram chat is already linked to Zecto." if owner else
                        "That link has expired or was already used. Create a fresh link in Zecto settings.")
            user_id = owner.user_id if owner else None
        else:
            challenge.used_at = now
            account = await db.scalar(select(TelegramAccount).where(
                (TelegramAccount.user_id == challenge.user_id) | (TelegramAccount.chat_id == str(chat_id))
            ).with_for_update())
            if account and (account.user_id != challenge.user_id or account.chat_id != str(chat_id)):
                response = "This Telegram chat or Zecto account is already linked elsewhere. Unlink it first."
                user_id = None
            else:
                if account is None:
                    account = TelegramAccount(user_id=challenge.user_id, chat_id=str(chat_id))
                    db.add(account)
                account.username = (message.get("from") or {}).get("username")
                response = "Your Telegram account is linked to Zecto. Price-alert notifications are enabled."
                user_id = challenge.user_id
            await db.commit()
        if user_id is not None:
            db.add(TelegramOutbox(user_id=user_id, chat_id=str(chat_id), text=response))
            await db.commit()
    if user_id is None:
        await telegram_api(client, "sendMessage", {"chat_id": str(chat_id), "text": response})


async def queue_price_alert(db, user_id, price: str, chain: str, address: str, condition: str, threshold: str):
    account = await db.scalar(select(TelegramAccount).where(TelegramAccount.user_id == user_id))
    if account:
        direction = "reached or exceeded" if condition == "above" else "fell to or below"
        db.add(TelegramOutbox(
            user_id=user_id, chat_id=account.chat_id,
            text=f"Zecto price alert: {chain} token {address} {direction} ${threshold}. Observed price: ${price}. This is informational only; no trade was executed.",
        ))


async def _deliver_batch(client: httpx.AsyncClient) -> None:
    now = datetime.now(timezone.utc)
    async with SessionFactory() as db:
        await db.execute(text("UPDATE telegram_outbox SET status='pending', locked_at=NULL WHERE status='processing' AND locked_at < :cutoff"), {"cutoff": now - timedelta(minutes=5)})
        rows = (await db.scalars(select(TelegramOutbox).where(
            TelegramOutbox.status == "pending", TelegramOutbox.available_at <= now,
        ).order_by(TelegramOutbox.created_at).limit(20).with_for_update(skip_locked=True))).all()
        for row in rows:
            row.status = "processing"
            row.locked_at = now
        await db.commit()
        ids = [row.id for row in rows]

    for item_id in ids:
        async with SessionFactory() as db:
            row = await db.get(TelegramOutbox, item_id)
            if row is None or row.status != "processing":
                continue
            linked = await db.scalar(select(TelegramAccount.id).where(
                TelegramAccount.user_id == row.user_id, TelegramAccount.chat_id == row.chat_id,
            ))
            if linked is None:
                row.status = "cancelled"
                row.locked_at = None
                await db.commit()
                continue
            try:
                await telegram_api(client, "sendMessage", {"chat_id": row.chat_id, "text": row.text, "disable_web_page_preview": True})
                row.status = "sent"
                row.sent_at = datetime.now(timezone.utc)
                row.last_error = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                row.attempts += 1
                row.last_error = type(exc).__name__[:200]
                row.locked_at = None
                if row.attempts >= _MAX_ATTEMPTS:
                    row.status = "dead_letter"
                    logger.error("Telegram delivery moved to dead letter (id=%s)", row.id)
                else:
                    row.status = "pending"
                    row.available_at = datetime.now(timezone.utc) + timedelta(seconds=min(3600, 5 * 2 ** row.attempts))
            await db.commit()


async def _delivery_leader(stop: asyncio.Event) -> None:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5)) as client:
        while not stop.is_set():
            try:
                await _deliver_batch(client)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Telegram outbox cycle failed (%s)", type(exc).__name__)
            try:
                await asyncio.wait_for(stop.wait(), timeout=2)
            except asyncio.TimeoutError:
                pass


async def telegram_delivery_loop(stop: asyncio.Event) -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        return
    while not stop.is_set():
        connection = None
        acquired = False
        try:
            connection = await engine.connect()
            acquired = bool(await connection.scalar(text("SELECT pg_try_advisory_lock(:lock_id)"), {"lock_id": _DELIVERY_LOCK_ID}))
            if acquired:
                await _delivery_leader(stop)
                await connection.execute(text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": _DELIVERY_LOCK_ID})
                await connection.commit()
                return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Telegram delivery worker waiting for PostgreSQL (%s)", type(exc).__name__)
        finally:
            if connection is not None:
                await connection.close()
        try:
            await asyncio.wait_for(stop.wait(), timeout=15)
        except asyncio.TimeoutError:
            pass


async def _telegram_polling(stop: asyncio.Event) -> None:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=httpx.Timeout(40, connect=5)) as client:
        try:
            info = await telegram_api(client, "getWebhookInfo")
            if isinstance(info, dict) and info.get("url"):
                logger.error("Telegram polling skipped: this bot already has a webhook configured")
                return
        except Exception as exc:
            logger.error("Telegram polling could not inspect webhook state (%s)", type(exc).__name__)
            return
        offset = None
        while not stop.is_set():
            try:
                payload = {"timeout": 30, "allowed_updates": ["message"]}
                if offset is not None:
                    payload["offset"] = offset
                updates = await telegram_api(client, "getUpdates", payload)
                for update in updates or []:
                    await handle_update(update, client)
                    offset = int(update.get("update_id", 0)) + 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Telegram local polling failed (%s)", type(exc).__name__)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=5)
                except asyncio.TimeoutError:
                    pass


async def telegram_polling_loop(stop: asyncio.Event) -> None:
    """Single-leader long polling for local development without a public URL."""
    settings = get_settings()
    if not settings.telegram_bot_token or settings.public_base_url.strip():
        return
    while not stop.is_set():
        connection = None
        try:
            connection = await engine.connect()
            acquired = bool(await connection.scalar(text("SELECT pg_try_advisory_lock(:lock_id)"), {"lock_id": _POLLING_LOCK_ID}))
            if acquired:
                try:
                    await _telegram_polling(stop)
                finally:
                    await connection.execute(text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": _POLLING_LOCK_ID})
                    await connection.commit()
                return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Telegram polling worker waiting for PostgreSQL (%s)", type(exc).__name__)
        finally:
            if connection is not None:
                await connection.close()
        try:
            await asyncio.wait_for(stop.wait(), timeout=15)
        except asyncio.TimeoutError:
            pass


def new_link_token() -> str:
    return secrets.token_urlsafe(24)
