"""Stage 3 prep: converts SAVED feature records into one reproducible
wallet-window table, offline, with no network access and no model behind
it yet.

A row here is a candidate's (or an independently sourced control wallet's)
observed activity within one declared window, not the wallet itself: the
same address observed in two different windows is two distinct rows. The
address string never becomes a feature value -- ``wallet_id`` is a
pseudonymous digest, computed the same way every time from
(network, address), so the same wallet always gets the same id without the
raw address ever appearing in a feature column.

No address string, complaint label, future outcome, or case id is a
feature. A control_category, when independently established, travels with
the row as its own field -- never folded into the numeric features, and
never invented when no evaluation_wallets.csv record exists for the
address (see app.services.evaluation_wallets.find_evaluation_wallet: a
missing record means "not independently evaluated", not "negative").

Current-state and historical resource features stay under their own,
already-distinct names (see app.services.features.extract_features); this
module does not compute any feature that merges the two.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.services.features import Feature

#: Fields a wallet-window row must never carry as a feature. Enforced by
#: _reject_disallowed_feature_names below -- a caller passing a Feature
#: named one of these (or containing an address-shaped value) is a bug to
#: surface immediately, not a row to silently accept.
DISALLOWED_FEATURE_NAME_FRAGMENTS = (
    "address",
    "complaint",
    "case_id",
    "outcome",
    "service_name",
    "review_state",
)

#: Bumped whenever the feature set/definitions change. Included in every
#: WalletWindowRow and in the evaluation-dataset snapshot hash, so a change
#: to what a feature *means* is never silently hidden inside an unchanged
#: dataset identity (Stage 3B item 4/item 5 "changing feature_definition_version
#: changes the dataset snapshot identity").
FEATURE_DEFINITION_VERSION = "v1-2026-09-20"


class FeatureDatasetError(RuntimeError):
    """A row would have carried something it must never carry."""


def wallet_id(network: str, address: str) -> str:
    """A deterministic, non-reversible-in-practice identifier for one
    (network, address) pair. Same input always yields the same id; the
    address itself never appears in any exported feature row."""
    digest = hashlib.sha256(f"{network}:{address}".encode()).hexdigest()
    return digest[:16]


@dataclass(frozen=True)
class WalletWindowRow:
    wallet_id: str
    network: str
    window_start: dt.datetime
    window_end: dt.datetime
    #: feature name -> value (None means missing/unknown, never 0).
    features: dict[str, Any]
    #: feature name -> True if that feature's value is missing/unknown.
    missingness: dict[str, bool]
    acquisition_completeness: str
    verification_quality: str
    source_run_ids: tuple[str, ...]
    #: None means "not independently evaluated" -- never a negative label.
    control_category: str | None = None
    #: Bumped whenever the feature definitions change (see
    #: FEATURE_DEFINITION_VERSION). Recorded on the row itself so a stored
    #: dataset never silently mixes rows built under two different
    #: definitions of the same feature name.
    feature_definition_version: str = FEATURE_DEFINITION_VERSION
    #: LIVE / RECORDED_PUBLIC / SYNTHETIC -- carried through from the
    #: evaluation-wallet record and/or saved evidence run this row was built
    #: from. Never inferred; a caller that doesn't know it must say so.
    data_mode: str = "UNKNOWN"
    #: Points back to the evaluation-registry record (network/address is
    #: already pseudonymized into wallet_id; this is the record's own
    #: source_reference) this row's control_category came from, if any.
    evaluation_source_reference: str | None = None

    @property
    def dedupe_key(self) -> tuple[str, str, str, str]:
        """Identifies "the same materialized row" for duplicate suppression:
        same wallet, same declared window, same feature definitions. Built
        twice from the same saved evidence, this key is identical -- so
        re-materializing never silently doubles a wallet's contribution to
        the dataset."""
        return (
            self.wallet_id,
            self.window_start.isoformat(),
            self.window_end.isoformat(),
            self.feature_definition_version,
        )

    def to_flat_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "wallet_id": self.wallet_id,
            "network": self.network,
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "acquisition_completeness": self.acquisition_completeness,
            "verification_quality": self.verification_quality,
            "source_run_ids": ";".join(self.source_run_ids),
            "control_category": self.control_category or "",
            "feature_definition_version": self.feature_definition_version,
            "data_mode": self.data_mode,
            "evaluation_source_reference": self.evaluation_source_reference or "",
        }
        for name, value in self.features.items():
            row[f"feature__{name}"] = value
            row[f"missing__{name}"] = self.missingness.get(name, value is None)
        return row


def _reject_disallowed_feature_names(features: list[Feature]) -> None:
    for f in features:
        lowered = f.name.lower()
        for fragment in DISALLOWED_FEATURE_NAME_FRAGMENTS:
            if fragment in lowered:
                raise FeatureDatasetError(
                    f"feature {f.name!r} is disallowed in a wallet-window row: "
                    f"contains {fragment!r}"
                )


def build_wallet_window_row(
    *,
    network: str,
    address: str,
    window_start: dt.datetime,
    window_end: dt.datetime,
    acquisition_completeness: str,
    verification_quality: str,
    source_run_ids: tuple[str, ...],
    behavioral_features: Sequence[Feature] = (),
    resource_features: Sequence[Feature] = (),
    control_category: str | None = None,
    feature_definition_version: str = FEATURE_DEFINITION_VERSION,
    data_mode: str = "UNKNOWN",
    evaluation_source_reference: str | None = None,
) -> WalletWindowRow:
    """Pure function: same inputs always produce an equal WalletWindowRow
    (see test_feature_dataset.py::test_feature_dataset_generation_is_deterministic).

    ``behavioral_features`` and ``resource_features`` are the already-computed
    Feature lists from compute_behavioral_features_from_run and
    extract_features respectively -- this function does not recompute
    anything, it only assembles what was already saved. Namespacing each
    source's features under its own prefix (behavioral_*, resource_*) is
    what keeps current-state resource features (already separately named,
    e.g. current_resource_counterparty_count) and historical ones
    (historical_delegation_operation_count) from ever being merged into one
    combined number.
    """
    behavioral_list = list(behavioral_features)
    resource_list = list(resource_features)
    _reject_disallowed_feature_names(behavioral_list)
    _reject_disallowed_feature_names(resource_list)

    features: dict[str, Any] = {}
    missingness: dict[str, bool] = {}
    for prefix, feats in (("behavioral_", behavioral_list), ("resource_", resource_list)):
        for f in feats:
            key = f"{prefix}{f.name}"
            features[key] = f.value
            missingness[key] = f.value is None

    return WalletWindowRow(
        wallet_id=wallet_id(network, address),
        network=network,
        window_start=window_start,
        window_end=window_end,
        features=features,
        missingness=missingness,
        acquisition_completeness=acquisition_completeness,
        verification_quality=verification_quality,
        source_run_ids=tuple(source_run_ids),
        control_category=control_category,
        feature_definition_version=feature_definition_version,
        data_mode=data_mode,
        evaluation_source_reference=evaluation_source_reference,
    )


def dedupe_rows(rows: list[WalletWindowRow]) -> list[WalletWindowRow]:
    """Drop rows that are "the same materialized row" by dedupe_key,
    keeping the first occurrence. Re-materializing from the same saved
    evidence run (or re-ingesting the same evaluation-wallet CSV row) must
    never double a wallet's contribution to the dataset."""
    seen: set[tuple[str, str, str, str]] = set()
    out: list[WalletWindowRow] = []
    for row in rows:
        key = row.dedupe_key
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


