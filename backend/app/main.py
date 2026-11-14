from contextlib import asynccontextmanager
import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID
from fastapi import Depends, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from .config import get_settings
from .database import engine, get_db
from .models import AgentMemory, BrowserSession, ConversationMessage, DemoQuote, DemoWallet, Evidence, Investigation, InvestigationFinding, LLMUsage, Position, Trade, TradingChat
from .market_data import autonomous_loop, fetch_discovery_candidates, fetch_token_observation
from .orchestration import run_investigation, run_trading_roundtable
from .realtime import hub
from .services import AGENTS, ProviderUnavailable, generate, persist_event, provider_models, recent_events
import httpx

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema is managed only through Alembic migrations; never create or drop tables here.
    stop = asyncio.Event()
    task = asyncio.create_task(autonomous_loop(stop)) if settings.auto_scan_enabled else None
    try:
        yield
    finally:
        stop.set()
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    await engine.dispose()


app = FastAPI(title="ClawIntel API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type"])


@app.middleware("http")
async def check_origin(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.method in {"POST", "DELETE", "PUT", "PATCH"} and origin and origin not in settings.cors_origins:
        return Response(status_code=403, content="Origin is not allowed")
    return await call_next(request)


class MessageInput(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    chat_id: UUID | None = None


class NewChatInput(BaseModel):
    title: str = Field(default="New chat", min_length=1, max_length=120)


class WalletInput(BaseModel):
    label: str = Field(default="Demo NEAR Wallet", min_length=1, max_length=80)


class QuoteInput(BaseModel):
    chain: str = Field(min_length=1, max_length=48)
    token_address: str = Field(min_length=3, max_length=160)
    side: str = Field(pattern="^(buy|sell)$")
    amount_near: Decimal = Field(gt=0, le=Decimal("250"))


class ApproveInput(BaseModel):
    quote_id: UUID
    idempotency_key: str = Field(min_length=12, max_length=96)
    approved: bool


async def current_session(request: Request, db: AsyncSession = Depends(get_db)) -> BrowserSession:
    raw = request.cookies.get("claw_session")
    try:
        sid = UUID(raw or "")
    except ValueError:
        raise HTTPException(401, "Create a browser session first")
    session = await db.get(BrowserSession, sid)
    if not session:
        raise HTTPException(401, "Browser session expired")
    return session


async def trading_session(session: BrowserSession = Depends(current_session)) -> BrowserSession:
    if not session.wallet_connected:
        raise HTTPException(403, "Connect the demo wallet to open the Trading Room")
    return session


_trading_turn_locks: dict[UUID, asyncio.Lock] = {}


def serialize_trading_turn(endpoint):
    """Serialize full chat turns so same-session agent replies cannot interleave."""
    async def wrapped(body: MessageInput, session: BrowserSession = Depends(trading_session),
                      db: AsyncSession = Depends(get_db)):
        lock = _trading_turn_locks.setdefault(session.id, asyncio.Lock())
        async with lock:
            return await endpoint(body, session, db)
    return wrapped


def settings_status(department: str) -> dict:
    prefix = "warroom" if department == "autonomous" else "trading"
    provider_order = (settings.warroom_providers if department == "autonomous" else settings.trading_providers).split(",")
    providers = []
    for provider in provider_order:
        provider = provider.strip().lower()
        if provider not in {"gemini", "openrouter", "cerebras"}:
            continue
        key = getattr(settings, f"{prefix}_{provider}_api_key", None)
        model = getattr(settings, f"{prefix}_{provider}_model", None)
        if provider == "gemini":
            model = ",".join(provider_models(department, provider, settings))
        providers.append({"provider": provider, "configured": bool(key and model), "model": model if key else None})
    return {"department": department, "providers": providers, "available": any(p["configured"] for p in providers)}


@app.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(503, "database unavailable")
    return {"status": "ok", "database": "postgresql",
            "llm": {"autonomous": settings_status("autonomous")["available"], "trading": settings_status("trading")["available"]},
            "market_data": data_source_status()}


@app.post("/api/session")
async def create_session(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    raw = request.cookies.get("claw_session")
    try:
        existing = await db.get(BrowserSession, UUID(raw or ""))
    except ValueError:
        existing = None
    session = existing or BrowserSession()
    if not existing:
        db.add(session)
        await db.commit()
    response.set_cookie("claw_session", str(session.id), httponly=True, secure=settings.cookie_secure,
                        samesite="strict", max_age=60 * 60 * 24 * 7, path="/")
    return {"session_id": str(session.id), "wallet_connected": session.wallet_connected}


@app.get("/api/agents")
async def agents(department: str | None = None, db: AsyncSession = Depends(get_db)):
    if department not in {None, "autonomous", "trading"}:
        raise HTTPException(422, "department must be autonomous or trading")
    findings_query = select(InvestigationFinding).join(
        Investigation, Investigation.id == InvestigationFinding.investigation_id,
    )
    usage_query = select(LLMUsage)
    if department:
        findings_query = findings_query.where(InvestigationFinding.department == department)
        usage_query = usage_query.where(LLMUsage.department == department)
    finding_rows = (await db.scalars(findings_query)).all()
    finding_counts: dict[str, set[UUID]] = {}
    scanned_tokens: dict[str, set[tuple[str, str]]] = {}
    latest: dict[str, datetime] = {}
    active_counts: dict[str, set[UUID]] = {}
    investigation_rows = {row.id: row for row in (await db.scalars(
        select(Investigation).where(Investigation.department == department) if department else select(Investigation)
    )).all()}
    for finding in finding_rows:
        finding_counts.setdefault(finding.agent_id, set()).add(finding.investigation_id)
        investigation = investigation_rows.get(finding.investigation_id)
        if investigation:
            scanned_tokens.setdefault(finding.agent_id, set()).add((investigation.chain.lower(), investigation.token_address.lower()))
            if investigation.status == "active":
                active_counts.setdefault(finding.agent_id, set()).add(investigation.id)
        latest[finding.agent_id] = max(latest.get(finding.agent_id, finding.created_at), finding.created_at)
    usage_rows = (await db.scalars(usage_query)).all()
    llm_token_counts: dict[str, int] = {}
    for usage in usage_rows:
        llm_token_counts[usage.agent_id] = llm_token_counts.get(usage.agent_id, 0) + (usage.input_tokens or 0) + (usage.output_tokens or 0)
    return {"agents": [{
        "id": key,
        "name": value.split(" — ")[0],
        "role": value.split(" — ", 1)[1],
        "investigations": len(finding_counts.get(key, set())),
        "tokens_analyzed": len(scanned_tokens.get(key, set())),
        "llm_tokens": llm_token_counts.get(key, 0),
        "active_investigations": len(active_counts.get(key, set())),
        "last_activity": latest[key].isoformat() if latest.get(key) else None,
    } for key, value in AGENTS.items()]}


@app.get("/api/settings/status")
async def settings_api():
    return {"departments": [settings_status("autonomous"), settings_status("trading")],
            "data_sources": data_source_status()}


def data_source_status() -> dict:
    return {
        "dexscreener": {"configured": True, "authentication_required": False},
        "coingecko": {"configured": bool(settings.coingecko_api_key)},
        "rpc": {
            "ethereum": bool(settings.eth_rpc_url),
            "bsc": bool(settings.bsc_rpc_url),
            "base": bool(settings.base_rpc_url),
            "solana": bool(settings.solana_rpc_url),
        },
        "auto_scan_enabled": settings.auto_scan_enabled,
        "scan_interval_seconds": settings.auto_scan_interval_seconds,
    }


@app.get("/api/settings/usage")
async def settings_usage(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(LLMUsage.department, func.count(LLMUsage.id), func.coalesce(func.sum(LLMUsage.input_tokens), 0),
               func.coalesce(func.sum(LLMUsage.output_tokens), 0))
        .group_by(LLMUsage.department)
    )).all()
    totals = {department: {"requests": int(count), "input_tokens": int(input_tokens),
                           "output_tokens": int(output_tokens), "cost_usd": None}
              for department, count, input_tokens, output_tokens in rows}
    return {"departments": {key: totals.get(key, {"requests": 0, "input_tokens": 0,
                                                    "output_tokens": 0, "cost_usd": None})
                            for key in ("autonomous", "trading")}}


@app.get("/api/autonomous/messages")
async def warroom_messages(limit: int = 100, db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(ConversationMessage).where(ConversationMessage.department == "autonomous")
                             .order_by(ConversationMessage.created_at.desc()).limit(min(max(limit, 1), 200)))).all()
    return {"messages": [message_json(row) for row in reversed(rows)]}


@app.get("/api/autonomous/evidence")
async def warroom_evidence(db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(Evidence).where(Evidence.department == "autonomous").order_by(Evidence.observed_at.desc()).limit(100))).all()
    return {"evidence": [evidence_json(row) for row in rows]}


