"""Canonical enumerations (design/SCHEMA_AND_API.md).

The four status axes are deliberately separate types. Collapsing them into a
single confidence score is the failure mode this project exists to avoid (D006).
"""

from __future__ import annotations

from enum import StrEnum


class NetworkFamily(StrEnum):
    account = "account"
    utxo = "utxo"


class AssetKind(StrEnum):
    native = "native"
    token = "token"  # noqa: S105 - an asset kind, not a credential


class ExecutionStatus(StrEnum):
    success = "success"
    failed = "failed"
    reverted = "reverted"
    unknown = "unknown"


class ConfirmationState(StrEnum):
    provisional = "provisional"
    confirmed = "confirmed"
    removed = "removed"
    unknown = "unknown"


class CoverageStatus(StrEnum):
    complete_within_scope = "complete_within_scope"
    partial = "partial"
    unknown = "unknown"
    failed = "failed"


class AttributionStatus(StrEnum):
    supported = "supported"
    inferred = "inferred"
    candidate = "candidate"
    conflicted = "conflicted"
    unresolved = "unresolved"
    unsupported = "unsupported"


class CaseFlowLinkage(StrEnum):
    established = "established"
    partial = "partial"
    not_established = "not_established"
    ambiguous = "ambiguous"


class BoundaryReason(StrEnum):
    service_boundary = "service_boundary"
    hop_limit = "hop_limit"
    event_limit = "event_limit"
    time_limit = "time_limit"
    api_budget = "api_budget"
    unsupported_asset_change = "unsupported_asset_change"
    bridge = "bridge"
    privacy_mechanism = "privacy_mechanism"
    opaque_contract = "opaque_contract"
    no_outgoing_activity = "no_outgoing_activity"
    ambiguous_ordering = "ambiguous_ordering"
    cancelled = "cancelled"
    provider_failure = "provider_failure"


class EventKind(StrEnum):
    transfer = "transfer"
    approval = "approval"
    internal_transfer = "internal_transfer"
    contract_call = "contract_call"
    unknown = "unknown"


class ResourceType(StrEnum):
    """TRON stakeable resources. The account index endpoint names neither."""

    energy = "energy"
    bandwidth = "bandwidth"


class DelegationBasis(StrEnum):
    """What a delegation record rests on.

    ``current_state`` comes from a state query and carries no start time; only
    ``historical_operation`` can date anything (day-one test 12).
    """

    current_state = "current_state"
    historical_operation = "historical_operation"


class EntityType(StrEnum):
    exchange = "exchange"
    custodial_service = "custodial_service"
    payment_processor = "payment_processor"
    mixer = "mixer"
    bridge = "bridge"
    merchant = "merchant"
    gambling = "gambling"
    sanctioned_entity = "sanctioned_entity"
    unknown = "unknown"


class AddressRole(StrEnum):
    deposit = "deposit"
    hot_wallet = "hot_wallet"
    cold_reserve = "cold_reserve"
    withdrawal = "withdrawal"
    settlement = "settlement"
    unknown = "unknown"


class AssertionType(StrEnum):
    service_control = "service_control"
    deposit_candidate = "deposit_candidate"
    complaint_allegation = "complaint_allegation"
    public_abuse_report = "public_abuse_report"
    sanctions_tag = "sanctions_tag"


class ReviewState(StrEnum):
    unreviewed = "unreviewed"
    accepted = "accepted"
    rejected = "rejected"
    quarantined = "quarantined"
    conflicted = "conflicted"


class AcquisitionStatus(StrEnum):
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"
    partial = "partial"


class SeedMode(StrEnum):
    incident = "incident"
    address_discovery = "address_discovery"


class TraceRunStatus(StrEnum):
    queued = "queued"
    running = "running"
    partial = "partial"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class WatchPollStatus(StrEnum):
    """Outcome of one bounded monitoring poll. Only ``succeeded`` advances a checkpoint.

    ``provider_failure`` is never reported as a successful poll with zero new
    events (T3); ``truncated`` means the page budget ended the window early.
    """

    running = "running"
    succeeded = "succeeded"
    partial = "partial"
    provider_failure = "provider_failure"
    truncated = "truncated"
    refused = "refused"


class AlertState(StrEnum):
    """An alert is retracted, never deleted, when later evidence undoes it (T7)."""

    active = "active"
    retracted = "retracted"


class CaseAmountBasis(StrEnum):
    """How a case-associated amount was derived. Default is honest ignorance."""

    allocation_unknown = "allocation_unknown"
    direct_seed_transfer = "direct_seed_transfer"
    bounded_estimate = "bounded_estimate"