class TimeLeakageError(RuntimeError):
    """A wallet's later window landed in train while an earlier window of
    the SAME wallet landed in eval (or vice versa) -- a stronger, per-wallet
    check than the global split_by_time boundary."""


def assert_no_within_wallet_time_leakage(
    train: list[WalletWindowRow], eval_rows: list[WalletWindowRow]
) -> None:
    """Raise if any wallet has a train window that starts at or after an
    eval window of that same wallet. A global time cutoff (split_by_time)
    only guarantees train windows are chronologically before eval windows
    in aggregate; it says nothing, by itself, about one specific wallet
    that might contribute rows on both sides straddling the cutoff."""
    earliest_eval_by_wallet: dict[str, dt.datetime] = {}
    for row in eval_rows:
        current = earliest_eval_by_wallet.get(row.wallet_id)
        if current is None or row.window_start < current:
            earliest_eval_by_wallet[row.wallet_id] = row.window_start

    for row in train:
        earliest_eval = earliest_eval_by_wallet.get(row.wallet_id)
        if earliest_eval is not None and row.window_start >= earliest_eval:
            raise TimeLeakageError(
                f"wallet {row.wallet_id} has a train window starting "
                f"{row.window_start.isoformat()}, at or after its own eval window "
                f"starting {earliest_eval.isoformat()}"
            )