@app.get("/api/autonomous/events")
async def warroom_events(after: int = 0, db: AsyncSession = Depends(get_db)):
    return {"events": await recent_events(db, "autonomous", None, max(after, 0))}


def message_json(row: ConversationMessage):
    return {"id": str(row.id), "department": row.department, "agent_id": row.agent_id,
            "role": row.role, "content": row.content, "created_at": row.created_at.isoformat(),
            "investigation_id": str(row.investigation_id) if row.investigation_id else None,
            "simulated": bool(row.simulated)}


def evidence_json(row: Evidence):
    return {"id": str(row.id), "chain": row.chain, "token_address": row.token_address,
            "source": row.source, "data_kind": row.data_kind, "observed_at": row.observed_at.isoformat(),
            "fields": row.fields, "limitations": row.limitations,
            "investigation_id": str(row.investigation_id) if row.investigation_id else None}


async def investigation_records(db: AsyncSession, department: str, session_id: UUID | None = None, limit: int = 50):
    query = select(Investigation).where(Investigation.department == department)
    query = query.where(Investigation.session_id.is_(None) if session_id is None else Investigation.session_id == session_id)
    rows = (await db.scalars(query.order_by(Investigation.updated_at.desc()).limit(min(max(limit, 1), 100)))).all()
    ids = [row.id for row in rows]
    findings = (await db.scalars(
        select(InvestigationFinding).where(InvestigationFinding.investigation_id.in_(ids))
        .order_by(InvestigationFinding.created_at)
    )).all() if ids else []
    grouped: dict[UUID, list[dict]] = {}
    for finding in findings:
        grouped.setdefault(finding.investigation_id, []).append({
            "id": str(finding.id), "agent_id": finding.agent_id, "round": finding.round_number,
            "phase": finding.phase, "content": finding.content,
            "confidence": float(finding.confidence) if finding.confidence is not None else None,
            "evidence_ids": finding.evidence_ids, "created_at": finding.created_at.isoformat(),
        })
    return {"investigations": [{
        "id": str(row.id), "department": row.department, "chain": row.chain, "token_address": row.token_address,
        "title": row.title, "status": row.status, "scenario_id": row.scenario_id,
        "confidence": float(row.confidence) if row.confidence is not None else None,
        "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat(),
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "findings": grouped.get(row.id, []),
    } for row in rows]}


