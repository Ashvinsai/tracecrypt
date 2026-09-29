"""Stage 4: draft investigator legal-process requests.

This module drafts three distinct request types the five-stage plan's Stage 4
calls for -- information, preservation, and asset-restriction -- against one
target address from an already-run trace result. It is not a tracer, not a
label registry, and not a new source of truth: every fact it prints (the
target's endpoint class, attribution status, address role, review state) is
copied through verbatim from the trace result and the label registry, and
every investigator-supplied fact (agency, officer, case reference, incident
summary) is exactly what was passed in, never invented or defaulted to
something that looks real.

Per AGENTS.md ("Report drafts require human review... Never auto-submit or
impersonate an officer") and the five-stage plan's own Stage 4 instruction
("Generate distinct information/preservation/asset-restriction request
drafts marked DRAFT / INVESTIGATOR REVIEW REQUIRED... do not fabricate legal
authority or signatures. No automatic external sending."):

- Every draft carries a fixed ``draft_marker`` stating plainly that it is not
  legal process, has not been sent, and was not signed or authorised by
  anyone.
- Nothing here sends a request anywhere. Building a draft is the entire
  action this module performs.
- The field checklist is not invented. It reproduces, field for field, one
  real provider's own published law-enforcement request guide (see
  ``CHECKLIST_SOURCE``) -- the same "use a verified provider guide as a field
  checklist" instruction Stage 4 gives, and the same source
  ``docs/FIVE_STAGE_PLAN.md`` already cites.

The pooled-wallet refusal rule ("Do not request a blanket freeze of a pooled
exchange wallet") is enforced structurally, not left to investigator
judgement: ``build_request_draft`` refuses (returns ``status="refused"``,
never raises) to draft an ``asset_restriction`` request against an address
whose label carries a pooled/operational ``address_role``
(``hot_wallet``/``cold_reserve``/``settlement``) *or* whose role has not been
established at all -- because an unestablished role cannot be shown to be
anything narrower. This project's own real accepted anchors
(``data/verified_anchors.csv``) are both ``address_role=unknown`` today for
exactly this reason: a reserve-disclosure signature shows control of a
signing key, not whether the address is a pooled hot wallet or one
customer's deposit account. Only ``address_role=deposit`` -- or an unreviewed
``deposit_candidate`` lead, clearly marked as such -- may be targeted.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass
from typing import Any, Literal

RequestKind = Literal["information", "preservation", "asset_restriction"]
KIND_INFORMATION: RequestKind = "information"
KIND_PRESERVATION: RequestKind = "preservation"
KIND_ASSET_RESTRICTION: RequestKind = "asset_restriction"
REQUEST_KINDS: tuple[RequestKind, ...] = (
    KIND_INFORMATION,
    KIND_PRESERVATION,
    KIND_ASSET_RESTRICTION,
)

DraftStatus = Literal["drafted", "refused"]
STATUS_DRAFTED: DraftStatus = "drafted"
STATUS_REFUSED: DraftStatus = "refused"

ChecklistFieldSource = Literal["provider", "internal"]

#: Roles that name a pooled/operational address an exchange controls for many
#: customers at once, never one customer's own account (app.models.enums.
#: AddressRole). Restraining one of these is the omnibus-wallet mistake Stage
#: 4 explicitly forbids.
POOLED_ADDRESS_ROLES = frozenset({"hot_wallet", "cold_reserve", "settlement"})

ADDRESS_ROLE_UNKNOWN = "unknown"
ADDRESS_ROLE_DEPOSIT = "deposit"

#: This project does not invent a field checklist. This reproduces OKX's own
#: published law-enforcement request guide, retrieved and read (not just
#: linked) on the date below -- the guide docs/FIVE_STAGE_PLAN.md's reference
#: list already names. It does not claim any other provider follows the same
#: checklist.
CHECKLIST_SOURCE = {
    "provider": "OKX",
    "source_reference": "https://www.okx.com/help/okx-law-enforcement-request-guide",
    "retrieved_at": "2026-09-22",
    "submission_channel": (
        "Per the guide's own wording: submitted through OKX's Kodex portal "
        "(https://app.kodexglobal.com/okx/signin); enforcement@okx.com for "
        "emergencies. This module submits nothing anywhere."
    ),
}

DRAFT_MARKER = (
    "DRAFT -- INVESTIGATOR REVIEW REQUIRED. This is not legal process, "
    "establishes no legal authority, has not been sent to any provider, and "
    "was not signed or authorised by any officer."
)

_ITEMS_REQUESTED_TEXT: dict[RequestKind, str] = {
    KIND_INFORMATION: (
        "Account records and identifying information associated with the "
        "named address(es): registered username/UID, registration email/"
        "phone, KYC identification number, and any retained IP/session logs."
    ),
    KIND_PRESERVATION: (
        "Preserve all account records, transaction logs, and identifying "
        "information associated with the named address(es) pending further "
        "legal process. This request does not seek to restrict any funds."
    ),
    KIND_ASSET_RESTRICTION: (
        "Restrict outgoing activity on the specific customer account "
        "associated with the named target address, pending legal process. "
        "This request does not seek restriction of any pooled/omnibus "
        "exchange wallet, and covers only the named target address."
    ),
}


class RequestDraftError(ValueError):
    """A caller error -- a missing required field or an unknown target
    address -- as distinct from a refused-but-valid draft outcome."""


@dataclass(frozen=True)
class ChecklistField:
    key: str
    label: str
    value: str | None
    provided: bool
    required_by: ChecklistFieldSource

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RequestDraftTarget:
    address: str
    network_key: str
    endpoint_class: str
    attribution_status: str
    address_role: str | None
    review_state: str | None
    entity_name: str | None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RequestDraft:
    status: DraftStatus
    request_kind: RequestKind
    refusal_reason: str | None
    target: RequestDraftTarget
    checklist: tuple[ChecklistField, ...]
    identifiers: dict[str, Any]
    checklist_source: dict[str, str]
    draft_marker: str
    generated_at: str

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "request_kind": self.request_kind,
            "refusal_reason": self.refusal_reason,
            "target": self.target.to_json(),
            "checklist": [f.to_json() for f in self.checklist],
            "identifiers": self.identifiers,
            "checklist_source": self.checklist_source,
            "draft_marker": self.draft_marker,
            "generated_at": self.generated_at,
        }


def _find_branch_ending(result: dict[str, Any], address: str) -> dict[str, Any] | None:
    for b in result["branch_endings"]:
        if b["address"] == address:
            return b
    return None


def _require(value: str, field_name: str) -> str:
    if not value or not value.strip():
        raise RequestDraftError(f"{field_name} is required and cannot be blank")
    return value.strip()


def _asset_restriction_refusal_reason(
    target: RequestDraftTarget, label_present: bool
) -> str | None:
    role = target.address_role
    if role in POOLED_ADDRESS_ROLES:
        return (
            f"{target.address} carries address_role={role}: a pooled/operational "
            "address an exchange controls for many customers at once, not one "
            "customer's account. Restraining it would halt liquidity for "
            "uninvolved customers -- the exact mistake Stage 4 forbids "
            "(docs/FIVE_STAGE_PLAN.md: 'Do not request a blanket freeze of a "
            "pooled exchange wallet')."
        )
    if role is None or role == ADDRESS_ROLE_UNKNOWN:
        return (
            f"{target.address}'s address_role is not established "
            f"(label present: {label_present}). An asset-restriction request "
            "cannot rule out this being a pooled/operational address without "
            "a narrower, reviewed role naming it otherwise."
        )
    return None


def _collect_identifiers(result: dict[str, Any], target_address: str) -> dict[str, Any]:
    seed = result["seed"]
    seed_transfer = result.get("seed_transfer")
    tx_hashes = sorted(
        {
            t["tx_hash"]
            for t in ([seed_transfer] if seed_transfer else []) + list(result["observed_transfers"])
            if t.get("tx_hash")
        }
    )
    return {
        "network_key": seed["network_key"],
        "asset": seed["asset"],
        "seed_address": seed["address"],
        "seed_event_reference": seed["event_reference"],
        "target_address": target_address,
        "observed_transaction_hashes": tx_hashes,
        "observed_transaction_count": len(tx_hashes),
        "note": (
            "This is the identifier set observed within this trace's declared "
            "scope, not a claim of every transaction the target address has "
            "ever made. See the evidence export bundle "
            "(POST /api/v1/traces/export) for the full transfer list in "
            "copiable CSV format, per the provider guide's own request for "
            "identifiers 'in a copiable format (e.g., csv)'."
        ),
    }


def _build_checklist(
    *,
    request_kind: RequestKind,
    result: dict[str, Any],
    target: RequestDraftTarget,
    requesting_agency: str,
    requesting_officer: str,
    case_reference: str,
    alleged_incident_summary: str,
    legal_authority_reference: str | None,
    exchange_account_identifiers: str | None,
) -> tuple[ChecklistField, ...]:
    seed_transfer = result.get("seed_transfer")
    investigation_amount = (
        f"{seed_transfer['amount_display']} {seed_transfer['asset']['display_symbol']}"
        if seed_transfer
        else "not established -- no seed transfer recorded on this trace"
    )

    def field(
        key: str,
        label: str,
        value: str,
        required_by: ChecklistFieldSource,
        *,
        provided: bool = True,
    ) -> ChecklistField:
        return ChecklistField(
            key=key, label=label, value=value, provided=provided, required_by=required_by
        )

    return (
        field(
            "requesting_agency",
            "Full name of the requesting agency and its official contact information",
            requesting_agency,
            "provider",
        ),
        field(
            "requesting_officer",
            "Requesting officer (this project's own accountability field -- not "
            "itself required by the cited provider guide, which asks only for "
            "agency-level authorisation)",
            requesting_officer,
            "internal",
        ),
        field(
            "case_reference",
            "Case reference",
            case_reference,
            "internal",
        ),
        field(
            "legal_authority_reference",
            "A signed court order and/or official request letter on agency "
            "letterhead, or other documentation evidencing authority to make "
            "this request",
            legal_authority_reference or "NOT PROVIDED -- required before this draft may be sent",
            "provider",
            provided=bool(legal_authority_reference and legal_authority_reference.strip()),
        ),
        field(
            "items_requested",
            "Specific actions/items requested",
            _ITEMS_REQUESTED_TEXT[request_kind],
            "provider",
        ),
        field(
            "alleged_incident_overview",
            "Overview of the alleged incident under investigation",
            alleged_incident_summary,
            "provider",
        ),
        field(
            "investigation_findings_to_date",
            "Investigation findings to date (auto-filled from this trace's own "
            "recorded facts, not free text)",
            (
                f"Forward trace from {result['seed']['address']} reached "
                f"{target.address} ({target.endpoint_class}, "
                f"attribution_status={target.attribution_status}) within the "
                "declared trace scope. See the attached evidence export "
                "bundle for the full observed path."
            ),
            "provider",
        ),
        field(
            "total_investigation_amount",
            "Total investigation amount",
            investigation_amount,
            "provider",
        ),
        field(
            "exchange_account_identifiers",
            "Relevant provider user name, account number, phone number, "
            "email address, or identification number, if known",
            exchange_account_identifiers or "NOT PROVIDED -- not yet established",
            "provider",
            provided=bool(exchange_account_identifiers and exchange_account_identifiers.strip()),
        ),
        field(
            "wallet_and_transaction_identifiers",
            "All available identifiers: relevant wallet address(es) and "
            "transaction hashes, in a copiable format",
            f"{target.address} -- see the identifiers block and the evidence "
            "export bundle for the full transaction-hash list",
            "provider",
        ),
    )


def build_request_draft(
    result: dict[str, Any],
    *,
    request_kind: RequestKind,
    target_address: str,
    requesting_agency: str,
    requesting_officer: str,
    case_reference: str,
    alleged_incident_summary: str,
    legal_authority_reference: str | None = None,
    exchange_account_identifiers: str | None = None,
    generated_at: dt.datetime | None = None,
) -> RequestDraft:
    """Build one request draft. Pure function: no I/O, no network, no send.

    Raises ``RequestDraftError`` for a caller error (a blank required field,
    or a target address this trace never actually reached). Returns a draft
    with ``status="refused"`` -- never an exception -- for the pooled-wallet
    asset-restriction case: that is a correct, expected, inspectable outcome,
    not a bug in the caller's request.
    """
    if request_kind not in REQUEST_KINDS:
        raise RequestDraftError(f"unknown request_kind: {request_kind!r}")

    requesting_agency = _require(requesting_agency, "requesting_agency")
    requesting_officer = _require(requesting_officer, "requesting_officer")
    case_reference = _require(case_reference, "case_reference")
    alleged_incident_summary = _require(alleged_incident_summary, "alleged_incident_summary")

    branch = _find_branch_ending(result, target_address)
    if branch is None:
        raise RequestDraftError(
            f"{target_address} is not a branch ending in this trace result; a "
            "request draft must name an address the trace actually reached"
        )

    label = branch.get("label") or {}
    target = RequestDraftTarget(
        address=branch["address"],
        network_key=result["seed"]["network_key"],
        endpoint_class=branch["endpoint_class"],
        attribution_status=branch["attribution_status"],
        address_role=label.get("address_role"),
        review_state=label.get("review_state"),
        entity_name=label.get("entity_name"),
    )

    refusal_reason: str | None = None
    if request_kind == KIND_ASSET_RESTRICTION:
        refusal_reason = _asset_restriction_refusal_reason(target, label_present=bool(label))

    checklist = _build_checklist(
        request_kind=request_kind,
        result=result,
        target=target,
        requesting_agency=requesting_agency,
        requesting_officer=requesting_officer,
        case_reference=case_reference,
        alleged_incident_summary=alleged_incident_summary,
        legal_authority_reference=legal_authority_reference,
        exchange_account_identifiers=exchange_account_identifiers,
    )

    return RequestDraft(
        status=STATUS_REFUSED if refusal_reason else STATUS_DRAFTED,
        request_kind=request_kind,
        refusal_reason=refusal_reason,
        target=target,
        checklist=checklist,
        identifiers=_collect_identifiers(result, target_address),
        checklist_source=CHECKLIST_SOURCE,
        draft_marker=DRAFT_MARKER,
        generated_at=(generated_at or dt.datetime.now(dt.UTC)).isoformat(),
    )
