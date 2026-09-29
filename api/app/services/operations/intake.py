"""Validated, idempotent complaint ingestion and bounded fan-out of trace jobs."""
from __future__ import annotations
import datetime as dt
import hashlib
import secrets
import uuid
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.settings import Settings
from app.models.casework import AuditEvent, Case
from app.models.chain import Asset, Network
from app.models.operations import ComplaintIntake, IntakeCredential, InvestigationJob
from app.services.addresses import canonicalize, AddressValidationError
from app.services.tracecrypt_intelligence import trace_digest
from .contracts import ComplaintPayload

MAX_JOBS_PER_INTAKE = 60
MAX_OPEN_JOBS_PER_ORGANIZATION = 1000


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_credential(db: Session, *, organization_id: uuid.UUID, name: str, source: str, days: int = 30):
    if source not in {"agency_gateway", "ncrp_gateway", "sahyog_gateway", "vasp_gateway"}:
        raise ValueError("unsupported gateway source")
    if not 1 <= days <= 90 or not 1 <= len(name.strip()) <= 120:
        raise ValueError("credential name and 1..90-day expiry are required")
    token = "tcu_" + secrets.token_urlsafe(40)
    row = IntakeCredential(organization_id=organization_id, name=name.strip(), source=source,
        token_hash=token_digest(token), expires_at=dt.datetime.now(dt.UTC)+dt.timedelta(days=days))
    db.add(row); db.flush()
    return row, token


def accepted_jobs(db: Session, *, organization_id, case_id, intake_id=None):
    query = select(InvestigationJob).where(InvestigationJob.organization_id==organization_id,
                                           InvestigationJob.case_id==case_id)
    if intake_id is not None:
        query = query.where(InvestigationJob.intake_id==intake_id)
    return db.execute(query.order_by(InvestigationJob.created_at, InvestigationJob.id)).scalars().all()


def receipt(db: Session, row: ComplaintIntake, *, duplicate=False):
    jobs = accepted_jobs(db, organization_id=row.organization_id, case_id=row.case_id, intake_id=row.id)
    return {"intake_id": str(row.id), "case_id": str(row.case_id), "external_reference": row.external_reference,
        "source": row.source, "data_mode": row.data_mode, "duplicate": duplicate,
        "payload_sha256": row.payload_sha256, "jobs": [{"id": str(j.id), "status": j.status,
            "network_key": j.input_payload.get("network_key"), "token_contract": j.input_payload.get("token_contract")} for j in jobs],
        "scope": "Explicit selected assets, or registered supported assets only; native/internal transfers and unregistered tokens are not searched.",
        "allegation_status": "reported_not_adjudicated", "external_submission": "none"}


