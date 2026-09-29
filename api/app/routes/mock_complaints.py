"""Stage 4: a clearly-marked MOCK complaint intake.

Read-only, backed by exactly one local fixture file
(``fixtures/mock_complaints.json``). Not NCRP, not SAHYOG, not any real
government portal -- see ``app.services.mock_complaint_adapter``'s module
docstring and ``docs/DECISIONS.md`` D028. Authenticated like every other
case-adjacent route in this project, per Stage 4's own instruction to
"require appropriate authentication/authorization before exposure beyond
local public-data use".
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.authz import CurrentUser
from app.core.envelope import ok
from app.core.settings import Settings, get_settings
from app.services.mock_complaint_adapter import (
    SOURCE_CHANNEL,
    MockComplaint,
    get_mock_complaint,
    list_mock_complaints,
    mock_complaint_to_seed_draft,
)

router = APIRouter(prefix="/api/v1/complaints/mock")

_QUEUE_NOTE = (
    "Fictional local queue. Not NCRP, not SAHYOG, not any real government "
    "portal -- see docs/DECISIONS.md D028."
)


def _require_complaint(complaint_reference: str) -> MockComplaint:
    complaint = get_mock_complaint(complaint_reference)
    if complaint is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no mock complaint with this reference")
    return complaint


@router.get("")
def list_complaints(
    request: Request,
    user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    return ok(
        {
            "source_channel": SOURCE_CHANNEL,
            "note": _QUEUE_NOTE,
            "complaints": [c.to_json() for c in list_mock_complaints()],
        },
        settings,
        request.state.request_id,
    )


@router.get("/{complaint_reference}")
def get_complaint(
    complaint_reference: str,
    request: Request,
    user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    complaint = _require_complaint(complaint_reference)
    return ok(complaint.to_json(), settings, request.state.request_id)


@router.get("/{complaint_reference}/seed-draft")
def get_seed_draft(
    complaint_reference: str,
    request: Request,
    user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """A suggested -- never submitted -- seed payload shaped from one
    complaint. An investigator resolves ``token_contract`` to a real
    ``asset_id`` and reviews every field before POSTing it to
    ``/api/v1/cases/{case_id}/seeds`` themselves; this route creates nothing."""
    complaint = _require_complaint(complaint_reference)
    return ok(mock_complaint_to_seed_draft(complaint), settings, request.state.request_id)
