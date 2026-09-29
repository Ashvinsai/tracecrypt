"""Tests for shadow mode execution, rules authority, and routing audit records (Task 08)."""

from __future__ import annotations

import httpx
import pytest

from app.models.investigation_routing import (
    ACTION_CATALOG_VERSION,
    STATE_SCHEMA_VERSION,
    InvestigationActionKey,
    InvestigationState,
    PolicyGuardDecision,
    RouterMode,
    ShadowStatus,
)
from app.services.routing.clm_client import ClmRouter
from app.services.routing.router import InvestigationRouter


def _mock_state(**kwargs) -> InvestigationState:
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
        "report_ready": False,
        "terminal_address": "TMqg...",
    }
    defaults.update(kwargs)
    return InvestigationState(**defaults)


@pytest.mark.asyncio
async def test_rules_only_mode():
    """Rules-only mode returns deterministic rule decision without touching CLM."""
    router = InvestigationRouter(mode=RouterMode.rules)
    state = _mock_state(unresolved_branch_count=1)
    decision = await router.route(state)

    assert decision.router_requested == "rules"
    assert decision.router_used == "rules"
    assert decision.shadow_status == ShadowStatus.not_configured.value
    assert decision.clm_available is False
    assert decision.actual_selected_action == InvestigationActionKey.CONTINUE_SAME_CHAIN.value
    assert decision.shadow_agreement is None
    assert decision.shadow_clm_choice is None
    assert decision.shadow_failure_reason is None
    assert decision.state_schema_version == STATE_SCHEMA_VERSION
    assert decision.action_catalog_version == ACTION_CATALOG_VERSION
    assert decision.latency_ms >= 0.0

    audit = decision.to_dict()
    assert audit["notice"] == "DECISION SUPPORT METADATA - NOT BLOCKCHAIN EVIDENCE"
    assert len(audit["serialized_state_hash"]) == 64
    assert len(audit["candidate_action_set_hash"]) == 64
    assert len(audit["routing_input_hash"]) == 64


@pytest.mark.asyncio
async def test_shadow_mode_agreement():
    """When CLM and rules agree, shadow_agreement is True, and rules still control execution."""
    state = _mock_state(unresolved_branch_count=1)
    act_same = InvestigationActionKey.CONTINUE_SAME_CHAIN.value

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "qwen3-8b",
                "answers": {
                    "next_action": {
                        "type": "choice",
                        "choice": act_same,
                        "confidence": 0.95,
                        "probabilities": {act_same: 0.95},
                    }
                },
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        clm = ClmRouter(clm_url="http://mock-clm:8700", http_client=client)
        router = InvestigationRouter(mode=RouterMode.shadow_clm, clm_router=clm)
        decision = await router.route(state)

        assert decision.router_requested == "shadow_clm"
        assert decision.router_used == "rules"
        assert decision.shadow_status == ShadowStatus.success.value
        assert decision.clm_available is True
        assert decision.shadow_agreement is True
        assert decision.actual_selected_action == act_same
        assert decision.shadow_clm_choice == act_same
        assert decision.shadow_clm_probabilities is not None
        assert decision.shadow_clm_probabilities[act_same] == 0.95


@pytest.mark.asyncio
async def test_shadow_mode_clm_never_controls_execution():
    """Even if CLM ranks an action differently from rules, rules decide the executed action."""
    state = _mock_state(unresolved_branch_count=1)
    act_same = InvestigationActionKey.CONTINUE_SAME_CHAIN.value
    act_rev = InvestigationActionKey.REQUEST_HUMAN_REVIEW.value

    # CLM prefers REQUEST_HUMAN_REVIEW, while rules prefer CONTINUE_SAME_CHAIN
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "qwen3-8b",
                "answers": {
                    "next_action": {
                        "type": "choice",
                        "choice": act_rev,
                        "confidence": 0.99,
                        "probabilities": {act_rev: 0.99, act_same: 0.01},
                    }
                },
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        clm = ClmRouter(clm_url="http://mock-clm:8700", http_client=client)
        router = InvestigationRouter(mode=RouterMode.shadow_clm, clm_router=clm)
        decision = await router.route(state)

        # Rules chose CONTINUE_SAME_CHAIN; CLM chose REQUEST_HUMAN_REVIEW
        assert decision.router_used == "rules"
        assert decision.shadow_status == ShadowStatus.success.value
        assert decision.shadow_agreement is False
        assert decision.actual_selected_action == act_same
        assert decision.shadow_clm_choice == act_rev


@pytest.mark.asyncio
async def test_shadow_mode_failure_leaves_selected_rule_action_unchanged():
    """When CLM fails (timeout/error), router_used remains 'rules' and action is unchanged."""
    state = _mock_state(unresolved_branch_count=1)

    # First get rule-only reference
    rules_router = InvestigationRouter(mode=RouterMode.rules)
    baseline_decision = await rules_router.route(state)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused to mock CLM")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        clm = ClmRouter(clm_url="http://mock-clm:8700", http_client=client)
        router = InvestigationRouter(mode=RouterMode.shadow_clm, clm_router=clm)
        decision = await router.route(state)

        assert decision.router_requested == "shadow_clm"
        assert decision.router_used == "rules"
        assert decision.shadow_status == ShadowStatus.failed.value
        assert decision.clm_available is False
        assert "Connection refused" in (decision.shadow_failure_reason or "")
        # Must be identical to rule-only action
        assert decision.actual_selected_action == baseline_decision.actual_selected_action
        assert decision.actual_selected_action == InvestigationActionKey.CONTINUE_SAME_CHAIN.value
        assert decision.shadow_agreement is False
        assert decision.shadow_clm_choice is None

        selected_res = decision.guard_results[decision.actual_selected_action]
        assert selected_res.decision is PolicyGuardDecision.ALLOWED


def test_clm_assisted_mode_disabled():
    """Attempting to instantiate router in clm_assisted mode must raise ValueError."""
    with pytest.raises(ValueError, match="clm_assisted.*is disabled"):
        InvestigationRouter(mode="clm_assisted")
