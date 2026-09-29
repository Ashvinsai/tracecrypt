"""The trace result contract.

One object, consumed by the API, the evidence report, and the frontend. If the
report and the screen can disagree, one of them is wrong, so they read the same
structure.

Amounts serialize as strings (D004). The four status axes stay separate (D006).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from app.core.amounts import serialize, to_display
from app.core.settings import DataMode
from app.models.enums import (
    AttributionStatus,
    BoundaryReason,
    CaseAmountBasis,
    CaseFlowLinkage,
    CoverageStatus,
)


class EndpointClass(StrEnum):
    """How a branch ended. These are not interchangeable (PRD section 3)."""

    known_service = "known_service"
    deposit_candidate = "deposit_candidate"
    unresolved = "unresolved"
    boundary = "boundary"


@dataclass(frozen=True)
class ObservedTransfer:
    """One observed edge. Everything here came from a provider, nothing inferred."""

    event_reference: str
    tx_hash: str
    from_address: str | None
    to_address: str | None
    amount_base_units: int
    asset_contract: str | None
    asset_decimals: int
    asset_symbol: str
    block_time: dt.datetime | None
    chain_sequence: str | None
    ordering_ambiguous: bool
    execution_status: str
    confirmation_state: str
    hop_depth: int
    acquisition_id: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "event_reference": self.event_reference,
            "tx_hash": self.tx_hash,
            "from_address": self.from_address,
            "to_address": self.to_address,
            "amount_base_units": serialize(self.amount_base_units),
            "amount_display": to_display(self.amount_base_units, self.asset_decimals),
            "asset": {
                "token_contract": self.asset_contract,
                "decimals": self.asset_decimals,
                "display_symbol": self.asset_symbol,
            },
            "block_time": self.block_time.isoformat() if self.block_time else None,
            "chain_sequence": self.chain_sequence,
            "ordering_ambiguous": self.ordering_ambiguous,
            "execution_status": self.execution_status,
            "confirmation_state": self.confirmation_state,
            "hop_depth": self.hop_depth,
            "acquisition_id": self.acquisition_id,
        }


@dataclass
class LabelEvidence:
    """Why an address carries a name. A label without this is not displayable."""

    entity_name: str
    entity_type: str
    assertion_type: str
    address_role: str
    review_state: str
    source_reference: str
    retrieval_date: str | None
    methodology: str
    reviewer: str | None
    valid_from: str | None
    valid_to: str | None
    last_verified_at: str | None
    label_set_version: str
    #: Where the claim came from and who accepted it. Empty for the synthetic
    #: fixture set, which nothing reviewed.
    source_hash: str | None = None
    source_file: str | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    label_source: str | None = None
    #: The publication the claim was cut from, when the imported file was a
    #: selection rather than the document itself (D022).
    original_reference: str | None = None
    original_hash: str | None = None
    original_member: str | None = None
    original_row_locator: str | None = None

    @property
    def review_reference(self) -> str | None:
        """Points into ``review_log.csv``: which decision, on which document."""
        if not self.source_hash or not self.reviewed_at:
            return None
        return f"{self.source_hash[:16]}@{self.reviewed_at}"

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["review_reference"] = self.review_reference
        return data


@dataclass
class BranchEnding:
    """Where one branch stopped, and why."""

    address: str
    endpoint_class: EndpointClass
    attribution_status: AttributionStatus
    boundary_reason: BoundaryReason | None
    hop_depth: int
    branch_path: list[str]
    arrival_event_reference: str | None
    observed_amount_base_units: int | None
    asset_decimals: int
    label: LabelEvidence | None = None
    note: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "endpoint_class": self.endpoint_class.value,
            "attribution_status": self.attribution_status.value,
            "boundary_reason": self.boundary_reason.value if self.boundary_reason else None,
            "hop_depth": self.hop_depth,
            "branch_path": self.branch_path,
            "arrival_event_reference": self.arrival_event_reference,
            "observed_amount_base_units": serialize(self.observed_amount_base_units),
            "observed_amount_display": (
                to_display(self.observed_amount_base_units, self.asset_decimals)
                if self.observed_amount_base_units is not None
                else None
            ),
            # Deliberately separate from the observed amount. An observed path is
            # a sequence of transfers, not ownership of fungible units.
            "case_amount_basis": CaseAmountBasis.allocation_unknown.value,
            "label": self.label.to_json() if self.label else None,
            "note": self.note,
        }


@dataclass
class Limitation:
    """Something the run could not establish. Never omitted to make a result look clean."""

    code: str
    message: str
    address: str | None = None
    event_reference: str | None = None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BudgetUse:
    """How much of the tracer's own hop-walk budget this run used.

    ``traversal_requests`` counts only the tracer's own forward-walk pages
    (``ChronologicalTracer._collect_outgoing``) against ``traversal_request_
    limit`` (``Settings.budget_max_provider_requests``). It does not include
    the seed-event search, enrichment, or receipt verification a live
    validation also performs -- those are a separate acquisition total,
    reported elsewhere (the live-validation manifest's
    ``provider_exchanges``). A direct seed-to-anchor trace that terminates at
    hop 0 never calls the hop walk at all, so this reads 0 even though real
    requests were made to find and verify the seed.
    """

    hops_used: int = 0
    events_examined: int = 0
    traversal_requests: int = 0
    elapsed_seconds: float = 0.0
    hop_limit: int = 0
    event_limit: int = 0
    traversal_request_limit: int = 0
    wall_clock_limit_seconds: int = 0

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["note"] = "budgets are configuration targets, not measured performance"
        return data


@dataclass
class TraceResult:
    """The whole answer, including everything it could not answer."""

    seed_address: str
    seed_event_reference: str | None
    network_key: str
    asset_contract: str | None
    asset_symbol: str
    asset_decimals: int
    data_mode: DataMode
    analysis_cutoff: dt.datetime
    started_at: dt.datetime
    finished_at: dt.datetime | None
    engine_version: str
    label_set_version: str
    coverage_status: CoverageStatus
    case_flow_linkage: CaseFlowLinkage
    #: The seed transfer itself, when the run was started from an explicit
    #: event. It is the case link, not an onward hop, so it is reported
    #: separately from ``observed_transfers`` (a direct seed-to-boundary trace
    #: has zero onward transfers but exactly one seed transfer).
    analysis_start: dt.datetime | None = None
    seed_transfer: ObservedTransfer | None = None
    observed_transfers: list[ObservedTransfer] = field(default_factory=list)
    branch_endings: list[BranchEnding] = field(default_factory=list)
    limitations: list[Limitation] = field(default_factory=list)
    budget_use: BudgetUse = field(default_factory=BudgetUse)
    acquisitions: list[dict[str, Any]] = field(default_factory=list)
    #: Which label files were read, their hashes and row counts. Saved with the
    #: result so a reopened report does not depend on today's CSV.
    label_snapshot: dict[str, Any] = field(default_factory=dict)
    #: Protocol-verifiable cross-chain links across network boundaries (Task 07).
    #: Reported as explicit boundary transitions, never as same-chain transfers.
    cross_chain_links: list[dict[str, Any]] = field(default_factory=list)

    @property
    def supported_destinations(self) -> list[BranchEnding]:
        return [b for b in self.branch_endings if b.endpoint_class is EndpointClass.known_service]

    @property
    def candidate_destinations(self) -> list[BranchEnding]:
        return [
            b for b in self.branch_endings if b.endpoint_class is EndpointClass.deposit_candidate
        ]

    def to_json(self) -> dict[str, Any]:
        return {
            "seed": {
                "address": self.seed_address,
                "event_reference": self.seed_event_reference,
                "network_key": self.network_key,
                "asset": {
                    "token_contract": self.asset_contract,
                    "display_symbol": self.asset_symbol,
                    "decimals": self.asset_decimals,
                },
            },
            "scope": {
                "data_mode": self.data_mode.value,
                "analysis_cutoff": self.analysis_cutoff.isoformat(),
                "analysis_start": self.analysis_start.isoformat() if self.analysis_start else None,
                "started_at": self.started_at.isoformat(),
                "finished_at": self.finished_at.isoformat() if self.finished_at else None,
                "engine_version": self.engine_version,
                "label_set_version": self.label_set_version,
                "coverage_status": self.coverage_status.value,
                "case_flow_linkage": self.case_flow_linkage.value,
                "label_snapshot": self.label_snapshot,
            },
            "seed_transfer": self.seed_transfer.to_json() if self.seed_transfer else None,
            "observed_transfers": [t.to_json() for t in self.observed_transfers],
            "branch_endings": [b.to_json() for b in self.branch_endings],
            "cross_chain_links": self.cross_chain_links,
            "limitations": [x.to_json() for x in self.limitations],
            "budget_use": self.budget_use.to_json(),
            "acquisitions": self.acquisitions,
            "disclaimer": (
                "An observed path establishes a sequence of transfers, not ownership of "
                "fungible units. Case-associated amounts default to allocation_unknown. "
                "This output does not identify a person, establish guilt, or authorise a freeze."
            ),
        }