@app.get("/api/autonomous/investigations")
async def warroom_investigations(limit: int = 50, db: AsyncSession = Depends(get_db)):
    return await investigation_records(db, "autonomous", None, limit)


@app.get("/api/trading/investigations")
async def trading_investigations(limit: int = 50, session: BrowserSession = Depends(trading_session), db: AsyncSession = Depends(get_db)):
    return await investigation_records(db, "trading", session.id, limit)


@app.get("/api/wallet")
async def wallet_status(session: BrowserSession = Depends(current_session), db: AsyncSession = Depends(get_db)):
    wallet = await db.scalar(select(DemoWallet).where(DemoWallet.session_id == session.id))
    return {"connected": session.wallet_connected, "address": session.wallet_address, "label": session.wallet_label,
            "kind": "simulated", "network": "DEMO ONLY", "near_balance": str(wallet.near_balance) if wallet else None}


@app.post("/api/wallet/connect")
async def wallet_connect(body: WalletInput, session: BrowserSession = Depends(current_session), db: AsyncSession = Depends(get_db)):
    session.wallet_connected = True
    session.wallet_label = body.label
    session.wallet_address = f"clawintel-demo-{session.id.hex[:12]}.near"
    wallet = await db.scalar(select(DemoWallet).where(DemoWallet.session_id == session.id))
    if wallet is None:
        db.add(DemoWallet(session_id=session.id, near_balance=Decimal("1000.00000000")))
    await db.commit()
    await persist_event(db, "trading", "WALLET_CONNECTED", {"address": session.wallet_address, "simulated": True}, session.id, "makto")
    return await wallet_status(session, db)


@app.post("/api/wallet/disconnect")
async def wallet_disconnect(session: BrowserSession = Depends(current_session), db: AsyncSession = Depends(get_db)):
    session.wallet_connected = False
    session.wallet_address = None
    session.wallet_label = None
    await db.commit()
    await persist_event(db, "trading", "WALLET_DISCONNECTED", {"simulated": True}, session.id, "makto")
    await hub.close_private_session(str(session.id))
    return {"connected": False}


@app.get("/api/trading/chats")
async def trading_chats(session: BrowserSession = Depends(trading_session), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(TradingChat).where(TradingChat.session_id == session.id)
                             .order_by(TradingChat.updated_at.desc()))).all()
    return {"chats": [{"id": str(row.id), "title": row.title, "created_at": row.created_at.isoformat(),
                       "updated_at": row.updated_at.isoformat()} for row in rows]}


@app.post("/api/trading/chats")
async def create_trading_chat(body: NewChatInput, session: BrowserSession = Depends(trading_session), db: AsyncSession = Depends(get_db)):
    chat = TradingChat(session_id=session.id, title=body.title.strip() or "New chat")
    db.add(chat)
    await db.commit()
    await db.refresh(chat)
    return {"id": str(chat.id), "title": chat.title, "created_at": chat.created_at.isoformat(),
            "updated_at": chat.updated_at.isoformat()}


@app.get("/api/trading/messages")
async def trading_messages(chat_id: UUID, session: BrowserSession = Depends(trading_session), db: AsyncSession = Depends(get_db)):
    chat = await db.scalar(select(TradingChat).where(TradingChat.id == chat_id, TradingChat.session_id == session.id))
    if not chat:
        raise HTTPException(404, "Chat not found")
    rows = (await db.scalars(select(ConversationMessage).where(ConversationMessage.department == "trading",
        ConversationMessage.session_id == session.id, ConversationMessage.chat_id == chat.id)
        .order_by(ConversationMessage.created_at.desc()).limit(100))).all()
    messages = [row for row in reversed(rows) if not (
        row.agent_id == "system" and (
            "saved the token evidence, but no configured agent model" in row.content.lower()
            or "saved this address for review, but no configured agent model" in row.content.lower()
        )
    )]
    return {"messages": [message_json(row) for row in messages]}


