"""Curated evaluation dataset and benchmarking for Investigation Routing (Task 08).

Evaluates 12 controlled synthetic scenarios covering:
1. normal same-chain continuation
2. CCTP boundary detected
3. COMPLETE CCTP linkage
4. incomplete CCTP linkage
5. reviewed VASP reached
6. VASP candidate only
7. provider failure with retry budget
8. provider failure without retry budget
9. ambiguous ordering
10. receipt unverified
11. finality unknown
12. report-ready case

Metrics measured:
- Top-1 accuracy
- Top-3 accuracy
- Guard rejection rate
- Unsafe-action execution rate (Must be 0.0%)
- Fallback rate
- Median and p95 latency
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "api"))

from app.models.investigation_routing import (  # noqa: E402
    InvestigationActionKey,
    InvestigationState,
    PolicyGuardDecision,
)
from app.services.routing.actions import FORBIDDEN_ACTIONS, default_investigation_actions  # noqa: E402
from app.services.routing.guard import ActionPolicyGuard  # noqa: E402
from app.services.routing.rules import DeterministicRuleRouter  # noqa: E402


@dataclass(frozen=True)
class EvaluationScenario:
    name: str
    description: str
    state: InvestigationState
    allowed_actions: frozenset[str]
    expected_preferred: frozenset[str]
    forbidden_actions: frozenset[str]


def build_evaluation_scenarios() -> list[EvaluationScenario]:
    """12 Curated controlled synthetic scenarios for investigation routing."""
    base_defaults = {
        "network": "tron",
        "asset_symbol": "USDT",
        "asset_contract": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
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
        "terminal_address": "TMqg...",
    }

    all_forbidden = frozenset(FORBIDDEN_ACTIONS.keys())

    scenarios = [
        # 1. Normal same-chain continuation
        EvaluationScenario(
            name="normal_same_chain_continuation",
            description="Active forward trace on TRON with unresolved branch and budget available.",
            state=InvestigationState(
                **{
                    **base_defaults,
                    "unresolved_branch_count": 1,
                    "request_budget_remaining": True,
                }
            ),
            allowed_actions=frozenset(
                {
                    InvestigationActionKey.CONTINUE_SAME_CHAIN.value,
                    InvestigationActionKey.REQUEST_HUMAN_REVIEW.value,
                    InvestigationActionKey.CHECK_REVIEWED_VASP.value,
                }
            ),
            expected_preferred=frozenset(
                {InvestigationActionKey.CONTINUE_SAME_CHAIN.value}
            ),
            forbidden_actions=all_forbidden,
        ),
        # 2. CCTP boundary detected (status INCOMPLETE)
        EvaluationScenario(
            name="cctp_boundary_detected",
            description="Circle CCTP MessageSent log identified on Ethereum, attestation pending.",
            state=InvestigationState(
                **{
                    **base_defaults,
                    "network": "ethereum",
                    "asset_symbol": "USDC",
                    "cross_chain_protocol": "circle_cctp_v2",
                    "cross_chain_status": "MESSAGE_IDENTIFIED",
                    "destination_network_known": True,
                    "destination_network": "base",
                }
            ),
            allowed_actions=frozenset(
                {
                    InvestigationActionKey.REQUEST_HUMAN_REVIEW.value,
                    InvestigationActionKey.CHECK_REVIEWED_VASP.value,
                }
            ),
            expected_preferred=frozenset(
                {InvestigationActionKey.REQUEST_HUMAN_REVIEW.value}
            ),
            forbidden_actions=all_forbidden,
        ),
        # 3. COMPLETE CCTP linkage
        EvaluationScenario(
            name="complete_cctp_linkage",
            description="Circle CCTP source burn, attestation, and Base mint fully reconciled.",
            state=InvestigationState(
                **{
                    **base_defaults,
                    "network": "ethereum",
                    "asset_symbol": "USDC",
                    "cross_chain_protocol": "circle_cctp_v2",
                    "cross_chain_status": "COMPLETE",
                    "cross_chain_link_available": True,
                    "cross_chain_continuation_pending": True,
                    "destination_network_known": True,
                    "destination_network": "base",
                    "destination_execution_verified": True,
                    "destination_trace_started": False,
                    "destination_trace_complete": False,
                }
            ),
            allowed_actions=frozenset(
                {
                    InvestigationActionKey.FOLLOW_CROSS_CHAIN_LINK.value,
                    InvestigationActionKey.REQUEST_HUMAN_REVIEW.value,
                    InvestigationActionKey.CHECK_REVIEWED_VASP.value,
                }
            ),
            expected_preferred=frozenset(
                {InvestigationActionKey.FOLLOW_CROSS_CHAIN_LINK.value}
            ),
            forbidden_actions=all_forbidden,
        ),
        # 4. Incomplete CCTP linkage
        EvaluationScenario(
            name="incomplete_cctp_linkage",
            description="CCTP burn observed but Iris API or Base execution failed.",
            state=InvestigationState(
                **{
                    **base_defaults,
                    "network": "ethereum",
                    "asset_symbol": "USDC",
                    "cross_chain_protocol": "circle_cctp_v2",
                    "cross_chain_status": "INCOMPLETE",
                    "destination_network_known": True,
                    "human_review_required": True,
                }
            ),
            allowed_actions=frozenset(
                {
                    InvestigationActionKey.REQUEST_HUMAN_REVIEW.value,
                    InvestigationActionKey.STOP_COVERAGE_GAP.value,
                    InvestigationActionKey.CHECK_REVIEWED_VASP.value,
                }
            ),
            expected_preferred=frozenset(
                {InvestigationActionKey.REQUEST_HUMAN_REVIEW.value}
            ),
            forbidden_actions=all_forbidden,
        ),
        # 5. Reviewed VASP reached
        EvaluationScenario(
            name="reviewed_vasp_reached",
            description="Trace reached accepted OKX service-control anchor.",
            state=InvestigationState(
                **{
                    **base_defaults,
                    "has_supported_vasp_boundary": True,
                    "reviewed_service_control_available": True,
                    "report_ready": True,
                }
            ),
            allowed_actions=frozenset(
                {
                    InvestigationActionKey.GENERATE_EVIDENCE_REPORT.value,
                    InvestigationActionKey.CHECK_REVIEWED_VASP.value,
                    InvestigationActionKey.REQUEST_HUMAN_REVIEW.value,
                }
            ),
            expected_preferred=frozenset(
                {InvestigationActionKey.GENERATE_EVIDENCE_REPORT.value}
            ),
            forbidden_actions=all_forbidden,
        ),
        # 6. VASP candidate only
        EvaluationScenario(
            name="vasp_candidate_only",
            description="Trace reached unreviewed deposit candidate without reviewed service control.",
            state=InvestigationState(
                **{
                    **base_defaults,
                    "has_vasp_candidate": True,
                    "reviewed_service_control_available": False,
                    "candidate_only": True,
                    "human_review_required": True,
                }
            ),
            allowed_actions=frozenset(
                {
                    InvestigationActionKey.REVIEW_VASP_CANDIDATE.value,
                    InvestigationActionKey.REQUEST_HUMAN_REVIEW.value,
                    InvestigationActionKey.CHECK_REVIEWED_VASP.value,
                }
            ),
            expected_preferred=frozenset(
                {InvestigationActionKey.REVIEW_VASP_CANDIDATE.value}
            ),
            forbidden_actions=all_forbidden,
        ),
        # 7. Provider failure with retry budget
        EvaluationScenario(
            name="provider_failure_with_retry_budget",
            description="TronGrid 429 / timeout with remaining requests budget.",
            state=InvestigationState(
                **{
                    **base_defaults,
                    "provider_error_class": "rate_limited",
                    "coverage_status": "partial",
                    "request_budget_remaining": True,
                }
            ),
            allowed_actions=frozenset(
                {
                    InvestigationActionKey.RETRY_PROVIDER.value,
                    InvestigationActionKey.STOP_COVERAGE_GAP.value,
                    InvestigationActionKey.REQUEST_HUMAN_REVIEW.value,
                    InvestigationActionKey.CHECK_REVIEWED_VASP.value,
                }
            ),
            expected_preferred=frozenset(
                {InvestigationActionKey.RETRY_PROVIDER.value}
            ),
            forbidden_actions=all_forbidden,
        ),
        # 8. Provider failure without retry budget
        EvaluationScenario(
            name="provider_failure_without_budget",
            description="Provider failed and request budget is completely exhausted.",
            state=InvestigationState(
                **{
                    **base_defaults,
                    "provider_error_class": "timeout",
                    "coverage_status": "failed",
                    "request_budget_remaining": False,
                }
            ),
            allowed_actions=frozenset(
                {
                    InvestigationActionKey.STOP_COVERAGE_GAP.value,
                    InvestigationActionKey.REQUEST_HUMAN_REVIEW.value,
                    InvestigationActionKey.CHECK_REVIEWED_VASP.value,
                }
            ),
            expected_preferred=frozenset(
                {InvestigationActionKey.STOP_COVERAGE_GAP.value}
            ),
            forbidden_actions=all_forbidden,
        ),
        # 9. Ambiguous ordering
        EvaluationScenario(
            name="ambiguous_ordering",
            description="Multiple same-block events with ambiguous chronological sequence.",
            state=InvestigationState(
                **{
                    **base_defaults,
                    "human_review_required": True,
                    "coverage_status": "complete_within_scope",
                    "unresolved_branch_count": 0,
                    "report_ready": True,
                }
            ),
            allowed_actions=frozenset(
                {
                    InvestigationActionKey.REQUEST_HUMAN_REVIEW.value,
                    InvestigationActionKey.GENERATE_EVIDENCE_REPORT.value,
                    InvestigationActionKey.CHECK_REVIEWED_VASP.value,
                }
            ),
            expected_preferred=frozenset(
                {
                    InvestigationActionKey.REQUEST_HUMAN_REVIEW.value,
                    InvestigationActionKey.GENERATE_EVIDENCE_REPORT.value,
                }
            ),
            forbidden_actions=all_forbidden,
        ),
        # 10. Receipt unverified
        EvaluationScenario(
            name="receipt_unverified",
            description="Seed transaction receipt execution status unverified.",
            state=InvestigationState(
                **{
                    **base_defaults,
                    "receipt_verified": False,
                    "finality_state": "unknown",
                }
            ),
            allowed_actions=frozenset(
                {
                    InvestigationActionKey.VERIFY_EXECUTION_RECEIPT.value,
                    InvestigationActionKey.REQUEST_HUMAN_REVIEW.value,
                    InvestigationActionKey.CHECK_REVIEWED_VASP.value,
                }
            ),
            expected_preferred=frozenset(
                {InvestigationActionKey.VERIFY_EXECUTION_RECEIPT.value}
            ),
            forbidden_actions=all_forbidden,
        ),
        # 11. Finality unknown
        EvaluationScenario(
            name="finality_unknown",
            description="Transaction receipt success but finality classification is provisional.",
            state=InvestigationState(
                **{
                    **base_defaults,
                    "receipt_verified": True,
                    "finality_state": "provisional",
                }
            ),
            allowed_actions=frozenset(
                {
                    InvestigationActionKey.VERIFY_EXECUTION_RECEIPT.value,
                    InvestigationActionKey.REQUEST_HUMAN_REVIEW.value,
                    InvestigationActionKey.CHECK_REVIEWED_VASP.value,
                }
            ),
            expected_preferred=frozenset(
                {InvestigationActionKey.VERIFY_EXECUTION_RECEIPT.value}
            ),
            forbidden_actions=all_forbidden,
        ),
        # 12. Report-ready case
        EvaluationScenario(
            name="report_ready_case",
            description="Multi-hop trace complete, all branches resolved or bounded, ready for export.",
            state=InvestigationState(
                **{
                    **base_defaults,
                    "hop_depth": 3,
                    "branch_count": 2,
                    "unresolved_branch_count": 0,
                    "has_supported_vasp_boundary": True,
                    "reviewed_service_control_available": True,
                    "report_ready": True,
                }
            ),
            allowed_actions=frozenset(
                {
                    InvestigationActionKey.GENERATE_EVIDENCE_REPORT.value,
                    InvestigationActionKey.CHECK_REVIEWED_VASP.value,
                    InvestigationActionKey.REQUEST_HUMAN_REVIEW.value,
                }
            ),
            expected_preferred=frozenset(
                {InvestigationActionKey.GENERATE_EVIDENCE_REPORT.value}
            ),
            forbidden_actions=all_forbidden,
        ),
    ]
    return scenarios


def evaluate_rule_router(
    scenarios: list[EvaluationScenario],
) -> dict[str, Any]:
    """Evaluate DeterministicRuleRouter against the curated dataset."""
    router = DeterministicRuleRouter()
    guard = ActionPolicyGuard()
    all_actions = default_investigation_actions()

    top_1_hits = 0
    top_3_hits = 0
    unsafe_executions = 0
    guard_rejections = 0
    total_evaluations = len(scenarios)
    latencies: list[float] = []

    scenario_reports: list[dict[str, Any]] = []

    for sc in scenarios:
        t0 = time.perf_counter()
        result = router.rank_actions(sc.state, all_actions)
        latencies.append((time.perf_counter() - t0) * 1000.0)

        guard_res = guard.evaluate_all([a.action for a in result.ranked_actions], sc.state)
        selected = guard.select_highest_allowed(result.ranked_actions, guard_res)

        # Count guard rejections
        rejections = sum(1 for g in guard_res.values() if g.decision is PolicyGuardDecision.REJECTED)
        guard_rejections += rejections

        # Safety check: selected action must NEVER be in forbidden actions
        if selected in sc.forbidden_actions:
            unsafe_executions += 1

        top_1 = result.ranked_actions[0].action if result.ranked_actions else None
        top_3 = {a.action for a in result.ranked_actions[:3]}

        is_top_1 = top_1 in sc.expected_preferred
        is_top_3 = bool(top_3 & sc.expected_preferred)

        if is_top_1:
            top_1_hits += 1
        if is_top_3:
            top_3_hits += 1

        scenario_reports.append(
            {
                "scenario": sc.name,
                "top_1": top_1,
                "selected": selected,
                "expected": list(sc.expected_preferred),
                "is_top_1_match": is_top_1,
                "is_top_3_match": is_top_3,
            }
        )

    median_lat = statistics.median(latencies) if latencies else 0.0
    p95_lat = (
        statistics.quantiles(latencies, n=20)[-1]
        if len(latencies) >= 20
        else max(latencies, default=0.0)
    )

    return {
        "router": "DeterministicRuleRouter",
        "notice": (
            "Measures rule-policy conformance on curated deterministic scenarios; "
            "NOT model accuracy."
        ),
        "scenarios_evaluated": total_evaluations,
        "rule_policy_conformance_top1": round(top_1_hits / total_evaluations, 4),
        "rule_policy_conformance_top3": round(top_3_hits / total_evaluations, 4),
        "conformance_summary": (
            f"{top_1_hits}/{total_evaluations} curated deterministic-policy scenarios conform."
        ),
        "unsafe_action_execution_rate": round(unsafe_executions / total_evaluations, 4),
        "total_guard_rejections": guard_rejections,
        "median_latency_ms": round(median_lat, 3),
        "p95_latency_ms": round(p95_lat, 3),
        "scenario_results": scenario_reports,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate investigation routing on curated scenarios."
    )
    parser.add_argument(
        "--json-out", type=Path, default=None, help="Save evaluation report to JSON."
    )
    args = parser.parse_args()

    scenarios = build_evaluation_scenarios()
    report = evaluate_rule_router(scenarios)

    print("=" * 65)
    print("INVESTIGATION ROUTING EVALUATION REPORT")
    print("=" * 65)
    print(f"Router:                         {report['router']}")
    print(f"Scenarios Evaluated:            {report['scenarios_evaluated']}")
    print(
        f"Rule-Policy Conformance Top-1:  {report['rule_policy_conformance_top1'] * 100:.1f}%"
    )
    print(
        f"Rule-Policy Conformance Top-3:  {report['rule_policy_conformance_top3'] * 100:.1f}%"
    )
    print(f"Conformance Summary:            {report['conformance_summary']}")
    print(
        f"Unsafe-Action Execution Rate:   {report['unsafe_action_execution_rate'] * 100:.1f}%"
    )
    print(f"Total Guard Rejections:         {report['total_guard_rejections']}")
    print(f"Median Latency:                 {report['median_latency_ms']} ms")
    print(f"P95 Latency:                    {report['p95_latency_ms']} ms")
    print("Notice:                         " + report["notice"])
    print("=" * 65)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2))
        print(f"Report saved to {args.json_out}")


if __name__ == "__main__":
    main()
