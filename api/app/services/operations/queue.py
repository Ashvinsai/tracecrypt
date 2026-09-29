"""Database-backed leased queue with retries and fenced, atomic result commits.

PostgreSQL uses SKIP LOCKED. SQLite uses one atomic UPDATE .. RETURNING and is
intended for a single worker. No queue state lives only in process memory.
"""
from __future__ import annotations
import asyncio
import datetime as dt
import time
import uuid
from fastapi import HTTPException
from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session
from app.adapters.base import AssetRef, ProviderError
from app.core.settings import Settings
from app.models.casework import AuditEvent, Case
from app.models.chain import Asset, Network
from app.models.enums import CaseFlowLinkage
from app.models.operations import InvestigationJob, OperationSignal
from app.models.unified import InvestigationSnapshot
from app.services.trace_service import run_trace, TraceUnavailable
from app.services.tracecrypt_intelligence import analyze_trace, trace_digest
from .attribution import attribution_summary
from .indexing import index_snapshot

TERMINAL = {"succeeded", "partial", "failed", "blocked", "cancelled"}


def job_json(job: InvestigationJob) -> dict:
    def iso(x): return x.isoformat() if x else None
    return {"id": str(job.id), "case_id": str(job.case_id), "intake_id": str(job.intake_id) if job.intake_id else None,
        "kind": job.kind, "status": job.status, "data_mode": job.data_mode,
        "network_key": job.input_payload.get("network_key"), "address": job.input_payload.get("address"),
        "token_contract": job.input_payload.get("token_contract"), "attempts": job.attempts,
        "max_attempts": job.max_attempts, "created_at": iso(job.created_at), "started_at": iso(job.started_at),
        "finished_at": iso(job.finished_at), "available_at": iso(job.available_at), "lease_until": iso(job.lease_until),
        "duration_ms": job.duration_ms, "run_id": str(job.run_id) if job.run_id else None,
        "error_code": job.error_code, "error_message": job.error_message, "outcome": job.outcome}


def claim(db: Session, settings: Settings, *, organization_id=None, job_id=None, now=None):
    now = now or dt.datetime.now(dt.UTC)
    token = uuid.uuid4().hex
    ready = and_(InvestigationJob.data_mode==settings.data_mode.value,
        InvestigationJob.attempts < InvestigationJob.max_attempts,
        or_(and_(InvestigationJob.status.in_(["queued", "retry"]), InvestigationJob.available_at<=now),
            and_(InvestigationJob.status=="running", InvestigationJob.lease_until<=now)))
    scope = [InvestigationJob.data_mode==settings.data_mode.value]
    if organization_id:
        ready = and_(ready, InvestigationJob.organization_id==organization_id)
        scope.append(InvestigationJob.organization_id==organization_id)
    if job_id:
        ready = and_(ready, InvestigationJob.id==job_id)
        scope.append(InvestigationJob.id==job_id)
    exhausted = and_(*scope, InvestigationJob.status=="running",
        InvestigationJob.lease_until<=now, InvestigationJob.attempts>=InvestigationJob.max_attempts)
    # An idle poll must not reserve SQLite's sole writer lock. Close this probe's
    # read transaction before the atomic conditional claim; the probe is only an
    # optimization, never the authority to acquire a job.
    candidate = db.scalar(select(InvestigationJob.id).where(or_(ready, exhausted)).limit(1))
    db.commit()
    if candidate is None:
        return None
    # A final-attempt crash must not leave a job permanently 'running'.
    db.execute(update(InvestigationJob).where(exhausted)
        .values(status="failed", error_code="lease_expired", error_message="Worker lease expired after the final attempt.",
                finished_at=now, lease_token=None, lease_until=None))
    choice = select(InvestigationJob.id).where(ready).order_by(InvestigationJob.available_at,
        InvestigationJob.created_at, InvestigationJob.id).limit(1)
    if db.get_bind().dialect.name == "postgresql":
        choice = choice.with_for_update(skip_locked=True)
    lease_seconds = max(180, settings.budget_wall_clock_seconds + 120)
    result = db.execute(update(InvestigationJob).where(InvestigationJob.id==choice.scalar_subquery(), ready)
        .values(status="running", attempts=InvestigationJob.attempts+1, lease_token=token,
                lease_until=now+dt.timedelta(seconds=lease_seconds), started_at=now,
                finished_at=None, error_code=None, error_message=None)
        .returning(InvestigationJob.id).execution_options(synchronize_session=False)).scalar_one_or_none()
    db.commit()
    if result is None:
        return None
    db.expire_all()
    return db.get(InvestigationJob, result)


