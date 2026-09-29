"""Network-scoped address validation."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.authz import CurrentUser
from app.core.envelope import ok
from app.core.settings import Settings, get_settings
from app.db.base import get_db
from app.models.chain import Network
from app.services.addresses import AddressValidationError, canonicalize

router = APIRouter(prefix="/api/v1/addresses")


@router.get("/validate")
def validate_address(
    request: Request,
    network_key: str,
    address: str,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Validate ``address`` *on the stated network*. The network is never inferred (D002)."""
    network = db.execute(select(Network).where(Network.key == network_key)).scalar_one_or_none()
    if network is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown network")
    try:
        canonical = canonicalize(network.key, address)
    except AddressValidationError as exc:
        return ok(
            {"valid": False, "reason": str(exc), "network_key": network.key},
            settings,
            request.state.request_id,
        )
    return ok(
        {
            "valid": True,
            "network_key": network.key,
            "canonical_address": canonical.canonical,
            "original_input": canonical.original,
            "address_format": canonical.address_format,
        },
        settings,
        request.state.request_id,
    )
