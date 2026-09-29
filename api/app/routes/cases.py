"""Case and seed intake. Every route is organization-scoped server-side."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.amounts import serialize
from app.core.authz import AuthorizedCase, CurrentOrganization, CurrentUser
from app.core.envelope import ok
from app.core.settings import Settings, get_settings
from app.db.base import get_db
from app.models.casework import Case, CaseSeed
from app.models.chain import Address, Asset, Network
from app.models.enums import SeedMode
from app.services.addresses import AddressValidationError, canonicalize

router = APIRouter(prefix="/api/v1/cases")


class CaseCreate(BaseModel):
    case_reference: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=300)


class SeedCreate(BaseModel):
    mode: SeedMode
    network_key: str
    address: str
    asset_id: uuid.UUID | None = None
    transaction_hash: str | None = None
    transfer_event_reference: str | None = None
    #: A string, because an amount is an integer in base units and JSON numbers lie (D004).
    amount_base_units: str | None = None
    incident_time: dt.datetime | None = None
    window_start: dt.datetime | None = None
    window_end: dt.datetime | None = None

    @model_validator(mode="after")
    def _mode_rules(self) -> SeedCreate:
        if self.mode is SeedMode.incident and self.asset_id is None:
            raise ValueError("incident mode requires an explicit network-scoped asset_id")
        if self.mode is SeedMode.address_discovery and self.amount_base_units is not None:
            raise ValueError(
                "address_discovery mode asserts nothing about victim funds; "
                "an amount is not accepted"
            )
        if self.amount_base_units is not None and not self.amount_base_units.lstrip("-").isdigit():
            raise ValueError("amount_base_units must be an integer string in base units")
        return self


def _case_json(case: Case) -> dict[str, Any]:
    return {
        "id": str(case.id),
        "case_reference": case.case_reference,
        "title": case.title,
        "status": case.status,
        "data_mode": case.data_mode.value,
        "created_at": case.created_at.isoformat() if case.created_at else None,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_case(
    payload: CaseCreate,
    request: Request,
    user: CurrentUser,
    org: CurrentOrganization,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    case = Case(
        organization_id=org.id,
        case_reference=payload.case_reference,
        title=payload.title,
        data_mode=settings.data_mode,
        created_by=user.id,
    )
    db.add(case)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "case_reference already used") from exc
    db.refresh(case)
    return ok(_case_json(case), settings, request.state.request_id)


@router.get("")
def list_cases(
    request: Request,
    org: CurrentOrganization,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    cases = (
        db.execute(
            select(Case)
            .where(Case.organization_id == org.id)
            .order_by(Case.created_at.desc())
            .limit(200)
        )
        .scalars()
        .all()
    )
    return ok([_case_json(c) for c in cases], settings, request.state.request_id)


@router.get("/{case_id}")
def get_case(
    request: Request,
    case: AuthorizedCase,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    return ok(_case_json(case), settings, request.state.request_id)


@router.post("/{case_id}/seeds", status_code=status.HTTP_201_CREATED)
def create_seed(
    payload: SeedCreate,
    request: Request,
    case: AuthorizedCase,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    network = db.execute(
        select(Network).where(Network.key == payload.network_key)
    ).scalar_one_or_none()
    if network is None or not network.is_supported:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "unsupported network")

    try:
        canonical = canonicalize(network.key, payload.address)
    except AddressValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    asset = None
    if payload.asset_id is not None:
        asset = db.get(Asset, payload.asset_id)
        if asset is None or asset.network_id != network.id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "asset is not defined on the selected network",
            )

    address = db.execute(
        select(Address).where(
            Address.network_id == network.id,
            Address.canonical_address == canonical.canonical,
        )
    ).scalar_one_or_none()
    if address is None:
        address = Address(
            network_id=network.id,
            canonical_address=canonical.canonical,
            original_input=canonical.original,
            address_format=canonical.address_format,
            data_mode=settings.data_mode,
        )
        db.add(address)
        db.flush()

    seed = CaseSeed(
        case_id=case.id,
        mode=payload.mode,
        network_id=network.id,
        address_id=address.id,
        asset_id=asset.id if asset else None,
        amount_base_units=(
            int(payload.amount_base_units) if payload.amount_base_units is not None else None
        ),
        incident_time=payload.incident_time,
        window_start=payload.window_start,
        window_end=payload.window_end,
    )
    db.add(seed)
    db.commit()
    db.refresh(seed)
    return ok(
        {
            "id": str(seed.id),
            "case_id": str(seed.case_id),
            "mode": seed.mode.value,
            "network_key": network.key,
            "canonical_address": canonical.canonical,
            "original_input": canonical.original,
            "asset_id": str(seed.asset_id) if seed.asset_id else None,
            "amount_base_units": serialize(seed.amount_base_units),
            "case_flow_linkage": (
                "established" if seed.mode is SeedMode.incident else "not_established"
            ),
        },
        settings,
        request.state.request_id,
    )
