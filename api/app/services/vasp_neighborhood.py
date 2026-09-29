"""Deterministic, report-only candidate observations around a reviewed anchor."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from app.models.enums import AssertionType, ReviewState
from app.services.labels import Anchor

POLICY_VERSION = "1"
NOT_SERVICE_CONTROL_REASON = (
    "This relationship is a candidate generated from observed transactions; "
    "it does not establish service ownership, address role, customer identity, "
    "common control, fraud, or unique fund ownership. Only an independently "
    "evidence-backed, human-reviewed service_control claim can establish that."
)


@dataclass(frozen=True)
class NeighborhoodObservation:
    network: str
    token_contract: str
    event_reference: str
    tx_hash: str
    event_index: int | None
    source_address: str
    target_address: str
    amount_base_units: int
    block_time: dt.datetime
    execution_status: str
    confirmation_state: str
    ordering_ambiguous: bool
    direction: str


@dataclass(frozen=True)
class NeighborhoodRequest:
    anchor_address: str
    token_contract: str
    network: str
    window_start: dt.datetime
    window_end: dt.datetime
    max_requests: int
    page_limit: int
    event_limit: int
    address_limit: int
    pages_per_address: int = 2
    verify_execution: bool = True
    enrich_events: bool = True

    def __post_init__(self) -> None:
        if self.network != "tron":
            raise ValueError("the first neighborhood discovery supports TRON only")
        if self.window_start > self.window_end:
            raise ValueError("window_start must not be after window_end")
        if min(
            self.max_requests,
            self.page_limit,
            self.event_limit,
            self.address_limit,
            self.pages_per_address,
        ) < 1:
            raise ValueError("all discovery budgets must be positive")


@dataclass(frozen=True)
class NeighborhoodCoverage:
    complete: bool
    window_start: dt.datetime
    window_end: dt.datetime
    requests_used: int = 0
    max_requests: int = 0
    page_limit: int = 0
    pages_used: int = 0
    address_limit: int = 0
    pages_per_address: int = 0
    addresses_examined: int = 0
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class NeighborhoodCandidate:
    address: str
    network: str
    token_contract: str
    relationship_type: str
    anchor_address: str
    anchor_entity_name: str
    first_observed_at: dt.datetime
    last_observed_at: dt.datetime
    evidence_references: tuple[str, ...]
    features: dict[str, Any]
    matched_rules: tuple[str, ...]
    coverage_complete: bool
    limitations: tuple[str, ...]
    policy_version: str
    review_status: str
    human_reviewed: bool
    not_service_control_reason: str

    def to_json(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "network": self.network,
            "token_contract": self.token_contract,
            "relationship_type": self.relationship_type,
            "anchor": {
                "address": self.anchor_address,
                "entity_name": self.anchor_entity_name,
            },
            "first_observed_at": self.first_observed_at.isoformat(),
            "last_observed_at": self.last_observed_at.isoformat(),
            "evidence_references": list(self.evidence_references),
            "features": self.features,
            "matched_rules": list(self.matched_rules),
            "coverage_complete": self.coverage_complete,
            "limitations": list(self.limitations),
            "policy_version": self.policy_version,
            "review_status": self.review_status,
            "human_reviewed": self.human_reviewed,
            "not_service_control_reason": self.not_service_control_reason,
        }


@dataclass(frozen=True)
class NeighborhoodResult:
    anchor_address: str
    anchor_entity_name: str
    anchor_source_reference: str
    anchor_source_hash: str | None
    anchor_valid_from: dt.datetime | None
    anchor_valid_to: dt.datetime | None
    network: str
    token_contract: str
    observation_window_start: dt.datetime
    observation_window_end: dt.datetime
    coverage: NeighborhoodCoverage
    policy_version: str
    candidates: tuple[NeighborhoodCandidate, ...]
    address_only_context: tuple[dict[str, Any], ...]
    excluded_observation_count: int
    limitations: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "report_type": "vasp_candidate_neighborhood",
            "policy_version": self.policy_version,
            "anchor": {
                "address": self.anchor_address,
                "entity_name": self.anchor_entity_name,
                "assertion_type": "service_control",
                "review_state": "accepted",
                "source_reference": self.anchor_source_reference,
                "source_hash": self.anchor_source_hash,
                "valid_from": (
                    self.anchor_valid_from.isoformat() if self.anchor_valid_from else None
                ),
                "valid_to": self.anchor_valid_to.isoformat() if self.anchor_valid_to else None,
            },
            "network": self.network,
            "token_contract": self.token_contract,
            "observation_window": {
                "start": self.observation_window_start.isoformat(),
                "end": self.observation_window_end.isoformat(),
            },
            "coverage": {
                "complete": self.coverage.complete,
                "requests_used": self.coverage.requests_used,
                "max_requests": self.coverage.max_requests,
                "page_limit": self.coverage.page_limit,
                "pages_used": self.coverage.pages_used,
                "address_limit": self.coverage.address_limit,
                "pages_per_address": self.coverage.pages_per_address,
                "addresses_examined": self.coverage.addresses_examined,
                "limitations": list(self.coverage.limitations),
            },
            "candidate_count": len(self.candidates),
            "candidates": [candidate.to_json() for candidate in self.candidates],
            "address_only_context": list(self.address_only_context),
            "excluded_observation_count": self.excluded_observation_count,
            "limitations": list(self.limitations),
            "disclaimer": NOT_SERVICE_CONTROL_REASON,
        }


def _require_accepted_anchor(anchor: Anchor) -> None:
    if (
        anchor.assertion_type is not AssertionType.service_control
        or anchor.review_state is not ReviewState.accepted
    ):
        raise ValueError("candidate neighborhoods require an accepted service_control anchor")


def generate_neighborhood(
    *,
    anchor: Anchor,
    network: str,
    token_contract: str,
    observations: list[NeighborhoodObservation],
    coverage: NeighborhoodCoverage,
) -> NeighborhoodResult:
    """Generate independent address candidates from explicit bounded observations."""
    _require_accepted_anchor(anchor)
    if network != anchor.network_key:
        raise ValueError("anchor and neighborhood network must match")
    if not token_contract:
        raise ValueError("token_contract is required")
    if coverage.window_start > coverage.window_end:
        raise ValueError("observation window start must not be after its end")

    excluded = 0
    by_address: dict[str, list[NeighborhoodObservation]] = {}
    address_only_context: list[dict[str, Any]] = []
    eligible_observations: list[NeighborhoodObservation] = []
    seen_event_ids: set[tuple[str, str]] = set()
    context_limitations: list[str] = list(coverage.limitations)
    for observation in observations:
        if observation.network != network or observation.token_contract != token_contract:
            excluded += 1
            continue
        if not coverage.window_start <= observation.block_time <= coverage.window_end:
            excluded += 1
            continue
        if observation.amount_base_units <= 0 or observation.confirmation_state == "removed":
            excluded += 1
            continue
        if observation.execution_status in {"failed", "reverted"}:
            excluded += 1
            continue
        if observation.ordering_ambiguous or observation.event_index is None:
            excluded += 1
            continue
        event_identity = (observation.network, observation.event_reference)
        if event_identity in seen_event_ids:
            excluded += 1
            continue
        seen_event_ids.add(event_identity)
        if observation.target_address == anchor.address and not anchor.covers(
            observation.block_time
        ):
            address_only_context.append(
                {
                    "address": observation.source_address,
                    "event_reference": observation.event_reference,
                    "observed_at": observation.block_time.isoformat(),
                    "direction": observation.direction,
                    "reason": "outside the reviewed service-control claim's validity interval",
                }
            )
            continue
        eligible_observations.append(observation)
        by_address.setdefault(observation.source_address, []).append(observation)

    candidate_addresses = sorted(
        {
            row.source_address
            for row in eligible_observations
            if row.target_address == anchor.address and anchor.covers(row.block_time)
        }
    )
    candidates: list[NeighborhoodCandidate] = []
    for address in candidate_addresses:
        out_to_anchor = [
            row
            for row in eligible_observations
            if row.source_address == address
            and row.target_address == anchor.address
            and anchor.covers(row.block_time)
        ]
        in_scope = out_to_anchor
        if not in_scope:
            continue
        ordered = sorted(in_scope, key=lambda row: (row.block_time, row.event_reference))
        repeated = len(ordered) >= 2
        relationship_supported = coverage.complete
        incoming_rows = [
            row
            for row in eligible_observations
            if row.direction == "incoming"
            and row.target_address == address
            and row.block_time < ordered[-1].block_time
        ]
        distinct_incoming_senders = {row.source_address for row in incoming_rows}
        is_collection = relationship_supported and repeated and len(distinct_incoming_senders) >= 2
        candidate_observations = [*ordered]
        if is_collection:
            candidate_observations.extend(incoming_rows)
        candidates.append(
            NeighborhoodCandidate(
                address=address,
                network=network,
                token_contract=token_contract,
                relationship_type=(
                    "collection_candidate"
                    if is_collection
                    else "service_neighbor_candidate"
                    if relationship_supported and repeated
                    else "deposit_candidate"
                    if relationship_supported
                    else "unresolved_candidate_relationship"
                ),
                anchor_address=anchor.address,
                anchor_entity_name=anchor.entity_name,
                first_observed_at=min(row.block_time for row in candidate_observations),
                last_observed_at=max(row.block_time for row in candidate_observations),
                evidence_references=tuple(
                    sorted({row.event_reference for row in candidate_observations})
                ),
                features={
                    "repeated_transfer_count": len(ordered),
                    "distinct_incoming_senders": len(distinct_incoming_senders),
                    "distinct_observation_dates": len({row.block_time.date() for row in ordered}),
                    "observed_amount_base_units": str(
                        sum(row.amount_base_units for row in ordered)
                    ),
                },
                matched_rules=(
                    ("distinct_sender_aggregation_then_repeated_anchor_forwarding",)
                    if is_collection
                    else ("repeated_outgoing_to_anchor",)
                    if relationship_supported and repeated
                    else ()
                ),
                coverage_complete=coverage.complete,
                limitations=tuple(context_limitations),
                policy_version=POLICY_VERSION,
                review_status="unreviewed",
                human_reviewed=False,
                not_service_control_reason=NOT_SERVICE_CONTROL_REASON,
            )
        )

    limitations = list(context_limitations)
    if address_only_context:
        limitations.append(
            "Transfers outside the reviewed anchor's validity interval are shown only as "
            "address-level context and are not attributed to the reviewed service."
        )
    if not coverage.complete:
        limitations.append(
            "Coverage is incomplete; candidates and omitted addresses are based only "
            "on observed rows."
        )
    return NeighborhoodResult(
        anchor_address=anchor.address,
        anchor_entity_name=anchor.entity_name,
        anchor_source_reference=anchor.source_reference,
        anchor_source_hash=anchor.source_hash,
        anchor_valid_from=anchor.valid_from,
        anchor_valid_to=anchor.valid_to,
        network=network,
        token_contract=token_contract,
        observation_window_start=coverage.window_start,
        observation_window_end=coverage.window_end,
        coverage=coverage,
        policy_version=POLICY_VERSION,
        candidates=tuple(candidates),
        address_only_context=tuple(
            sorted(
                address_only_context,
                key=lambda row: (row["observed_at"], row["event_reference"]),
            )
        ),
        excluded_observation_count=excluded,
        limitations=tuple(dict.fromkeys(limitations)),
    )
