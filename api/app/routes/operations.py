"""Tenant-authorized complaint automation, queue, intelligence and event ledger."""
from __future__ import annotations
import datetime as dt
import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session
from app.core.authz import AuthorizedCase, CurrentOrganization, CurrentUser
from app.core.envelope import ok
from app.core.settings import AppEnv, Settings, get_settings
from app.db.base import get_db
from app.models.casework import AuditEvent, Case
from app.models.operations import (ComplaintIntake, IntakeCredential, InvestigationJob,
    IndexedInvestigationEvent, OperationSignal)
from app.models.unified import InvestigationSnapshot
from app.routes.unified import _saved
from app.services.addresses import canonicalize, AddressValidationError
from app.services.operations.attribution import attribution_summary
from app.services.operations.contracts import ComplaintPayload
from app.services.operations.indexing import index_snapshot
from app.services.operations.intake import ingest, token_digest
from app.services.operations.queue import job_json, process_one
from app.services.tracecrypt_intelligence import trace_digest

router = APIRouter(prefix="/api/v1", tags=["operations-automation"])
DB = Annotated[Session, Depends(get_db)]
Config = Annotated[Settings, Depends(get_settings)]


def gateway(request: Request, db: DB, settings: Config) -> IntakeCredential:
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer tcu_") or not 45<=len(authorization)<=160:
        raise HTTPException(401, "invalid or expired intake credential")
    row = db.execute(select(IntakeCredential).where(IntakeCredential.token_hash==token_digest(
        authorization[7:]), IntakeCredential.is_active.is_(True),
        IntakeCredential.expires_at>dt.datetime.now(dt.UTC))).scalar_one_or_none()
    if not row:
        raise HTTPException(401, "invalid or expired intake credential")
    if settings.app_env is AppEnv.prod and request.url.scheme!="https":
        raise HTTPException(403, "production intake requires HTTPS via a trusted proxy")
    return row


@router.post("/operations/intakes", status_code=202)
def intake_manual(payload: ComplaintPayload, request: Request, user: CurrentUser,
                  org: CurrentOrganization, db: DB, settings: Config):
    return ok(ingest(db, settings, payload, organization_id=org.id, source="manual",
                    user_id=user.id, request_id=request.state.request_id), settings, request.state.request_id)


@router.post("/integrations/complaints", status_code=202)
def intake_gateway(payload: ComplaintPayload, request: Request, db: DB, settings: Config,
                   credential: Annotated[IntakeCredential, Depends(gateway)]):
    return ok(ingest(db, settings, payload, organization_id=credential.organization_id,
        source=credential.source, credential_id=credential.id, request_id=request.state.request_id),
        settings, request.state.request_id)


@router.get("/operations/jobs")
def jobs(request: Request, org: CurrentOrganization, db: DB, settings: Config,
         state: str | None=None, limit: int=Query(default=100, ge=1, le=200)):
    query = select(InvestigationJob).where(InvestigationJob.organization_id==org.id,
                                           InvestigationJob.data_mode==settings.data_mode.value)
    if state:
        query=query.where(InvestigationJob.status==state)
    rows=db.scalars(query.order_by(InvestigationJob.created_at.desc(), InvestigationJob.id.desc()).limit(limit+1)).all()
    return ok({"jobs": [job_json(j) for j in rows[:limit]], "truncated": len(rows)>limit}, settings, request.state.request_id)


def owned_job(db, org_id, job_id):
    job=db.scalar(select(InvestigationJob).where(InvestigationJob.id==job_id,
                                                InvestigationJob.organization_id==org_id))
    if not job:
        raise HTTPException(404, "job not found")
    return job


@router.get("/operations/jobs/{job_id}")
def job_detail(job_id: uuid.UUID, request: Request, org: CurrentOrganization, db: DB, settings: Config):
    return ok(job_json(owned_job(db, org.id, job_id)), settings, request.state.request_id)


@router.post("/operations/process-next")
async def process_next(request: Request, user: CurrentUser, org: CurrentOrganization, db: DB, settings: Config):
    if settings.app_env is AppEnv.prod:
        raise HTTPException(409, "run operations_worker.py for production queue processing")
    return ok(await process_one(db, settings, organization_id=org.id), settings, request.state.request_id)


