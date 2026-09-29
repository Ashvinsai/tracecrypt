"""One combined API: CFA tracing/evidence + TraceCrypt investigative workflows.

All case reads/writes use server-side organization authorization. Saved-run
exports never make new provider calls. Demonstration APIs are separate and
unregistered in production. No endpoint sends a government/VASP request.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import io
import json
import uuid
import zipfile
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.authz import AuthorizedCase, CurrentOrganization, CurrentUser
from app.core.envelope import ok
from app.core.settings import Settings, get_settings
from app.db.base import get_db
from app.models.casework import AuditEvent, Case
from app.models.chain import Asset, Network
from app.models.unified import InvestigationSnapshot
from app.reports.evidence import render_evidence_html
from app.reports.fund_flow import build_fund_flow
from app.reports.legal_request import render_request_draft_html
from app.routes.traces import TraceRequest, _resolve_asset, _trace
from app.routes.watches import _case_watch
from app.services.demo_presets import preset_by_id, load_preset, summarize_presets
from app.services.evidence_export import build_evidence_bundle, EvidenceExportError
from app.services.legal_requests import build_request_draft, RequestDraftError
from app.services.monitoring import poll_watch, MonitoringError
from app.services.trace_service import build_adapter, TraceUnavailable
from app.services.tracecrypt_intelligence import analyze_trace, correlate_traces, trace_digest, VERSION

router = APIRouter(prefix="/api/v1", tags=["unified-workspace"])
demo_router = APIRouter(prefix="/api/v1/workspace/demo", tags=["local-demo-only"])


class InvestigationRequest(TraceRequest):
    address: str = Field(min_length=1, max_length=128)
    seed_event_reference: str | None = Field(default=None, max_length=256)
    token_contract: str | None = Field(default=None, max_length=128)

    @field_validator("analysis_cutoff")
    @classmethod
    def aware_cutoff(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("analysis_cutoff must include a timezone")
        return value


class SavedDraftRequest(BaseModel):
    request_kind: str
    target_address: str = Field(min_length=1, max_length=128)
    requesting_agency: str = Field(min_length=1, max_length=200)
    requesting_officer: str = Field(min_length=1, max_length=200)
    alleged_incident_summary: str = Field(min_length=1, max_length=5000)
    legal_authority_reference: str | None = Field(default=None, max_length=1000)
    exchange_account_identifiers: str | None = Field(default=None, max_length=1000)


def _audit(db, case, user, request, action, object_id, **metadata):
    db.add(AuditEvent(organization_id=case.organization_id, actor_user_id=user.id,
                     action=action, object_type="investigation", object_id=str(object_id),
                     request_id=request.state.request_id, audit_metadata=metadata))


def _saved(db: Session, case: Case, run_id: uuid.UUID) -> InvestigationSnapshot:
    row = db.execute(select(InvestigationSnapshot).where(
        InvestigationSnapshot.id == run_id, InvestigationSnapshot.case_id == case.id
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "investigation not found")
    if trace_digest(row.trace) != row.trace_sha256 or trace_digest(row.intelligence) != row.intelligence_sha256:
        raise HTTPException(409, "saved investigation checksum mismatch; refusing export or analysis")
    return row


def _summary(row: InvestigationSnapshot) -> dict[str, Any]:
    return {"id": str(row.id), "case_id": str(row.case_id), "created_at": row.created_at.isoformat(),
            "data_mode": row.data_mode, "seed": row.trace.get("seed"),
            "coverage_status": row.trace.get("scope", {}).get("coverage_status"),
            "risk": row.intelligence.get("risk"), "trace_sha256": row.trace_sha256,
            "intelligence_sha256": row.intelligence_sha256}


def _detail(row: InvestigationSnapshot) -> dict[str, Any]:
    return {**_summary(row), "trace": row.trace, "intelligence": row.intelligence,
            "graph": build_fund_flow(row.trace).to_json(), "integrity_verified": True}


def _result_envelope(data, trace, settings, request):
    envelope = ok(data, settings, request.state.request_id)
    # Historical/saved content reports its own mode/cutoff, not the process's.
    for field in ("data_mode", "analysis_cutoff", "engine_version", "label_set_version"):
        value = trace.get("scope", {}).get(field)
        if value is not None:
            envelope["meta"][field] = value
    return envelope


@router.get("/workspace/config")
def config(request: Request, db: Annotated[Session, Depends(get_db)],
           settings: Annotated[Settings, Depends(get_settings)]):
    networks = db.execute(select(Network).order_by(Network.key)).scalars().all()
    assets = db.execute(select(Asset)).scalars().all()
    return ok({"name": "TraceCrypt Unified", "version": VERSION,
        "data_mode": settings.data_mode.value,
        "networks": [{"key": n.key, "name": n.display_name, "supported": n.is_supported,
                      "assets": [{"id": str(a.id), "contract": a.token_contract,
                                  "symbol": a.display_symbol, "decimals": a.decimals,
                                  "data_mode": a.data_mode.value}
                                 for a in assets if a.network_id == n.id and a.is_supported
                                 and a.data_mode == settings.data_mode]}
                     for n in networks],
        "connectors": {"NCRP": "not_configured", "SAHYOG": "not_configured", "VASP_submission": "draft_only"},
        "monitoring": "bounded manual polling and optional foreground scheduler; not a mempool feed",
        "provider_configured": {"tron": bool(settings.tron_api_key),
                                "ethereum": bool(settings.ethereum_rpc_url),
                                "bsc": bool(settings.bsc_rpc_url), "base": bool(settings.base_rpc_url)},
    }, settings, request.state.request_id)


@demo_router.get("")
def demo_list(request: Request, settings: Annotated[Settings, Depends(get_settings)]):
    return ok(summarize_presets(), settings, request.state.request_id)


@demo_router.get("/{preset_id}")
def demo_detail(preset_id: str, request: Request, settings: Annotated[Settings, Depends(get_settings)]):
    preset = preset_by_id(preset_id)
    if preset is None:
        raise HTTPException(404, "unknown allow-listed demonstration")
    view = load_preset(preset)
    if not view.trace:
        raise HTTPException(404, view.error or "saved trace unavailable")
    # Never rewrite historical evidence to pretend it was generated by this build.
    envelope = _result_envelope({"id": None, "preset_id": preset.id, "title": preset.title,
        "trace": view.trace, "graph": build_fund_flow(view.trace).to_json(),
        "intelligence": analyze_trace(view.trace), "historical_capture": True,
        "display_data_mode": view.data_mode, "warnings": view.warnings,
        "note": "Saved demonstration. Historical captures are not a new live verification or a case record."},
        view.trace, settings, request)
    envelope["meta"]["data_mode"] = view.data_mode
    return envelope


@router.post("/cases/{case_id}/investigations", status_code=201)
async def investigate(payload: InvestigationRequest, request: Request, case: AuthorizedCase,
                      user: CurrentUser, db: Annotated[Session, Depends(get_db)],
                      settings: Annotated[Settings, Depends(get_settings)]):
    if case.data_mode != settings.data_mode:
        raise HTTPException(409, "case data mode differs from this process; do not mix synthetic and real evidence")
    network = db.execute(select(Network).where(Network.key == payload.network_key)).scalar_one_or_none()
    if network is None or not network.is_supported:
        raise HTTPException(422, "unsupported network")
    asset = _resolve_asset(db, network, payload)
    if asset.data_mode != settings.data_mode:
        raise HTTPException(422, "asset provenance differs from this process data mode")
    try:
        result = await asyncio.wait_for(_trace(db, settings, payload),
                                        timeout=settings.budget_wall_clock_seconds + 10)
    except TimeoutError as exc:
        raise HTTPException(504, "investigation timed out; no complete result was saved") from exc
    intelligence = analyze_trace(result)
    from app.services.operations.attribution import attribution_summary
    intelligence["attribution_summary"] = attribution_summary(result)
    row = InvestigationSnapshot(case_id=case.id, created_by=user.id,
        data_mode=settings.data_mode.value, input_payload=payload.model_dump(mode="json"),
        trace=result, intelligence=intelligence, trace_sha256=trace_digest(result),
        intelligence_sha256=trace_digest(intelligence), request_id=request.state.request_id)
    db.add(row)
    db.flush()
    from app.services.operations.indexing import index_snapshot
    index_snapshot(db, case, row)
    _audit(db, case, user, request, "investigation.created", row.id, trace_sha256=row.trace_sha256)
    db.commit()
    db.refresh(row)
    return _result_envelope(_detail(row), result, settings, request)


@router.get("/cases/{case_id}/investigations")
def investigations(request: Request, case: AuthorizedCase, db: Annotated[Session, Depends(get_db)],
                   settings: Annotated[Settings, Depends(get_settings)]):
    rows = db.execute(select(InvestigationSnapshot).where(InvestigationSnapshot.case_id == case.id)
                      .order_by(InvestigationSnapshot.created_at.desc(), InvestigationSnapshot.id.desc()).limit(201)).scalars().all()
    return ok({"runs": [_summary(r) for r in rows[:200]], "truncated": len(rows) > 200}, settings, request.state.request_id)


@router.get("/cases/{case_id}/investigations/{run_id}")
def investigation(run_id: uuid.UUID, request: Request, case: AuthorizedCase,
                  db: Annotated[Session, Depends(get_db)], settings: Annotated[Settings, Depends(get_settings)]):
    row = _saved(db, case, run_id)
    return _result_envelope(_detail(row), row.trace, settings, request)


@router.get("/cases/{case_id}/investigations/{run_id}/report", response_class=HTMLResponse)
def report(run_id: uuid.UUID, request: Request, case: AuthorizedCase,
           db: Annotated[Session, Depends(get_db)]):
    row = _saved(db, case, run_id)
    return HTMLResponse(render_evidence_html(row.trace, request_id=row.request_id))


@router.get("/cases/{case_id}/investigations/{run_id}/export")
def export(run_id: uuid.UUID, request: Request, case: AuthorizedCase, user: CurrentUser,
           db: Annotated[Session, Depends(get_db)]):
    row = _saved(db, case, run_id)
    extra = {
        "intelligence.json": json.dumps(row.intelligence, indent=2, sort_keys=True).encode(),
        "investigation.json": json.dumps({**_summary(row), "request": row.input_payload,
            "export_note": "Exported from the saved snapshot; no re-tracing or external submission."},
            indent=2, sort_keys=True).encode(),
    }
    # Include the exact checked bridge evidence linked to a recipient run.
    # Never attach a review from another organization/case, mode, or corrupted bundle.
    protocol_id = row.input_payload.get("protocol_review_id")
    if protocol_id:
        from app.models.operations import CrossChainReview
        try:
            ident = uuid.UUID(protocol_id)
        except (ValueError, TypeError) as exc:
            raise HTTPException(409, "saved protocol reference is invalid") from exc
        protocol = db.scalar(select(CrossChainReview).where(CrossChainReview.id == ident,
            CrossChainReview.case_id == case.id, CrossChainReview.organization_id == case.organization_id,
            CrossChainReview.data_mode == row.data_mode))
        if protocol is None or trace_digest(protocol.evidence_bundle) != protocol.bundle_sha256:
            raise HTTPException(409, "linked cross-chain evidence is unavailable or changed; export refused")
        extra["cross-chain-evidence.json"] = json.dumps({"review_id": str(protocol.id),
            "bundle_sha256": protocol.bundle_sha256, "evidence_bundle": protocol.evidence_bundle},
            indent=2, sort_keys=True).encode()
    # All evidence was checked in a single read snapshot. Close that transaction
    # before expensive PDF rendering: an active polling worker must not make a
    # long-running report upgrade a stale SQLite read transaction to a writer.
    # SessionLocal retains these loaded scalar values after commit.
    db.commit()
    try:
        bundle = build_evidence_bundle(row.trace, request_id=row.request_id, generated_at=row.created_at)
    except EvidenceExportError as exc:
        raise HTTPException(503, str(exc)) from exc
    manifest = dict(bundle.manifest)
    manifest["files"] = dict(manifest["files"])
    manifest["files"].update({name: hashlib.sha256(content).hexdigest() for name, content in extra.items()})
    manifest["combined_workspace_version"] = VERSION
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in bundle.files:
            archive.writestr(file.name, file.content)
        for name, content in extra.items():
            archive.writestr(name, content)
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
    _audit(db, case, user, request, "investigation.exported", row.id, trace_sha256=row.trace_sha256)
    db.commit()
    return Response(out.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="investigation-{row.id}.zip"'})


@router.post("/cases/{case_id}/investigations/{run_id}/request-draft")
def request_draft(run_id: uuid.UUID, payload: SavedDraftRequest, request: Request,
                  case: AuthorizedCase, user: CurrentUser, db: Annotated[Session, Depends(get_db)],
                  settings: Annotated[Settings, Depends(get_settings)]):
    row = _saved(db, case, run_id)
    try:
        draft = build_request_draft(row.trace, case_reference=case.case_reference,
                                   **payload.model_dump()).to_json()
    except (RequestDraftError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    _audit(db, case, user, request, "investigation.request_draft", row.id,
           request_kind=payload.request_kind, submission="not_sent")
    db.commit()
    return ok({"draft": draft, "html": render_request_draft_html(draft, request_id=row.request_id),
               "submission": "not_sent"}, settings, request.state.request_id)


@router.get("/workspace/correlations")
def correlations(request: Request, org: CurrentOrganization,
                 db: Annotated[Session, Depends(get_db)], settings: Annotated[Settings, Depends(get_settings)]):
    # Latest snapshot per case, scoped to the currently selected organization.
    rows = db.execute(select(InvestigationSnapshot).join(Case, InvestigationSnapshot.case_id == Case.id)
        .where(Case.organization_id == org.id)
        .order_by(InvestigationSnapshot.created_at.desc(), InvestigationSnapshot.id.desc()).limit(501)).scalars().all()
    selected = {}
    rejected = 0
    for row in rows[:500]:
        if str(row.case_id) in selected:
            continue
        if trace_digest(row.trace) != row.trace_sha256:
            rejected += 1
            continue
        selected[str(row.case_id)] = {"case_id": str(row.case_id), "trace": row.trace}
    return ok({"links": correlate_traces(list(selected.values())), "cases_considered": len(selected),
               "truncated": len(rows) > 500, "integrity_rejections": rejected,
               "scope": "latest available snapshot per authorized case; exact address overlaps only"},
              settings, request.state.request_id)


@router.post("/cases/{case_id}/watches/{watch_id}/poll")
async def poll(watch_id: uuid.UUID, request: Request, case: AuthorizedCase, user: CurrentUser,
               db: Annotated[Session, Depends(get_db)], settings: Annotated[Settings, Depends(get_settings)]):
    watch = _case_watch(db, case, watch_id)
    network = db.get(Network, watch.network_id)
    if not network:
        raise HTTPException(422, "watch network unavailable")
    try:
        adapter = build_adapter(settings, network_key=network.key)
        outcome = await asyncio.wait_for(poll_watch(db, watch, adapter,
            observation_mode=settings.data_mode, max_pages=settings.monitor_max_pages,
            secrets=(settings.tron_api_key, settings.ethereum_rpc_url, settings.bsc_rpc_url, settings.base_rpc_url)),
            timeout=settings.budget_wall_clock_seconds + 10)
    except (MonitoringError, TraceUnavailable) as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    except TimeoutError as exc:
        db.rollback()
        raise HTTPException(504, "poll timed out; checkpoint not advanced by this request") from exc
    _audit(db, case, user, request, "watch.manual_poll", watch.id)
    db.commit()
    return ok(outcome.to_json(), settings, request.state.request_id)
