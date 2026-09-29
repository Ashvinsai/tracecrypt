"""Tests for deterministic rule router and typed action vocabulary (Task 08)."""

from __future__ import annotations

from app.models.investigation_routing import (
    ACTION_CATALOG_VERSION,
    InvestigationAction,
    InvestigationActionKey,
    InvestigationState,
    RiskClass,
)
from app.services.routing.actions import (
    CANONICAL_ACTION_ORDER,
    default_investigation_actions,
    get_canonical_action,
)
from app.services.routing.rules import DeterministicRuleRouter


def _base_state(**kwargs) -> InvestigationState:
    defaults = {
        "network": "tron",
        "asset_symbol": "USDT",
        "asset_contract": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
        "hop_depth": 1,
        "branch_count": 1,
        "unresolved_branch_count": 0,
        "has_supported_vasp_boundary": False,
        "has_vasp_candidate": False,
        "has_bridge_boundary": False,
        "coverage_status": "complete_within_scope",
        "provider_error_class": "none",
        "request_budget_remaining": True,
        "receipt_verified": True,
        "finality_state": "confirmed",
        "cross_chain_protocol": "none",
        "cross_chain_status": "NONE",
        "cross_chain_link_available": False,
        "cross_chain_continuation_pending": False,
        "destination_network_known": False,
        "destination_network": None,
        "destination_execution_verified": False,
        "destination_trace_started": False,
        "destination_trace_complete": False,
        "reviewed_service_control_available": False,
        "candidate_only": False,
        "no_attribution_evidence": True,
        "human_review_required": False,
        "report_ready": False,
        "terminal_address": "TMqg...",
    }
    defaults.update(kwargs)
    return InvestigationState(**defaults)


def test_action_catalog_version_and_stability():
    """Action catalog must have version 1.1.0 and calibrated descriptions."""
    assert ACTION_CATALOG_VERSION == "1.1.0"

    continue_action = get_canonical_action(InvestigationActionKey.CONTINUE_SAME_CHAIN.value)
    assert continue_action is not None
    assert continue_action.description == (
        "Continue automated chronological tracing on the current blockchain "
        "while unresolved outgoing branches remain available for investigation."
    )

    follow_action = get_canonical_action(InvestigationActionKey.FOLLOW_CROSS_CHAIN_LINK.value)
    assert follow_action is not None
    assert follow_action.description == (
        "Continue fund-flow tracing on the destination blockchain through an already "
        "verified cross-chain transfer when destination tracing remains pending."
    )

    candidate_action = get_canonical_action(InvestigationActionKey.REVIEW_VASP_CANDIDATE.value)
    assert candidate_action is not None
    assert candidate_action.description == (
        "Escalate an unverified VASP-related candidate for evidence review."
    )

    actions = default_investigation_actions()
    assert tuple(a.key for a in actions) == CANONICAL_ACTION_ORDER


def test_actions_are_typed_objects():
    """All actions must be typed immutable objects with documented metadata."""
    actions = default_investigation_actions()
    assert len(actions) == 9

    for act in actions:
        assert isinstance(act, InvestigationAction)
        assert isinstance(act.key, str)
        assert isinstance(act.description, str) and len(act.description) > 10
        assert isinstance(act.prerequisites, tuple)
        assert isinstance(act.risk_class, RiskClass)
        assert isinstance(act.requires_human_review, bool)
        assert isinstance(act.executable, bool)

    action_lookup = get_canonical_action(InvestigationActionKey.CONTINUE_SAME_CHAIN.value)
    assert action_lookup is not None
    assert action_lookup.key == InvestigationActionKey.CONTINUE_SAME_CHAIN.value


def test_rules_route_unverified_receipt():
    """When consensus receipt is unverified, VERIFY_EXECUTION_RECEIPT must rank top."""
    router = DeterministicRuleRouter()
    state = _base_state(receipt_verified=False, finality_state="unknown")
    result = router.rank_actions(state, default_investigation_actions())

    assert len(result.ranked_actions) == 9
    top_action = result.ranked_actions[0]
    assert top_action.action == InvestigationActionKey.VERIFY_EXECUTION_RECEIPT.value
    assert top_action.score >= 0.90


