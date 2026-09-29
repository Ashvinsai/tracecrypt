"""Liveness, readiness, and the capability/meta endpoint."""

from __future__ import annotations

from typing import Annotated, Any


from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.envelope import ok
from app.core.settings import Settings, get_settings
from app.db.base import get_db
from app.models.chain import Asset, Network
from app.services.demo_presets import (
    has_recorded_cctp_live_validation,
    has_recorded_successful_live_validation,
    load_anomaly_evaluation,
    load_readiness,
    summarize_presets,
)
from app.services.operational_status import (
    capability_details,
    evm_network_states,
    legacy_capabilities,
)

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness. Deliberately unauthenticated and dependency-free."""
    return {"status": "ok"}


@router.get("/readyz")
def readyz(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    checks: dict[str, str] = {}
    try:
        db.execute(text("select 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 - readiness reports, never raises
        checks["database"] = f"error: {type(exc).__name__}"
    if settings.redis_url:
        try:
            import redis

            redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1).ping()
            checks["redis"] = "ok"
        except Exception as exc:  # noqa: BLE001
            checks["redis"] = f"error: {type(exc).__name__}"
    else:
        checks["redis"] = "not configured"

    ready = all(v in ("ok", "not configured") for v in checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"ready": ready, "checks": checks}


@router.get("/api/v1/meta")
def meta_endpoint(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """What this deployment actually supports. Nothing aspirational belongs here."""
    networks = db.execute(select(Network)).scalars().all()
    assets = db.execute(select(Asset)).scalars().all()
    presets = summarize_presets()
    capabilities = capability_details(
        readiness=load_readiness(),
        saved_run_count=len([preset for preset in presets if preset.get("has_trace")]),
        live_key_configured=bool(settings.tron_api_key),
        configured_data_mode=settings.data_mode.value,
        anomaly_evaluation=load_anomaly_evaluation(),
        historical_live_run_recorded=has_recorded_successful_live_validation(network_key="tron"),
        evm_networks=evm_network_states(settings),
        cctp_historical_recorded=has_recorded_cctp_live_validation(),
    )
    return ok(
        {
            "supported_networks": [
                {
                    "key": n.key,
                    "display_name": n.display_name,
                    "family": n.family.value,
                    "chain_id": n.chain_id,
                    "is_supported": n.is_supported,
                }
                for n in networks
            ],
            "supported_assets": [
                {
                    "network_id": str(a.network_id),
                    "kind": a.kind.value,
                    "token_contract": a.token_contract,
                    "decimals": a.decimals,
                    "display_symbol": a.display_symbol,
                    "issuer_reference": a.issuer_reference,
                    "verified_at": a.verified_at.isoformat() if a.verified_at else None,
                    "is_supported": a.is_supported,
                }
                for a in assets
            ],
            "capabilities": legacy_capabilities(capabilities),
            "capability_details": capabilities,
            "budgets": {
                "max_hops": settings.budget_max_hops,
                "max_events": settings.budget_max_events,
                "max_provider_requests": settings.budget_max_provider_requests,
                "wall_clock_seconds": settings.budget_wall_clock_seconds,
                "note": "configuration targets, not measured performance",
            },
        },
        settings,
        request.state.request_id,
    )
