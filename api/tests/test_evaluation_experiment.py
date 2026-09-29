"""Experiment kinds and split-structure guards.

The wallet is the independence unit; multiple windows are repeated
observations. These tests pin the guards that keep a repeated-window split
from being mislabelled an independent-wallet holdout.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.services.anomaly_ranking import (
    AnalystRubric,
    AnomalyRankingError,
    evaluate_anomaly,
    train_anomaly,
)
from app.services.evaluation_experiment import (
    ExperimentKind,
    ExperimentSplitError,
    assert_model_eval_split_valid,
    plan_group_held_out,
    plan_wallet_held_out,
)
from app.services.feature_dataset import WalletWindowRow

DAY = dt.timedelta(days=1)
JAN = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
FEB = dt.datetime(2026, 2, 1, tzinfo=dt.UTC)

RUBRIC = AnalystRubric(
    rubric_id="test-rubric",
    description="test",
    review_worthy_categories=frozenset({"review"}),
    confounder_categories=frozenset({"confounder"}),
    expected_negative_categories=frozenset({"negative"}),
)


def _row(
    wallet: str,
    start: dt.datetime,
    *,
    category: str | None = "negative",
    data_mode: str = "RECORDED_PUBLIC",
) -> WalletWindowRow:
    return WalletWindowRow(
        wallet_id=wallet,
        network="tron",
        window_start=start,
        window_end=start + DAY,
        features={},
        missingness={},
        acquisition_completeness="complete_within_scope",
        verification_quality="history_only",
        source_run_ids=("run-1",),
        control_category=category,
        data_mode=data_mode,
    )


# --- E: wallet-level split keeps every window of a wallet together -------------


def test_wallet_split_keeps_all_windows_of_a_wallet_together() -> None:
    rows = [
        _row(wallet, JAN + dt.timedelta(days=i))
        for wallet in ("wallet-a", "wallet-b", "wallet-c")
        for i in range(3)
    ]
    plan = plan_wallet_held_out(rows, eval_fraction=0.34, seed=1)

    train_wallets = {r.wallet_id for r in plan.train}
    eval_wallets = {r.wallet_id for r in plan.eval}
    assert train_wallets.isdisjoint(eval_wallets)
    for wallet in ("wallet-a", "wallet-b", "wallet-c"):
        sides = {
            "train" if r in plan.train else "eval" for r in rows if r.wallet_id == wallet
        }
        assert len(sides) == 1, f"{wallet} windows landed on both sides"


# --- F: explicit grouping keeps a group's wallets together ---------------------


def test_group_split_keeps_each_group_together() -> None:
    rows = [
        _row(wallet, JAN + dt.timedelta(days=i))
        for wallet in ("a1", "a2", "b1", "b2")
        for i in range(2)
    ]
    group_of = {"a1": "group-a", "a2": "group-a", "b1": "group-b", "b2": "group-b"}
    plan = plan_group_held_out(rows, group_of=group_of, eval_fraction=0.5, seed=3)

    train_groups = {group_of[r.wallet_id] for r in plan.train}
    eval_groups = {group_of[r.wallet_id] for r in plan.eval}
    assert train_groups.isdisjoint(eval_groups)
    assert plan.grouping_supplied is True


# --- G: absent grouping is never inferred --------------------------------------


def test_group_split_without_explicit_grouping_is_refused() -> None:
    rows = [_row("a1", JAN), _row("a2", JAN)]
    with pytest.raises(ExperimentSplitError, match="never inferred"):
        plan_group_held_out(rows, group_of={}, eval_fraction=0.5, seed=1)


# --- H: wallet-held-out refuses wallet overlap ---------------------------------


def test_wallet_held_out_refuses_wallet_overlap() -> None:
    train = [_row("shared", JAN)]
    eval_rows = [_row("shared", FEB)]
    with pytest.raises(ExperimentSplitError, match="wallet_held_out"):
        assert_model_eval_split_valid(
            ExperimentKind.wallet_held_out,
            [r.dedupe_key for r in train],
            eval_rows,
        )


# --- I: group-held-out refuses group overlap -----------------------------------


def test_group_held_out_refuses_group_overlap() -> None:
    train = [_row("x", JAN)]
    eval_rows = [_row("y", FEB)]
    with pytest.raises(ExperimentSplitError, match="group_held_out"):
        assert_model_eval_split_valid(
            ExperimentKind.group_held_out,
            [r.dedupe_key for r in train],
            eval_rows,
            group_of={"x": "g", "y": "g"},
        )


# --- J/K: future-window ordering ----------------------------------------------


def test_future_window_permits_strictly_later_windows() -> None:
    train = [_row("w", JAN)]
    eval_rows = [_row("w", FEB)]
    assert_model_eval_split_valid(
        ExperimentKind.future_window, [r.dedupe_key for r in train], eval_rows
    )


def test_future_window_rejects_backward_leakage() -> None:
    train = [_row("w", JAN + 10 * DAY)]
    eval_rows = [_row("w", JAN + 2 * DAY)]  # starts before the train window ends
    with pytest.raises(ExperimentSplitError, match="backward temporal leakage"):
        assert_model_eval_split_valid(
            ExperimentKind.future_window, [r.dedupe_key for r in train], eval_rows
        )


def test_future_window_requires_a_shared_wallet() -> None:
    train = [_row("w-train", JAN)]
    eval_rows = [_row("w-eval", FEB)]
    with pytest.raises(ExperimentSplitError, match="no wallet appears in both"):
        assert_model_eval_split_valid(
            ExperimentKind.future_window, [r.dedupe_key for r in train], eval_rows
        )


# --- L: SYNTHETIC rows never enter a real metric -------------------------------


def test_synthetic_eval_rows_refused_for_real_kinds() -> None:
    train = [_row("x", JAN)]
    eval_rows = [_row("y", FEB, data_mode="SYNTHETIC")]
    with pytest.raises(ExperimentSplitError, match="SYNTHETIC"):
        assert_model_eval_split_valid(
            ExperimentKind.wallet_held_out, [r.dedupe_key for r in train], eval_rows
        )


def test_declared_synthetic_kind_refuses_real_rows() -> None:
    train = [_row("x", JAN, data_mode="SYNTHETIC")]
    eval_rows = [_row("y", FEB, data_mode="RECORDED_PUBLIC")]
    with pytest.raises(ExperimentSplitError, match="SYNTHETIC-only"):
        assert_model_eval_split_valid(
            ExperimentKind.synthetic_pipeline_demonstration,
            [r.dedupe_key for r in train],
            eval_rows,
        )


# --- evaluate_anomaly integration ----------------------------------------------


def _model():
    return train_anomaly([_row("w", JAN), _row("w", JAN + DAY)], seed=7)


def test_shared_wallet_real_split_requires_declared_kind() -> None:
    with pytest.raises(AnomalyRankingError, match="shares wallet"):
        evaluate_anomaly(_model(), [_row("w", FEB)], rubric=RUBRIC, k=1)


def test_future_window_kind_is_reported_and_validated() -> None:
    evaluation = evaluate_anomaly(
        _model(),
        [_row("w", FEB)],
        rubric=RUBRIC,
        k=1,
        experiment_kind=ExperimentKind.future_window,
    )
    assert evaluation.experiment_kind == "future_window"
    assert evaluation.evaluation_kind == "held_out_evaluation"
    assert any("future_window" in note for note in evaluation.notes)