@router.post("/operations/jobs/{job_id}/retry")
def retry(job_id: uuid.UUID, request: Request, user: CurrentUser, org: CurrentOrganization, db: DB, settings: Config):
    job=owned_job(db, org.id, job_id)
    if job.data_mode!=settings.data_mode.value:
        raise HTTPException(409, "job belongs to a different data mode")
    if job.status not in {"failed", "blocked"}:
        raise HTTPException(409, "only failed or blocked jobs can be retried; running or saved jobs cannot be duplicated")
    previous=job.attempts
    job.status="queued"; job.attempts=0; job.available_at=dt.datetime.now(dt.UTC)
    job.error_code=None; job.error_message=None; job.lease_token=None; job.lease_until=None
    db.add(AuditEvent(organization_id=org.id, actor_user_id=user.id, action="investigation.job_requeued",
        object_type="investigation_job", object_id=str(job.id), request_id=request.state.request_id,
        audit_metadata={"prior_attempts": previous, "input_sha256": job.input_sha256}))
    db.commit()
    return ok(job_json(job), settings, request.state.request_id)


@router.post("/operations/jobs/{job_id}/cancel")
def cancel(job_id: uuid.UUID, request: Request, user: CurrentUser, org: CurrentOrganization, db: DB, settings: Config):
    job=owned_job(db, org.id, job_id)
    changed=db.execute(update(InvestigationJob).where(InvestigationJob.id==job.id,
        InvestigationJob.status.in_(["queued", "retry", "running"]))
        .values(status="cancelled", lease_token=None, lease_until=None, finished_at=dt.datetime.now(dt.UTC)))
    if not changed.rowcount:
        raise HTTPException(409, "job already finished; existing evidence is not deleted")
    db.add(AuditEvent(organization_id=org.id, actor_user_id=user.id, action="investigation.job_cancelled",
        object_type="investigation_job", object_id=str(job.id), request_id=request.state.request_id, audit_metadata={}))
    db.commit(); db.refresh(job)
    return ok(job_json(job), settings, request.state.request_id)


@router.get("/operations/overview")
def overview(request: Request, org: CurrentOrganization, db: DB, settings: Config):
    counts=dict(db.execute(select(InvestigationJob.status, func.count()).where(
        InvestigationJob.organization_id==org.id, InvestigationJob.data_mode==settings.data_mode.value)
        .group_by(InvestigationJob.status)).all())
    runtimes=db.execute(select(func.count(InvestigationJob.duration_ms), func.avg(InvestigationJob.duration_ms),
        func.max(InvestigationJob.duration_ms)).where(InvestigationJob.organization_id==org.id,
            InvestigationJob.data_mode==settings.data_mode.value, InvestigationJob.status.in_(["succeeded", "partial"]))).one()
    signals=db.scalar(select(func.count()).select_from(OperationSignal).where(OperationSignal.organization_id==org.id,
        OperationSignal.data_mode==settings.data_mode.value, OperationSignal.acknowledged_at.is_(None))) or 0
    indexed=db.scalar(select(func.count()).select_from(IndexedInvestigationEvent).where(
        IndexedInvestigationEvent.organization_id==org.id, IndexedInvestigationEvent.data_mode==settings.data_mode.value)) or 0
    return ok({"data_mode": settings.data_mode.value, "job_counts": counts,
        "observed_processing_ms": {"completed_sample_count": runtimes[0], "mean": round(runtimes[1], 2) if runtimes[1] is not None else None,
            "maximum": runtimes[2], "note": "Measured worker durations in this database, not a production SLA."},
        "unacknowledged_signals": signals, "indexed_observations": indexed,
        "index_scope": "Exact saved-run observations, not all blockchain activity.",
        "government_connections": {"NCRP": "authorized_gateway_mapping_required", "SAHYOG": "authorized_gateway_mapping_required"},
        "outbound_submission": "disabled; investigator-reviewed packages only"}, settings, request.state.request_id)


@router.get("/operations/signals")
def signals(request: Request, org: CurrentOrganization, db: DB, settings: Config,
            after: int=Query(default=0, ge=0), limit: int=Query(default=100, ge=1, le=200), latest: bool=False):
    rows=db.scalars(select(OperationSignal).where(OperationSignal.organization_id==org.id,
        OperationSignal.data_mode==settings.data_mode.value, OperationSignal.id>after)
        .order_by(OperationSignal.id.desc() if latest else OperationSignal.id).limit(limit+1)).all()
    items=[{"id": r.id, "kind": r.kind, "priority": r.priority, "case_id": str(r.case_id),
        "job_id": str(r.job_id) if r.job_id else None, "data_mode": r.data_mode, "payload": r.payload,
        "created_at": r.created_at.isoformat(), "acknowledged_at": r.acknowledged_at.isoformat() if r.acknowledged_at else None} for r in rows[:limit]]
    return ok({"signals": items, "next_cursor": max((item["id"] for item in items), default=after), "has_more": len(rows)>limit,
        "ordering": "newest_snapshot" if latest else "chronological_cursor",
        "note": "latest=true is a bounded recent snapshot; use chronological cursor order to retrieve every signal."}, settings, request.state.request_id)