@app.post("/api/trading/messages")
@serialize_trading_turn
async def trading_message(body: MessageInput, session: BrowserSession = Depends(trading_session), db: AsyncSession = Depends(get_db)):
    chat = await db.scalar(select(TradingChat).where(TradingChat.id == body.chat_id, TradingChat.session_id == session.id)) if body.chat_id else None
    if body.chat_id and not chat:
        raise HTTPException(404, "Chat not found")
    if chat is None:
        chat = TradingChat(session_id=session.id, title="New chat")
        db.add(chat)
        await db.flush()
    mention = re.search(r"(?i)(?<![a-z0-9_])@(nova|atlas|vega|echo|orion|makto)\b", body.content)
    agent_id = mention.group(1).lower() if mention else "nova"
    user = ConversationMessage(session_id=session.id, chat_id=chat.id, department="trading", agent_id="human", role="user", content=body.content)
    if chat.title == "New chat":
        chat.title = re.sub(r"\s+", " ", body.content).strip()[:72] or "New chat"
    chat.updated_at = datetime.now(timezone.utc)
    db.add(user)
    await db.commit()
    await persist_event(db, "trading", "HUMAN_MESSAGE", {"content": body.content, "chat_id": str(chat.id)}, session.id, "human")

    direct_makto = bool(re.search(r"(?i)(?:^\s*makto\b|@makto\b)", body.content))
    open_intent = bool(re.search(r"(?i)\b(?:open|buy|enter|start)\b", body.content) and
                       re.search(r"(?i)\b(?:trade|position|long|buy)\b", body.content))
    fixture = next((item for item in DEMO_MARKETS.values()
                    if re.search(rf"(?i)\b{re.escape(item['symbol'])}\b", body.content)), None)
    if direct_makto and open_intent and fixture:
        token_address = "demo:" + fixture["symbol"].lower()
        amount_match = re.search(r"(?i)(\d+(?:\.\d+)?)\s*(?:near)\b", body.content)
        amount = Decimal(amount_match.group(1)) if amount_match else Decimal("10")
        if amount <= 0 or amount > Decimal("250"):
            raise HTTPException(422, "Demo trade amount must be between 0 and 250 NEAR")
        wallet = await db.scalar(select(DemoWallet).where(DemoWallet.session_id == session.id).with_for_update())
        price = fixture["price_near"]
        fee = (amount * Decimal("0.003")).quantize(Decimal("0.00000001"))
        if wallet is None or wallet.near_balance < amount + fee:
            raise HTTPException(422, "Insufficient demo NEAR balance for this amount and the demo fee")
        wallet.near_balance -= amount + fee
        position = await db.scalar(select(Position).where(Position.session_id == session.id,
            Position.chain == "demo", Position.token_address == token_address).with_for_update())
        quantity = amount / price
        if position:
            total_cost = position.quantity * position.average_price + amount
            position.quantity += quantity
            position.average_price = total_cost / position.quantity
            position.current_price = price
        else:
            db.add(Position(session_id=session.id, chain="demo", token_address=token_address,
                            quantity=quantity, average_price=price, current_price=price))
        db.add(Trade(session_id=session.id, idempotency_key=f"chat-{user.id}", chain="demo",
                     token_address=token_address, side="buy", amount_near=amount,
                     quote_price=price, status="confirmed_demo"))
        db.add(ConversationMessage(session_id=session.id, chat_id=chat.id, department="trading",
            agent_id="makto", role="assistant", content=(
                f"Opened a simulated {amount} NEAR {fixture['symbol']} position at the deterministic demo price. "
                "I’ve updated the ledger; this is not a live execution. The team will review the position below."
            ), simulated=True))
        await db.commit()
        await persist_event(db, "trading", "TRADE_CONFIRMED", {
            "simulated": True, "source": "deterministic fixture", "chain": "demo",
            "token_address": token_address, "side": "buy", "amount_near": str(amount),
            "chat_id": str(chat.id),
        }, session.id, "makto")
        agent_id = "makto"

    address_match = re.search(r"\b0x[a-fA-F0-9]{40}\b|\b[1-9A-HJ-NP-Za-km-z]{32,44}\b", body.content)
    if address_match:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5)) as client:
                observation = await fetch_token_observation(client, address_match.group(0), settings)
        except (httpx.HTTPError, ValueError, TypeError):
            observation = None
        if observation:
            portfolio_rows = (await db.scalars(select(Position).where(Position.session_id == session.id))).all()
            wallet = await db.scalar(select(DemoWallet).where(DemoWallet.session_id == session.id))
            holdings = [{"chain": row.chain, "token": row.token_address, "quantity": str(row.quantity)} for row in portfolio_rows]
            makto_context = (
                f" Makto demo context: balance {str(wallet.near_balance) if wallet else '0'} NEAR; "
                f"open positions {holdings}. These are simulated only; never imply a real quote or trade."
            )
            fields = {key: value for key, value in observation.items() if key not in {"source", "data_kind", "limitations"}}
            evidence = Evidence(
                department="trading", session_id=session.id, chain=observation["chain"],
                token_address=observation["token_address"], source=observation["source"],
                data_kind="live", fields=fields, limitations=observation["limitations"],
            )
            result = await run_investigation(
                db, evidence, title=f"{observation['symbol']} trading-room investigation",
                session_id=session.id, chat_id=chat.id, user_request=body.content + makto_context,
            )
            reply = await db.scalar(select(ConversationMessage).where(
                ConversationMessage.investigation_id == UUID(result["investigation_id"]),
                ConversationMessage.chat_id == chat.id,
                ConversationMessage.agent_id != "system", ConversationMessage.role == "assistant",
            ).order_by(ConversationMessage.created_at.desc()).limit(1))
            return {"human_message": message_json(user), "reply": message_json(reply) if reply else None,
                    "investigation": result, "provider_backed": result["findings"] > 0,
                    "complete": result["status"] == "completed"}
        # Keep an unindexed address as evidence so Nova and the other agents still
        # receive the exact subject and can explain which checks are unavailable.
        raw_address = address_match.group(0)
        evidence = Evidence(
            department="trading", session_id=session.id,
            chain="unknown",
            token_address=raw_address,
            source="DexScreener API",
            data_kind="delayed",
            fields={"symbol": "Unknown", "pair_lookup_status": "no exact token pair indexed"},
            limitations="No exact token pair was returned for this address. Market price, liquidity, token identity, contract details, and holder data are unverified.",
        )
        result = await run_investigation(
            db, evidence, title="Unindexed token address check",
            session_id=session.id, chat_id=chat.id, user_request=body.content,
        )
        reply = await db.scalar(select(ConversationMessage).where(
            ConversationMessage.investigation_id == UUID(result["investigation_id"]),
            ConversationMessage.chat_id == chat.id,
            ConversationMessage.agent_id != "system", ConversationMessage.role == "assistant",
        ).order_by(ConversationMessage.created_at.desc()).limit(1))
        return {"human_message": message_json(user), "reply": message_json(reply) if reply else None,
                "investigation": result, "provider_backed": result["findings"] > 0,
                "complete": result["status"] == "completed"}

    portfolio_rows = (await db.scalars(select(Position).where(Position.session_id == session.id))).all()
    wallet = await db.scalar(select(DemoWallet).where(DemoWallet.session_id == session.id))
    holdings = [{"chain": row.chain, "token": row.token_address, "quantity": str(row.quantity)} for row in portfolio_rows]
    wallet_context = (
        "Makto context: this is a simulated wallet only. "
        f"Available demo NEAR: {str(wallet.near_balance) if wallet else '0'}. Open demo positions: {holdings}. "
        "Do not claim live execution. A direct Makto request may create an immediate demo ledger position without a quote-panel approval."
    )
    if address_match:
        wallet_context += " The submitted address did not produce a usable live pair observation; report market facts as unavailable instead of guessing."
    market_request = bool(re.search(
        r"(?i)\b(?:market|markets|trending|what(?:'s| is) moving|which tokens?|what tokens?|"
        r"token|ticker|coin|crypto|price|recommend(?:ation)?|predict|forecast|trade|buy|sell|"
        r"trade today|buy today|should we (?:buy|trade)|"
        r"what should we (?:buy|trade))\b", body.content,
    ))
    shared_context = ""
    if market_request:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=5)) as client:
                candidates = await fetch_discovery_candidates(client, per_feed=1)
            snapshot = []
            for candidate in candidates[:4]:
                symbol = re.sub(r"[^A-Za-z0-9._-]", "", str(candidate.get("symbol") or "Unknown"))[:32]
                chain = re.sub(r"[^A-Za-z0-9_-]", "", str(candidate.get("chain") or "unknown"))[:32]
                address = re.sub(r"[^A-Za-z0-9]", "", str(candidate.get("token_address") or ""))[:64]
                snapshot.append({
                    "symbol": symbol or "Unknown", "chain": chain or "unknown", "token_address": address,
                    "price_usd": candidate.get("price_usd"), "liquidity_usd": candidate.get("liquidity_usd"),
                    "volume_24h_usd": candidate.get("volume_24h_usd"),
                    "change_1h_pct": candidate.get("price_change_1h_pct"),
                    "change_24h_pct": candidate.get("price_change_24h_pct"),
                    "buys_1h": candidate.get("buys_1h"), "sells_1h": candidate.get("sells_1h"),
                    "discovery_feeds": [str(feed)[:32] for feed in candidate.get("discovery_feeds", [])[:4]],
                    "observed_at": candidate.get("provider_retrieved_at"),
                })
            if snapshot:
                shared_context = (
                    "Current market snapshot from DexScreener (retrieved for this chat): "
                    + json.dumps(snapshot, separators=(",", ":"))
                    + ". These are recent-profile/boost discovery candidates, not a full market index; boosts can be paid promotion. "
                    "Use the supplied observations as facts and any outlook as a separate, uncertain forecast."
                )
            else:
                shared_context = (
                    "A live DexScreener discovery snapshot was requested, but no current candidates were returned. "
                    "Do not claim current market facts; if the trader asks for a prediction, offer only a clearly labeled qualitative guess and state its uncertainty."
                )
        except (httpx.HTTPError, ValueError, TypeError):
            shared_context = (
                "A live DexScreener discovery lookup failed for this request. Do not claim current market facts; "
                "if the trader asks for a prediction, offer only a clearly labeled qualitative guess and state its uncertainty."
            )
    try:
        discussion = await run_trading_roundtable(
            db, session_id=session.id, chat_id=chat.id, user_request=body.content,
            lead_agent=agent_id if mention else None, wallet_context=wallet_context,
            shared_context=shared_context,
        )
    except ProviderUnavailable as exc:
        await persist_event(db, "trading", "AGENT_STATUS", {"status": "unavailable", "reason": str(exc)}, session.id, agent_id)
        raise HTTPException(503, str(exc))
    replies = discussion["replies"]
    return {"human_message": message_json(user), "replies": replies,
            "turns_completed": len(replies), "turns_expected": discussion["turns_expected"],
            "complete": len(replies) == discussion["turns_expected"]}


