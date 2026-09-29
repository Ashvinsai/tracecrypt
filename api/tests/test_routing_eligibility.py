"""Tests for ActionEligibilityFilter and candidate action filtering (Task 08)."""

from __future__ import annotations

import pytest

from app.models.investigation_routing import (
    InvestigationActionKey,
    InvestigationState,
    PolicyGuardDecision,
    RouterMode,
)
from app.services.routing.actions import FORBIDDEN_ACTIONS
from app.services.routing.eligibility import ActionEligibilityFilter
from app.services.routing.router import InvestigationRouter


def _sample_state(**kwargs) -> InvestigationState:
    defaults = {
        "network": "ethereum",
        "asset_symbol": "USDC",
        "asset_contract": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
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
        "terminal_address": "0x1234...",
    }
    defaults.update(kwargs)
    return InvestigationState(**defaults)


def test_eligibility_filter_cross_chain_pending_vs_completed():
    """FOLLOW_CROSS_CHAIN_LINK is eligible only when link is pending, not when completed."""
    eligibility = ActionEligibilityFilter()

    # Continuation pending -> ELIGIBLE
    state_pending = _sample_state(
        cross_chain_protocol="circle_cctp_v2",
        cross_chain_status="COMPLETE",
        cross_chain_link_available=True,
        cross_chain_continuation_pending=True,
        destination_network_known=True,
        destination_network="base",
        destination_trace_complete=False,
    )
    eligible_pending = [a.key for a in eligibility.filter_eligible(None, state_pending)]
    assert InvestigationActionKey.FOLLOW_CROSS_CHAIN_LINK.value in eligible_pending

    # Continuation already completed -> NOT ELIGIBLE
    state_completed = _sample_state(
        cross_chain_protocol="circle_cctp_v2",
        cross_chain_status="COMPLETE",
        cross_chain_link_available=True,
        cross_chain_continuation_pending=False,
        destination_network_known=True,
        destination_network="base",
        destination_trace_complete=True,
    )
    eligible_completed = [a.key for a in eligibility.filter_eligible(None, state_completed)]
    assert InvestigationActionKey.FOLLOW_CROSS_CHAIN_LINK.value not in eligible_completed


def test_eligibility_filter_retry_provider():
    """RETRY_PROVIDER is eligible only when an error occurred and budget remains."""
    eligibility = ActionEligibilityFilter()

    # No error -> NOT ELIGIBLE
    state_clean = _sample_state(provider_error_class="none", request_budget_remaining=True)
    eligible_clean = [a.key for a in eligibility.filter_eligible(None, state_clean)]
    assert InvestigationActionKey.RETRY_PROVIDER.value not in eligible_clean

    # Error and budget remains -> ELIGIBLE
    state_err = _sample_state(
        provider_error_class="timeout",
        coverage_status="partial",
        request_budget_remaining=True,
    )
    eligible_err = [a.key for a in eligibility.filter_eligible(None, state_err)]
    assert InvestigationActionKey.RETRY_PROVIDER.value in eligible_err


def test_eligibility_filter_vasp_candidate():
    """REVIEW_VASP_CANDIDATE is eligible only when candidate relationship is present."""
    eligibility = ActionEligibilityFilter()

    # No candidate -> NOT ELIGIBLE
    state_no_cand = _sample_state(has_vasp_candidate=False)
    eligible_no_cand = [a.key for a in eligibility.filter_eligible(None, state_no_cand)]
    assert InvestigationActionKey.REVIEW_VASP_CANDIDATE.value not in eligible_no_cand

    # Candidate present without reviewed control -> ELIGIBLE
    state_cand = _sample_state(
        has_vasp_candidate=True,
        reviewed_service_control_available=False,
    )
    eligible_cand = [a.key for a in eligibility.filter_eligible(None, state_cand)]
    assert InvestigationActionKey.REVIEW_VASP_CANDIDATE.value in eligible_cand


