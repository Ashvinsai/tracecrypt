"""Stage 4: a clearly-marked MOCK complaint intake.

Per docs/FIVE_STAGE_PLAN.md's Stage 4 instruction ("Provide a clearly marked
mock complaint adapter only. Do not invent NCRP/SAHYOG APIs or claim approved
connectivity.") and AGENTS.md ("Government connectors remain MOCK/NOT
CONFIGURED until approved documentation, credentials, and permission exist.
Do not invent NCRP or SAHYOG production APIs."):

- This module makes no network call, and reads no real complaint anywhere.
  It reads exactly one repository file, ``fixtures/mock_complaints.json``,
  whose own ``note`` field states plainly that every complaint in it is
  fictional and that the queue is not NCRP, not SAHYOG, and not any real
  government portal.
- ``SOURCE_CHANNEL`` is a fixed constant carried on every complaint and every
  API response derived from one, so a consumer can never mistake this for a
  real connector -- the same "state plainly what is mock" posture
  ``app.services.operational_status`` already applies to the capability
  matrix as a whole.
- This module never creates a ``Case``/``CaseSeed`` itself.
  ``mock_complaint_to_seed_draft`` only *shapes* a suggested seed payload for
  a human investigator to review and, if they choose, submit through the
  existing authenticated ``POST /api/v1/cases/{case_id}/seeds`` route -- the
  one real intake path this project has, reused rather than duplicated. It
  never resolves a database ``asset_id`` (this module has no database
  access), so the draft is expressed the same way ``POST /api/v1/traces``
  already accepts an asset: by ``token_contract``, for the caller's own
  lookup.

Per AGENTS.md's PII rule ("Keep complaint PII... out of public intelligence
tables, shared case caches, logs, demos, and external AI prompts."): every
reporter-contact value in the fixture is itself fictional test data, clearly
marked ``FICTIONAL``, the same convention this project already uses for
synthetic entity names (see ``data/anchors.csv``'s "Northwind Exchange
(FICTIONAL)"). A real complaint connector would need real PII-handling
controls this module does not implement or claim to.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.settings import REPO_ROOT

SOURCE_CHANNEL = "MOCK_LOCAL_QUEUE"

_DEFAULT_FIXTURE_PATH = REPO_ROOT / "fixtures" / "mock_complaints.json"


class MockComplaintAdapterError(ValueError):
    pass


@dataclass(frozen=True)
class MockComplaint:
    complaint_reference: str
    received_at: str
    network_key: str
    reported_address: str
    asset_token_contract: str | None
    asset_display_symbol: str
    reported_transaction_hash: str | None
    seed_event_reference: str | None
    incident_time: str | None
    amount_reported_base_units: str | None
    incident_summary: str
    reporter_contact: str
    category: str

    def to_json(self) -> dict[str, Any]:
        return {
            "source_channel": SOURCE_CHANNEL,
            "complaint_reference": self.complaint_reference,
            "received_at": self.received_at,
            "network_key": self.network_key,
            "reported_address": self.reported_address,
            "asset": {
                "token_contract": self.asset_token_contract,
                "display_symbol": self.asset_display_symbol,
            },
            "reported_transaction_hash": self.reported_transaction_hash,
            "seed_event_reference": self.seed_event_reference,
            "incident_time": self.incident_time,
            "amount_reported_base_units": self.amount_reported_base_units,
            "incident_summary": self.incident_summary,
            "reporter_contact": self.reporter_contact,
            "category": self.category,
        }


def _load_fixture(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise MockComplaintAdapterError(f"mock complaint fixture not found: {path}")
    data = json.loads(path.read_text())
    if data.get("source_channel") != SOURCE_CHANNEL:
        raise MockComplaintAdapterError(
            f"fixture at {path} does not declare source_channel={SOURCE_CHANNEL!r}; "
            "refusing to load a file that might not be this project's own mock fixture"
        )
    return data


def _parse_complaint(row: dict[str, Any]) -> MockComplaint:
    asset = row.get("asset") or {}
    return MockComplaint(
        complaint_reference=row["complaint_reference"],
        received_at=row["received_at"],
        network_key=row["network_key"],
        reported_address=row["reported_address"],
        asset_token_contract=asset.get("token_contract"),
        asset_display_symbol=asset.get("display_symbol", ""),
        reported_transaction_hash=row.get("reported_transaction_hash"),
        seed_event_reference=row.get("seed_event_reference"),
        incident_time=row.get("incident_time"),
        amount_reported_base_units=row.get("amount_reported_base_units"),
        incident_summary=row["incident_summary"],
        reporter_contact=row["reporter_contact"],
        category=row["category"],
    )


def list_mock_complaints(*, fixture_path: Path | None = None) -> list[MockComplaint]:
    """Every complaint in the fixture, in file order. No filtering, no
    claimed/unclaimed state -- this module writes nothing, so it cannot track
    whether a complaint has already been turned into a case."""
    data = _load_fixture(fixture_path or _DEFAULT_FIXTURE_PATH)
    return [_parse_complaint(row) for row in data["complaints"]]


def get_mock_complaint(
    complaint_reference: str, *, fixture_path: Path | None = None
) -> MockComplaint | None:
    for complaint in list_mock_complaints(fixture_path=fixture_path):
        if complaint.complaint_reference == complaint_reference:
            return complaint
    return None


def mock_complaint_to_seed_draft(complaint: MockComplaint) -> dict[str, Any]:
    """Shape a suggested (not submitted) seed payload from one complaint.

    ``mode`` is ``incident`` only when the complaint names a specific seed
    event; a complaint with no recorded transaction cannot assert case-flow
    linkage to anything, so it is offered as ``address_discovery`` instead
    (see app.models.enums.SeedMode, PRD section 2) -- this module does not
    invent a transaction reference to force incident mode.
    """
    has_event = bool(complaint.seed_event_reference)
    return {
        "source": {
            "channel": SOURCE_CHANNEL,
            "complaint_reference": complaint.complaint_reference,
        },
        "mode": "incident" if has_event else "address_discovery",
        "network_key": complaint.network_key,
        "address": complaint.reported_address,
        "token_contract": complaint.asset_token_contract,
        "transaction_hash": complaint.reported_transaction_hash,
        "transfer_event_reference": complaint.seed_event_reference,
        "amount_base_units": complaint.amount_reported_base_units if has_event else None,
        "incident_time": complaint.incident_time,
        "note": (
            "Suggested draft only -- nothing has been submitted. An investigator "
            "must resolve token_contract to this deployment's own asset_id and "
            "review every field before POSTing to "
            "/api/v1/cases/{case_id}/seeds. Reported amounts are the "
            "complainant's own account of the transfer, not a verified figure; "
            "a trace against this seed establishes what the chain actually "
            "shows."
        ),
    }
