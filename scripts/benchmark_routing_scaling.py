"""Benchmark scaling tooling for candidate action sets from 5 to 1000 actions (Task 08).

Tests router performance across candidate set sizes:
5, 10, 25, 50, 100, 500, 1000 actions.

Uses clearly labeled synthetic distractor actions (BENCHMARK_DISTRACTOR_xxx).
Measures:
- Median latency
- P95 latency
- Top-1 result stability
- Top-5 stability
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "api"))

from app.models.investigation_routing import (  # noqa: E402
    InvestigationAction,
    InvestigationState,
    RiskClass,
)
from app.services.routing.actions import default_investigation_actions  # noqa: E402
from app.services.routing.rules import DeterministicRuleRouter  # noqa: E402


def generate_benchmark_action_set(target_size: int) -> list[InvestigationAction]:
    """Build candidate action set of target_size using canonical actions + labeled distractors."""
    canonical = default_investigation_actions()
    if target_size <= len(canonical):
        return canonical[:target_size]

    actions = list(canonical)
    needed = target_size - len(actions)

    for i in range(1, needed + 1):
        key = f"BENCHMARK_DISTRACTOR_{i:04d}"
        actions.append(
            InvestigationAction(
                key=key,
                description=f"Synthetic benchmark-only distractor action {i} (non-production).",
                prerequisites=(),
                risk_class=RiskClass.LOW,
                requires_human_review=False,
                executable=False,
            )
        )

    return actions


def benchmark_candidate_scaling(
    scales: tuple[int, ...] = (5, 10, 25, 50, 100, 500, 1000),
    iterations_per_scale: int = 50,
) -> dict[str, Any]:
    """Measure latency and top-k stability across candidate action set scales."""
    router = DeterministicRuleRouter()

    # Benchmark state: CCTP complete
    state = InvestigationState(
        network="ethereum",
        asset_symbol="USDC",
        asset_contract="0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        hop_depth=2,
        branch_count=1,
        unresolved_branch_count=0,
        has_supported_vasp_boundary=False,
        has_vasp_candidate=False,
        has_bridge_boundary=True,
        coverage_status="complete_within_scope",
        provider_error_class="none",
        request_budget_remaining=True,
        receipt_verified=True,
        finality_state="confirmed",
        cross_chain_protocol="circle_cctp_v2",
        cross_chain_status="COMPLETE",
        cross_chain_link_available=True,
        cross_chain_continuation_pending=True,
        destination_network_known=True,
        destination_network="base",
        destination_execution_verified=True,
        destination_trace_started=False,
        destination_trace_complete=False,
        reviewed_service_control_available=False,
        candidate_only=False,
        no_attribution_evidence=True,
        human_review_required=False,
        report_ready=False,
        terminal_address="0x1234...",
    )

    results: list[dict[str, Any]] = []

    for scale in scales:
        actions = generate_benchmark_action_set(scale)
        latencies_ms: list[float] = []
        top_1_samples: list[str] = []
        top_5_samples: list[tuple[str, ...]] = []

        # Warmup
        router.rank_actions(state, actions)

        for _ in range(iterations_per_scale):
            t0 = time.perf_counter()
            routing_res = router.rank_actions(state, actions)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            latencies_ms.append(elapsed_ms)
            top_1_samples.append(routing_res.ranked_actions[0].action)
            top_5_samples.append(tuple(a.action for a in routing_res.ranked_actions[:5]))

        median_lat = statistics.median(latencies_ms)
        p95_lat = (
            statistics.quantiles(latencies_ms, n=20)[-1]
            if len(latencies_ms) >= 20
            else max(latencies_ms)
        )

        top_1_stable = len(set(top_1_samples)) == 1
        top_5_stable = len(set(top_5_samples)) == 1

        results.append(
            {
                "candidate_action_count": scale,
                "iterations": iterations_per_scale,
                "median_latency_ms": round(median_lat, 4),
                "p95_latency_ms": round(p95_lat, 4),
                "top_1_action": top_1_samples[0],
                "top_1_stable": top_1_stable,
                "top_5_stable": top_5_stable,
            }
        )

    return {
        "benchmark": "local_candidate_set_construction_and_validation_overhead",
        "description": (
            "Local harness overhead across candidate action set scales (5..1000). "
            "NOTE: Real CLM scaling benchmark will use POST /v1/rank against remote CLM service."
        ),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scales_evaluated": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run investigation routing candidate-action scaling benchmark."
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Path to save benchmark report JSON.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=50,
        help="Iterations per scale factor (default: 50).",
    )
    args = parser.parse_args()

    print("Running Candidate Action Set Scaling Benchmark (5 -> 1000 actions)...")
    report = benchmark_candidate_scaling(iterations_per_scale=args.iterations)

    print("=" * 72)
    print("LOCAL ROUTING HARNESS & CANDIDATE SET OVERHEAD BENCHMARK")
    print("Note: Measures local Python evaluation overhead, NOT remote CLM latency.")
    print("=" * 72)
    print(
        f"{'Scale (Actions)':<16} | {'Median (ms)':<14} | {'P95 (ms)':<14} | {'Top-1 Action':<20}"
    )
    print("-" * 72)
    for row in report["scales_evaluated"]:
        print(
            f"{row['candidate_action_count']:<16} | "
            f"{row['median_latency_ms']:<14.4f} | "
            f"{row['p95_latency_ms']:<14.4f} | "
            f"{row['top_1_action']:<20}"
        )
    print("=" * 72)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2))
        print(f"Benchmark results saved to {args.json_out}")


if __name__ == "__main__":
    main()
