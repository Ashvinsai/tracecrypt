"""Action Eligibility Filter for System-1 Investigation Routing (Task 08).

Filters all canonical actions down to contextually eligible candidate actions
before ranking and policy guarding:
    ALL CANONICAL ACTIONS
            ↓
    ActionEligibilityFilter
            ↓
    contextually eligible candidate actions
            ↓
    rules + CLM shadow ranking
            ↓
    ActionPolicyGuard
            ↓
    authorized actual action
"""

from __future__ import annotations

from collections.abc import Sequence

from app.models.investigation_routing import (
    InvestigationAction,
    InvestigationActionKey,
    InvestigationState,
    RiskClass,
)
from app.services.routing.actions import (
    default_investigation_actions,
    get_canonical_action,
    sort_actions_canonical,
)


class ActionEligibilityFilter:
    """Filters candidate actions to only those contextually eligible given evidence state."""

    def is_eligible(
        self, action: InvestigationAction | str, state: InvestigationState
    ) -> bool:
        """Check if one action is contextually eligible."""
        action_obj = (
            action
            if isinstance(action, InvestigationAction)
            else get_canonical_action(action)
        )
        if action_obj is None or action_obj.risk_class is RiskClass.FORBIDDEN:
            return False

        key = action_obj.key

        if key == InvestigationActionKey.FOLLOW_CROSS_CHAIN_LINK.value:
            return (
                state.cross_chain_link_available
                and state.cross_chain_continuation_pending
                and state.destination_network_known
                and not state.destination_trace_complete
            )

        if key == InvestigationActionKey.RETRY_PROVIDER.value:
            is_retryable_error = state.provider_error_class in (
                "rate_limited",
                "timeout",
                "provider_error",
            )
            return bool(is_retryable_error and state.request_budget_remaining)

        if key == InvestigationActionKey.REVIEW_VASP_CANDIDATE.value:
            return bool(
                state.has_vasp_candidate and not state.reviewed_service_control_available
            )

        if key == InvestigationActionKey.VERIFY_EXECUTION_RECEIPT.value:
            return bool(
                not state.receipt_verified
                or state.finality_state in ("provisional", "unknown")
            )

        if key == InvestigationActionKey.CHECK_REVIEWED_VASP.value:
            if state.reviewed_service_control_available or state.has_supported_vasp_boundary:
                return False
            if state.service_lookup_status != "not_checked":
                return False
            if state.cross_chain_continuation_pending and not state.destination_trace_complete:
                return False
            return bool(
                state.network
                and (
                    state.terminal_address is not None
                    or state.has_vasp_candidate
                )
            )

        if key == InvestigationActionKey.CONTINUE_SAME_CHAIN.value:
            return bool(
                state.unresolved_branch_count > 0
                and state.request_budget_remaining
                and not state.has_supported_vasp_boundary
            )

        if key == InvestigationActionKey.STOP_COVERAGE_GAP.value:
            is_unrecoverable_provider = (
                state.provider_error_class != "none"
                and not state.request_budget_remaining
            )
            is_exhausted_partial = (
                state.coverage_status in ("partial", "failed")
                and not state.request_budget_remaining
            )
            is_explicitly_failed = state.coverage_status == "failed"
            return bool(is_unrecoverable_provider or is_exhausted_partial or is_explicitly_failed)

        if key == InvestigationActionKey.GENERATE_EVIDENCE_REPORT.value:
            return bool(
                state.report_ready
                or state.has_supported_vasp_boundary
                or state.hop_depth > 0
            )

        if key == InvestigationActionKey.REQUEST_HUMAN_REVIEW.value:
            # Human review is generally eligible as a safe fallback lead
            return True

        return False

    def filter_eligible(
        self,
        actions: Sequence[InvestigationAction | str] | None,
        state: InvestigationState,
    ) -> list[InvestigationAction]:
        """Filter actions to only contextually eligible ones, in canonical catalog order."""
        action_pool = default_investigation_actions() if actions is None else [
            a if isinstance(a, InvestigationAction) else get_canonical_action(a)
            for a in actions
        ]

        eligible = [
            a for a in action_pool
            if a is not None and self.is_eligible(a, state)
        ]

        # Ensure fallback availability: if nothing else is eligible, offer REQUEST_HUMAN_REVIEW
        if not eligible:
            fallback = get_canonical_action(InvestigationActionKey.REQUEST_HUMAN_REVIEW.value)
            if fallback:
                eligible = [fallback]

        # Sort in stable canonical catalog order
        sorted_keys = sort_actions_canonical(eligible)
        key_map = {a.key: a for a in eligible}
        return [key_map[k] for k in sorted_keys if k in key_map]