@app.get("/api/trading/events")
async def trading_events(after: int = 0, session: BrowserSession = Depends(trading_session), db: AsyncSession = Depends(get_db)):
    return {"events": await recent_events(db, "trading", session.id, max(after, 0))}


@app.get("/api/trading/portfolio")
async def portfolio(session: BrowserSession = Depends(trading_session), db: AsyncSession = Depends(get_db)):
    wallet = await db.scalar(select(DemoWallet).where(DemoWallet.session_id == session.id))
    positions = (await db.scalars(select(Position).where(Position.session_id == session.id))).all()
    trades = (await db.scalars(select(Trade).where(Trade.session_id == session.id).order_by(Trade.created_at.desc()).limit(50))).all()
    return {"simulated": True, "near_balance": str(wallet.near_balance) if wallet else "0",
            "positions": [{"chain": p.chain, "token_address": p.token_address, "quantity": str(p.quantity), "average_price_near": str(p.average_price),
                           "current_price_near": str(p.current_price) if p.current_price is not None else None,
                           "value_near": str(p.quantity * p.current_price) if p.current_price is not None else None}
                          for p in positions],
            "trades": [{"id": str(t.id), "chain": t.chain, "token_address": t.token_address, "side": t.side, "amount_near": str(t.amount_near), "status": t.status, "created_at": t.created_at.isoformat()} for t in trades]}


