"""Tests for ActionPolicyGuard and adversarial action rejection (Task 08)."""

from __future__ import annotations

from app.models.investigation_routing import (
    InvestigationActionKey,
    InvestigationState,
    PolicyGuardDecision,
    RankedAction,
)
from app.services.routing.actions import FORBIDDEN_ACTIONS
from app.services.routing.guard import ActionPolicyGuard


def _safe_state(**kwargs) -> InvestigationState:
    defaults = {
        "network": "tron",
        "asset_symbol": "USDT",
        "asset_contract": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
        "hop_depth": 1,
        "branch_count": 1,
        "unresolved_branch_count": 1,
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
        "report_ready": True,
        "terminal_address": "TMqg...",
    }
    defaults.update(kwargs)
    return InvestigationState(**defaults)


def test_policy_guard_rejects_declare_wallet_criminal():
    """Policy guard must unconditionally reject DECLARE_WALLET_CRIMINAL."""
    guard = ActionPolicyGuard()
    state = _safe_state()
    result = guard.evaluate_action("DECLARE_WALLET_CRIMINAL", state)

    assert result.decision is PolicyGuardDecision.REJECTED
    assert "Forbidden" in result.reason
    assert result.prerequisites_satisfied is False


def test_policy_guard_rejects_declare_vasp_ownership():
    """Policy guard must unconditionally reject DECLARE_VASP_OWNERSHIP."""
    guard = ActionPolicyGuard()
    state = _safe_state()
    result = guard.evaluate_action("DECLARE_VASP_OWNERSHIP", state)

    assert result.decision is PolicyGuardDecision.REJECTED
    assert "Forbidden" in result.reason
    assert result.prerequisites_satisfied is False


def test_policy_guard_rejects_freeze_funds():
    """Policy guard must unconditionally reject FREEZE_FUNDS_AUTOMATICALLY."""
    guard = ActionPolicyGuard()
    state = _safe_state()
    result = guard.evaluate_action("FREEZE_FUNDS_AUTOMATICALLY", state)

    assert result.decision is PolicyGuardDecision.REJECTED
    assert "Forbidden" in result.reason
    assert result.prerequisites_satisfied is False


def test_policy_guard_rejects_all_adversarial_actions():
    """All actions defined in FORBIDDEN_ACTIONS catalog must be rejected."""
    guard = ActionPolicyGuard()
    state = _safe_state()

    for forbidden_key, action in FORBIDDEN_ACTIONS.items():
        result1 = guard.evaluate_action(action, state)
        assert result1.decision is PolicyGuardDecision.REJECTED

        result2 = guard.evaluate_action(forbidden_key, state)
        assert result2.decision is PolicyGuardDecision.REJECTED


def test_policy_guard_independent_from_router_score():
    """Even if an untrusted router ranks a forbidden action at score 1.0, guard rejects it."""
    guard = ActionPolicyGuard()
    state = _safe_state(unresolved_branch_count=1, request_budget_remaining=True)

    adversarial_ranked = [
        RankedAction(action="FREEZE_FUNDS_AUTOMATICALLY", score=1.0, reason="Model hallucination"),
        RankedAction(action="DECLARE_WALLET_CRIMINAL", score=0.99, reason="Model hallucination"),
        RankedAction(action=InvestigationActionKey.CONTINUE_SAME_CHAIN.value, score=0.80),
    ]

    guard_results = guard.evaluate_all([r.action for r in adversarial_ranked], state)

    assert guard_results["FREEZE_FUNDS_AUTOMATICALLY"].decision is PolicyGuardDecision.REJECTED
    assert guard_results["DECLARE_WALLET_CRIMINAL"].decision is PolicyGuardDecision.REJECTED
    assert (
        guard_results[InvestigationActionKey.CONTINUE_SAME_CHAIN.value].decision
        is PolicyGuardDecision.ALLOWED
    )

    selected = guard.select_highest_allowed(adversarial_ranked, guard_results)
    assert selected == InvestigationActionKey.CONTINUE_SAME_CHAIN.value
    assert selected != "FREEZE_FUNDS_AUTOMATICALLY"


def test_policy_guard_cross_chain_prerequisites():
    """FOLLOW_CROSS_CHAIN_LINK rejected if bridge protocol not detected or status incomplete."""
    guard = ActionPolicyGuard()

    # Incomplete link
    state_incomplete = _safe_state(
        cross_chain_protocol="circle_cctp_v2",
        cross_chain_status="INCOMPLETE",
        cross_chain_link_available=False,
        cross_chain_continuation_pending=False,
        destination_network_known=True,
    )
    res_incomplete = guard.evaluate_action(
        InvestigationActionKey.FOLLOW_CROSS_CHAIN_LINK.value, state_incomplete
    )
    assert res_incomplete.decision is PolicyGuardDecision.REJECTED

    # Unknown destination
    state_unknown_dst = _safe_state(
        cross_chain_protocol="circle_cctp_v2",
        cross_chain_status="COMPLETE",
        cross_chain_link_available=True,
        cross_chain_continuation_pending=True,
        destination_network_known=False,
    )
    res_unknown = guard.evaluate_action(
        InvestigationActionKey.FOLLOW_CROSS_CHAIN_LINK.value, state_unknown_dst
    )
    assert res_unknown.decision is PolicyGuardDecision.REJECTED

    # Valid link and continuation pending
    state_valid = _safe_state(
        cross_chain_protocol="circle_cctp_v2",
        cross_chain_status="COMPLETE",
        cross_chain_link_available=True,
        cross_chain_continuation_pending=True,
        destination_network_known=True,
        destination_trace_complete=False,
    )
    res_valid = guard.evaluate_action(
        InvestigationActionKey.FOLLOW_CROSS_CHAIN_LINK.value, state_valid
    )
    assert res_valid.decision is PolicyGuardDecision.ALLOWED

    # Valid link but destination trace already completed -> REJECTED
    state_already_completed = _safe_state(
        cross_chain_protocol="circle_cctp_v2",
        cross_chain_status="COMPLETE",
        cross_chain_link_available=True,
        cross_chain_continuation_pending=False,
        destination_network_known=True,
        destination_trace_complete=True,
    )
    res_already_completed = guard.evaluate_action(
        InvestigationActionKey.FOLLOW_CROSS_CHAIN_LINK.value, state_already_completed
    )
    assert res_already_completed.decision is PolicyGuardDecision.REJECTED


def test_policy_guard_provider_retry_prerequisites():
    """RETRY_PROVIDER allowed only when error occurred and budget remains."""
    guard = ActionPolicyGuard()

    # No error -> rejected
    state_no_error = _safe_state(
        provider_error_class="none", coverage_status="complete_within_scope"
    )
    res_no_error = guard.evaluate_action(
        InvestigationActionKey.RETRY_PROVIDER.value, state_no_error
    )
    assert res_no_error.decision is PolicyGuardDecision.REJECTED

    # Error but no budget -> rejected
    state_no_budget = _safe_state(
        provider_error_class="timeout", request_budget_remaining=False
    )
    res_no_budget = guard.evaluate_action(
        InvestigationActionKey.RETRY_PROVIDER.value, state_no_budget
    )
    assert res_no_budget.decision is PolicyGuardDecision.REJECTED

    # Error and budget remains -> allowed
    state_ok = _safe_state(
        provider_error_class="timeout", request_budget_remaining=True
    )
    res_ok = guard.evaluate_action(
        InvestigationActionKey.RETRY_PROVIDER.value, state_ok
    )
    assert res_ok.decision is PolicyGuardDecision.ALLOWED