def split_by_wallet(
    rows: list[WalletWindowRow],
    *,
    eval_fraction: float,
    seed: int,
    group_of: dict[str, str] | None = None,
) -> tuple[list[WalletWindowRow], list[WalletWindowRow]]:
    """Stage 3 prep only -- no model is trained here.

    Groups every row by wallet_id (or, if ``group_of`` maps a wallet_id to a
    wider group id, by that group instead) and assigns each *group* wholly
    to train or to eval, so near-duplicate windows from the same wallet --
    or from wallets a caller has explicitly declared related for split
    purposes only, never for attribution -- cannot land on both sides.

    Deterministic: the same rows, eval_fraction, seed, and group_of always
    produce the same split, via a hash of (seed, group_id) rather than
    Python's process-randomized hash or an unseeded shuffle.
    """
    if not 0.0 <= eval_fraction <= 1.0:
        raise ValueError("eval_fraction must be between 0.0 and 1.0")

    def _group(row: WalletWindowRow) -> str:
        return (group_of or {}).get(row.wallet_id, row.wallet_id)

    groups = sorted({_group(row) for row in rows})
    if not groups:
        return [], []
    ranked = sorted(groups, key=lambda g: hashlib.sha256(f"{seed}:{g}".encode()).hexdigest())
    eval_count = round(len(ranked) * eval_fraction)
    eval_groups = set(ranked[:eval_count])

    train_rows = [row for row in rows if _group(row) not in eval_groups]
    eval_rows = [row for row in rows if _group(row) in eval_groups]
    return train_rows, eval_rows


def split_by_time(
    rows: list[WalletWindowRow], *, cutoff: dt.datetime
) -> tuple[list[WalletWindowRow], list[WalletWindowRow]]:
    """Every row whose window starts before ``cutoff`` goes to train;
    every row starting at or after it goes to eval. Deterministic given a
    fixed cutoff -- no randomness, no shuffling.

    This does not by itself prevent the same wallet from appearing on both
    sides across the cutoff; combine with split_by_wallet's grouping (pass
    the same wallet's rows entirely to one side) when that matters."""
    train_rows = [row for row in rows if row.window_start < cutoff]
    eval_rows = [row for row in rows if row.window_start >= cutoff]
    return train_rows, eval_rows


def build_feature_table(rows: list[WalletWindowRow]) -> tuple[list[str], list[dict[str, Any]]]:
    """A wide table over an arbitrary set of rows: the header is the union
    of every column any row carries, and every row is padded with blanks
    for columns it does not have -- so two candidates observed with
    different feature sets (e.g. one with resource evidence, one without)
    can still sit in one reproducible table.

    Deterministic column order: fixed columns first, then every
    feature/missing pair in sorted name order.
    """
    fixed = [
        "wallet_id",
        "network",
        "window_start",
        "window_end",
        "acquisition_completeness",
        "verification_quality",
        "source_run_ids",
        "control_category",
    ]
    flat_rows = [row.to_flat_dict() for row in rows]
    dynamic_columns = sorted({key for row in flat_rows for key in row if key not in fixed})
    header = fixed + dynamic_columns
    table = [{col: row.get(col, "") for col in header} for row in flat_rows]
    return header, table
