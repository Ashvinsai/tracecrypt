"""Stage 3C: the Isolation Forest ranker fits and scores deterministically,
keeps missing data missing, never reports a metric, and is isolated from the
attribution/evidence path."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from app.services.anomaly_ranking import (
    ANOMALY_FEATURE_NAMES,
    MIN_TRAIN_ROWS,
    AnomalyRankingError,
    assert_no_training_overlap,
    extract_features,
    score_anomaly,
    synthetic_demonstration_rows,
    train_anomaly,
)
from app.services.feature_dataset import (
    DISALLOWED_FEATURE_NAME_FRAGMENTS,
    WalletWindowRow,
)

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


def _row(wallet: str, **overrides: Any) -> WalletWindowRow:
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
        data_mode="SYNTHETIC",
    )


def _training_rows(n: int = 12) -> list[WalletWindowRow]:
    return [
        _row(
            f"train-{i}",
            **{
                "behavioral_observed_incoming_transfer_count": 3 + (i % 4),
                "behavioral_observed_outgoing_transfer_count": 2 + (i % 3),
            },
        )
        for i in range(n)
    ]


# --- allowlist / extraction ---------------------------------------------------


def test_allowlist_contains_no_disallowed_fragments() -> None:
    for name in ANOMALY_FEATURE_NAMES:
        for fragment in DISALLOWED_FEATURE_NAME_FRAGMENTS:
            assert fragment not in name.lower(), name


def test_extract_features_leaves_missing_as_none_not_zero() -> None:
    matrix = extract_features([_row("w1", behavioral_observed_incoming_transfer_count=None)])
    index = matrix.feature_names.index("behavioral_observed_incoming_transfer_count")
    assert matrix.values[0][index] is None


def test_extract_features_rejects_non_numeric_value() -> None:
    with pytest.raises(AnomalyRankingError):
        extract_features([_row("w1", behavioral_repeated_forwarding_count="lots")])


def test_extract_features_rejects_boolean_for_numeric_feature() -> None:
    with pytest.raises(AnomalyRankingError):
        extract_features([_row("w1", behavioral_repeated_forwarding_count=True)])


# --- training -----------------------------------------------------------------


def test_train_requires_a_computability_floor() -> None:
    assert MIN_TRAIN_ROWS >= 2
    with pytest.raises(AnomalyRankingError):
        train_anomaly([_row("only-one")], seed=7)


def test_training_cutoff_is_enforced() -> None:
    with pytest.raises(AnomalyRankingError):
        train_anomaly(_training_rows(), seed=7, training_cutoff=WINDOW_START)


def test_metadata_is_reproducible_and_reports_no_metric() -> None:
    model = train_anomaly(_training_rows(), seed=11)
    meta = model.metadata()
    assert meta["seed"] == 11
    assert meta["sample_selection"] == "all_supplied_training_rows"
    assert meta["calibrated_probability"] is False
    assert meta["metrics_reported"] is False
    assert meta["training_row_count"] == len(_training_rows())
    for banned in ("accuracy", "precision", "recall", "auc"):
        assert banned not in " ".join(meta.keys()).lower()


# --- scoring ------------------------------------------------------------------


def test_scoring_is_deterministic_for_a_fixed_seed() -> None:
    rows = _training_rows() + [_row("eval-x", behavioral_observed_outgoing_transfer_count=500)]
    model_a = train_anomaly(_training_rows(), seed=7)
    model_b = train_anomaly(_training_rows(), seed=7)
    scores_a = [s.to_dict() for s in score_anomaly(model_a, rows)]
    scores_b = [s.to_dict() for s in score_anomaly(model_b, rows)]
    assert scores_a == scores_b


def test_ranks_are_contiguous_and_start_at_one_most_isolated() -> None:
    rows = _training_rows() + [
        _row("eval-burst", behavioral_observed_outgoing_transfer_count=5000),
        _row("eval-plain"),
    ]
    scores = score_anomaly(train_anomaly(_training_rows(), seed=7), rows)
    assert [s.rank for s in scores] == list(range(1, len(rows) + 1))
    assert scores[0].score <= scores[-1].score
    by_wallet = {s.wallet_id: s for s in scores}
    assert by_wallet["eval-burst"].rank < by_wallet["eval-plain"].rank
    assert by_wallet["eval-burst"].is_outlier is True


def test_score_carries_raw_observed_values_not_transformed() -> None:
    rows = [_row("eval-x", behavioral_observed_outgoing_transfer_count=500)]
    score = score_anomaly(train_anomaly(_training_rows(), seed=7), rows)[0]
    assert score.observed_feature_values["behavioral_observed_outgoing_transfer_count"] == 500
    assert score.to_dict()["interpretation"]


def test_missing_feature_is_imputed_at_train_median_and_not_flagged_suspicious() -> None:
    model = train_anomaly(_training_rows(), seed=7)
    typical = _row("eval-missing", behavioral_observed_incoming_transfer_count=None)
    burst = _row(
        "eval-burst",
        behavioral_observed_incoming_transfer_count=5000,
        behavioral_observed_outgoing_transfer_count=5000,
    )
    scores = {s.wallet_id: s for s in score_anomaly(model, [typical, burst])}
    missing_score = scores["eval-missing"]
    assert "behavioral_observed_incoming_transfer_count" in missing_score.imputed_features
    assert missing_score.rank > scores["eval-burst"].rank
    assert missing_score.is_outlier is False


def test_scoring_empty_rows_returns_empty() -> None:
    model = train_anomaly(_training_rows(), seed=7)
    assert score_anomaly(model, []) == []


# --- fit/evaluate disjointness ------------------------------------------------


def test_assert_no_training_overlap_rejects_a_training_row() -> None:
    train = _training_rows()
    model = train_anomaly(train, seed=7)
    with pytest.raises(AnomalyRankingError):
        assert_no_training_overlap(model, train)
    assert_no_training_overlap(model, [_row("held-out")])


def test_score_can_forbid_training_rows() -> None:
    train = _training_rows()
    model = train_anomaly(train, seed=7)
    with pytest.raises(AnomalyRankingError):
        score_anomaly(model, train, allow_training_rows=False)


# --- synthetic demonstration + isolation --------------------------------------


def test_synthetic_demonstration_rows_are_labelled_synthetic() -> None:
    rows = synthetic_demonstration_rows()
    assert len(rows) >= MIN_TRAIN_ROWS
    assert {row.data_mode for row in rows} == {"SYNTHETIC"}


def _imported_module_names(module: object) -> set[str]:
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(module))  # type: ignore[arg-type]
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_anomaly_ranking_never_imports_the_attribution_path() -> None:
    import app.services.anomaly_ranking as anomaly_module

    imported = _imported_module_names(anomaly_module)
    for forbidden in (
        "app.services.service_outcome",
        "app.services.strong_inference_policy",
        "app.services.evidence_comparison",
        "app.engine.tracer",
    ):
        assert forbidden not in imported


def test_attribution_path_never_imports_anomaly_ranking() -> None:
    """Gate: disabling the ranker cannot change observed transfer evidence or
    service labels."""
    import app.engine.tracer as tracer_module
    import app.services.evidence_comparison as comparison_module
    import app.services.service_outcome as outcome_module
    import app.services.strong_inference_policy as policy_module

    for module in (comparison_module, outcome_module, policy_module, tracer_module):
        assert "anomaly_ranking" not in _imported_module_names(module)


def _all_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        keys = {str(k).lower() for k in value}
        for item in value.values():
            keys |= _all_keys(item)
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for item in value:
            keys |= _all_keys(item)
        return keys
    return set()


def test_cli_runs_offline_and_labels_a_pipeline_demonstration() -> None:
    import json
    import subprocess
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "anomaly_ranking.py"
    result = subprocess.run(  # noqa: S603 -- fixed local script path, no untrusted input
        [sys.executable, str(script), "--seed", "7"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["evaluation_kind"] == "pipeline_demonstration"
    assert report["data_mode"] == "SYNTHETIC"
    assert report["real_data_used"] is False
    assert report["model"]["metrics_reported"] is False
    assert report["scores"], "expected a held-out scored slice"
    assert [s["rank"] for s in report["scores"]] == list(range(1, len(report["scores"]) + 1))
    keys = _all_keys(report)
    # precision@k is the requested review-prioritization metric; the banned
    # set is fabricated quality metrics only.
    assert not {"accuracy", "recall", "auc"} & keys
    assert "precision" not in keys
    assert report["evaluation"]["evaluation_kind"] == "pipeline_demonstration"