@router.post("/operations/signals/{signal_id}/acknowledge")
def acknowledge(signal_id: int, request: Request, user: CurrentUser, org: CurrentOrganization, db: DB, settings: Config):
    row=db.scalar(select(OperationSignal).where(OperationSignal.id==signal_id, OperationSignal.organization_id==org.id))
    if not row:
        raise HTTPException(404, "signal not found")
    if row.acknowledged_at is None:
        row.acknowledged_at=dt.datetime.now(dt.UTC); row.acknowledged_by=user.id
        db.add(AuditEvent(organization_id=org.id, actor_user_id=user.id, action="operation.signal_acknowledged",
            object_type="operation_signal", object_id=str(row.id), request_id=request.state.request_id, audit_metadata={}))
        db.commit()
    return ok({"id": row.id, "acknowledged_at": row.acknowledged_at.isoformat()}, settings, request.state.request_id)


@router.get("/operations/events")
def events(request: Request, org: CurrentOrganization, db: DB, settings: Config,
           network_key: str | None=None, address: str | None=None, case_id: uuid.UUID | None=None,
           after: int=Query(default=0, ge=0), limit: int=Query(default=100, ge=1, le=500)):
    query=select(IndexedInvestigationEvent).where(IndexedInvestigationEvent.organization_id==org.id,
        IndexedInvestigationEvent.data_mode==settings.data_mode.value, IndexedInvestigationEvent.id>after)
    if case_id:
        query=query.where(IndexedInvestigationEvent.case_id==case_id)
    if network_key:
        query=query.where(IndexedInvestigationEvent.network_key==network_key)
    if address:
        if not network_key:
            raise HTTPException(422, "address search requires an explicit network")
        try:
            addr=canonicalize(network_key, address).canonical
        except AddressValidationError as exc:
            raise HTTPException(422, str(exc)) from exc
        query=query.where(or_(IndexedInvestigationEvent.from_address==addr, IndexedInvestigationEvent.to_address==addr))
    rows=db.scalars(query.order_by(IndexedInvestigationEvent.id).limit(limit+1)).all()
    result=[]
    for row in rows[:limit]:
        if trace_digest(row.observed)!=row.observed_sha256:
            raise HTTPException(409, "indexed observation checksum mismatch")
        result.append({"id": row.id, "case_id": str(row.case_id), "run_id": str(row.run_id),
            "network_key": row.network_key, "data_mode": row.data_mode, "event": row.observed,
            "sha256": row.observed_sha256})
    return ok({"observations": result, "next_cursor": result[-1]["id"] if result else after,
        "has_more": len(rows)>limit, "scope": "Versioned saved-run observations; repeats across runs are not additional unique transfers."}, settings, request.state.request_id)


@router.get("/cases/{case_id}/investigations/{run_id}/attribution")
def attribution(run_id: uuid.UUID, request: Request, case: AuthorizedCase, db: DB, settings: Config):
    row=_saved(db, case, run_id)
    return ok(attribution_summary(row.trace), settings, request.state.request_id)


@router.post("/cases/{case_id}/investigations/{run_id}/index")
def index(run_id: uuid.UUID, request: Request, case: AuthorizedCase, user: CurrentUser, db: DB, settings: Config):
    row=_saved(db, case, run_id)
    outcome=index_snapshot(db, case, row)
    db.add(AuditEvent(organization_id=case.organization_id, actor_user_id=user.id,
        action="investigation.indexed", object_type="investigation", object_id=str(row.id),
        request_id=request.state.request_id, audit_metadata=outcome))
    db.commit()
    return ok(outcome, settings, request.state.request_id)


@router.get("/operations/audit")
def audit(request: Request, org: CurrentOrganization, db: DB, settings: Config,
          limit: int=Query(default=100, ge=1, le=300)):
    rows=db.scalars(select(AuditEvent).where(AuditEvent.organization_id==org.id)
        .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc()).limit(limit+1)).all()
    return ok({"events": [{"id": str(r.id), "action": r.action, "object_type": r.object_type,
        "object_id": r.object_id, "request_id": r.request_id, "occurred_at": r.occurred_at.isoformat(),
        "metadata": r.audit_metadata} for r in rows[:limit]], "truncated": len(rows)>limit,
        "integrity_note": "Application audit trail. External immutable storage/signing is not configured."}, settings, request.state.request_id)