# Controlled, clearly simulated fixtures. No external market value is implied.
DEMO_MARKETS = {
    ("demo", "demo:claw"): {"symbol": "CLAW", "price_near": Decimal("0.050000000000"), "source": "deterministic fixture"},
    ("demo", "demo:signal"): {"symbol": "SIGNAL", "price_near": Decimal("0.120000000000"), "source": "deterministic fixture"},
}


@app.post("/api/trading/quotes")
async def make_quote(body: QuoteInput, session: BrowserSession = Depends(trading_session), db: AsyncSession = Depends(get_db)):
    fixture = DEMO_MARKETS.get((body.chain.lower(), body.token_address.lower()))
    if not fixture:
        raise HTTPException(404, "No quote available for this token in the deterministic demo fixtures")
    if body.side == "buy":
        wallet = await db.scalar(select(DemoWallet).where(DemoWallet.session_id == session.id).with_for_update())
        if wallet is None or wallet.near_balance < body.amount_near:
            raise HTTPException(422, "Insufficient demo NEAR balance")
        price = fixture["price_near"]
    else:
        position = await db.scalar(select(Position).where(
            Position.session_id == session.id, Position.chain == body.chain.lower(),
            Position.token_address == body.token_address.lower(),
        ))
        if position is None or position.quantity <= 0:
            raise HTTPException(422, "No demo position is available to sell")
        price = position.current_price or position.average_price
        if body.amount_near > position.quantity * price:
            raise HTTPException(422, "Sell value exceeds the open demo position")
    quote = DemoQuote(session_id=session.id, chain=body.chain.lower(), token_address=body.token_address.lower(),
                      side=body.side, amount_near=body.amount_near, price=price,
                      expires_at=datetime.now(timezone.utc) + timedelta(seconds=30))
    db.add(quote)
    await db.commit()
    return {"quote_id": str(quote.id), "simulated": True, "source": fixture["source"], "symbol": fixture["symbol"],
            "chain": quote.chain, "token_address": quote.token_address, "side": quote.side,
            "amount_near": str(quote.amount_near), "price_near_per_token": str(quote.price),
            "estimated_quantity": str(quote.amount_near / quote.price), "fee_near": str((quote.amount_near * Decimal("0.003")).quantize(Decimal("0.00000001"))),
            "expires_at": quote.expires_at.isoformat()}


