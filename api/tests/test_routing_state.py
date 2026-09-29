"""Tests for deterministic investigation state extraction and serialization (Task 08)."""

from __future__ import annotations

import datetime as dt

from app.core.settings import DataMode
from app.engine.result import (
    BoundaryReason,
    BranchEnding,
    BudgetUse,
    CoverageStatus,
    EndpointClass,
    Limitation,
    ObservedTransfer,
    TraceResult,
)
from app.models.enums import AttributionStatus, CaseFlowLinkage
from app.models.investigation_routing import InvestigationState, ServiceLookupStatus
from app.services.routing.actions import (
    compute_candidate_action_set_hash,
    default_investigation_actions,
)
from app.services.routing.state import (
    compute_routing_input_hash,
    extract_investigation_state,
    hash_serialized_state,
    serialize_investigation_state,
)


def _sample_state(**kwargs) -> InvestigationState:
    defaults = {
        "network": "ethereum",
        "asset_symbol": "USDC",
        "asset_contract": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "hop_depth": 2,
        "branch_count": 1,
        "unresolved_branch_count": 0,
        "has_supported_vasp_boundary": False,
        "has_vasp_candidate": True,
        "has_bridge_boundary": True,
        "coverage_status": "complete_within_scope",
        "provider_error_class": "none",
        "request_budget_remaining": True,
        "receipt_verified": True,
        "finality_state": "confirmed",
        "cross_chain_protocol": "circle_cctp_v2",
        "cross_chain_status": "COMPLETE",
        "cross_chain_link_available": True,
        "cross_chain_continuation_pending": True,
        "destination_network_known": True,
        "destination_network": "base",
        "destination_execution_verified": True,
        "destination_trace_started": False,
        "destination_trace_complete": False,
        "reviewed_service_control_available": False,
        "candidate_only": True,
        "no_attribution_evidence": False,
        "human_review_required": True,
        "report_ready": True,
        "terminal_address": "0x1234567890abcdef1234567890abcdef12345678",
    }
    defaults.update(kwargs)
    return InvestigationState(**defaults)


def test_model_facing_semantic_state_projection_healthy_continuation():
    """Healthy same-chain continuation projects active_frontier without coverage_status=partial."""
    state = _sample_state(
        network="ethereum",
        asset_symbol="USDT",
        hop_depth=2,
        branch_count=20,
        unresolved_branch_count=4,
        request_budget_remaining=True,
        coverage_status="partial",
        provider_error_class="none",
        cross_chain_continuation_pending=False,
    )
    serialized = serialize_investigation_state(state)

    # Must contain unambiguous semantic fields
    assert "TRACE_PROGRESS_STATE=active_frontier" in serialized
    assert "CONTINUATION_AVAILABLE=true" in serialized
    assert "COVERAGE_BLOCKING=false" in serialized
    assert "PROVIDER_IMPAIRED=false" in serialized

    # Must NOT expose raw overloaded COVERAGE_STATUS=partial
    assert "COVERAGE_STATUS=" not in serialized


