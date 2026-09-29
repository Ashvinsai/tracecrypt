"""Deterministic Action Policy Guard (Task 08).

Authorizes or rejects candidate investigative actions against deterministic evidence state.
Enforces the strict trust boundary:
- The model / router produces only recommendations / ranking.
- The policy guard is authoritative.
- Forbidden actions (e.g. declaring criminal guilt, asserting unverified VASP ownership,
  or freezing funds) are unconditionally REJECTED.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from app.models.investigation_routing import (
    GuardResult,
    InvestigationAction,
    InvestigationActionKey,
    InvestigationState,
    PolicyGuardDecision,
    RankedAction,
    RiskClass,
)
from app.services.routing.actions import get_canonical_action

FORBIDDEN_KEYS: Final[frozenset[str]] = frozenset(
    {
        "DECLARE_WALLET_CRIMINAL",
        "DECLARE_VASP_OWNERSHIP",
        "FREEZE_FUNDS_AUTOMATICALLY",
        "IGNORE_EVIDENCE_GAP",
        "IDENTIFY_CUSTOMER",
    }
)


class ActionPolicyGuard:
    """Deterministic policy guard for investigative actions."""

    def evaluate_action(
        self, action: InvestigationAction | str, state: InvestigationState
    ) -> GuardResult:
        """Evaluate one candidate action against deterministic evidence state."""
        action_obj: InvestigationAction | None
        if isinstance(action, InvestigationAction):
            action_obj = action
            action_key = action.key
        else:
            action_key = action
            action_obj = get_canonical_action(action_key)

        # 1. Unconditional rejection of forbidden actions
        if action_key in FORBIDDEN_KEYS or (
            action_obj and action_obj.risk_class is RiskClass.FORBIDDEN
        ):
            return GuardResult(
                action_key=action_key,
                decision=PolicyGuardDecision.REJECTED,
                reason="Forbidden action violating non-attribution and non-freezing policy.",
                prerequisites_satisfied=False,
            )

        if action_obj is None:
            return GuardResult(
                action_key=action_key,
                decision=PolicyGuardDecision.REJECTED,
                reason="Unknown action key not in canonical vocabulary.",
                prerequisites_satisfied=False,
            )

        # 2. Domain rules per canonical action key
        key = action_obj.key

        if key == InvestigationActionKey.FOLLOW_CROSS_CHAIN_LINK.value:
            has_protocol = state.cross_chain_protocol != "none"
            status_ok = state.cross_chain_status in ("COMPLETE", "DESTINATION_RECEIVED")
            dst_ok = state.destination_network_known
            pending_ok = (
                state.cross_chain_link_available
                and state.cross_chain_continuation_pending
                and not state.destination_trace_complete
            )
            if has_protocol and status_ok and dst_ok and pending_ok:
                return GuardResult(
                    action_key=key,
                    decision=PolicyGuardDecision.ALLOWED,
                    reason=(
                        "Cross-chain protocol detected with verified destination and "
                        "continuation pending."
                    ),
                    prerequisites_satisfied=True,
                )
            return GuardResult(
                action_key=key,
                decision=PolicyGuardDecision.REJECTED,
                reason=(
                    "Cross-chain continuation requires protocol detected, status COMPLETE or "
                    "DESTINATION_RECEIVED, known destination, continuation pending, and "
                    f"destination trace not complete (protocol={state.cross_chain_protocol}, "
                    f"status={state.cross_chain_status}, "
                    f"dst_known={state.destination_network_known}, "
                    f"pending={state.cross_chain_continuation_pending}, "
                    f"dst_complete={state.destination_trace_complete})."
                ),
                prerequisites_satisfied=False,
            )

        if key == InvestigationActionKey.CHECK_REVIEWED_VASP.value:
            if state.reviewed_service_control_available or state.has_supported_vasp_boundary:
                return GuardResult(
                    action_key=key,
                    decision=PolicyGuardDecision.REJECTED,
                    reason="Reviewed VASP status is already verified.",
                    prerequisites_satisfied=False,
                )
            if state.service_lookup_status != "not_checked":
                return GuardResult(
                    action_key=key,
                    decision=PolicyGuardDecision.REJECTED,
                    reason=(
                        "Reviewed service lookup already completed with status "
                        f"'{state.service_lookup_status}'."
                    ),
                    prerequisites_satisfied=False,
                )
            if state.cross_chain_continuation_pending and not state.destination_trace_complete:
                return GuardResult(
                    action_key=key,
                    decision=PolicyGuardDecision.REJECTED,
                    reason=(
                        "Cross-chain continuation is pending; local VASP check is not applicable."
                    ),
                    prerequisites_satisfied=False,
                )
            has_ctx = bool(state.network) and (
                state.terminal_address is not None
                or state.has_vasp_candidate
            )
            if has_ctx:
                return GuardResult(
                    action_key=key,
                    decision=PolicyGuardDecision.ALLOWED,
                    reason="Target address and network context present for registry check.",
                    prerequisites_satisfied=True,
                )
            return GuardResult(
                action_key=key,
                decision=PolicyGuardDecision.REJECTED,
                reason="Address or network context missing for reviewed VASP check.",
                prerequisites_satisfied=False,
            )

        if key == InvestigationActionKey.REVIEW_VASP_CANDIDATE.value:
            if state.has_vasp_candidate and not state.reviewed_service_control_available:
                return GuardResult(
                    action_key=key,
                    decision=PolicyGuardDecision.ALLOWED,
                    reason=(
                        "Unreviewed VASP candidate relationship present for investigator review."
                    ),
                    prerequisites_satisfied=True,
                )
            return GuardResult(
                action_key=key,
                decision=PolicyGuardDecision.REJECTED,
                reason=(
                    "Action permitted only when a VASP candidate exists without existing "
                    "reviewed service control."
                ),
                prerequisites_satisfied=False,
            )

        if key == InvestigationActionKey.VERIFY_EXECUTION_RECEIPT.value:
            needs_verification = (
                not state.receipt_verified
                or state.finality_state in ("provisional", "unknown")
            )
            if needs_verification:
                return GuardResult(
                    action_key=key,
                    decision=PolicyGuardDecision.ALLOWED,
                    reason="Receipt is unverified or finality state is provisional/unknown.",
                    prerequisites_satisfied=True,
                )
            return GuardResult(
                action_key=key,
                decision=PolicyGuardDecision.REJECTED,
                reason="All execution receipts already confirmed and finalized.",
                prerequisites_satisfied=False,
            )

        if key == InvestigationActionKey.RETRY_PROVIDER.value:
            has_error = (
                state.provider_error_class != "none"
                or state.coverage_status in ("failed", "partial")
            )
            has_budget = state.request_budget_remaining
            if has_error and has_budget:
                return GuardResult(
                    action_key=key,
                    decision=PolicyGuardDecision.ALLOWED,
                    reason="Provider acquisition failed and request budget remains.",
                    prerequisites_satisfied=True,
                )
            return GuardResult(
                action_key=key,
                decision=PolicyGuardDecision.REJECTED,
                reason=(
                    "Provider retry permitted only when an error occurred and budget remains "
                    f"(has_error={has_error}, budget_remaining={has_budget})."
                ),
                prerequisites_satisfied=False,
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
            can_stop = bool(
                is_unrecoverable_provider or is_exhausted_partial or is_explicitly_failed
            )
            if can_stop:
                return GuardResult(
                    action_key=key,
                    decision=PolicyGuardDecision.ALLOWED,
                    reason="Coverage is incomplete/failed or request budget is exhausted.",
                    prerequisites_satisfied=True,
                )
            return GuardResult(
                action_key=key,
                decision=PolicyGuardDecision.REJECTED,
                reason="No coverage gap or budget exhaustion present.",
                prerequisites_satisfied=False,
            )

        if key == InvestigationActionKey.CONTINUE_SAME_CHAIN.value:
            can_continue = (
                state.unresolved_branch_count > 0
                and state.request_budget_remaining
                and not state.has_supported_vasp_boundary
            )
            if can_continue:
                return GuardResult(
                    action_key=key,
                    decision=PolicyGuardDecision.ALLOWED,
                    reason="Unresolved branches exist and request budget remains on same chain.",
                    prerequisites_satisfied=True,
                )
            return GuardResult(
                action_key=key,
                decision=PolicyGuardDecision.REJECTED,
                reason=(
                    "Same-chain continuation requires unresolved branches, remaining budget, "
                    f"and no terminal boundary (unresolved={state.unresolved_branch_count}, "
                    f"budget_remaining={state.request_budget_remaining}, "
                    f"supported_vasp={state.has_supported_vasp_boundary})."
                ),
                prerequisites_satisfied=False,
            )

        if key == InvestigationActionKey.GENERATE_EVIDENCE_REPORT.value:
            if (
                state.report_ready
                or state.has_supported_vasp_boundary
                or state.hop_depth > 0
            ):
                return GuardResult(
                    action_key=key,
                    decision=PolicyGuardDecision.ALLOWED,
                    reason="Trace evidence artifacts are available for report compilation.",
                    prerequisites_satisfied=True,
                )
            return GuardResult(
                action_key=key,
                decision=PolicyGuardDecision.REJECTED,
                reason="No trace evidence or boundary available to compile a report.",
                prerequisites_satisfied=False,
            )

        if key == InvestigationActionKey.REQUEST_HUMAN_REVIEW.value:
            # Human review is always safe to request
            return GuardResult(
                action_key=key,
                decision=PolicyGuardDecision.ALLOWED,
                reason="Human investigator review is always permitted.",
                prerequisites_satisfied=True,
            )

        return GuardResult(
            action_key=key,
            decision=PolicyGuardDecision.REJECTED,
            reason=f"Action {key} has no defined policy guard rule.",
            prerequisites_satisfied=False,
        )

    def evaluate_all(
        self, actions: Sequence[InvestigationAction | str], state: InvestigationState
    ) -> dict[str, GuardResult]:
        """Evaluate a sequence of actions against the state, keyed by action key."""
        results: dict[str, GuardResult] = {}
        for action in actions:
            key = action.key if isinstance(action, InvestigationAction) else action
            results[key] = self.evaluate_action(action, state)
        return results

    def select_highest_allowed(
        self, ranked_actions: Sequence[RankedAction], guard_results: dict[str, GuardResult]
    ) -> str | None:
        """Select the highest-scoring action that is ALLOWED by policy guard."""
        for ranked in ranked_actions:
            result = guard_results.get(ranked.action)
            if result and result.decision is PolicyGuardDecision.ALLOWED:
                return ranked.action
        return None
