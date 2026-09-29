"""Trace endpoints: JSON result, a printable evidence view, and an export bundle."""

from __future__ import annotations

import datetime as dt
import io
import uuid
import zipfile
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.base import AssetRef, ProviderError
from app.core.authz import CurrentUser
from app.core.envelope import ok
from app.core.settings import Settings, get_settings
from app.db.base import get_db
from app.models.chain import Asset, Network
from app.models.enums import CaseFlowLinkage, SeedMode
from app.reports.evidence import render_evidence_html
from app.reports.legal_request import render_request_draft_html
from app.services.addresses import AddressValidationError, canonicalize
from app.services.evidence_export import build_evidence_bundle
from app.services.legal_requests import (
    REQUEST_KINDS,
    RequestDraftError,
    build_request_draft,
)
from app.services.trace_service import TraceUnavailable, run_trace

router = APIRouter(prefix="/api/v1/traces")


class TraceRequest(BaseModel):
    network_key: str
    address: str
    asset_id: str | None = None
    token_contract: str | None = None
    #: A transaction can hold several transfers, so the caller names the event.
    seed_event_reference: str | None = None
    mode: SeedMode = SeedMode.incident
    analysis_cutoff: dt.datetime | None = Field(default=None)


class LegalRequestDraftRequest(TraceRequest):
    request_kind: str
    #: The exact branch-ending address this draft targets. Must be an address
    #: the trace actually reached -- never inferred or guessed.
    target_address: str
    requesting_agency: str
    requesting_officer: str
    case_reference: str
    alleged_incident_summary: str
    legal_authority_reference: str | None = None
    exchange_account_identifiers: str | None = None


async def _request_draft(
    db: Session, settings: Settings, payload: LegalRequestDraftRequest
) -> dict[str, Any]:
    if payload.request_kind not in REQUEST_KINDS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"request_kind must be one of {REQUEST_KINDS}",
        )
    result = await _trace(db, settings, payload)
    try:
        draft = build_request_draft(
            result,
            request_kind=payload.request_kind,  # type: ignore[arg-type]
            target_address=payload.target_address,
            requesting_agency=payload.requesting_agency,
            requesting_officer=payload.requesting_officer,
            case_reference=payload.case_reference,
            alleged_incident_summary=payload.alleged_incident_summary,
            legal_authority_reference=payload.legal_authority_reference,
            exchange_account_identifiers=payload.exchange_account_identifiers,
        )
    except RequestDraftError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return draft.to_json()


def _resolve_asset(db: Session, network: Network, payload: TraceRequest) -> Asset:
    query = select(Asset).where(Asset.network_id == network.id, Asset.is_supported.is_(True))
    if payload.asset_id:
        try:
            asset_key = uuid.UUID(payload.asset_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(422, "asset_id must be a UUID") from exc
        asset = db.get(Asset, asset_key)
        if asset is None or asset.network_id != network.id or not asset.is_supported:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "asset is not defined on the selected network",
            )
        return asset
    if payload.token_contract:
        asset = db.execute(
            query.where(Asset.token_contract == payload.token_contract)
        ).scalar_one_or_none()
        if asset is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "token contract is not a supported asset on this network",
            )
        return asset
    supported = db.execute(query).scalars().all()
    if len(supported) != 1:
        # A ticker is not an identity, so we will not pick one for the caller.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "specify asset_id or token_contract; the network has no single supported asset",
        )
    return supported[0]


async def _trace(db: Session, settings: Settings, payload: TraceRequest) -> dict[str, Any]:
    network = db.execute(
        select(Network).where(Network.key == payload.network_key)
    ).scalar_one_or_none()
    if network is None or not network.is_supported:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "unsupported network")

    try:
        canonical = canonicalize(network.key, payload.address)
    except AddressValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    asset = _resolve_asset(db, network, payload)
    asset_ref = AssetRef(network_key=network.key, token_contract=asset.token_contract,
                         decimals=asset.decimals, display_symbol=asset.display_symbol)
    # Provider I/O may be slow. Do not retain a read snapshot and later attempt
    # a SQLite read-to-write upgrade when the caller saves its investigation.
    db.commit()
    try:
        result = await run_trace(
            settings,
            seed_address=canonical.canonical,
            asset=asset_ref,
            seed_event_reference=payload.seed_event_reference,
            analysis_cutoff=payload.analysis_cutoff,
            case_flow_linkage=(
                CaseFlowLinkage.established
                if payload.mode is SeedMode.incident and payload.seed_event_reference
                else CaseFlowLinkage.not_established
            ),
        )
    except TraceUnavailable as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"provider error ({exc.error_class.value}): {exc}"
        ) from exc
    return result.to_json()


@router.post("")
async def create_trace(
    payload: TraceRequest,
    request: Request,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Run a trace synchronously and return the full result.

    This is the retained interactive endpoint. Automated complaint intake uses
    the durable operations queue instead.
    """
    return ok(await _trace(db, settings, payload), settings, request.state.request_id)


@router.post("/report", response_class=HTMLResponse)
async def create_trace_report(
    payload: TraceRequest,
    request: Request,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> HTMLResponse:
    """The same result as an evidence view that prints to PDF from a browser."""
    result = await _trace(db, settings, payload)
    return HTMLResponse(render_evidence_html(result, request_id=request.state.request_id))


@router.post("/export")
async def create_trace_export(
    payload: TraceRequest,
    request: Request,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """A downloadable zip: the same result as JSON, CSV, a generated PDF, and
    a checksum manifest (Stage 4). The PDF is rendered from the exact HTML the
    ``/report`` route serves, so the two views can never disagree."""
    result = await _trace(db, settings, payload)
    bundle = build_evidence_bundle(result, request_id=request.state.request_id)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in bundle.files:
            zf.writestr(f.name, f.content)
        zf.writestr("manifest.json", bundle.manifest_bytes())

    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=evidence-bundle.zip"},
    )


@router.post("/legal-request-draft")
async def create_legal_request_draft(
    payload: LegalRequestDraftRequest,
    request: Request,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Draft (never send) an information/preservation/asset-restriction
    request against one address the trace reached (Stage 4). A refused draft
    (e.g. the target is a pooled exchange wallet) is a 200 with
    ``status: "refused"`` and a stated reason, not an error -- refusal is a
    correct, inspectable outcome, not a caller mistake."""
    return ok(await _request_draft(db, settings, payload), settings, request.state.request_id)


@router.post("/legal-request-draft/report", response_class=HTMLResponse)
async def create_legal_request_draft_report(
    payload: LegalRequestDraftRequest,
    request: Request,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> HTMLResponse:
    """The same draft as a printable page."""
    draft = await _request_draft(db, settings, payload)
    return HTMLResponse(render_request_draft_html(draft, request_id=request.state.request_id))
