"""Experiment kinds and split-structure guards for the evaluation corpus.

The wallet is the primary independence unit. Several windows saved for one
wallet are REPEATED OBSERVATIONS of that wallet, never several independent
subjects -- so a corpus of 20 windows from 2 wallets is a 2-wallet corpus, not
a 20-wallet one. Upstream-source independence is a third, separate axis: five
windows sourced from one first-party disclosure are still one source basis.

This module supplies two things and no modeling:

- the explicit ``ExperimentKind`` vocabulary a report must declare, and
- guards that fail loudly when a declared kind disagrees with the actual split
  structure (wallet overlap for ``wallet_held_out``, group overlap for
  ``group_held_out``, backward temporal leakage for ``future_window``, or
  SYNTHETIC rows in any real metric).

Related-wallet grouping is EXTERNAL input (``group_of``). This module never
infers relatedness from a shared funder, resource sponsor, behavioral
similarity, timing, or destination.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.services.feature_dataset import WalletWindowRow, split_by_wallet

#: The dedupe key carried by a WalletWindowRow: (wallet_id, window_start,
#: window_end, feature_definition_version).
RowKey = tuple[str, str, str, str]


class ExperimentSplitError(RuntimeError):
    """The declared experiment kind and the split structure disagree, or a
    split would leak information across train and evaluation."""


class ExperimentKind(StrEnum):
    wallet_held_out = "wallet_held_out"
    group_held_out = "group_held_out"
    future_window = "future_window"
    synthetic_pipeline_demonstration = "synthetic_pipeline_demonstration"


@dataclass(frozen=True)
class SplitPlan:
    """A train/eval partition plus the experiment it represents. ``train`` and
    ``eval`` are tuples so a plan cannot be mutated after validation while a
    later step still holds a reference to it."""

    experiment_kind: ExperimentKind
    train: tuple[WalletWindowRow, ...]
    eval: tuple[WalletWindowRow, ...]
    group_of: dict[str, str] | None = None
    grouping_supplied: bool = False

    @property
    def train_wallet_ids(self) -> frozenset[str]:
        return frozenset(row.wallet_id for row in self.train)

    @property
    def eval_wallet_ids(self) -> frozenset[str]:
        return frozenset(row.wallet_id for row in self.eval)


def _parse(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value)


def _windows_by_wallet(
    train_keys: Iterable[RowKey],
) -> dict[str, list[tuple[dt.datetime, dt.datetime]]]:
    windows: dict[str, list[tuple[dt.datetime, dt.datetime]]] = {}
    for key in train_keys:
        windows.setdefault(key[0], []).append((_parse(key[1]), _parse(key[2])))
    return windows


def _validate(
    *,
    experiment_kind: ExperimentKind,
    training_row_keys: Iterable[RowKey],
    eval_rows: Sequence[WalletWindowRow],
    group_of: Mapping[str, str] | None,
) -> None:
    train_keys = set(training_row_keys)
    eval_keys = {row.dedupe_key for row in eval_rows}

    overlap = train_keys & eval_keys
    if overlap:
        raise ExperimentSplitError(
            f"{len(overlap)} row(s) appear in both training and evaluation"
        )
    if not eval_rows:
        return

    train_wallets = {key[0] for key in train_keys}
    eval_wallets = {row.wallet_id for row in eval_rows}
    eval_modes = {row.data_mode for row in eval_rows}

    if experiment_kind is ExperimentKind.synthetic_pipeline_demonstration:
        unexpected = eval_modes - {"SYNTHETIC"}
        if unexpected:
            raise ExperimentSplitError(
                "declared synthetic_pipeline_demonstration but evaluation rows carry "
                f"data_mode(s) {sorted(unexpected)}; a demonstration must be "
                "SYNTHETIC-only"
            )
        return

    if "SYNTHETIC" in eval_modes:
        raise ExperimentSplitError(
            "SYNTHETIC rows must never enter a real evaluation metric; declare "
            "synthetic_pipeline_demonstration for a synthetic-only run"
        )

    if experiment_kind is ExperimentKind.wallet_held_out:
        shared = train_wallets & eval_wallets
        if shared:
            raise ExperimentSplitError(
                f"wallet_held_out: {len(shared)} wallet id(s) appear in both training "
                "and evaluation; windows of one wallet are not independent subjects"
            )
        return

    if experiment_kind is ExperimentKind.group_held_out:
        if not group_of:
            raise ExperimentSplitError(
                "group_held_out requires an explicit group_of mapping; related-wallet "
                "grouping is externally supplied and never inferred"
            )

        def group(wallet: str) -> str:
            return group_of.get(wallet, wallet)

        train_groups = {group(w) for w in train_wallets}
        eval_groups = {group(w) for w in eval_wallets}
        shared_groups = train_groups & eval_groups
        if shared_groups:
            raise ExperimentSplitError(
                f"group_held_out: {len(shared_groups)} related-wallet group(s) appear on "
                "both sides of the split"
            )
        return

    if experiment_kind is ExperimentKind.future_window:
        shared = train_wallets & eval_wallets
        if not shared:
            raise ExperimentSplitError(
                "future_window declared but no wallet appears in both training and "
                "evaluation; a future-window experiment evaluates a wallet already "
                "represented in training"
            )
        train_windows = _windows_by_wallet(train_keys)
        for wallet in sorted(shared):
            latest_train_end = max(end for _, end in train_windows[wallet])
            earliest_eval_start = min(
                row.window_start for row in eval_rows if row.wallet_id == wallet
            )
            if earliest_eval_start <= latest_train_end:
                raise ExperimentSplitError(
                    f"future_window: wallet {wallet} has an evaluation window starting "
                    f"{earliest_eval_start.isoformat()}, not strictly after its latest "
                    f"training window ending {latest_train_end.isoformat()} "
                    "(backward temporal leakage)"
                )
        return

    raise ExperimentSplitError(f"unknown experiment kind {experiment_kind!r}")


def assert_model_eval_split_valid(
    experiment_kind: ExperimentKind | str,
    training_row_keys: Iterable[RowKey],
    eval_rows: Sequence[WalletWindowRow],
    *,
    group_of: Mapping[str, str] | None = None,
) -> None:
    """Guard used where only the fitted model's row keys are available (the
    model already records exactly which rows it was trained on)."""
    _validate(
        experiment_kind=ExperimentKind(experiment_kind),
        training_row_keys=training_row_keys,
        eval_rows=eval_rows,
        group_of=group_of,
    )


def assert_split_plan_valid(plan: SplitPlan) -> None:
    """Guard used where both row sets are in hand."""
    _validate(
        experiment_kind=plan.experiment_kind,
        training_row_keys=[row.dedupe_key for row in plan.train],
        eval_rows=list(plan.eval),
        group_of=plan.group_of,
    )


def plan_wallet_held_out(
    rows: Sequence[WalletWindowRow], *, eval_fraction: float, seed: int = 0
) -> SplitPlan:
    train, eval_rows = split_by_wallet(list(rows), eval_fraction=eval_fraction, seed=seed)
    plan = SplitPlan(
        experiment_kind=ExperimentKind.wallet_held_out,
        train=tuple(train),
        eval=tuple(eval_rows),
    )
    assert_split_plan_valid(plan)
    return plan


def plan_group_held_out(
    rows: Sequence[WalletWindowRow],
    *,
    group_of: Mapping[str, str],
    eval_fraction: float,
    seed: int = 0,
) -> SplitPlan:
    if not group_of:
        raise ExperimentSplitError(
            "group_held_out requires a non-empty explicit group_of mapping; "
            "related-wallet grouping is never inferred"
        )
    train, eval_rows = split_by_wallet(
        list(rows), eval_fraction=eval_fraction, seed=seed, group_of=dict(group_of)
    )
    plan = SplitPlan(
        experiment_kind=ExperimentKind.group_held_out,
        train=tuple(train),
        eval=tuple(eval_rows),
        group_of=dict(group_of),
        grouping_supplied=True,
    )
    assert_split_plan_valid(plan)
    return plan


def plan_future_window(
    train_rows: Sequence[WalletWindowRow], eval_rows: Sequence[WalletWindowRow]
) -> SplitPlan:
    plan = SplitPlan(
        experiment_kind=ExperimentKind.future_window,
        train=tuple(train_rows),
        eval=tuple(eval_rows),
    )
    assert_split_plan_valid(plan)
    return plan


def plan_synthetic_pipeline_demonstration(
    train_rows: Sequence[WalletWindowRow], eval_rows: Sequence[WalletWindowRow]
) -> SplitPlan:
    plan = SplitPlan(
        experiment_kind=ExperimentKind.synthetic_pipeline_demonstration,
        train=tuple(train_rows),
        eval=tuple(eval_rows),
    )
    assert_split_plan_valid(plan)
    return plan