def test_eligibility_filter_stop_coverage_gap_unresolved_branches_alone_not_eligible():
    """Unresolved branches with remaining budget alone must NOT allow STOP_COVERAGE_GAP."""
    eligibility = ActionEligibilityFilter()
    state_healthy = _sample_state(
        unresolved_branch_count=4,
        request_budget_remaining=True,
        coverage_status="complete_within_scope",
        provider_error_class="none",
    )
    eligible = [a.key for a in eligibility.filter_eligible(None, state_healthy)]
    assert InvestigationActionKey.STOP_COVERAGE_GAP.value not in eligible
    assert InvestigationActionKey.CONTINUE_SAME_CHAIN.value in eligible


def test_eligibility_filter_stop_coverage_gap_unrecoverable_conditions():
    """STOP_COVERAGE_GAP is eligible when budget is exhausted or coverage explicitly failed."""
    eligibility = ActionEligibilityFilter()

    # Budget exhausted -> ELIGIBLE
    state_exhausted = _sample_state(
        unresolved_branch_count=2,
        request_budget_remaining=False,
        coverage_status="partial",
    )
    eligible_exh = [a.key for a in eligibility.filter_eligible(None, state_exhausted)]
    assert InvestigationActionKey.STOP_COVERAGE_GAP.value in eligible_exh

    # Coverage explicitly failed -> ELIGIBLE
    state_failed = _sample_state(
        coverage_status="failed",
        request_budget_remaining=True,
        provider_error_class="timeout",
    )
    eligible_fail = [a.key for a in eligibility.filter_eligible(None, state_failed)]
    assert InvestigationActionKey.STOP_COVERAGE_GAP.value in eligible_fail


def test_eligibility_filter_retry_provider_requires_actual_error():
    """Partial coverage alone without provider error does not allow RETRY_PROVIDER."""
    eligibility = ActionEligibilityFilter()
    state_partial_no_err = _sample_state(
        coverage_status="partial",
        provider_error_class="none",
        request_budget_remaining=True,
    )
    eligible = [a.key for a in eligibility.filter_eligible(None, state_partial_no_err)]
    assert InvestigationActionKey.RETRY_PROVIDER.value not in eligible


def test_eligibility_filter_check_reviewed_vasp_bounded_semantics():
    """CHECK_REVIEWED_VASP is disabled if reviewed control is known or cross-chain pending."""
    eligibility = ActionEligibilityFilter()

    # Reviewed control already established -> NOT ELIGIBLE
    state_reviewed = _sample_state(
        has_supported_vasp_boundary=True,
        reviewed_service_control_available=True,
    )
    eligible_rev = [a.key for a in eligibility.filter_eligible(None, state_reviewed)]
    assert InvestigationActionKey.CHECK_REVIEWED_VASP.value not in eligible_rev

    # Cross-chain continuation pending -> NOT ELIGIBLE
    state_cctp = _sample_state(
        cross_chain_protocol="circle_cctp_v2",
        cross_chain_status="COMPLETE",
        cross_chain_link_available=True,
        cross_chain_continuation_pending=True,
        destination_network_known=True,
        destination_network="base",
        destination_trace_complete=False,
    )
    eligible_cctp = [a.key for a in eligibility.filter_eligible(None, state_cctp)]
    assert InvestigationActionKey.CHECK_REVIEWED_VASP.value not in eligible_cctp

    # Unresolved terminal address requiring check -> ELIGIBLE
    state_unresolved = _sample_state(
        reviewed_service_control_available=False,
        has_supported_vasp_boundary=False,
        terminal_address="0x1234...",
        service_lookup_status="not_checked",
    )
    eligible_unres = [a.key for a in eligibility.filter_eligible(None, state_unresolved)]
    assert InvestigationActionKey.CHECK_REVIEWED_VASP.value in eligible_unres


