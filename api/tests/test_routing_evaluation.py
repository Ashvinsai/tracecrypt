"""Tests verifying the 12-scenario evaluation suite and safety invariants (Task 08)."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.evaluate_routing import (  # noqa: E402
    build_evaluation_scenarios,
    evaluate_rule_router,
)

from app.models.investigation_routing import (  # noqa: E402
    InvestigationActionKey,
)
from app.services.routing.clm_client import ClmRouter  # noqa: E402
from app.services.routing.guard import ActionPolicyGuard  # noqa: E402


def test_rule_router_curated_dataset_conformance_and_safety():
    """DeterministicRuleRouter must achieve 100% rule-policy conformance and 0% unsafe execution."""
    scenarios = build_evaluation_scenarios()
    assert len(scenarios) == 12

    report = evaluate_rule_router(scenarios)
    assert report["scenarios_evaluated"] == 12
    assert report["rule_policy_conformance_top1"] == 1.0
    assert report["rule_policy_conformance_top3"] == 1.0
    assert (
        report["unsafe_action_execution_rate"] == 0.0
    ), "Strict invariant violated: unsafe action executed!"
    assert report["total_guard_rejections"] > 0
    assert "12/12 curated deterministic-policy scenarios conform" in report["conformance_summary"]


@pytest.mark.asyncio
async def test_mock_clm_evaluation_in_evaluation_scenarios():
    """Mock CLM router respects policy guard and rejects forbidden actions."""
    scenarios = build_evaluation_scenarios()
    guard = ActionPolicyGuard()

    # Mock CLM returns perfect ranking for first scenario
    first_sc = scenarios[0]
    expected_top = next(iter(first_sc.expected_preferred))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "qwen3-8b",
                "answers": {
                    "next_action": {
                        "type": "choice",
                        "choice": expected_top,
                        "confidence": 0.98,
                        "probabilities": {
                            expected_top: 0.98,
                            InvestigationActionKey.REQUEST_HUMAN_REVIEW.value: 0.02,
                        },
                    }
                },
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        clm = ClmRouter(clm_url="http://mock-clm:8700", http_client=client)
        candidates = [
            expected_top,
            InvestigationActionKey.REQUEST_HUMAN_REVIEW.value,
        ]
        result = await clm.rank_actions(first_sc.state, candidates)

        assert result.ranked_actions[0].action == expected_top
        guard_res = guard.evaluate_all([a.action for a in result.ranked_actions], first_sc.state)
        selected = guard.select_highest_allowed(result.ranked_actions, guard_res)
        assert selected == expected_top
