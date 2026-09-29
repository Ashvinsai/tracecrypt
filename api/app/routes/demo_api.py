"""Read-only JSON facade for the investigator console (local prototype).

The console (``/console``) already renders saved artifacts as HTML. This
module exposes the same allow-listed artifacts as JSON so the React
investigator workspace can draw a graph, open an inspector drawer, and show
cross-chain / decision-support / candidate / evidence detail without
navigating away.

It is deliberately narrow and mirrors ``routes.console``: registered only in
non-prod, requires no session, contacts no provider, and reads no case data.
Every run id is validated and resolved under a known ``var/`` root by
``app.services.demo_artifacts``. Nothing here recomputes an attribution or
promotes a candidate -- it only shapes what is already saved on disk.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.envelope import ok
from app.core.settings import Settings, get_settings
from app.reports.fund_flow import build_fund_flow
from app.services.demo_artifacts import (
    list_candidate_reports,
    list_cctp_bundles,
    list_evidence_bundles,
    list_routing_bundles,
)
from app.services.demo_presets import (
    all_presets,
    load_preset,
    preset_by_id,
    summarize_presets,
)
from app.services.operational_status import capability_details

router = APIRouter(prefix="/api/v1/demo", tags=["demo"])


def _preset_detail(preset_id: str) -> dict[str, Any] | None:
    preset = preset_by_id(preset_id)
    if preset is None:
        return None
    view = load_preset(preset)
    trace = view.trace
    graph = None
    cross_chain_links: list[Any] = []
    if isinstance(trace, dict):
        graph = build_fund_flow(trace).to_json()
        links = trace.get("cross_chain_links")
        if isinstance(links, list):
            cross_chain_links = links
    return {
        "id": preset.id,
        "title": preset.title,
        "scenario": preset.scenario,
        "data_mode": view.data_mode,
        "capture_data_mode": view.capture_data_mode,
        "address": preset.address,
        "description": preset.description,
        "scope_note": preset.scope_note,
        "error": view.error,
        "warnings": view.warnings,
        "has_outcome": view.has_outcome,
        "has_comparison": view.has_comparison,
        "has_report": view.has_report,
        "trace": trace,
        "graph": graph,
        "outcome": view.outcome,
        "comparison": view.comparison,
        "behavioral": view.behavioral_evidence,
        "behavioral_manifest": view.behavioral_manifest,
        "manifest": view.manifest,
        "cross_chain_links": cross_chain_links,
    }


@router.get("/presets")
def demo_presets(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """All saved trace presets, with counts derived from each saved result."""

    return ok(
        {"presets": summarize_presets(), "count": len(all_presets())},
        settings,
        request.state.request_id,
    )


@router.get("/presets/{preset_id}")
def demo_preset_detail(
    preset_id: str,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    detail = _preset_detail(preset_id)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no saved preset with this id")
    return ok(detail, settings, request.state.request_id)


@router.get("/cctp")
def demo_cctp(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Saved Circle CCTP V2 cross-chain validation bundles."""

    bundles = list_cctp_bundles()
    return ok({"bundles": bundles, "count": len(bundles)}, settings, request.state.request_id)


@router.get("/routing")
def demo_routing(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Saved System-1 routing shadow-validation bundles (decision support)."""

    payload = list_routing_bundles()
    payload["count"] = len(payload["bundles"])
    return ok(payload, settings, request.state.request_id)


@router.get("/candidates")
def demo_candidates(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Saved candidate-neighborhood reports (leads, not ownership)."""

    reports = list_candidate_reports()
    return ok({"reports": reports, "count": len(reports)}, settings, request.state.request_id)


@router.get("/evidence")
def demo_evidence(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Saved evidence-export bundles with a re-verified manifest."""

    bundles = list_evidence_bundles()
    return ok({"bundles": bundles, "count": len(bundles)}, settings, request.state.request_id)


@router.get("/capabilities")
def demo_capabilities(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """The canonical capability catalog, from one implementation/configuration/
    live-verification model -- the same source ``/api/v1/meta`` uses."""

    from app.services.demo_presets import (
        has_recorded_cctp_live_validation,
        has_recorded_successful_live_validation,
        load_anomaly_evaluation,
        load_readiness,
    )
    from app.services.operational_status import evm_network_states

    capabilities = capability_details(
        readiness=load_readiness(),
        saved_run_count=len([p for p in summarize_presets() if p.get("has_trace")]),
        live_key_configured=bool(settings.tron_api_key),
        configured_data_mode=settings.data_mode.value,
        anomaly_evaluation=load_anomaly_evaluation(),
        historical_live_run_recorded=has_recorded_successful_live_validation(network_key="tron"),
        evm_networks=evm_network_states(settings),
        cctp_historical_recorded=has_recorded_cctp_live_validation(),
    )
    return ok(
        {"capabilities": capabilities, "data_mode": settings.data_mode.value},
        settings,
        request.state.request_id,
    )
