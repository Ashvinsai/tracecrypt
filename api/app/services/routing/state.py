"""Deterministic state extraction and serialization for investigation routing (Task 08)."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any

from app.engine.result import EndpointClass, TraceResult
from app.models.enums import CoverageStatus
from app.models.investigation_routing import (
    ACTION_CATALOG_VERSION,
    STATE_SCHEMA_VERSION,
    InvestigationAction,
    InvestigationState,
    ServiceLookupStatus,
)
from app.services.routing.actions import (
    get_canonical_action,
    sort_actions_canonical,
)

SYSTEMONE_INSTRUCTIONS = "Which investigative action should be prioritized next?"

# Fields strictly excluded from model-facing state to prevent leakage of addresses or contracts
LOCAL_ONLY_FIELDS = frozenset(
    {
        "terminal_address",
        "asset_contract",
        "coverage_status",
        "cross_chain_status",
    }
)


def _derive_model_semantic_fields(state: InvestigationState) -> dict[str, Any]:
    """Derive unambiguous model-facing semantic fields from raw investigation state."""
    # 1. Coverage & Progress Semantics
    # Disambiguate overloaded 'partial' into active_frontier vs impaired vs exhausted
    is_impaired = state.provider_error_class not in ("none", "", None)
    has_budget = bool(state.request_budget_remaining)
    has_active_branches = state.unresolved_branch_count > 0

    if state.coverage_status == "failed" or (is_impaired and not has_budget):
        progress_state = "failed"
        coverage_blocking = True
        continuation_avail = False
    elif not has_budget:
        progress_state = "budget_exhausted"
        coverage_blocking = True
        continuation_avail = False
    elif is_impaired:
        progress_state = "provider_impaired"
        coverage_blocking = True
        continuation_avail = False
    elif has_active_branches or state.coverage_status == "partial":
        progress_state = "active_frontier"
        coverage_blocking = False
        continuation_avail = True
    else:
        progress_state = "complete_within_scope"
        coverage_blocking = False
        continuation_avail = False

    # 2. Cross-Chain Semantics
    # Disambiguate overloaded CROSS_CHAIN_STATUS=COMPLETE (relay verified != trace complete)
    link_verified = state.cross_chain_status in ("COMPLETE", "completed", "VERIFIED", "verified")
    continuation_pending = bool(state.cross_chain_continuation_pending)
    dest_complete = bool(state.destination_trace_complete)

    dest_trace_pending = continuation_pending and not dest_complete
    cc_continuation_avail = link_verified and dest_trace_pending

    return {
        "trace_progress_state": progress_state,
        "coverage_blocking": coverage_blocking,
        "continuation_available": continuation_avail,
        "provider_impaired": is_impaired,
        "cross_chain_link_verified": link_verified,
        "cross_chain_relay_complete": link_verified and bool(state.destination_execution_verified),
        "cross_chain_continuation_available": cc_continuation_avail,
        "destination_trace_pending": dest_trace_pending,
    }


def serialize_investigation_state(state: InvestigationState) -> str:
    """Deterministically serialize an InvestigationState to a byte-for-byte stable string.

    Rules:
    - Excludes local-only address/contract and overloaded raw status fields.
    - Projects unambiguous model-facing semantic fields (Task 08C-C1).
    - Sorted alphabetically by key.
    - Booleans serialized as lowercase 'true'/'false'.
    - None serialized as 'none'.
    - One KEY=VALUE per line.
    - No PII, RPC URLs, or credentials.
    """
    raw_dict = state.to_dict()
    # Merge model-facing semantic projections
    semantic_projections = _derive_model_semantic_fields(state)
    raw_dict.update(semantic_projections)

    lines: list[str] = []

    for key in sorted(raw_dict.keys()):
        if key in LOCAL_ONLY_FIELDS:
            continue
        val = raw_dict[key]
        if isinstance(val, bool):
            val_str = "true" if val else "false"
        elif val is None:
            val_str = "none"
        else:
            val_str = str(val)
        lines.append(f"{key.upper()}={val_str}")

    return "\n".join(lines)


def hash_serialized_state(serialized_state: str) -> str:
    """Compute deterministic SHA-256 hash of serialized state string."""
    return hashlib.sha256(serialized_state.encode("utf-8")).hexdigest()


def compute_routing_input_hash(
    *,
    serialized_model_state: str,
    candidate_actions: Sequence[str | InvestigationAction],
    configured_model: str | None,
    instructions: str = SYSTEMONE_INSTRUCTIONS,
) -> str:
    """Compute deterministic SHA-256 hash of the full routing input.

    Covers:
    - state schema version
    - serialized model-facing state
    - action catalog version
    - ordered candidate action keys and descriptions
    - question instructions
    - configured model identifier
    """
    sorted_keys = sort_actions_canonical(candidate_actions)
    lines: list[str] = [
        f"STATE_SCHEMA_VERSION={STATE_SCHEMA_VERSION}",
        serialized_model_state,
        f"ACTION_CATALOG_VERSION={ACTION_CATALOG_VERSION}",
        f"INSTRUCTIONS={instructions}",
        f"MODEL={configured_model or 'none'}",
    ]
    for key in sorted_keys:
        act = get_canonical_action(key)
        desc = act.description if act else "UNKNOWN_ACTION"
        lines.append(f"CANDIDATE={key}:{desc}")

    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _extract_service_lookup_status(
    trace_result: TraceResult,
    target_address: str | None,
) -> str:
    """Determine reviewed service lookup status for the specific target address."""
    if not target_address:
        if trace_result.supported_destinations:
            return ServiceLookupStatus.match_found.value
        return ServiceLookupStatus.not_checked.value

    # Look for branch endings matching target address
    matching_endings = [
        b for b in trace_result.branch_endings if b.address == target_address
    ]

    if not matching_endings:
        # Target address has not ended a branch in this trace
        if trace_result.supported_destinations:
            return ServiceLookupStatus.not_checked.value
        if not trace_result.observed_transfers and target_address == trace_result.seed_address:
            # Seed address before traversal has begun
            return ServiceLookupStatus.not_checked.value
        return ServiceLookupStatus.not_checked.value

    # Evaluate the endings for this target address
    if any(b.endpoint_class is EndpointClass.known_service for b in matching_endings):
        return ServiceLookupStatus.match_found.value

    if any(b.endpoint_class is EndpointClass.deposit_candidate for b in matching_endings):
        # Reviewed-anchor check was performed and returned no accepted anchor;
        # candidate relationship only.
        return ServiceLookupStatus.no_match.value

    # All other branch endings at this address passed label check without finding an anchor
    return ServiceLookupStatus.no_match.value


def extract_investigation_state(trace_result: TraceResult) -> InvestigationState:
    """Extract a compact, sanitized InvestigationState from a TraceResult."""
    # Check transfers
    all_transfers = (
        [trace_result.seed_transfer] if trace_result.seed_transfer else []
    ) + trace_result.observed_transfers

    receipt_verified = False
    if all_transfers:
        receipt_verified = all(t.execution_status == "success" for t in all_transfers)

    finality_state = "unknown"
    if all_transfers:
        if all(t.confirmation_state == "confirmed" for t in all_transfers):
            finality_state = "confirmed"
        elif any(t.confirmation_state == "removed" for t in all_transfers):
            finality_state = "removed"
        elif any(t.confirmation_state == "provisional" for t in all_transfers):
            finality_state = "provisional"

    # Check limitations for provider errors
    provider_error_class = "none"
    for lim in trace_result.limitations:
        code_lower = lim.code.lower()
        if "timeout" in code_lower:
            provider_error_class = "timeout"
        elif "rate_limit" in code_lower or "429" in code_lower:
            provider_error_class = "rate_limited"
        elif "provider" in code_lower or "http" in code_lower:
            provider_error_class = "provider_error"

    if (
        trace_result.coverage_status is CoverageStatus.failed
        and provider_error_class == "none"
    ):
        provider_error_class = "provider_error"

    # Budget
    budget = trace_result.budget_use
    if budget.traversal_request_limit > 0:
        budget_remaining = budget.traversal_requests < budget.traversal_request_limit
    else:
        budget_remaining = True

    # Topology
    hop_depth = max([t.hop_depth for t in all_transfers], default=0)
    branch_count = len(trace_result.branch_endings)
    unresolved_count = sum(
        1 for b in trace_result.branch_endings if b.endpoint_class is EndpointClass.unresolved
    )
    has_supported_vasp = bool(trace_result.supported_destinations)
    has_candidate = bool(trace_result.candidate_destinations)

    # Cross-chain
    has_bridge = bool(trace_result.cross_chain_links)
    cross_chain_protocol = "none"
    cross_chain_status = "NONE"
    dst_net_known = False
    dst_net: str | None = None
    dst_exec_verified = False
    dst_trace_started = False
    dst_trace_complete = False

    if trace_result.cross_chain_links:
        first_link = trace_result.cross_chain_links[0]
        cross_chain_protocol = first_link.get("protocol_family", "circle_cctp")
        cross_chain_status = first_link.get("linkage_status", "NONE")
        dst_net = first_link.get("destination_network")
        dst_net_known = dst_net is not None and dst_net != ""
        dst_exec_verified = first_link.get("destination_tx_hash") is not None
        # Check if destination network tracing was performed
        if dst_net and trace_result.network_key == dst_net:
            dst_trace_started = True
            dst_trace_complete = True
        elif dst_net and dst_exec_verified and any(
            t.chain_sequence and dst_net in t.chain_sequence for t in all_transfers
        ):
            dst_trace_started = True
            dst_trace_complete = unresolved_count == 0 or has_supported_vasp

    cross_chain_link_available = has_bridge and cross_chain_status in (
        "COMPLETE",
        "DESTINATION_RECEIVED",
    )
    cross_chain_continuation_pending = (
        cross_chain_link_available and not dst_trace_complete
    )

    terminal_addr = None
    if trace_result.branch_endings:
        terminal_addr = trace_result.branch_endings[0].address
    elif trace_result.seed_address:
        terminal_addr = trace_result.seed_address

    report_ready = bool(trace_result.branch_endings or has_supported_vasp)
    service_lookup = _extract_service_lookup_status(trace_result, terminal_addr)

    return InvestigationState(
        network=trace_result.network_key,
        asset_symbol=trace_result.asset_symbol,
        asset_contract=trace_result.asset_contract,
        hop_depth=hop_depth,
        branch_count=branch_count,
        unresolved_branch_count=unresolved_count,
        has_supported_vasp_boundary=has_supported_vasp,
        has_vasp_candidate=has_candidate,
        has_bridge_boundary=has_bridge,
        coverage_status=trace_result.coverage_status.value,
        provider_error_class=provider_error_class,
        request_budget_remaining=budget_remaining,
        receipt_verified=receipt_verified,
        finality_state=finality_state,
        cross_chain_protocol=cross_chain_protocol,
        cross_chain_status=cross_chain_status,
        cross_chain_link_available=cross_chain_link_available,
        cross_chain_continuation_pending=cross_chain_continuation_pending,
        destination_network_known=dst_net_known,
        destination_network=dst_net,
        destination_execution_verified=dst_exec_verified,
        destination_trace_started=dst_trace_started,
        destination_trace_complete=dst_trace_complete,
        reviewed_service_control_available=has_supported_vasp,
        candidate_only=has_candidate and not has_supported_vasp,
        no_attribution_evidence=not (has_supported_vasp or has_candidate),
        human_review_required=has_candidate or unresolved_count > 0,
        report_ready=report_ready,
        service_lookup_status=service_lookup,
        terminal_address=terminal_addr,
    )
