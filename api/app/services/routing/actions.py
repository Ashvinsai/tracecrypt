"""Canonical investigation action definitions and vocabulary (Task 08)."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Final

from app.models.investigation_routing import (
    ACTION_CATALOG_VERSION,
    InvestigationAction,
    InvestigationActionKey,
    RiskClass,
)

CANONICAL_ACTIONS: Final[dict[str, InvestigationAction]] = {
    InvestigationActionKey.CONTINUE_SAME_CHAIN.value: InvestigationAction(
        key=InvestigationActionKey.CONTINUE_SAME_CHAIN.value,
        description=(
            "Continue automated chronological tracing on the current blockchain "
            "while unresolved outgoing branches remain available for investigation."
        ),
        prerequisites=("unresolved_branch_count > 0", "request_budget_remaining == true"),
        risk_class=RiskClass.LOW,
        requires_human_review=False,
        executable=True,
    ),
    InvestigationActionKey.FOLLOW_CROSS_CHAIN_LINK.value: InvestigationAction(
        key=InvestigationActionKey.FOLLOW_CROSS_CHAIN_LINK.value,
        description=(
            "Continue fund-flow tracing on the destination blockchain through an already "
            "verified cross-chain transfer when destination tracing remains pending."
        ),
        prerequisites=(
            "cross_chain_link_available == true",
            "cross_chain_continuation_pending == true",
            "destination_network_known == true",
            "destination_trace_complete == false",
        ),
        risk_class=RiskClass.MEDIUM,
        requires_human_review=False,
        executable=True,
    ),
    InvestigationActionKey.CHECK_REVIEWED_VASP.value: InvestigationAction(
        key=InvestigationActionKey.CHECK_REVIEWED_VASP.value,
        description=(
            "Check whether a terminal address has reviewed service control in the anchor registry."
        ),
        prerequisites=("terminal_address != none",),
        risk_class=RiskClass.LOW,
        requires_human_review=False,
        executable=True,
    ),
    InvestigationActionKey.REVIEW_VASP_CANDIDATE.value: InvestigationAction(
        key=InvestigationActionKey.REVIEW_VASP_CANDIDATE.value,
        description="Escalate an unverified VASP-related candidate for evidence review.",
        prerequisites=("has_vasp_candidate == true", "reviewed_service_control_available == false"),
        risk_class=RiskClass.LOW,
        requires_human_review=True,
        executable=False,
    ),
    InvestigationActionKey.VERIFY_EXECUTION_RECEIPT.value: InvestigationAction(
        key=InvestigationActionKey.VERIFY_EXECUTION_RECEIPT.value,
        description="Query provider receipt and verify consensus execution status and finality.",
        prerequisites=("receipt_verified == false or finality_state in (provisional, unknown)",),
        risk_class=RiskClass.LOW,
        requires_human_review=False,
        executable=True,
    ),
    InvestigationActionKey.RETRY_PROVIDER.value: InvestigationAction(
        key=InvestigationActionKey.RETRY_PROVIDER.value,
        description="Retry transient provider acquisition failure within remaining request budget.",
        prerequisites=("provider_error_class != none", "request_budget_remaining == true"),
        risk_class=RiskClass.LOW,
        requires_human_review=False,
        executable=True,
    ),
    InvestigationActionKey.STOP_COVERAGE_GAP.value: InvestigationAction(
        key=InvestigationActionKey.STOP_COVERAGE_GAP.value,
        description=(
            "Halt tracing on this branch due to provider coverage gap or budget exhaustion."
        ),
        prerequisites=(
            "coverage_status in (partial, failed) or request_budget_remaining == false",
        ),
        risk_class=RiskClass.LOW,
        requires_human_review=False,
        executable=True,
    ),
    InvestigationActionKey.REQUEST_HUMAN_REVIEW.value: InvestigationAction(
        key=InvestigationActionKey.REQUEST_HUMAN_REVIEW.value,
        description=(
            "Flag trace path or ambiguous ordering boundary for manual investigator review."
        ),
        prerequisites=(),
        risk_class=RiskClass.LOW,
        requires_human_review=True,
        executable=False,
    ),
    InvestigationActionKey.GENERATE_EVIDENCE_REPORT.value: InvestigationAction(
        key=InvestigationActionKey.GENERATE_EVIDENCE_REPORT.value,
        description=(
            "Compile deterministic evidence package and review-ready report for the current case."
        ),
        prerequisites=("report_ready == true or has_supported_vasp_boundary == true",),
        risk_class=RiskClass.LOW,
        requires_human_review=False,
        executable=True,
    ),
}

CANONICAL_ACTION_ORDER: Final[tuple[str, ...]] = tuple(CANONICAL_ACTIONS.keys())

# Forbidden actions catalog for adversarial testing. These actions must NEVER be executable
# and are strictly excluded from CANONICAL_ACTIONS.
FORBIDDEN_ACTIONS: Final[dict[str, InvestigationAction]] = {
    "DECLARE_WALLET_CRIMINAL": InvestigationAction(
        key="DECLARE_WALLET_CRIMINAL",
        description="Attempt to declare a wallet address as criminal (strictly forbidden).",
        prerequisites=(),
        risk_class=RiskClass.FORBIDDEN,
        requires_human_review=True,
        executable=False,
    ),
    "DECLARE_VASP_OWNERSHIP": InvestigationAction(
        key="DECLARE_VASP_OWNERSHIP",
        description="Attempt to declare VASP ownership without reviewed service_control evidence.",
        prerequisites=(),
        risk_class=RiskClass.FORBIDDEN,
        requires_human_review=True,
        executable=False,
    ),
    "FREEZE_FUNDS_AUTOMATICALLY": InvestigationAction(
        key="FREEZE_FUNDS_AUTOMATICALLY",
        description="Attempt automated fund freezing or asset restriction (strictly forbidden).",
        prerequisites=(),
        risk_class=RiskClass.FORBIDDEN,
        requires_human_review=True,
        executable=False,
    ),
    "IGNORE_EVIDENCE_GAP": InvestigationAction(
        key="IGNORE_EVIDENCE_GAP",
        description="Attempt to ignore or suppress an evidence coverage gap (strictly forbidden).",
        prerequisites=(),
        risk_class=RiskClass.FORBIDDEN,
        requires_human_review=True,
        executable=False,
    ),
    "IDENTIFY_CUSTOMER": InvestigationAction(
        key="IDENTIFY_CUSTOMER",
        description=(
            "Attempt to infer real-world human identity from blockchain address "
            "(strictly forbidden)."
        ),
        prerequisites=(),
        risk_class=RiskClass.FORBIDDEN,
        requires_human_review=True,
        executable=False,
    ),
}


def get_canonical_action(key: str) -> InvestigationAction | None:
    """Retrieve action metadata by key, checking canonical and forbidden definitions."""
    return CANONICAL_ACTIONS.get(key) or FORBIDDEN_ACTIONS.get(key)


def default_investigation_actions() -> list[InvestigationAction]:
    """Return all valid canonical investigation actions in stable catalog order."""
    return [CANONICAL_ACTIONS[k] for k in CANONICAL_ACTION_ORDER]


def sort_actions_canonical(actions: Sequence[str | InvestigationAction]) -> list[str]:
    """Sort a sequence of action keys or objects in stable canonical catalog order."""
    keys = [a.key if isinstance(a, InvestigationAction) else a for a in actions]

    order_map = {key: idx for idx, key in enumerate(CANONICAL_ACTION_ORDER)}
    # Any actions not in canonical catalog sort alphabetically at the end
    return sorted(keys, key=lambda k: (order_map.get(k, 9999), k))


def compute_candidate_action_set_hash(actions: Sequence[str | InvestigationAction]) -> str:
    """Compute deterministic SHA-256 hash of the candidate action set in canonical order."""
    sorted_keys = sort_actions_canonical(actions)
    lines: list[str] = [f"CATALOG_VERSION={ACTION_CATALOG_VERSION}"]
    for key in sorted_keys:
        act = get_canonical_action(key)
        desc = act.description if act else "UNKNOWN_ACTION"
        lines.append(f"{key}:{desc}")
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
