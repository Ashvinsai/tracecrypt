"""Audit record generation for investigation routing decisions (Task 08)."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any

from app.models.investigation_routing import (
    ACTION_CATALOG_VERSION,
    STATE_SCHEMA_VERSION,
    GuardResult,
    RankedAction,
    RoutingDecision,
)


def create_routing_decision(
    *,
    router_requested: str,
    router_used: str,
    shadow_status: str,
    clm_available: bool,
    serialized_state_hash: str,
    candidate_action_set_hash: str,
    routing_input_hash: str,
    candidate_actions: Sequence[str],
    rule_ranked_actions: Sequence[RankedAction],
    actual_selected_action: str | None,
    guard_results: dict[str, GuardResult],
    shadow_clm_choice: str | None = None,
    shadow_clm_probabilities: dict[str, float] | None = None,
    shadow_agreement: bool | None = None,
    shadow_failure_reason: str | None = None,
    configured_model: str | None = None,
    response_model: str | None = None,
    latency_ms: float = 0.0,
    generated_at: str | None = None,
) -> RoutingDecision:
    """Create a validated, immutable RoutingDecision audit record."""
    return RoutingDecision(
        router_requested=router_requested,
        router_used=router_used,
        shadow_status=shadow_status,
        clm_available=clm_available,
        state_schema_version=STATE_SCHEMA_VERSION,
        action_catalog_version=ACTION_CATALOG_VERSION,
        serialized_state_hash=serialized_state_hash,
        candidate_action_set_hash=candidate_action_set_hash,
        routing_input_hash=routing_input_hash,
        candidate_actions=tuple(candidate_actions),
        rule_ranked_actions=tuple(rule_ranked_actions),
        actual_selected_action=actual_selected_action,
        guard_results=guard_results,
        shadow_clm_choice=shadow_clm_choice,
        shadow_clm_probabilities=shadow_clm_probabilities,
        shadow_agreement=shadow_agreement,
        shadow_failure_reason=shadow_failure_reason,
        configured_model=configured_model,
        response_model=response_model,
        latency_ms=latency_ms,
        generated_at=generated_at or dt.datetime.now(dt.UTC).isoformat(),
    )


def audit_dict(decision: RoutingDecision) -> dict[str, Any]:
    """Format a RoutingDecision as a dictionary stamped with decision-support disclaimer."""
    return decision.to_dict()
