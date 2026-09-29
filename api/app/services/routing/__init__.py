"""Investigation routing package (Task 08)."""

from app.models.investigation_routing import (
    ACTION_CATALOG_VERSION,
    STATE_SCHEMA_VERSION,
    GuardResult,
    InvestigationAction,
    InvestigationActionKey,
    InvestigationState,
    PolicyGuardDecision,
    RankedAction,
    RiskClass,
    RouterMode,
    RoutingDecision,
    RoutingResult,
    ShadowStatus,
)
from app.services.routing.actions import (
    CANONICAL_ACTION_ORDER,
    CANONICAL_ACTIONS,
    FORBIDDEN_ACTIONS,
    compute_candidate_action_set_hash,
    default_investigation_actions,
    get_canonical_action,
    sort_actions_canonical,
)
from app.services.routing.audit import create_routing_decision
from app.services.routing.clm_client import ClmRouter, ClmRoutingError
from app.services.routing.eligibility import ActionEligibilityFilter
from app.services.routing.guard import ActionPolicyGuard
from app.services.routing.router import InvestigationRouter
from app.services.routing.rules import DeterministicRuleRouter
from app.services.routing.state import (
    compute_routing_input_hash,
    extract_investigation_state,
    hash_serialized_state,
    serialize_investigation_state,
)

__all__ = [
    "ACTION_CATALOG_VERSION",
    "CANONICAL_ACTIONS",
    "CANONICAL_ACTION_ORDER",
    "FORBIDDEN_ACTIONS",
    "STATE_SCHEMA_VERSION",
    "ActionEligibilityFilter",
    "ActionPolicyGuard",
    "ClmRouter",
    "ClmRoutingError",
    "DeterministicRuleRouter",
    "GuardResult",
    "InvestigationAction",
    "InvestigationActionKey",
    "InvestigationRouter",
    "InvestigationState",
    "PolicyGuardDecision",
    "RankedAction",
    "RiskClass",
    "RouterMode",
    "RoutingDecision",
    "RoutingResult",
    "ShadowStatus",
    "compute_candidate_action_set_hash",
    "compute_routing_input_hash",
    "create_routing_decision",
    "default_investigation_actions",
    "extract_investigation_state",
    "get_canonical_action",
    "hash_serialized_state",
    "serialize_investigation_state",
    "sort_actions_canonical",
]
