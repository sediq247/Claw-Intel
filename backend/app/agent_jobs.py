"""PostgreSQL-backed autonomous investigation queue with leases and retries."""
import asyncio
import hashlib
import logging
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import case, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .database import SessionFactory
from .models import AgentJob, AutonomousSchedule, Evidence, Investigation
from .orchestration import run_investigation
from .services import persist_event

logger = logging.getLogger(__name__)
LEASE_DURATION = timedelta(minutes=3)
RECLAIM_INTERVAL_SECONDS = 30
HEARTBEAT_INTERVAL_SECONDS = 30


def retry_delay_seconds(attempt: int) -> int:
    return min(60 * (2 ** max(0, attempt - 1)), 900)


def auto_scan_dedupe_key(chain: str, address: str, window: int) -> str:
    stable = f"{chain.strip().lower()}:{address.strip().lower()}:{window}"
    return "scan:" + hashlib.sha256(stable.encode("utf-8")).hexdigest()


async def enqueue_investigation_job(
    db: AsyncSession,
    evidence: Evidence,
    *,
    title: str,
    user_request: str,
    dedupe_key: str,
    simulated: bool = False,
) -> AgentJob:
    job = AgentJob(
        job_type="investigation",
        dedupe_key=dedupe_key[:128],
        payload={
            "evidence_id": str(evidence.id),
            "title": title[:200],
            "user_request": user_request[:2500],
            "simulated": simulated,
        },
    )
    db.add(job)
    try:
        await db.commit()
        await persist_event(db, "autonomous", "AGENT_JOB_QUEUED", {
            "job_id": str(job.id), "evidence_id": str(evidence.id), "title": title[:200],
        })
        return job
    except IntegrityError:
        await db.rollback()
        existing = await db.scalar(select(AgentJob).where(AgentJob.dedupe_key == dedupe_key[:128]))
        if existing is None:
            raise
        return existing


async def _reclaim_expired_jobs(db: AsyncSession, now: datetime) -> None:
    await db.execute(
        update(AgentJob)
        .where(AgentJob.status == "processing", AgentJob.locked_at < now - LEASE_DURATION)
        .values(
            status=case((AgentJob.attempts < AgentJob.max_attempts, "retrying"), else_="dead"),
            available_at=now,
            locked_at=None,
            last_error="Worker lease expired before completion",
            updated_at=now,
        )
    )


async def _claim_job(reclaim_expired: bool = False) -> tuple[UUID, str, dict, int, int] | None:
    now = datetime.now(timezone.utc)
    async with SessionFactory() as db:
        schedule = await db.scalar(select(AutonomousSchedule).where(AutonomousSchedule.id == 1).with_for_update())
        if schedule is not None and schedule.phase != "working":
            await db.commit()
            return None
        if reclaim_expired:
            await _reclaim_expired_jobs(db, now)
        job = await db.scalar(
            select(AgentJob)
            .where(AgentJob.status.in_(("queued", "retrying")), AgentJob.available_at <= now)
            .order_by(AgentJob.available_at, AgentJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            await db.commit()
            return None
        job.status = "processing"
        job.attempts += 1
        job.locked_at = now
        job.updated_at = now
        claim = (job.id, job.job_type, dict(job.payload), job.attempts, job.max_attempts)
        await db.commit()
        return claim


async def _execute_investigation(payload: dict) -> dict:
    evidence_id = UUID(str(payload["evidence_id"]))
    async with SessionFactory() as db:
        evidence = await db.get(Evidence, evidence_id)
        if evidence is None:
            raise ValueError("Queued investigation evidence no longer exists")
        if evidence.investigation_id:
            prior = await db.get(Investigation, evidence.investigation_id)
            if prior is not None and prior.status == "completed":
                return {"investigation_id": str(prior.id), "status": "completed", "recovered": True}
        return await run_investigation(
            db,
            evidence,
            title=str(payload.get("title") or "Market investigation"),
            user_request=str(payload.get("user_request") or ""),
            simulated=bool(payload.get("simulated", False)),
            reuse_active=True,
        )


async def _finish_job(job_id: UUID, attempts: int, max_attempts: int,
                      result: dict | None = None, error_type: str | None = None) -> None:
    now = datetime.now(timezone.utc)
    partial = result is not None and result.get("status") != "completed"
    should_retry = (error_type is not None or partial) and attempts < max_attempts
    async with SessionFactory() as db:
        job = await db.get(AgentJob, job_id)
        if job is None:
            return
        job.result = result
        job.last_error = error_type or ("Investigation returned partial results" if partial else None)
        job.locked_at = None
        job.updated_at = now
        if should_retry:
            job.status = "retrying"
            job.available_at = now + timedelta(seconds=retry_delay_seconds(attempts))
        elif error_type is not None or partial:
            job.status = "dead"
            job.completed_at = now
        else:
            job.status = "completed"
            job.completed_at = now
        await db.commit()
        await persist_event(db, "autonomous", "AGENT_JOB_STATUS", {
            "job_id": str(job.id), "status": job.status, "attempts": job.attempts,
            "result_status": (result or {}).get("status"), "error_type": error_type,
        })


async def _heartbeat(job_id: UUID, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=HEARTBEAT_INTERVAL_SECONDS)
            return
        except asyncio.TimeoutError:
            pass
        now = datetime.now(timezone.utc)
        async with SessionFactory() as db:
            job = await db.get(AgentJob, job_id)
            if job is None or job.status != "processing":
                return
            job.locked_at = now
            job.updated_at = now
            await db.commit()


async def agent_job_worker_loop(stop: asyncio.Event) -> None:
    """Claim jobs with SKIP LOCKED so multiple replicas can safely share the queue."""
    last_reclaim = 0.0
    while not stop.is_set():
        try:
            reclaim_expired = time.monotonic() - last_reclaim >= RECLAIM_INTERVAL_SECONDS
            if reclaim_expired:
                last_reclaim = time.monotonic()
            claim = await _claim_job(reclaim_expired)
            if claim is None:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=1.5)
                except asyncio.TimeoutError:
                    pass
                continue
            job_id, job_type, payload, attempts, max_attempts = claim
            heartbeat_stop = asyncio.Event()
            heartbeat = asyncio.create_task(_heartbeat(job_id, heartbeat_stop))
            try:
                if job_type != "investigation":
                    raise ValueError("Unsupported agent job type")
                result = await _execute_investigation(payload)
                heartbeat_stop.set()
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
                await _finish_job(job_id, attempts, max_attempts, result=result)
            except asyncio.CancelledError:
                heartbeat_stop.set()
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
                raise
            except Exception as exc:
                heartbeat_stop.set()
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
                logger.error("Agent job failed (%s)", type(exc).__name__)
                await _finish_job(job_id, attempts, max_attempts, error_type=type(exc).__name__)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Agent job queue unavailable (%s)", type(exc).__name__)
            try:
                await asyncio.wait_for(stop.wait(), timeout=3)
            except asyncio.TimeoutError:
                pass