def fence(db: Session, job_id, token, now=None) -> bool:
    now = now or dt.datetime.now(dt.UTC)
    # Acquires the row write lock in the same transaction as the result commit.
    changed = db.execute(update(InvestigationJob).where(InvestigationJob.id==job_id,
        InvestigationJob.status=="running", InvestigationJob.lease_token==token,
        InvestigationJob.lease_until>now).values(lease_token=token)
        .execution_options(synchronize_session=False))
    return changed.rowcount == 1


async def trace_payload(db: Session, settings: Settings, payload: dict) -> dict:
    asset = db.get(Asset, uuid.UUID(payload["asset_id"]))
    network = db.execute(select(Network).where(Network.key==payload["network_key"], Network.is_supported.is_(True))).scalar_one_or_none()
    if not asset or not network or asset.network_id!=network.id or not asset.is_supported or asset.data_mode!=settings.data_mode:
        raise TraceUnavailable("supported asset/network configuration changed since intake")
    if asset.token_contract != payload["token_contract"]:
        raise TraceUnavailable("token identity changed since intake")
    asset_ref = AssetRef(network_key=network.key, token_contract=asset.token_contract,
                         decimals=asset.decimals, display_symbol=asset.display_symbol)
    # Do not hold a read transaction open during network I/O.
    db.commit()
    parse = lambda x: dt.datetime.fromisoformat(x.replace("Z", "+00:00")) if x else None
    result = await run_trace(settings, seed_address=payload["address"], asset=asset_ref,
        seed_event_reference=payload.get("seed_event_reference"),
        analysis_cutoff=parse(payload.get("analysis_cutoff")), analysis_start=parse(payload.get("analysis_start")),
        case_flow_linkage=CaseFlowLinkage.established if payload.get("seed_event_reference") else CaseFlowLinkage.not_established)
    return result.to_json()


def failure(db, job_id, token, code, message, *, retryable, started):
    db.rollback()
    now = dt.datetime.now(dt.UTC)
    if not fence(db, job_id, token, now):
        db.rollback(); return {"id": str(job_id), "status": "lease_lost", "result_discarded": True}
    db.expire_all(); job = db.get(InvestigationJob, job_id)
    retry = retryable and job.attempts < job.max_attempts
    job.status = "retry" if retry else "blocked" if code=="configuration_unavailable" else "failed"
    job.error_code = code; job.error_message = message[:1000]
    job.available_at = now + dt.timedelta(seconds=min(300, 10 * 2**job.attempts))
    job.finished_at = None if retry else now
    job.duration_ms = int((time.monotonic()-started)*1000)
    job.lease_token = None; job.lease_until = None
    db.add(OperationSignal(organization_id=job.organization_id, case_id=job.case_id, job_id=job.id,
        data_mode=job.data_mode, kind="investigation_retry" if retry else "investigation_unresolved",
        priority="review", payload={"error_code": code, "message": message[:1000], "attempt": job.attempts}))
    db.commit(); return job_json(job)