@router.get('/operations/ml-ranking')
def ml_ranking(request: Request, org: CurrentOrganization, db: DB, settings: Config,
               network_key: str, token_contract: str):
    """Optional bounded ML graph ranking, never an ownership or guilt label."""
    from app.services.operations.ml import rank_cohort
    try:
        token_contract=canonicalize(network_key,token_contract).canonical
    except AddressValidationError as exc:
        raise HTTPException(422,str(exc)) from exc
    snapshots=db.scalars(select(InvestigationSnapshot).join(Case,Case.id==InvestigationSnapshot.case_id)
        .where(Case.organization_id==org.id,InvestigationSnapshot.data_mode==settings.data_mode.value)
        .order_by(InvestigationSnapshot.created_at.desc(),InvestigationSnapshot.id.desc()).limit(501)).all()
    result=rank_cohort([{"run_id":str(r.id),"case_id":str(r.case_id),"created_at":r.created_at.isoformat(),
        "trace":r.trace,"trace_sha256":r.trace_sha256} for r in snapshots[:500]],network_key=network_key,
        token_contract=token_contract,data_mode=settings.data_mode.value)
    result['selection_scope']='Most recent 500 saved snapshots in this organization and mode; filtered to the selected network/token.'
    result['snapshot_scan_truncated']=len(snapshots)>500
    return ok(result,settings,request.state.request_id)


from app.services.operations.cctp import CctpRequest


def crosschain_json(row):
    return {'id':str(row.id),'case_id':str(row.case_id),'status':row.status,'data_mode':row.data_mode,
        'created_at':row.created_at.isoformat(),'input':row.input_payload,'bundle_sha256':row.bundle_sha256,
        'result':row.evidence_bundle.get('result'),
        'continuation_job_id':str(row.continuation_job_id) if row.continuation_job_id else None}


@router.post('/cases/{case_id}/cross-chain/cctp',status_code=201)
async def check_cctp(payload: CctpRequest, case: AuthorizedCase, request: Request, user: CurrentUser,
                     db: DB, settings: Config):
    import asyncio
    import httpx
    from app.models.operations import CrossChainReview
    from app.services.operations.cctp import acquire,EvidenceRejected
    if settings.data_mode.value!='LIVE' or case.data_mode.value!='LIVE':
        raise HTTPException(409,'Live protocol checks require a LIVE case and LIVE server. The recorded demo is separate.')
    if not settings.ethereum_rpc_url or not settings.base_rpc_url:
        raise HTTPException(409,'Configure both Ethereum and Base RPC providers before live protocol checks.')
    case_id,org_id,user_id=case.id,case.organization_id,user.id
    db.commit() # Do not hold a read transaction open while making provider requests.
    partial={}
    try:
        async with asyncio.timeout(150):bundle=await acquire(settings,payload,partial=partial)
    except EvidenceRejected as exc:
        bundle={'result':{'status':'unresolved_evidence_check','reason':str(exc),'data_mode':'LIVE',
            'attestation_signature_verified':False},**partial,
            'limitation':'This rejected attempt retains only the provider responses acquired before failure. It is not a completed protocol evidence bundle.'}
    except (httpx.HTTPError,TimeoutError,ValueError,TypeError,KeyError) as exc:
        bundle={'result':{'status':'provider_or_decoding_failure','error_class':type(exc).__name__,
            'reason':'Provider acquisition or decoding failed. No cross-chain match was established.','data_mode':'LIVE'},
            **partial}
    row=CrossChainReview(organization_id=org_id,case_id=case_id,created_by=user_id,data_mode='LIVE',
        status=bundle['result']['status'],input_payload=payload.model_dump(mode='json'),evidence_bundle=bundle,
        bundle_sha256=trace_digest(bundle))
    db.add(row);db.flush()
    db.add(AuditEvent(organization_id=org_id,actor_user_id=user_id,action='cross_chain.checked',object_type='cross_chain_review',
        object_id=str(row.id),request_id=request.state.request_id,audit_metadata={'status':row.status,'bundle_sha256':row.bundle_sha256}))
    db.add(OperationSignal(organization_id=org_id,case_id=case_id,data_mode='LIVE',kind='cross_chain_review_saved',
        priority='review',payload={'review_id':str(row.id),'status':row.status}))
    db.commit();db.refresh(row)
    return ok(crosschain_json(row),settings,request.state.request_id)