@app.post("/api/trading/approve")
async def approve_trade(body: ApproveInput, session: BrowserSession = Depends(trading_session), db: AsyncSession = Depends(get_db)):
    # Serialize approvals per browser wallet before checking idempotency or balance.
    wallet_connected = await db.scalar(select(BrowserSession.wallet_connected).where(BrowserSession.id == session.id).with_for_update())
    if not wallet_connected:
        raise HTTPException(403, "Connect the demo wallet to approve trades")
    existing = await db.scalar(select(Trade).where(Trade.session_id == session.id, Trade.idempotency_key == body.idempotency_key))
    if existing:
        return {"status": existing.status, "trade_id": str(existing.id), "idempotent_replay": True}
    quote = await db.scalar(select(DemoQuote).where(DemoQuote.id == body.quote_id, DemoQuote.session_id == session.id).with_for_update())
    if not quote:
        raise HTTPException(404, "Quote not found")
    if quote.consumed:
        raise HTTPException(409, "Quote already used")
    if quote.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(409, "Quote expired; request a new quote")
    quote.consumed = True
    trade = Trade(session_id=session.id, idempotency_key=body.idempotency_key, chain=quote.chain,
                  token_address=quote.token_address, side=quote.side, amount_near=quote.amount_near,
                  quote_price=quote.price, status="rejected" if not body.approved else "confirmed_demo")
    db.add(trade)
    if body.approved and quote.side == "buy":
        wallet = await db.scalar(select(DemoWallet).where(DemoWallet.session_id == session.id).with_for_update())
        fee = (quote.amount_near * Decimal("0.003")).quantize(Decimal("0.00000001"))
        if not wallet or wallet.near_balance < quote.amount_near + fee:
            await db.rollback()
            raise HTTPException(422, "Demo balance no longer covers amount and fee")
        wallet.near_balance -= quote.amount_near + fee
        position = await db.scalar(select(Position).where(Position.session_id == session.id, Position.chain == quote.chain,
                                                           Position.token_address == quote.token_address).with_for_update())
        quantity = quote.amount_near / quote.price
        if position:
            old_cost = position.quantity * position.average_price
            position.quantity += quantity
            position.average_price = (old_cost + quote.amount_near) / position.quantity
        else:
            db.add(Position(session_id=session.id, chain=quote.chain, token_address=quote.token_address,
                            quantity=quantity, average_price=quote.price, current_price=quote.price))
    elif body.approved:
        position = await db.scalar(select(Position).where(
            Position.session_id == session.id, Position.chain == quote.chain,
            Position.token_address == quote.token_address,
        ).with_for_update())
        quantity = quote.amount_near / quote.price
        if position is None or position.quantity < quantity:
            await db.rollback()
            raise HTTPException(422, "Demo position changed and no longer covers this sell quote")
        fee = (quote.amount_near * Decimal("0.003")).quantize(Decimal("0.00000001"))
        position.quantity -= quantity
        wallet = await db.scalar(select(DemoWallet).where(DemoWallet.session_id == session.id).with_for_update())
        if wallet is None:
            await db.rollback()
            raise HTTPException(409, "Demo wallet is unavailable")
        wallet.near_balance += quote.amount_near - fee
        if position.quantity == 0:
            await db.delete(position)
    await db.commit()
    await persist_event(db, "trading", "TRADE_CONFIRMED" if body.approved else "TRADE_REJECTED",
                        {"trade_id": str(trade.id), "simulated": True}, session.id, "makto")
    return {"status": trade.status, "trade_id": str(trade.id), "simulated": True, "idempotent_replay": False}