async def process_one(db: Session, settings: Settings, *, organization_id=None, job_id=None) -> dict:
    job = claim(db, settings, organization_id=organization_id, job_id=job_id)
    if job is None:
        return {"status": "idle", "processed": 0}
    ident, token, payload = job.id, job.lease_token, dict(job.input_payload)
    started = time.monotonic()
    try:
        if trace_digest(payload)!=job.input_sha256:
            raise ValueError("job input checksum mismatch")
        case = db.get(Case, job.case_id)
        if not case or case.organization_id!=job.organization_id or case.data_mode.value!=job.data_mode:
            raise ValueError("job tenant or mode mismatch")
        trace = await asyncio.wait_for(trace_payload(db, settings, payload), timeout=settings.budget_wall_clock_seconds+10)
        if trace.get("scope", {}).get("data_mode") != settings.data_mode.value:
            raise ValueError("trace provenance differs from worker mode")
        intelligence = analyze_trace(trace)
        attribution = attribution_summary(trace)
        intelligence = {**intelligence, "attribution_summary": attribution}
        now = dt.datetime.now(dt.UTC)
        if not fence(db, ident, token, now):
            db.rollback(); return {"id": str(ident), "status": "lease_lost", "result_discarded": True}
        db.expire_all(); job = db.get(InvestigationJob, ident); case = db.get(Case, job.case_id)
        snapshot = InvestigationSnapshot(case_id=case.id, created_by=job.created_by,
            data_mode=job.data_mode, input_payload=payload, trace=trace, intelligence=intelligence,
            trace_sha256=trace_digest(trace), intelligence_sha256=trace_digest(intelligence),
            request_id="job-"+str(ident))
        db.add(snapshot); db.flush()
        index = index_snapshot(db, case, snapshot)
        complete = trace.get("scope", {}).get("coverage_status")=="complete_within_scope"
        job.run_id=snapshot.id; job.status="succeeded" if complete else "partial"
        job.finished_at=now; job.duration_ms=int((time.monotonic()-started)*1000)
        job.lease_token=None; job.lease_until=None
        job.outcome={"coverage_status": trace.get("scope", {}).get("coverage_status"),
            "attribution_status": attribution["status"], "nearest_vasps": attribution["nearest_within_observed_scope"],
            "risk": intelligence["risk"], "index": index,
            "interpretation": "Job completion is not successful identity attribution or a fund recovery."}
        kind = "receiving_vasp_observed" if attribution["nearest_within_observed_scope"] else "trace_completed_unresolved"
        db.add(OperationSignal(organization_id=job.organization_id, case_id=case.id, job_id=ident,
            data_mode=job.data_mode, kind=kind, priority="review", payload={"run_id": str(snapshot.id),
                "risk": intelligence["risk"], "coverage_status": trace.get("scope", {}).get("coverage_status"),
                "attribution_status": attribution["status"], "submission": "not_sent"}))
        if not complete:
            db.add(OperationSignal(organization_id=job.organization_id, case_id=case.id, job_id=ident,
                data_mode=job.data_mode, kind="coverage_gap", priority="review",
                payload={"run_id": str(snapshot.id), "limitations": trace.get("limitations", [])}))
        db.add(AuditEvent(organization_id=job.organization_id, actor_user_id=job.created_by,
            action="investigation.job_completed", object_type="investigation_job", object_id=str(ident),
            request_id="job-"+str(ident), audit_metadata={"run_id": str(snapshot.id),
                "trace_sha256": snapshot.trace_sha256, "intelligence_sha256": snapshot.intelligence_sha256,
                "status": job.status, "attempt": job.attempts}))
        db.commit()
        return job_json(job)
    except (ProviderError, TimeoutError) as exc:
        code = "provider_failure" if isinstance(exc, ProviderError) else "time_budget_exceeded"
        return failure(db, ident, token, code, "Provider unavailable or analysis budget exhausted; no complete result asserted.", retryable=True, started=started)
    except TraceUnavailable:
        return failure(db, ident, token, "configuration_unavailable", "Provider, verified seed, token metadata or reviewed labels unavailable. Check configuration and incident scope.", retryable=False, started=started)
    except Exception as exc:
        # Never serialize provider URLs, credentials, complaint input or tracebacks.
        return failure(db, ident, token, "processing_error", f"Investigation failed ({type(exc).__name__}); inspect local validation and configuration.", retryable=False, started=started)