def ingest(db: Session, settings: Settings, payload: ComplaintPayload, *, organization_id: uuid.UUID,
           source: str, user_id=None, credential_id=None, request_id="intake") -> dict:
    raw = payload.model_dump(mode="json")
    digest = trace_digest(raw)
    existing = db.execute(select(ComplaintIntake).where(ComplaintIntake.organization_id==organization_id,
        ComplaintIntake.source==source, ComplaintIntake.external_reference==payload.external_reference)).scalar_one_or_none()
    if existing:
        if existing.data_mode != settings.data_mode.value or existing.payload_sha256 != digest:
            raise HTTPException(409, "reference already used with a different payload or data mode; refusing overwrite")
        return receipt(db, existing, duplicate=True)
    cutoff = payload.analysis_cutoff or settings.cutoff
    if payload.incident_start and payload.incident_start > cutoff:
        raise HTTPException(422, "incident_start is later than the analysis cutoff")
    if settings.data_mode.value == "LIVE" and cutoff > dt.datetime.now(dt.UTC) + dt.timedelta(seconds=5):
        raise HTTPException(422, "LIVE analysis cutoff must not be in the future")
    tasks = []
    unique = set()
    for report in payload.wallets:
        network = db.execute(select(Network).where(Network.key==report.network_key,
                                                    Network.is_supported.is_(True))).scalar_one_or_none()
        if not network:
            raise HTTPException(422, "selected network is not registered and supported")
        try:
            address = canonicalize(report.network_key, report.address).canonical
            contract = canonicalize(report.network_key, report.token_contract).canonical if report.token_contract else None
        except AddressValidationError as exc:
            raise HTTPException(422, str(exc)) from exc
        query = select(Asset).where(Asset.network_id==network.id, Asset.is_supported.is_(True),
                                     Asset.data_mode==settings.data_mode)
        if contract:
            query = query.where(Asset.token_contract==contract)
        assets = db.execute(query.order_by(Asset.id)).scalars().all()
        if not assets:
            raise HTTPException(422, "no matching supported assets in this data mode; register reviewed token metadata first")
        if report.seed_event_reference and len(assets) != 1:
            raise HTTPException(422, "a seed event requires one exact token contract")
        for asset in assets:
            if not asset.token_contract:
                continue
            task = {"network_key": network.key, "address": address, "asset_id": str(asset.id),
                "token_contract": asset.token_contract, "seed_event_reference": report.seed_event_reference,
                "mode": "incident" if report.seed_event_reference else "address_discovery",
                "analysis_cutoff": cutoff.isoformat(),
                "analysis_start": payload.incident_start.isoformat() if payload.incident_start else None}
            fingerprint = trace_digest(task)
            if fingerprint not in unique:
                tasks.append(task); unique.add(fingerprint)
    if not tasks or len(tasks) > MAX_JOBS_PER_INTAKE:
        raise HTTPException(422, "intake must produce 1..60 supported token trace jobs; narrow the request")
    pending = db.scalar(select(func.count()).select_from(InvestigationJob).where(
        InvestigationJob.organization_id==organization_id,
        InvestigationJob.status.in_(["queued", "retry", "running"]))) or 0
    if pending + len(tasks) > MAX_OPEN_JOBS_PER_ORGANIZATION:
        raise HTTPException(429, "organization queue capacity reached; retry after current investigations finish")
    now = dt.datetime.now(dt.UTC)
    row = None
    try:
        # A savepoint protects an existing transaction on a racing duplicate.
        with db.begin_nested():
            # Separate from manually entered references; short, deterministic, tenant-specific.
            case_ref = "INTAKE-" + trace_digest({"org": str(organization_id), "source": source,
                                                "ref": payload.external_reference})[:32]
            case = Case(organization_id=organization_id, case_reference=case_ref,
                        title=payload.title, data_mode=settings.data_mode, created_by=user_id)
            db.add(case); db.flush()
            row = ComplaintIntake(organization_id=organization_id, case_id=case.id,
                credential_id=credential_id, source=source, external_reference=payload.external_reference,
                data_mode=settings.data_mode.value, allegation_type=payload.allegation_type,
                payload=raw, payload_sha256=digest)
            db.add(row); db.flush()
            for task in tasks:
                db.add(InvestigationJob(organization_id=organization_id, case_id=case.id, intake_id=row.id,
                    created_by=user_id, data_mode=settings.data_mode.value, input_payload=task,
                    input_sha256=trace_digest(task), available_at=now))
            db.add(AuditEvent(organization_id=organization_id, actor_user_id=user_id,
                action="complaint.intake_accepted", object_type="complaint_intake", object_id=str(row.id),
                request_id=request_id, audit_metadata={"source": source, "payload_sha256": digest,
                    "job_count": len(tasks), "allegation_status": "reported_not_adjudicated"}))
            db.flush()
    except IntegrityError:
        existing = db.execute(select(ComplaintIntake).where(ComplaintIntake.organization_id==organization_id,
            ComplaintIntake.source==source, ComplaintIntake.external_reference==payload.external_reference)).scalar_one_or_none()
        if existing and existing.payload_sha256==digest and existing.data_mode==settings.data_mode.value:
            return receipt(db, existing, duplicate=True)
        raise HTTPException(409, "intake reference conflicted; no duplicate complaint was created") from None
    db.commit()
    return receipt(db, row)
