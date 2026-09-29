"""Case-scoped watches and their alerts (Stage 4, D029).

Every route resolves the case through ``AuthorizedCase`` and the watch through
that case, so a foreign organization's case or watch is a 404, never a 403
(D008). Polling is deliberately not exposed here: it calls a provider, so it
runs from ``scripts/poll_watches.py``, not inside a web request.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.authz import AuthorizedCase, CurrentUser
from app.core.envelope import ok
from app.core.settings import Settings, get_settings
from app.db.base import get_db
from app.models.casework import Alert, Case, Watch, WatchPollRun
from app.services.monitoring import (
    MonitoringError,
    alert_to_json,
    create_watch,
    watch_to_json,
)

router = APIRouter(prefix="/api/v1/cases/{case_id}/watches")


class WatchCreate(BaseModel):
    network_key: str
    address: str
    #: The exact verified contract. A symbol is not accepted as an identity (D003).
    token_contract: str
    analysis_start: dt.datetime | None = None
    overlap_seconds: int | None = Field(default=None, ge=0, le=7 * 24 * 3600)


def _case_watch(db: Session, case: Case, watch_id: uuid.UUID) -> Watch:
    watch = db.execute(
        select(Watch).where(Watch.id == watch_id, Watch.case_id == case.id)
    ).scalar_one_or_none()
    if watch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "watch not found")
    return watch


@router.post("", status_code=status.HTTP_201_CREATED)
def create(
    payload: WatchCreate,
    request: Request,
    case: AuthorizedCase,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    try:
        watch = create_watch(
            db,
            case=case,
            network_key=payload.network_key,
            address=payload.address,
            token_contract=payload.token_contract,
            data_mode=settings.data_mode,
            analysis_start=payload.analysis_start,
            overlap_seconds=(
                payload.overlap_seconds
                if payload.overlap_seconds is not None
                else settings.monitor_overlap_seconds
            ),
            created_by=user.id,
        )
    except MonitoringError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    db.commit()
    return ok(watch_to_json(db, watch), settings, request.state.request_id)


@router.get("")
def list_watches(
    request: Request,
    case: AuthorizedCase,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    watches = (
        db.execute(select(Watch).where(Watch.case_id == case.id).order_by(Watch.created_at))
        .scalars()
        .all()
    )
    return ok([watch_to_json(db, w) for w in watches], settings, request.state.request_id)


@router.get("/{watch_id}")
def get_watch(
    watch_id: uuid.UUID,
    request: Request,
    case: AuthorizedCase,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    watch = _case_watch(db, case, watch_id)
    return ok(watch_to_json(db, watch), settings, request.state.request_id)


@router.get("/{watch_id}/alerts")
def list_alerts(
    watch_id: uuid.UUID,
    request: Request,
    case: AuthorizedCase,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    watch = _case_watch(db, case, watch_id)
    alerts = (
        db.execute(
            select(Alert)
            .where(Alert.watch_id == watch.id)
            .order_by(Alert.first_observed_at, Alert.event_reference)
            .limit(500)
        )
        .scalars()
        .all()
    )
    return ok([alert_to_json(a) for a in alerts], settings, request.state.request_id)


@router.get("/{watch_id}/polls")
def list_polls(
    watch_id: uuid.UUID,
    request: Request,
    case: AuthorizedCase,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    watch = _case_watch(db, case, watch_id)
    runs = (
        db.execute(
            select(WatchPollRun)
            .where(WatchPollRun.watch_id == watch.id)
            .order_by(WatchPollRun.started_at.desc())
            .limit(50)
        )
        .scalars()
        .all()
    )
    return ok(
        [
            {
                "id": str(r.id),
                "status": r.status.value,
                "coverage_status": r.coverage_status.value,
                "data_mode": r.data_mode.value,
                "provider": r.provider,
                "started_at": r.started_at.isoformat(),
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "window_start": r.window_start.isoformat(),
                "window_end": r.window_end.isoformat(),
                "checkpoint_before": (
                    r.checkpoint_before.isoformat() if r.checkpoint_before else None
                ),
                "checkpoint_after": r.checkpoint_after.isoformat() if r.checkpoint_after else None,
                "pages_fetched": r.pages_fetched,
                "provider_requests": r.provider_requests,
                "events_observed": r.events_observed,
                "new_alerts": r.new_alerts,
                "duplicate_events": r.duplicate_events,
                "error_class": r.error_class,
                "error_message": r.error_message,
                "summary": r.summary,
            }
            for r in runs
        ],
        settings,
        request.state.request_id,
    )
