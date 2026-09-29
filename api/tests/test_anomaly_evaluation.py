"""Stage 3C held-out evaluation: precision@k is computed from the predeclared
rubric, never fabricated, excludes unlabeled rows, and is isolated from the
attribution path."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import pytest

from app.reports.anomaly_evaluation import render_anomaly_evaluation_html
from app.services.anomaly_ranking import (
    ANOMALY_FEATURE_NAMES,
    AnalystRubric,
    AnomalyRankingError,
    evaluate_anomaly,
    train_anomaly,
)
from app.services.feature_dataset import WalletWindowRow

WINDOW_START = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
WINDOW_END = dt.datetime(2026, 1, 31, tzinfo=dt.UTC)

_TYPICAL: dict[str, Any] = {
    "behavioral_observed_incoming_transfer_count": 4,
    "behavioral_observed_outgoing_transfer_count": 3,
    "behavioral_distinct_incoming_counterparty_count": 3,
    "behavioral_distinct_outgoing_counterparty_count": 2,
    "behavioral_observed_incoming_amount_base_units": 1_000_000,
    "behavioral_observed_outgoing_amount_base_units": 900_000,
    "behavioral_outgoing_concentration_toward_accepted_anchor": 0.5,
    "behavioral_outgoing_concentration_max_by_count": 0.5,
    "behavioral_outgoing_concentration_max_by_amount": 0.5,
    "behavioral_outgoing_counterparties_with_repeat_count": 1,
    "behavioral_repeated_forwarding_count": 2,
    "behavioral_receipt_to_outflow_observation_count": 3,
    "behavioral_receipt_to_outflow_ambiguous_count": 0,
    "behavioral_receipt_to_outflow_min_gap_seconds": 3600.0,
    "behavioral_receipt_to_outflow_median_gap_seconds": 7200.0,
    "behavioral_post_outflow_residue_base_units": 100_000,
    "behavioral_ordering_ambiguous_observation_count": 0,
    "behavioral_event_index_missing_count": 0,
    "behavioral_block_number_missing_count": 0,
}

RUBRIC = AnalystRubric(
    rubric_id="test-rubric-v1",
    description="test only",
    review_worthy_categories=frozenset({"review"}),
    confounder_categories=frozenset({"confounder"}),
    expected_negative_categories=frozenset({"negative"}),
)


def _row(
    wallet: str, category: str | None, *, data_mode: str = "RECORDED_PUBLIC", **overrides: Any
) -> WalletWindowRow:
    features: dict[str, Any] = {name: _TYPICAL[name] for name in ANOMALY_FEATURE_NAMES}
    features.update(overrides)
    return WalletWindowRow(
        wallet_id=wallet,
        network="tron",
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        features=features,
        missingness={name: value is None for name, value in features.items()},
        acquisition_completeness="complete_within_scope",
        verification_quality="history_only",
        source_run_ids=("run-1",),
        control_category=category,
        data_mode=data_mode,
    )


def _train() -> list[WalletWindowRow]:
    return [
        _row(
            f"train-{i}",
            "negative",
            behavioral_observed_incoming_transfer_count=3 + (i % 4),
        )
        for i in range(12)
    ]


def _eval() -> list[WalletWindowRow]:
    return [
        _row("rw-a", "review", behavioral_observed_outgoing_transfer_count=900),
        _row("cw-a", "confounder", behavioral_observed_outgoing_transfer_count=800),
        _row("neg-a", "negative"),
        _row("neg-b", "negative"),
        _row("neg-c", "negative"),
        _row("unlabeled-a", None),
        _row("outside-a", "some_other_category"),
    ]


# --- rubric validation --------------------------------------------------------


def test_rubric_rejects_overlapping_categories() -> None:
    with pytest.raises(AnomalyRankingError):
        AnalystRubric(
            rubric_id="bad",
            description="bad",
            review_worthy_categories=frozenset({"x"}),
            confounder_categories=frozenset({"x"}),
            expected_negative_categories=frozenset(),
        )


# --- evaluation ---------------------------------------------------------------


def test_evaluation_computes_consistent_ratios_and_ranks() -> None:
    evaluation = evaluate_anomaly(train_anomaly(_train(), seed=7), _eval(), rubric=RUBRIC, k=3)
    m = evaluation.metrics
    assert m.review_worthy_precision_at_k == (
        m.review_worthy_in_top_k / m.labeled_in_top_k
    )
    assert m.random_ranking_baseline_precision_at_k == evaluation.review_worthy_total / (
        evaluation.labeled_row_count
    )
    assert len(evaluation.confounder_ranks) == evaluation.confounder_total
    assert len(evaluation.review_worthy_ranks) == evaluation.review_worthy_total


def test_unlabeled_and_outside_rubric_rows_are_excluded_not_negatives() -> None:
    evaluation = evaluate_anomaly(train_anomaly(_train(), seed=7), _eval(), rubric=RUBRIC, k=3)
    assert evaluation.eval_row_count == 7
    assert evaluation.unlabeled_excluded == 1
    assert evaluation.outside_rubric_excluded == 1
    assert evaluation.labeled_row_count == 5
    assert evaluation.review_worthy_total == 1
    assert evaluation.confounder_total == 1
    assert evaluation.expected_negative_total == 3


def test_absent_review_worthy_class_gives_null_precision_not_zero() -> None:
    rows = [_row(f"neg-{i}", "negative") for i in range(5)]
    evaluation = evaluate_anomaly(train_anomaly(_train(), seed=7), rows, rubric=RUBRIC, k=3)
    assert evaluation.review_worthy_total == 0
    assert evaluation.metrics.review_worthy_precision_at_k is None
    assert evaluation.metrics.random_ranking_baseline_precision_at_k is None
    assert any("not computable" in note for note in evaluation.notes)


def test_evaluation_refuses_to_score_training_rows() -> None:
    train = _train()
    model = train_anomaly(train, seed=7)
    with pytest.raises(AnomalyRankingError):
        evaluate_anomaly(model, train, rubric=RUBRIC, k=3)


def test_k_must_be_at_least_one() -> None:
    with pytest.raises(AnomalyRankingError):
        evaluate_anomaly(train_anomaly(_train(), seed=7), _eval(), rubric=RUBRIC, k=0)


# --- labelling, determinism, report -------------------------------------------


def test_synthetic_evaluation_is_labelled_a_pipeline_demonstration() -> None:
    rows = [_row(f"s-{i}", "negative", data_mode="SYNTHETIC") for i in range(5)]
    evaluation = evaluate_anomaly(train_anomaly(_train(), seed=7), rows, rubric=RUBRIC, k=3)
    assert evaluation.evaluation_kind == "pipeline_demonstration"
    assert any("PIPELINE DEMONSTRATION" in note for note in evaluation.notes)


def test_real_records_are_labelled_held_out_not_demonstration() -> None:
    evaluation = evaluate_anomaly(train_anomaly(_train(), seed=7), _eval(), rubric=RUBRIC, k=3)
    assert evaluation.evaluation_kind == "held_out_evaluation"


def test_evaluation_is_deterministic_for_a_fixed_seed() -> None:
    a = evaluate_anomaly(train_anomaly(_train(), seed=7), _eval(), rubric=RUBRIC, k=3)
    b = evaluate_anomaly(train_anomaly(_train(), seed=7), _eval(), rubric=RUBRIC, k=3)
    assert a.to_json() == b.to_json()


def test_evaluation_report_never_claims_guilt_or_probability() -> None:
    payload = json.loads(
        evaluate_anomaly(train_anomaly(_train(), seed=7), _eval(), rubric=RUBRIC, k=3).to_json()
    )
    assert payload["measures_criminal_guilt"] is False
    assert payload["is_probability"] is False
    keys = _all_keys(payload)
    assert not {"accuracy", "recall", "auc"} & keys


def _all_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        keys = {str(k).lower() for k in value}
        for item in value.values():
            keys |= _all_keys(item)
        return keys
    if isinstance(value, list):
        keys = set()
        for item in value:
            keys |= _all_keys(item)
        return keys
    return set()


def test_rendered_html_states_the_caveat_and_omits_banned_metrics() -> None:
    evaluation = evaluate_anomaly(
        train_anomaly(_train(), seed=7), _eval(), rubric=RUBRIC, k=3
    )
    html = render_anomaly_evaluation_html(evaluation)
    lowered = html.lower()
    assert "review prioritization" in lowered
    assert "criminal guilt" in lowered
    assert "not an accuracy" in lowered
    assert "test-rubric-v1" in html
    assert "accuracy</td>" not in lowered  # no fabricated metric value in the table
