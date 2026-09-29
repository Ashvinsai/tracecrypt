"""Deterministic rule router for investigation actions (Task 08).

Acts as:
- Production baseline router.
- Fallback router when CLM is unavailable or fails.
- Evaluation comparator.
"""

from __future__ import annotations

import time
from collections.abc import Sequence

from app.models.investigation_routing import (
    InvestigationAction,
    InvestigationActionKey,
    InvestigationState,
    RankedAction,
    RoutingResult,
)


class DeterministicRuleRouter:
    """Ranks candidate actions using deterministic business rules."""

    ROUTER_NAME = "deterministic_rules"

    def rank_actions(
        self,
        state: InvestigationState,
        candidate_actions: Sequence[InvestigationAction | str],
    ) -> RoutingResult:
        """Rank candidate actions given deterministic state."""
        start_time = time.perf_counter()

        action_keys = [
            a.key if isinstance(a, InvestigationAction) else a
            for a in candidate_actions
        ]

        scored: list[tuple[str, float, str]] = []

        # Determine priority ordering
        priority_map: dict[str, tuple[float, str]] = {}

        # 1. Unverified receipt / finality
        if not state.receipt_verified or state.finality_state in ("provisional", "unknown"):
            priority_map[InvestigationActionKey.VERIFY_EXECUTION_RECEIPT.value] = (
                0.95,
                "Consensus receipt or finality is unverified.",
            )

        # 2. Provider transient failure with remaining budget
        if state.provider_error_class != "none" and state.request_budget_remaining:
            priority_map[InvestigationActionKey.RETRY_PROVIDER.value] = (
                0.92,
                f"Provider failed with {state.provider_error_class} and budget remains.",
            )

        # 3. Cross-chain continuation complete and pending
        if (
            state.cross_chain_link_available
            and state.cross_chain_continuation_pending
            and state.destination_network_known
            and not state.destination_trace_complete
        ):
            priority_map[InvestigationActionKey.FOLLOW_CROSS_CHAIN_LINK.value] = (
                0.90,
                (
                    f"Cross-chain transfer ({state.cross_chain_protocol}) linkage "
                    "verified and pending."
                ),
            )
        elif state.cross_chain_protocol != "none" and not state.destination_trace_complete:
            priority_map[InvestigationActionKey.REQUEST_HUMAN_REVIEW.value] = (
                0.82,
                (
                    f"Cross-chain transfer ({state.cross_chain_protocol}) detected with "
                    f"unresolved linkage status {state.cross_chain_status}."
                ),
            )

        # 4. Supported VASP reached or report ready -> Compile report
        if (
            state.has_supported_vasp_boundary
            or state.reviewed_service_control_available
            or state.report_ready
        ):
            priority_map[InvestigationActionKey.GENERATE_EVIDENCE_REPORT.value] = (
                0.88,
                "Case trace complete or terminal boundary reached; evidence report ready.",
            )
            if state.has_supported_vasp_boundary or state.reviewed_service_control_available:
                priority_map[InvestigationActionKey.CHECK_REVIEWED_VASP.value] = (
                    0.85,
                    "Terminal address reaches verified anchor.",
                )

        # 5. VASP candidate relationship present without reviewed service control
        if state.has_vasp_candidate and not state.reviewed_service_control_available:
            priority_map[InvestigationActionKey.REVIEW_VASP_CANDIDATE.value] = (
                0.84,
                "Unreviewed VASP candidate requires investigator review.",
            )

        # 6. Same-chain continuation when unresolved branches exist and budget remains
        if (
            state.unresolved_branch_count > 0
            and state.request_budget_remaining
            and not state.has_supported_vasp_boundary
        ):
            priority_map[InvestigationActionKey.CONTINUE_SAME_CHAIN.value] = (
                0.80,
                "Unresolved branch exists with budget available on same chain.",
            )

        # 7. Coverage failure / budget exhaustion -> Stop coverage gap
        if (
            state.coverage_status in ("failed", "partial")
            or not state.request_budget_remaining
        ):
            priority_map[InvestigationActionKey.STOP_COVERAGE_GAP.value] = (
                0.78,
                "Tracing stopped due to coverage gap or budget exhaustion.",
            )

        # 8. Human review requested
        if state.human_review_required:
            priority_map[InvestigationActionKey.REQUEST_HUMAN_REVIEW.value] = (
                0.75,
                "Case state requires human review.",
            )

        # 9. Fallback defaults for remaining canonical actions
        default_scores: dict[str, tuple[float, str]] = {
            InvestigationActionKey.CHECK_REVIEWED_VASP.value: (
                0.50,
                "Default check for reviewed VASP status.",
            ),
            InvestigationActionKey.GENERATE_EVIDENCE_REPORT.value: (
                0.40,
                "Compile current evidence state.",
            ),
            InvestigationActionKey.REQUEST_HUMAN_REVIEW.value: (
                0.30,
                "Request human review as safe fallback.",
            ),
            InvestigationActionKey.CONTINUE_SAME_CHAIN.value: (
                0.20,
                "Continue same chain tracing.",
            ),
            InvestigationActionKey.STOP_COVERAGE_GAP.value: (
                0.15,
                "Halt tracing on coverage gap.",
            ),
            InvestigationActionKey.REVIEW_VASP_CANDIDATE.value: (
                0.10,
                "Review candidate relationship.",
            ),
            InvestigationActionKey.FOLLOW_CROSS_CHAIN_LINK.value: (
                0.05,
                "Follow cross-chain link.",
            ),
            InvestigationActionKey.RETRY_PROVIDER.value: (
                0.05,
                "Retry provider request.",
            ),
            InvestigationActionKey.VERIFY_EXECUTION_RECEIPT.value: (
                0.05,
                "Verify execution receipt.",
            ),
        }

        # Score all candidate actions
        for key in action_keys:
            if key in priority_map:
                score, reason = priority_map[key]
            elif key in default_scores:
                score, reason = default_scores[key]
            else:
                score, reason = (0.01, "Unrecognized or benchmark candidate action.")
            scored.append((key, score, reason))

        # Sort descending by score, breaking ties by key name for determinism
        scored.sort(key=lambda item: (-item[1], item[0]))

        ranked = tuple(
            RankedAction(action=k, score=round(s, 4), reason=r) for k, s, r in scored
        )

        latency_ms = round((time.perf_counter() - start_time) * 1000.0, 3)

        return RoutingResult(
            router_name=self.ROUTER_NAME,
            ranked_actions=ranked,
            latency_ms=latency_ms,
        )