def test_model_facing_semantic_state_projection_cctp_continuation_pending():
    """CCTP verified relay with pending destination trace projects continuation pending."""
    state = _sample_state(
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
    serialized = serialize_investigation_state(state)

    assert "CROSS_CHAIN_LINK_VERIFIED=true" in serialized
    assert "CROSS_CHAIN_RELAY_COMPLETE=true" in serialized
    assert "CROSS_CHAIN_CONTINUATION_AVAILABLE=true" in serialized
    assert "DESTINATION_TRACE_PENDING=true" in serialized
    assert "DESTINATION_TRACE_COMPLETE=false" in serialized

    # Must NOT expose raw overloaded CROSS_CHAIN_STATUS=COMPLETE
    assert "CROSS_CHAIN_STATUS=" not in serialized


def test_model_facing_semantic_state_projection_impairments_and_exhaustion():
    """Provider failure and budget exhaustion map to explicit blocking progress states."""
    # 1. Provider impaired with budget
    state_impaired = _sample_state(
        provider_error_class="rate_limited",
        request_budget_remaining=True,
        coverage_status="partial",
    )
    ser_imp = serialize_investigation_state(state_impaired)
    assert "TRACE_PROGRESS_STATE=provider_impaired" in ser_imp
    assert "PROVIDER_IMPAIRED=true" in ser_imp
    assert "COVERAGE_BLOCKING=true" in ser_imp
    assert "CONTINUATION_AVAILABLE=false" in ser_imp

    # 2. Budget exhausted
    state_exhausted = _sample_state(
        provider_error_class="none",
        request_budget_remaining=False,
        coverage_status="partial",
    )
    ser_exh = serialize_investigation_state(state_exhausted)
    assert "TRACE_PROGRESS_STATE=budget_exhausted" in ser_exh
    assert "COVERAGE_BLOCKING=true" in ser_exh

    # 3. Explicitly failed
    state_failed = _sample_state(
        coverage_status="failed",
        request_budget_remaining=True,
    )
    ser_fail = serialize_investigation_state(state_failed)
    assert "TRACE_PROGRESS_STATE=failed" in ser_fail
    assert "COVERAGE_BLOCKING=true" in ser_fail


def test_routing_state_deterministic_serialization():
    """Serialization must produce byte-for-byte identical output regardless of instantiation."""
    state1 = _sample_state()
    state2 = _sample_state()

    serialized1 = serialize_investigation_state(state1)
    serialized2 = serialize_investigation_state(state2)

    assert serialized1 == serialized2
    assert isinstance(serialized1, str)
    assert "NETWORK=ethereum" in serialized1
    assert "ASSET_SYMBOL=USDC" in serialized1
    assert "CROSS_CHAIN_PROTOCOL=circle_cctp_v2" in serialized1
    assert "CROSS_CHAIN_LINK_VERIFIED=true" in serialized1
    assert "CROSS_CHAIN_STATUS=" not in serialized1
    assert "CROSS_CHAIN_LINK_AVAILABLE=true" in serialized1
    assert "CROSS_CHAIN_CONTINUATION_PENDING=true" in serialized1
    assert "DESTINATION_NETWORK=base" in serialized1

    lines = serialized1.splitlines()
    assert lines == sorted(lines), "Lines must be alphabetically sorted for byte-for-byte stability"


def test_routing_state_excludes_wallet_address_and_contract_from_clm_body():
    """Wallet addresses and raw token contracts must not be leaked into the model-facing state."""
    state = _sample_state(
        terminal_address="0x1234567890abcdef1234567890abcdef12345678",
        asset_contract="0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    )
    serialized = serialize_investigation_state(state)

    assert "0x1234567890abcdef1234567890abcdef12345678" not in serialized
    assert "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48" not in serialized
    assert "TERMINAL_ADDRESS" not in serialized
    assert "ASSET_CONTRACT" not in serialized
    assert "ASSET_SYMBOL=USDC" in serialized


def test_routing_state_hash_stability():
    """SHA-256 state hash must be deterministic across executions."""
    state = _sample_state()
    serialized = serialize_investigation_state(state)
    h1 = hash_serialized_state(serialized)
    h2 = hash_serialized_state(serialized)
    assert h1 == h2
    assert len(h1) == 64


def test_three_routing_hashes_determinism_and_insertion_independence():
    """Hashes must be deterministic and insertion independent."""
    actions = default_investigation_actions()
    actions_reversed = list(reversed(actions))

    state = _sample_state()
    serialized = serialize_investigation_state(state)

    h_cand1 = compute_candidate_action_set_hash(actions)
    h_cand2 = compute_candidate_action_set_hash(actions_reversed)
    assert h_cand1 == h_cand2, "Candidate set hash must be insertion-order independent"

    h_input1 = compute_routing_input_hash(
        serialized_model_state=serialized,
        candidate_actions=actions,
        configured_model="qwen3-8b",
    )
    h_input2 = compute_routing_input_hash(
        serialized_model_state=serialized,
        candidate_actions=actions_reversed,
        configured_model="qwen3-8b",
    )
    assert h_input1 == h_input2, "Routing input hash must be insertion-order independent"
    assert len(h_cand1) == 64
    assert len(h_input1) == 64


def test_routing_state_contains_no_secrets_or_pii():
    """InvestigationState string representation must never leak credentials, RPC URLs, or PII."""
    state = _sample_state()
    serialized = serialize_investigation_state(state)

    forbidden_tokens = [
        "http://",
        "https://",
        "api_key",
        "secret",
        "password",
        "victim",
        "suspect",
        "complaint_text",
        "bearer",
        "authorization",
    ]

    serialized_lower = serialized.lower()
    for token in forbidden_tokens:
        assert token not in serialized_lower, f"Forbidden token {token!r} leaked in state!"


def test_extract_investigation_state_service_lookup_status_provenance():
    """Test extract_investigation_state derives ServiceLookupStatus across topologies."""
    base_result = TraceResult(
        network_key="tron",
        seed_address="TSeed123",
        seed_event_reference="ref1",
        asset_symbol="USDT",
        asset_contract="TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
        asset_decimals=6,
        data_mode=DataMode.LIVE,
        analysis_cutoff=dt.datetime.now(dt.UTC),
        started_at=dt.datetime.now(dt.UTC),
        finished_at=dt.datetime.now(dt.UTC),
        engine_version="1.0.0",
        label_set_version="1.0.0",
        coverage_status=CoverageStatus.complete_within_scope,
        case_flow_linkage=CaseFlowLinkage.established,
    )

    # 1. Fresh pre-lookup state (seed address only, no transfers, no endings) -> NOT_CHECKED
    s1 = extract_investigation_state(base_result)
    assert s1.service_lookup_status == ServiceLookupStatus.not_checked.value

    # 2. Reviewed VASP boundary reached -> MATCH_FOUND
    res_vasp = TraceResult(
        **{
            **base_result.__dict__,
            "branch_endings": [
                BranchEnding(
                    address="TVasp123",
                    endpoint_class=EndpointClass.known_service,
                    attribution_status=AttributionStatus.supported,
                    boundary_reason=BoundaryReason.service_boundary,
                    hop_depth=1,
                    branch_path=["ref1"],
                    arrival_event_reference="ref1",
                    observed_amount_base_units=1000,
                    asset_decimals=6,
                )
            ],
        }
    )
    s2 = extract_investigation_state(res_vasp)
    assert s2.service_lookup_status == ServiceLookupStatus.match_found.value

    # 3. Unresolved endpoint after registry check -> NO_MATCH
    res_unresolved = TraceResult(
        **{
            **base_result.__dict__,
            "branch_endings": [
                BranchEnding(
                    address="TUnresolved123",
                    endpoint_class=EndpointClass.unresolved,
                    attribution_status=AttributionStatus.unresolved,
                    boundary_reason=BoundaryReason.no_outgoing_activity,
                    hop_depth=2,
                    branch_path=["ref1", "ref2"],
                    arrival_event_reference="ref2",
                    observed_amount_base_units=1000,
                    asset_decimals=6,
                )
            ],
        }
    )
    s3 = extract_investigation_state(res_unresolved)
    assert s3.service_lookup_status == ServiceLookupStatus.no_match.value

    # 4. Deposit candidate only -> NO_MATCH (reviewed-anchor check failed to find accepted anchor)
    res_candidate = TraceResult(
        **{
            **base_result.__dict__,
            "branch_endings": [
                BranchEnding(
                    address="TCandidate123",
                    endpoint_class=EndpointClass.deposit_candidate,
                    attribution_status=AttributionStatus.candidate,
                    boundary_reason=None,
                    hop_depth=1,
                    branch_path=["ref1"],
                    arrival_event_reference="ref1",
                    observed_amount_base_units=1000,
                    asset_decimals=6,
                )
            ],
        }
    )
    s4 = extract_investigation_state(res_candidate)
    assert s4.service_lookup_status == ServiceLookupStatus.no_match.value

    # 5. Multi-branch result: Branch 0 is unresolved (TBranch0), Branch 1 is VASP (TVasp)
    # Target address is Branch 0 -> must not inherit Branch 1's MATCH_FOUND!
    res_multi = TraceResult(
        **{
            **base_result.__dict__,
            "branch_endings": [
                BranchEnding(
                    address="TBranch0",
                    endpoint_class=EndpointClass.unresolved,
                    attribution_status=AttributionStatus.unresolved,
                    boundary_reason=BoundaryReason.no_outgoing_activity,
                    hop_depth=1,
                    branch_path=["ref1"],
                    arrival_event_reference="ref1",
                    observed_amount_base_units=500,
                    asset_decimals=6,
                ),
                BranchEnding(
                    address="TVasp",
                    endpoint_class=EndpointClass.known_service,
                    attribution_status=AttributionStatus.supported,
                    boundary_reason=BoundaryReason.service_boundary,
                    hop_depth=1,
                    branch_path=["ref2"],
                    arrival_event_reference="ref2",
                    observed_amount_base_units=500,
                    asset_decimals=6,
                ),
            ],
        }
    )
    s5 = extract_investigation_state(res_multi)
    assert s5.terminal_address == "TBranch0"
    assert s5.service_lookup_status == ServiceLookupStatus.no_match.value

    """extract_investigation_state maps TraceResult correctly into InvestigationState."""
    now = dt.datetime.now(dt.UTC)
    transfer = ObservedTransfer(
        event_reference="eip155:1:0xabc:0",
        tx_hash="0xabc",
        from_address="0xfrom",
        to_address="0xto",
        amount_base_units=1000000,
        asset_contract="0xcontract",
        asset_decimals=6,
        asset_symbol="USDC",
        block_time=now,
        chain_sequence="100:0",
        ordering_ambiguous=False,
        execution_status="success",
        confirmation_state="confirmed",
        hop_depth=1,
    )
    branch = BranchEnding(
        address="0xto",
        endpoint_class=EndpointClass.unresolved,
        attribution_status=AttributionStatus.unresolved,
        boundary_reason=None,
        hop_depth=1,
        branch_path=["0xfrom", "0xto"],
        arrival_event_reference="eip155:1:0xabc:0",
        observed_amount_base_units=1000000,
        asset_decimals=6,
    )
    trace = TraceResult(
        seed_address="0xfrom",
        seed_event_reference=None,
        network_key="ethereum",
        asset_contract="0xcontract",
        asset_symbol="USDC",
        asset_decimals=6,
        data_mode="SYNTHETIC",  # type: ignore[arg-type]
        analysis_cutoff=now,
        started_at=now,
        finished_at=now,
        engine_version="0.1.0",
        label_set_version="0",
        coverage_status=CoverageStatus.complete_within_scope,
        case_flow_linkage="not_established",  # type: ignore[arg-type]
        observed_transfers=[transfer],
        branch_endings=[branch],
        limitations=[Limitation(code="PROVIDER_TIMEOUT", message="provider timed out")],
        budget_use=BudgetUse(
            hops_used=1,
            events_examined=1,
            traversal_requests=5,
            traversal_request_limit=100,
        ),
    )

    state = extract_investigation_state(trace)
    assert state.network == "ethereum"
    assert state.asset_symbol == "USDC"
    assert state.hop_depth == 1
    assert state.unresolved_branch_count == 1
    assert state.receipt_verified is True
    assert state.finality_state == "confirmed"
    assert state.provider_error_class == "timeout"
    assert state.request_budget_remaining is True
    assert state.human_review_required is True
