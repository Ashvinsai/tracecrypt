"""Investigation Router orchestrating deterministic rules, CLM shadow mode, and guards (Task 08)."""

from __future__ import annotations

import time
from collections.abc import Sequence

from app.models.investigation_routing import (
    InvestigationAction,
    InvestigationState,
    RouterMode,
    RoutingDecision,
    ShadowStatus,
)
from app.services.routing.actions import (
    compute_candidate_action_set_hash,
    sort_actions_canonical,
)
from app.services.routing.audit import create_routing_decision
from app.services.routing.clm_client import ClmRouter, ClmRoutingError
from app.services.routing.eligibility import ActionEligibilityFilter
from app.services.routing.guard import ActionPolicyGuard
from app.services.routing.rules import DeterministicRuleRouter
from app.services.routing.state import (
    compute_routing_input_hash,
    hash_serialized_state,
    serialize_investigation_state,
)


class InvestigationRouter:
    """Orchestrator for System-1 investigation action ranking and policy authorization."""

    def __init__(
        self,
        mode: str | RouterMode = RouterMode.rules,
        clm_url: str | None = None,
        clm_timeout_seconds: float = 2.0,
        clm_model: str = "qwen3-8b",
        clm_api_key: str | None = None,
        clm_router: ClmRouter | None = None,
    ) -> None:
        self.mode = RouterMode(mode) if isinstance(mode, str) else mode
        if self.mode is RouterMode.clm_assisted:
            raise ValueError(
                "Router mode 'clm_assisted' is disabled in this release. "
                "Use 'rules' or 'shadow_clm'."
            )

        self.rule_router = DeterministicRuleRouter()
        self.guard = ActionPolicyGuard()
        self.eligibility = ActionEligibilityFilter()
        self.clm_model = clm_model

        if clm_router is not None:
            self.clm_router: ClmRouter | None = clm_router
        elif clm_url:
            self.clm_router = ClmRouter(
                clm_url=clm_url,
                timeout_seconds=clm_timeout_seconds,
                model_identifier=clm_model,
                api_key=clm_api_key,
            )
        else:
            self.clm_router = None

    async def route(
        self,
        state: InvestigationState,
        candidate_actions: Sequence[InvestigationAction | str] | None = None,
        *,
        bypass_eligibility_filter: bool = False,
    ) -> RoutingDecision:
        """Route investigation actions according to configured mode and policy guard."""
        start_time = time.perf_counter()

        # 1. Action Eligibility Filter
        eligible_actions: list[InvestigationAction | str]
        if candidate_actions is None:
            eligible_actions = list(self.eligibility.filter_eligible(None, state))
        elif bypass_eligibility_filter:
            # Used in adversarial tests to inject forbidden/ineligible actions directly
            eligible_actions = list(candidate_actions)
        else:
            eligible_actions = list(
                self.eligibility.filter_eligible(candidate_actions, state)
            )

        # 2. Canonical sorting for candidate order determinism
        sorted_action_keys = sort_actions_canonical(eligible_actions)

        # 3. Deterministic hashes
        serialized_state = serialize_investigation_state(state)
        state_hash = hash_serialized_state(serialized_state)
        candidate_set_hash = compute_candidate_action_set_hash(sorted_action_keys)
        input_hash = compute_routing_input_hash(
            serialized_model_state=serialized_state,
            candidate_actions=sorted_action_keys,
            configured_model=self.clm_model,
        )

        # 4. Deterministic rules always evaluate as the primary/authoritative baseline
        rules_result = self.rule_router.rank_actions(state, sorted_action_keys)

        # 5. Evaluate Policy Guard on all candidate actions
        guard_results = self.guard.evaluate_all(sorted_action_keys, state)

        # 6. Authoritative execution action: highest allowed by policy guard from rules
        actual_selected_action = self.guard.select_highest_allowed(
            rules_result.ranked_actions, guard_results
        )

        # If mode is rules only, return immediately
        if self.mode is RouterMode.rules or self.clm_router is None:
            latency_ms = round((time.perf_counter() - start_time) * 1000.0, 3)
            return create_routing_decision(
                router_requested=self.mode.value,
                router_used="rules",
                shadow_status=ShadowStatus.not_configured.value,
                clm_available=False,
                serialized_state_hash=state_hash,
                candidate_action_set_hash=candidate_set_hash,
                routing_input_hash=input_hash,
                candidate_actions=sorted_action_keys,
                rule_ranked_actions=rules_result.ranked_actions,
                actual_selected_action=actual_selected_action,
                guard_results=guard_results,
                shadow_clm_choice=None,
                shadow_clm_probabilities=None,
                shadow_agreement=None,
                shadow_failure_reason=None,
                configured_model=self.clm_model,
                response_model=None,
                latency_ms=latency_ms,
            )

        # 7. Shadow mode: query CLM independently without giving it execution control
        shadow_status = ShadowStatus.success.value
        clm_available = True
        shadow_failure_reason: str | None = None
        shadow_clm_choice: str | None = None
        shadow_clm_probs: dict[str, float] | None = None
        shadow_agreement: bool | None = None
        response_model: str | None = None

        try:
            clm_result = await self.clm_router.rank_actions(state, sorted_action_keys)
            shadow_clm_choice = clm_result.chosen_action
            shadow_clm_probs = clm_result.relative_action_probabilities
            response_model = clm_result.response_model

            # Compare top-1 actions
            rules_top_1 = (
                rules_result.ranked_actions[0].action
                if rules_result.ranked_actions
                else None
            )
            shadow_agreement = (
                rules_top_1 == shadow_clm_choice
                if (rules_top_1 and shadow_clm_choice)
                else False
            )
        except ClmRoutingError as exc:
            shadow_status = ShadowStatus.failed.value
            clm_available = False
            shadow_failure_reason = str(exc)
            shadow_agreement = False

        latency_ms = round((time.perf_counter() - start_time) * 1000.0, 3)

        return create_routing_decision(
            router_requested=self.mode.value,
            router_used="rules",
            shadow_status=shadow_status,
            clm_available=clm_available,
            serialized_state_hash=state_hash,
            candidate_action_set_hash=candidate_set_hash,
            routing_input_hash=input_hash,
            candidate_actions=sorted_action_keys,
            rule_ranked_actions=rules_result.ranked_actions,
            actual_selected_action=actual_selected_action,
            guard_results=guard_results,
            shadow_clm_choice=shadow_clm_choice,
            shadow_clm_probabilities=shadow_clm_probs,
            shadow_agreement=shadow_agreement,
            shadow_failure_reason=shadow_failure_reason,
            configured_model=self.clm_model,
            response_model=response_model,
            latency_ms=latency_ms,
        )