@router.get('/cases/{case_id}/cross-chain')
def list_cctp(case: AuthorizedCase, request: Request, db: DB, settings: Config):
    from app.models.operations import CrossChainReview
    rows=db.scalars(select(CrossChainReview).where(CrossChainReview.case_id==case.id,
        CrossChainReview.organization_id==case.organization_id).order_by(CrossChainReview.created_at.desc()).limit(101)).all()
    for row in rows:
        if trace_digest(row.evidence_bundle)!=row.bundle_sha256:raise HTTPException(409,'Saved cross-chain evidence hash mismatch.')
    return ok({'reviews':[crosschain_json(r) for r in rows[:100]],'truncated':len(rows)>100},settings,request.state.request_id)


def checked_review(db,case,review_id):
    from app.models.operations import CrossChainReview
    row=db.scalar(select(CrossChainReview).where(CrossChainReview.id==review_id,CrossChainReview.case_id==case.id,
        CrossChainReview.organization_id==case.organization_id))
    if not row:raise HTTPException(404,'Protocol review not found.')
    if trace_digest(row.evidence_bundle)!=row.bundle_sha256:raise HTTPException(409,'Saved cross-chain evidence hash mismatch.')
    return row


@router.get('/cases/{case_id}/cross-chain/{review_id}/evidence')
def crosschain_evidence(review_id: uuid.UUID, case: AuthorizedCase, request: Request, db: DB, settings: Config):
    row=checked_review(db,case,review_id)
    return ok({'review':crosschain_json(row),'evidence_bundle':row.evidence_bundle,
        'integrity_note':'SHA256 detects changes relative to the saved hash; it is not an externally signed chain of custody.'},settings,request.state.request_id)


@router.post('/cases/{case_id}/cross-chain/{review_id}/continue',status_code=202)
def continue_cctp(review_id: uuid.UUID, case: AuthorizedCase, request: Request, user: CurrentUser,db: DB, settings: Config):
    from app.models.chain import Asset,Network
    row=checked_review(db,case,review_id)
    if row.data_mode!=settings.data_mode.value or row.status!='matched_finalized_provider_evidence':
        raise HTTPException(409,'Only a matched protocol review in the current data mode can continue.')
    if row.continuation_job_id:
        return ok(job_json(owned_job(db,case.organization_id,row.continuation_job_id)),settings,request.state.request_id)
    result=row.evidence_bundle['result']
    network=db.scalar(select(Network).where(Network.key=='base'))
    asset=db.scalar(select(Asset).where(Asset.network_id==network.id,Asset.token_contract==result['destination_token_contract'],
        Asset.data_mode==settings.data_mode,Asset.is_supported.is_(True))) if network else None
    if not asset:raise HTTPException(409,'Register official Base USDC in the LIVE asset catalog before continuing.')
    now=dt.datetime.now(dt.UTC)
    input_payload={'network_key':'base','asset_id':str(asset.id),'token_contract':asset.token_contract,'address':result['destination_recipient'],'mode':'address_discovery',
        'seed_event_reference':None,'analysis_start':result['destination_block_time'],'analysis_cutoff':now.isoformat(),
        'protocol_review_id':str(row.id),'linkage_note':'Recipient address discovery after verified protocol mint, not a victim-fund allocation.'}
    job=InvestigationJob(organization_id=case.organization_id,case_id=case.id,created_by=user.id,data_mode=settings.data_mode.value,
        kind='trace',status='queued',input_payload=input_payload,input_sha256=trace_digest(input_payload),available_at=now)
    db.add(job);db.flush()
    # Atomic claim prevents duplicate continuation jobs on concurrent requests.
    from app.models.operations import CrossChainReview
    changed=db.execute(update(CrossChainReview).where(CrossChainReview.id==row.id,CrossChainReview.continuation_job_id.is_(None))
        .values(continuation_job_id=job.id))
    if not changed.rowcount:
        db.rollback();raise HTTPException(409,'A concurrent request already queued this continuation; reload the review.')
    db.add(AuditEvent(organization_id=case.organization_id,actor_user_id=user.id,action='cross_chain.continuation_queued',
        object_type='investigation_job',object_id=str(job.id),request_id=request.state.request_id,
        audit_metadata={'protocol_review_id':str(row.id)}))
    db.commit();db.refresh(job)
    return ok(job_json(job),settings,request.state.request_id)