@app.post("/api/trading/scenarios/market-shift")
async def simulate_market_shift(session: BrowserSession = Depends(trading_session), db: AsyncSession = Depends(get_db)):
    """Scenario E: mark open demo positions 25% higher, then alert via Makto and Orion."""
    positions = (await db.scalars(select(Position).where(Position.session_id == session.id).with_for_update())).all()
    eligible = [position for position in positions if (position.chain, position.token_address) in DEMO_MARKETS]
    if not eligible:
        raise HTTPException(409, "Scenario E needs an open demo position. Complete a simulated buy first.")
    shift = Decimal("1.25")
    changes = [{
        "chain": item.chain, "token_address": item.token_address,
        "old_price_near": str(item.current_price or item.average_price),
        "new_price_near": str((item.current_price or item.average_price) * shift),
        "quantity": str(item.quantity),
    } for item in eligible]
    scenario_context = json.dumps({"simulated": True, "change_percent": 25, "positions": changes}, sort_keys=True)
    try:
        makto_text, makto_usage = await generate(
            "trading", "makto",
            "Scenario E: Review these deterministic simulated mark-price changes. Alert the trader that position values changed. "
            "State that this is a simulation and not an executable market quote. Do not claim any transaction occurred. " + scenario_context,
        )
        orion_text, orion_usage = await generate(
            "trading", "orion",
            "Discuss the portfolio change with Makto. State what changed, its simulated nature, and what remains unknown. "
            "Do not recommend a real trade or claim execution.\nMakto alert: " + makto_text + "\nScenario facts: " + scenario_context,
        )
    except ProviderUnavailable as exc:
        raise HTTPException(503, str(exc))
    for item in eligible:
        item.current_price = (item.current_price or item.average_price) * shift
    for agent_id, answer, usage in (("makto", makto_text, makto_usage), ("orion", orion_text, orion_usage)):
        db.add(ConversationMessage(session_id=session.id, department="trading", agent_id=agent_id,
                                   role="assistant", content=answer, simulated=True))
        counts = usage.get("usage") or {}
        db.add(LLMUsage(department="trading", session_id=session.id, agent_id=agent_id,
                        provider=usage["provider"], model=usage["model"],
                        input_tokens=counts.get("promptTokenCount", counts.get("prompt_tokens", counts.get("input_tokens"))),
                        output_tokens=counts.get("candidatesTokenCount", counts.get("completion_tokens", counts.get("output_tokens")))))
    await db.commit()
    await persist_event(db, "trading", "MARKET_ALERT", {"scenario": "market-shift", "simulated": True,
                        "change_percent": 25, "positions": changes, "alert": makto_text}, session.id, "makto")
    await persist_event(db, "trading", "AGENT_MESSAGE", {"content": makto_text, "simulated": True}, session.id, "makto")
    await persist_event(db, "trading", "AGENT_MESSAGE", {"content": orion_text, "simulated": True}, session.id, "orion")
    return {"scenario": "market-shift", "simulated": True, "change_percent": 25, "positions": changes,
            "messages": [makto_text, orion_text]}


@app.get("/api/scenarios")
async def scenarios():
    return {"scenarios": [
        {"id": "suspicious-token", "title": "Suspicious token", "kind": "simulated", "description": "Controlled market, contract and deployer evidence drives a debate."},
        {"id": "potential-opportunity", "title": "Potential opportunity", "kind": "simulated", "description": "A balanced opportunity case with explicit execution and verification limits."},
    ]}


@app.post("/api/scenarios/{scenario_id}/run")
async def run_scenario(scenario_id: str, db: AsyncSession = Depends(get_db)):
    if scenario_id not in {"suspicious-token", "potential-opportunity"}:
        raise HTTPException(404, "Unknown deterministic scenario")
    suspicious = scenario_id == "suspicious-token"
    token = "demo:claw" if suspicious else "demo:signal"
    title = "Suspicious token" if suspicious else "Potential opportunity"
    evidence_fields = ({"fixture": "simulated", "volume_change_pct": 410, "liquidity_change_pct": -62, "verified_contract_source": False}
                       if suspicious else {"fixture": "simulated", "volume_change_pct": 185, "liquidity_usd": None, "verified_contract_source": False})
    evidence = Evidence(department="autonomous", chain="demo", token_address=token,
                        source="deterministic scenario fixture", data_kind="simulated", fields=evidence_fields,
                        limitations="Controlled demo data. Not a live market observation or a contract audit.")
    result = await run_investigation(
        db,
        evidence,
        title=title,
        scenario_id=scenario_id,
        simulated=True,
    )
    if result["status"] != "completed":
        raise HTTPException(503, detail={
            "message": "Scenario evidence was stored, but no complete agent debate was produced. Check provider configuration and retry.",
            "evidence_id": result["evidence_id"],
            "investigation_id": result["investigation_id"],
        })
    return {"scenario": scenario_id, "simulated": True, **result}


@app.websocket("/ws/{department}")
async def websocket_endpoint(websocket: WebSocket, department: str, after: int = 0):
    if department not in {"autonomous", "trading"}:
        await websocket.close(code=1008)
        return
    origin = websocket.headers.get("origin")
    if origin and origin not in settings.cors_origins:
        await websocket.close(code=1008)
        return
    sid = ""
    if department == "trading":
        raw = websocket.cookies.get("claw_session")
        try:
            sid = str(UUID(raw or ""))
        except ValueError:
            await websocket.close(code=1008)
            return
        async with engine.connect() as conn:
            row = (await conn.execute(text("SELECT wallet_connected FROM browser_sessions WHERE id = :sid"), {"sid": UUID(sid)})).first()
        if not row or not row[0]:
            await websocket.close(code=1008)
            return
    await websocket.accept()
    await hub.add(websocket, department, sid)
    try:
        async with AsyncSession(engine) as db:
            events = await recent_events(db, department, UUID(sid) if sid else None, max(after, 0))
        for event in events:
            await websocket.send_json(event)
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                await websocket.send_json({"event_type": "PONG"})
    except WebSocketDisconnect:
        pass
    finally:
        await hub.remove(websocket, department, sid)


frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

    @app.get("/{frontend_path:path}", include_in_schema=False)
    async def frontend_fallback(frontend_path: str):
        candidate = frontend_dist / frontend_path
        if candidate.is_file() and frontend_dist in candidate.resolve().parents:
            return FileResponse(candidate)
        return FileResponse(frontend_dist / "index.html")