def test_iterative_service_lookup_sequence():
    """Sequence test: NOT_CHECKED is eligible, NO_MATCH and MATCH_FOUND are not eligible."""
    eligibility = ActionEligibilityFilter()
    router = InvestigationRouter(mode=RouterMode.rules)

    # 1. Initial state with uninspected terminal address -> NOT_CHECKED -> ELIGIBLE
    s1 = _sample_state(
        terminal_address="0x1234...",
        service_lookup_status="not_checked",
        reviewed_service_control_available=False,
        has_supported_vasp_boundary=False,
    )
    cands1 = [a.key for a in eligibility.filter_eligible(None, s1)]
    assert InvestigationActionKey.CHECK_REVIEWED_VASP.value in cands1

    # 2. Lookup executed returning NO_MATCH -> NO_MATCH -> NOT ELIGIBLE (No infinite loop!)
    s2 = _sample_state(
        terminal_address="0x1234...",
        service_lookup_status="no_match",
        reviewed_service_control_available=False,
        has_supported_vasp_boundary=False,
    )
    cands2 = [a.key for a in eligibility.filter_eligible(None, s2)]
    assert InvestigationActionKey.CHECK_REVIEWED_VASP.value not in cands2
    # Verify policy guard rejects injected attempt
    guard_res = router.guard.evaluate_action(InvestigationActionKey.CHECK_REVIEWED_VASP.value, s2)
    assert guard_res.decision is PolicyGuardDecision.REJECTED

    # 3. Lookup executed returning MATCH_FOUND -> MATCH_FOUND -> NOT ELIGIBLE
    s3 = _sample_state(
        terminal_address="0x1234...",
        service_lookup_status="match_found",
        reviewed_service_control_available=True,
        has_supported_vasp_boundary=True,
    )
    cands3 = [a.key for a in eligibility.filter_eligible(None, s3)]
    assert InvestigationActionKey.CHECK_REVIEWED_VASP.value not in cands3
    guard_res3 = router.guard.evaluate_action(InvestigationActionKey.CHECK_REVIEWED_VASP.value, s3)
    assert guard_res3.decision is PolicyGuardDecision.REJECTED



def test_forbidden_actions_never_eligible():
    """Forbidden actions are never marked eligible, even if passed directly."""
    eligibility = ActionEligibilityFilter()
    state = _sample_state()

    forbidden_keys = list(FORBIDDEN_ACTIONS.keys())
    filtered = eligibility.filter_eligible(forbidden_keys, state)
    filtered_keys = [a.key for a in filtered]

    for f_key in forbidden_keys:
        assert f_key not in filtered_keys


@pytest.mark.asyncio
async def test_guard_still_rejects_forbidden_actions_if_eligibility_bypassed():
    """Adversarial bypass of eligibility filter must still be blocked by ActionPolicyGuard."""
    router = InvestigationRouter(mode=RouterMode.rules)
    state = _sample_state()

    adversarial_candidates = [
        "FREEZE_FUNDS_AUTOMATICALLY",
        "DECLARE_WALLET_CRIMINAL",
        InvestigationActionKey.REQUEST_HUMAN_REVIEW.value,
    ]

    # Bypass eligibility filter to inject forbidden actions directly into routing pipeline
    decision = await router.route(
        state,
        candidate_actions=adversarial_candidates,
        bypass_eligibility_filter=True,
    )

    freeze_res = decision.guard_results["FREEZE_FUNDS_AUTOMATICALLY"]
    assert freeze_res.decision is PolicyGuardDecision.REJECTED
    criminal_res = decision.guard_results["DECLARE_WALLET_CRIMINAL"]
    assert criminal_res.decision is PolicyGuardDecision.REJECTED
    assert (
        decision.guard_results[InvestigationActionKey.REQUEST_HUMAN_REVIEW.value].decision
        is PolicyGuardDecision.ALLOWED
    )
    assert decision.actual_selected_action == InvestigationActionKey.REQUEST_HUMAN_REVIEW.value
