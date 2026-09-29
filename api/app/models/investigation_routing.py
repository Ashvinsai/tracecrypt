"""Domain models for System-1 investigation routing (Task 08).

Defines:
- Predefined canonical investigation action vocabulary and risk classes.
- Compact, deterministic investigation state (local vs model-facing).
- Action eligibility filter and policy guard definitions.
- Official Choice wire models and audit records.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

ACTION_CATALOG_VERSION = "1.1.0"
STATE_SCHEMA_VERSION = "1.2.0"
ROUTING_POLICY_VERSION = "1.2.0"


class ServiceLookupStatus(StrEnum):
    """Status of reviewed VASP service-anchor lookup for the terminal address."""

    not_checked = "not_checked"
    no_match = "no_match"
    match_found = "match_found"


class InvestigationActionKey(StrEnum):
    """Predefined canonical investigation action vocabulary."""

    CONTINUE_SAME_CHAIN = "CONTINUE_SAME_CHAIN"
    FOLLOW_CROSS_CHAIN_LINK = "FOLLOW_CROSS_CHAIN_LINK"
    CHECK_REVIEWED_VASP = "CHECK_REVIEWED_VASP"
    REVIEW_VASP_CANDIDATE = "REVIEW_VASP_CANDIDATE"
    VERIFY_EXECUTION_RECEIPT = "VERIFY_EXECUTION_RECEIPT"
    RETRY_PROVIDER = "RETRY_PROVIDER"
    STOP_COVERAGE_GAP = "STOP_COVERAGE_GAP"
    REQUEST_HUMAN_REVIEW = "REQUEST_HUMAN_REVIEW"
    GENERATE_EVIDENCE_REPORT = "GENERATE_EVIDENCE_REPORT"


class RiskClass(StrEnum):
    """Action risk classification.

    Actions classified as FORBIDDEN must be rejected unconditionally by the policy guard.
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    FORBIDDEN = "FORBIDDEN"


class PolicyGuardDecision(StrEnum):
    """Authorization decision issued by ActionPolicyGuard."""

    ALLOWED = "ALLOWED"
    REJECTED = "REJECTED"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"


class RouterMode(StrEnum):
    """Supported investigation router modes."""

    rules = "rules"
    shadow_clm = "shadow_clm"
    clm_assisted = "clm_assisted"


class ShadowStatus(StrEnum):
    """Execution status of CLM in shadow mode."""

    success = "success"
    failed = "failed"
    not_configured = "not_configured"


@dataclass(frozen=True)
class InvestigationAction:
    """Typed investigation action definition.

    Immutable and stable for contrastive ranking and embedding caching.
    """

    key: str
    description: str
    prerequisites: tuple[str, ...]
    risk_class: RiskClass
    requires_human_review: bool
    executable: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "description": self.description,
            "prerequisites": list(self.prerequisites),
            "risk_class": self.risk_class.value,
            "requires_human_review": self.requires_human_review,
            "executable": self.executable,
        }


@dataclass(frozen=True)
class InvestigationState:
    """Investigation state extracted from trace evidence.

    Contains local contextual state as well as model-facing derived state.
    Terminal addresses and token contracts are local-only and redacted from CLM serialization.
    """

    # Case context
    network: str
    asset_symbol: str
    asset_contract: str | None

    # Trace topology
    hop_depth: int
    branch_count: int
    unresolved_branch_count: int
    has_supported_vasp_boundary: bool
    has_vasp_candidate: bool
    has_bridge_boundary: bool

    # Coverage & budget
    coverage_status: str
    provider_error_class: str
    request_budget_remaining: bool

    # Execution & finality
    receipt_verified: bool
    finality_state: str

    # Cross-chain continuation facts
    cross_chain_protocol: str
    cross_chain_status: str
    cross_chain_link_available: bool
    cross_chain_continuation_pending: bool
    destination_network_known: bool
    destination_network: str | None
    destination_execution_verified: bool
    destination_trace_started: bool
    destination_trace_complete: bool

    # Attribution
    reviewed_service_control_available: bool
    candidate_only: bool
    no_attribution_evidence: bool

    # Review & readiness
    human_review_required: bool
    report_ready: bool

    # Service lookup state (Task 08C-B2)
    service_lookup_status: str = ServiceLookupStatus.not_checked.value

    # Local context only (never sent to model)
    terminal_address: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GuardResult:
    """Evaluation result for one action evaluated against policy."""

    action_key: str
    decision: PolicyGuardDecision
    reason: str
    prerequisites_satisfied: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_key": self.action_key,
            "decision": self.decision.value,
            "reason": self.reason,
            "prerequisites_satisfied": self.prerequisites_satisfied,
        }


@dataclass(frozen=True)
class RankedAction:
    """Action scored by a router."""

    action: str
    score: float
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "score": self.score,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RoutingResult:
    """Internal result returned by a router before policy guarding."""

    router_name: str
    ranked_actions: tuple[RankedAction, ...]
    latency_ms: float
    configured_model: str | None = None
    response_model: str | None = None
    relative_action_probabilities: dict[str, float] | None = None
    chosen_action: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RoutingDecision:
    """Complete audit record of an investigation routing decision.

    Labeled as DECISION_SUPPORT_METADATA, never blockchain evidence.
    """

    router_requested: str
    router_used: str
    shadow_status: str
    clm_available: bool
    state_schema_version: str
    action_catalog_version: str
    serialized_state_hash: str
    candidate_action_set_hash: str
    routing_input_hash: str
    candidate_actions: tuple[str, ...]
    rule_ranked_actions: tuple[RankedAction, ...]
    actual_selected_action: str | None
    guard_results: dict[str, GuardResult]
    routing_policy_version: str = ROUTING_POLICY_VERSION
    artifact_class: str = "DECISION_SUPPORT_METADATA"
    shadow_clm_choice: str | None = None
    shadow_clm_probabilities: dict[str, float] | None = None
    shadow_agreement: bool | None = None
    shadow_failure_reason: str | None = None
    configured_model: str | None = None
    response_model: str | None = None
    latency_ms: float = 0.0
    generated_at: str = field(
        default_factory=lambda: dt.datetime.now(dt.UTC).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_class": self.artifact_class,
            "notice": "DECISION SUPPORT METADATA - NOT BLOCKCHAIN EVIDENCE",
            "router_requested": self.router_requested,
            "router_used": self.router_used,
            "shadow_status": self.shadow_status,
            "shadow_failure_reason": self.shadow_failure_reason,
            "clm_available": self.clm_available,
            "state_schema_version": self.state_schema_version,
            "action_catalog_version": self.action_catalog_version,
            "routing_policy_version": self.routing_policy_version,
            "serialized_state_hash": self.serialized_state_hash,
            "candidate_action_set_hash": self.candidate_action_set_hash,
            "routing_input_hash": self.routing_input_hash,
            "candidate_actions": list(self.candidate_actions),
            "rule_ranked_actions": [a.to_dict() for a in self.rule_ranked_actions],
            "actual_selected_action": self.actual_selected_action,
            "shadow_clm_choice": self.shadow_clm_choice,
            "shadow_clm_probabilities": self.shadow_clm_probabilities,
            "shadow_agreement": self.shadow_agreement,
            "configured_model": self.configured_model,
            "response_model": self.response_model,
            "guard_results": {k: v.to_dict() for k, v in self.guard_results.items()},
            "latency_ms": self.latency_ms,
            "generated_at": self.generated_at,
        }