def test_rules_route_provider_retry():
    """When provider fails and budget remains, RETRY_PROVIDER must rank top."""
    router = DeterministicRuleRouter()
    state = _base_state(
        provider_error_class="timeout",
        request_budget_remaining=True,
        coverage_status="partial",
    )
    result = router.rank_actions(state, default_investigation_actions())

    top_action = result.ranked_actions[0]
    assert top_action.action == InvestigationActionKey.RETRY_PROVIDER.value
    assert top_action.score >= 0.90


def test_rules_route_cctp_continuation_pending():
    """When cross-chain linkage is complete and pending, FOLLOW_CROSS_CHAIN_LINK is top."""
    router = DeterministicRuleRouter()
    state = _base_state(
        network="ethereum",
        asset_symbol="USDC",
        cross_chain_protocol="circle_cctp_v2",
        cross_chain_status="COMPLETE",
        cross_chain_link_available=True,
        cross_chain_continuation_pending=True,
        destination_network_known=True,
        destination_network="base",
        destination_execution_verified=True,
        destination_trace_started=False,
        destination_trace_complete=False,
    )
    result = router.rank_actions(state, default_investigation_actions())

    top_action = result.ranked_actions[0]
    assert top_action.action == InvestigationActionKey.FOLLOW_CROSS_CHAIN_LINK.value
    assert top_action.score >= 0.90


def test_rules_route_cctp_already_completed_not_followed():
    """When cross-chain continuation has already completed, FOLLOW_CROSS_CHAIN_LINK is not top."""
    router = DeterministicRuleRouter()
    state = _base_state(
        network="ethereum",
        asset_symbol="USDC",
        cross_chain_protocol="circle_cctp_v2",
        cross_chain_status="COMPLETE",
        cross_chain_link_available=True,
        cross_chain_continuation_pending=False,
        destination_network_known=True,
        destination_network="base",
        destination_execution_verified=True,
        destination_trace_started=True,
        destination_trace_complete=True,
        report_ready=True,
        hop_depth=3,
    )
    result = router.rank_actions(state, default_investigation_actions())

    top_action = result.ranked_actions[0]
    assert top_action.action != InvestigationActionKey.FOLLOW_CROSS_CHAIN_LINK.value
    assert top_action.action == InvestigationActionKey.GENERATE_EVIDENCE_REPORT.value


def test_rules_route_evidence_report_on_vasp_reached():
    """When reviewed VASP boundary is reached, GENERATE_EVIDENCE_REPORT must rank top."""
    router = DeterministicRuleRouter()
    state = _base_state(
        has_supported_vasp_boundary=True,
        reviewed_service_control_available=True,
        report_ready=True,
    )
    result = router.rank_actions(state, default_investigation_actions())

    top_action = result.ranked_actions[0]
    assert top_action.action == InvestigationActionKey.GENERATE_EVIDENCE_REPORT.value


def test_rules_route_vasp_candidate_review():
    """When candidate relationship is present without reviewed control, candidate review is top."""
    router = DeterministicRuleRouter()
    state = _base_state(
        has_vasp_candidate=True,
        reviewed_service_control_available=False,
        candidate_only=True,
    )
    result = router.rank_actions(state, default_investigation_actions())

    top_action = result.ranked_actions[0]
    assert top_action.action == InvestigationActionKey.REVIEW_VASP_CANDIDATE.value


def test_rules_route_same_chain_continuation():
    """When unresolved branches exist with remaining budget, CONTINUE_SAME_CHAIN must rank top."""
    router = DeterministicRuleRouter()
    state = _base_state(
        unresolved_branch_count=2,
        request_budget_remaining=True,
        has_supported_vasp_boundary=False,
    )
    result = router.rank_actions(state, default_investigation_actions())

    top_action = result.ranked_actions[0]
    assert top_action.action == InvestigationActionKey.CONTINUE_SAME_CHAIN.value


def test_rules_route_coverage_stop():
    """When coverage failed and no budget remains, STOP_COVERAGE_GAP must rank top."""
    router = DeterministicRuleRouter()
    state = _base_state(
        coverage_status="failed",
        request_budget_remaining=False,
    )
    result = router.rank_actions(state, default_investigation_actions())

    top_action = result.ranked_actions[0]
    assert top_action.action == InvestigationActionKey.STOP_COVERAGE_GAP.value
