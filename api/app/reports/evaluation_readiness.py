"""Stage 3B model-readiness report.

This report describes the evaluation-corpus PIPELINE and its current
contents. It computes no model metric of any kind -- no accuracy,
precision, recall, AUC, anomaly-quality, fraud-detection-quality, or
attribution-quality number appears anywhere here, because no model exists
yet (Isolation Forest training is Stage 3C, not this).

It keeps two separate questions visibly separate:

- "does the pipeline structurally work?" -- can be true even with zero real
  records, demonstrated with SYNTHETIC fixtures.
- "is the dataset adequate for a meaningful real-world evaluation?" -- this
  is reported honestly via ``READINESS_NOT_READY``/``READINESS_READY`` plus
  exact stated reasons. No arbitrary numeric minimum sample size is invented
  and presented as a scientific threshold; "N real evaluation wallets on
  file" plus named structural gaps (e.g. no related-wallet grouping data)
  are reported as-is.

It also keeps the evaluation UNITS visibly separate: registry records,
distinct accepted wallets, materialized windows, and independent upstream
sources (and related-wallet groups, when externally supplied). A wallet may
contribute many windows -- ``materialized_window_count_real`` counts windows,
``materialized_distinct_wallet_count_real`` counts wallets, and the report
says so, so a window count can never be read as a wallet count. Grouping is
never inferred; its absence is reported as a limitation.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.services.evaluation_dataset import MaterializationResult
from app.services.evaluation_wallets import (
    CONTROL_CATEGORIES,
    EvaluationWallet,
    dedupe_by_upstream_source,
)
from app.services.feature_dataset import (
    TimeLeakageError,
    assert_no_within_wallet_time_leakage,
    split_by_wallet,
    wallet_id,
)

READINESS_READY = "READY_FOR_REAL_EVALUATION"
READINESS_NOT_READY = "NOT_READY_FOR_REAL_EVALUATION"

#: This project deliberately does not pick a magic minimum-N and call it
#: "scientifically sufficient". Any real corpus at or below this size is
#: reported as not-ready with the exact count as the stated reason; it is
#: not a claim that some larger N would automatically be enough.
_ZERO = 0


@dataclass(frozen=True)
class ReadinessReport:
    generated_from_registry: str
    real_wallet_count: int
    synthetic_wallet_count: int
    counts_by_category: dict[str, int]
    counts_by_data_mode: dict[str, int]
    independent_source_count_real: int
    materialized_window_count_real: int
    materialized_window_count_synthetic: int
    #: (Stage 3B.3) ACCEPTED-only breakdowns, distinct from the registry-wide
    #: counts_by_category/independent_source_count_real above (which include
    #: unreviewed/quarantined/rejected records too). These answer "what is
    #: actually usable toward a model dataset today", not "what exists in
    #: the registry at all" -- the two questions must stay visibly separate.
    accepted_counts_by_category: dict[str, int]
    accepted_independent_source_count: int
    #: Distinct (network, address) identities among ACCEPTED records that
    #: also have a materialized window on disk -- wallet-based, not
    #: window-based: two saved windows for the same wallet count once.
    accepted_materialized_distinct_wallet_count: int
    feature_missingness: dict[str, float]
    duplicate_rows_found: int
    leakage_check_passed: bool
    leakage_check_detail: str
    #: Backward-compat name. Redefined (Stage 3B.2) to mean exactly the same
    #: thing as model_dataset_split_feasible below -- the MODEL-dataset
    #: sense, never the registry-count sense. Any caller relying on the old
    #: (registry-count) meaning must be updated; grep for split_feasible.
    split_feasible: bool
    split_feasibility_reason: str
    #: (Stage 3B.2) Registry-level: are there at least two distinct
    #: (network, address) identities in the registry at all, regardless of
    #: review state or materialization? This is a much weaker claim than
    #: model_dataset_split_feasible and must never be read as "a model
    #: train/eval split is feasible".
    registry_wallet_split_structurally_possible: bool
    #: (Stage 3B.2) The real question for training: at least two distinct
    #: MATERIALIZED real wallet ids, split_by_wallet produces non-empty
    #: train and eval partitions, and no wallet leaks across the split.
    model_dataset_split_feasible: bool
    model_dataset_split_feasibility_reason: str
    unreviewed_real_registry_record_count: int
    accepted_real_registry_record_count: int
    missing_saved_evidence_bundle_count: int
    categories_with_zero_real_examples: list[str]
    related_wallet_grouping_is_hard_blocker: bool
    snapshot_hash_real: str
    snapshot_hash_synthetic: str
    feature_definition_version: str
    unresolved_blockers: list[str]
    status: str
    status_reasons: list[str] = field(default_factory=list)
    #: Explicit evaluation-unit accounting (Stage 3D). The names state the
    #: unit so a window count can never be read as a wallet count. All
    #: defaults are empty/zero so an older caller constructing this report
    #: with keyword arguments still works.
    #: Alias of real_wallet_count, named for the "registry record" unit.
    real_registry_record_count: int = 0
    #: Distinct pseudonymous wallet ids among materialized real rows.
    materialized_distinct_wallet_count_real: int = 0
    #: wallet_id -> number of materialized real windows for that wallet.
    materialized_windows_per_wallet: dict[str, int] = field(default_factory=dict)
    wallets_with_multiple_materialized_windows: int = 0
    maximum_windows_from_one_wallet: int = 0
    #: Share of all materialized real windows contributed by the most-
    #: represented wallet; None when there are no windows. Descriptive
    #: corpus diagnostic only, never a model-quality or adequacy metric.
    most_represented_wallet_window_fraction: float | None = None
    wallets_with_exactly_one_window: int = 0
    #: Real materialized coverage by category, counted separately at window
    #: level and at wallet level: {"other_operational_confounder": {"wallets":
    #: 1, "windows": 5}} is not "examples: 5".
    materialized_category_window_counts: dict[str, int] = field(default_factory=dict)
    materialized_category_wallet_counts: dict[str, int] = field(default_factory=dict)
    #: Per-wallet concentration rows (pseudonymous wallet_id only -- never a
    #: raw address). Descriptive diagnostics, not metrics.
    corpus_concentration: list[dict[str, Any]] = field(default_factory=list)
    #: Whether an explicit related-wallet grouping was supplied by the caller.
    #: Grouping is external input; this report never infers it.
    related_wallet_grouping_supplied: bool = False
    #: Distinct related-wallet groups among materialized wallets, when
    #: grouping was supplied; None when it was not.
    materialized_distinct_group_count_real: int | None = None
    group_held_out_split_feasible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_from_registry": self.generated_from_registry,
            "real_wallet_count": self.real_wallet_count,
            "synthetic_wallet_count": self.synthetic_wallet_count,
            "counts_by_category": dict(sorted(self.counts_by_category.items())),
            "counts_by_data_mode": dict(sorted(self.counts_by_data_mode.items())),
            "independent_source_count_real": self.independent_source_count_real,
            "materialized_window_count_real": self.materialized_window_count_real,
            "materialized_window_count_synthetic": self.materialized_window_count_synthetic,
            "accepted_counts_by_category": dict(sorted(self.accepted_counts_by_category.items())),
            "accepted_independent_source_count": self.accepted_independent_source_count,
            "accepted_materialized_distinct_wallet_count": (
                self.accepted_materialized_distinct_wallet_count
            ),
            "feature_missingness": dict(sorted(self.feature_missingness.items())),
            "duplicate_rows_found": self.duplicate_rows_found,
            "leakage_check_passed": self.leakage_check_passed,
            "leakage_check_detail": self.leakage_check_detail,
            "split_feasible": self.split_feasible,
            "split_feasibility_reason": self.split_feasibility_reason,
            "registry_wallet_split_structurally_possible": (
                self.registry_wallet_split_structurally_possible
            ),
            "model_dataset_split_feasible": self.model_dataset_split_feasible,
            "model_dataset_split_feasibility_reason": self.model_dataset_split_feasibility_reason,
            "unreviewed_real_registry_record_count": self.unreviewed_real_registry_record_count,
            "accepted_real_registry_record_count": self.accepted_real_registry_record_count,
            "missing_saved_evidence_bundle_count": self.missing_saved_evidence_bundle_count,
            "categories_with_zero_real_examples": list(self.categories_with_zero_real_examples),
            "related_wallet_grouping_is_hard_blocker": (
                self.related_wallet_grouping_is_hard_blocker
            ),
            "snapshot_hash_real": self.snapshot_hash_real,
            "snapshot_hash_synthetic": self.snapshot_hash_synthetic,
            "feature_definition_version": self.feature_definition_version,
            "unresolved_blockers": list(self.unresolved_blockers),
            "status": self.status,
            "status_reasons": list(self.status_reasons),
            "real_registry_record_count": self.real_registry_record_count,
            "materialized_distinct_wallet_count_real": (
                self.materialized_distinct_wallet_count_real
            ),
            "materialized_windows_per_wallet": dict(
                sorted(self.materialized_windows_per_wallet.items())
            ),
            "wallets_with_multiple_materialized_windows": (
                self.wallets_with_multiple_materialized_windows
            ),
            "maximum_windows_from_one_wallet": self.maximum_windows_from_one_wallet,
            "most_represented_wallet_window_fraction": (
                self.most_represented_wallet_window_fraction
            ),
            "wallets_with_exactly_one_window": self.wallets_with_exactly_one_window,
            "materialized_category_window_counts": dict(
                sorted(self.materialized_category_window_counts.items())
            ),
            "materialized_category_wallet_counts": dict(
                sorted(self.materialized_category_wallet_counts.items())
            ),
            "corpus_concentration": list(self.corpus_concentration),
            "related_wallet_grouping_supplied": self.related_wallet_grouping_supplied,
            "materialized_distinct_group_count_real": (
                self.materialized_distinct_group_count_real
            ),
            "group_held_out_split_feasible": self.group_held_out_split_feasible,
            "model_metrics_reported": False,
            "no_model_trained_in_this_report": True,
        }

    def to_json(self) -> str:
        """Deterministic: sorted keys, fixed separators, no timestamp."""
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


def build_readiness_report(
    *,
    registry_path: Path,
    real_wallets: list[EvaluationWallet],
    synthetic_wallets: list[EvaluationWallet],
    real_result: MaterializationResult,
    synthetic_result: MaterializationResult,
    min_wallets_reported_as_note: int = 0,
    group_of: dict[str, str] | None = None,
) -> ReadinessReport:
    """Assemble the readiness report from already-computed inputs. Pure and
    deterministic: no wall-clock read, no random ids -- callers who want a
    "generated_at" timestamp add it outside this dict, since including one
    here would break byte-identical reproducibility for identical inputs."""
    del min_wallets_reported_as_note  # deliberately unused; see module docstring

    counts_by_category: Counter[str] = Counter(w.control_category for w in real_wallets)
    counts_by_data_mode: Counter[str] = Counter(w.data_mode for w in real_wallets)

    independent_source_count_real = dedupe_by_upstream_source(real_wallets)

    accepted_real_wallets = [w for w in real_wallets if w.review_state == "accepted"]
    accepted_counts_by_category: Counter[str] = Counter(
        w.control_category for w in accepted_real_wallets
    )
    accepted_independent_source_count = dedupe_by_upstream_source(accepted_real_wallets)
    # materialize_evaluation_dataset only ever produces rows for ACCEPTED
    # registry records (see app.services.evaluation_dataset), so the set of
    # distinct materialized wallet ids below is already accepted-only; this
    # is named separately anyway so a future change to that invariant can't
    # silently make this field wrong without a caller noticing the name.
    accepted_materialized_distinct_wallet_count = len({row.wallet_id for row in real_result.rows})

    # --- explicit evaluation-unit accounting -------------------------------
    # Windows are repeated observations, not independent subjects. These
    # counts keep the three units visibly separate so no reader can turn "N
    # windows" into "N wallets".
    windows_by_wallet: Counter[str] = Counter(row.wallet_id for row in real_result.rows)
    materialized_distinct_wallet_count_real = len(windows_by_wallet)
    wallets_with_multiple_materialized_windows = sum(
        1 for count in windows_by_wallet.values() if count > 1
    )
    maximum_windows_from_one_wallet = max(windows_by_wallet.values(), default=0)
    most_represented_wallet_window_fraction = (
        maximum_windows_from_one_wallet / len(real_result.rows) if real_result.rows else None
    )
    wallets_with_exactly_one_window = sum(
        1 for count in windows_by_wallet.values() if count == 1
    )

    # Pseudonymous wallet_id -> registry record, for category/upstream
    # provenance in the concentration section. Raw addresses never appear.
    registry_by_wallet_id = {
        wallet_id(record.network, record.address): record for record in accepted_real_wallets
    }
    corpus_concentration: list[dict[str, Any]] = []
    for wid, count in sorted(windows_by_wallet.items()):
        wallet_rows = [row for row in real_result.rows if row.wallet_id == wid]
        record = registry_by_wallet_id.get(wid)
        corpus_concentration.append(
            {
                "wallet_id": wid,
                "window_count": count,
                "control_category": (
                    record.control_category
                    if record is not None
                    else wallet_rows[0].control_category
                ),
                "upstream_source_id": record.upstream_source_id if record is not None else "",
                "earliest_window_start": min(r.window_start for r in wallet_rows).isoformat(),
                "latest_window_cutoff": max(r.window_end for r in wallet_rows).isoformat(),
            }
        )

    materialized_category_window_counts: Counter[str] = Counter(
        row.control_category or "unknown" for row in real_result.rows
    )
    category_by_wallet: dict[str, str] = {}
    for row in real_result.rows:
        category_by_wallet.setdefault(row.wallet_id, row.control_category or "unknown")
    materialized_category_wallet_counts: Counter[str] = Counter(category_by_wallet.values())

    # Related-wallet grouping is EXTERNAL input. Supplying it enables a
    # group-held-out split; its absence is reported as a limitation, never
    # silently filled with an inferred heuristic.
    related_wallet_grouping_supplied = bool(group_of)
    materialized_distinct_group_count_real: int | None = None
    group_held_out_split_feasible = False
    if group_of and windows_by_wallet:
        materialized_distinct_group_count_real = len(
            {group_of.get(w, w) for w in windows_by_wallet}
        )
        if materialized_distinct_group_count_real >= 2:
            group_train, group_eval = split_by_wallet(
                real_result.rows, eval_fraction=0.5, seed=0, group_of=group_of
            )
            group_held_out_split_feasible = bool(group_train and group_eval)

    missingness: dict[str, list[bool]] = {}
    for row in real_result.rows:
        for name, is_missing in row.missingness.items():
            missingness.setdefault(name, []).append(is_missing)
    feature_missingness = {
        name: (sum(1 for m in flags if m) / len(flags)) for name, flags in missingness.items()
    }

    dedupe_keys = [row.dedupe_key for row in real_result.rows]
    duplicate_rows_found = len(dedupe_keys) - len(set(dedupe_keys))

    # Documented limitation, not a permanent hard policy blocker (Stage
    # 3B.2 DECISIONS.md entry, 2026-09-21): this repository has no
    # defensible related-wallet grouping data yet. split_by_wallet's
    # optional group_of mapping exists and is available to a future
    # operator decision; this report does not populate it with any
    # fabricated grouping heuristic. An operator may later decide this
    # should become a hard blocker on READY status -- that decision is not
    # made here.
    related_wallet_grouping_is_hard_blocker = False
    unresolved_blockers: list[str] = []
    if not related_wallet_grouping_supplied:
        unresolved_blockers.append(
            "no explicit related-wallet grouping was supplied; only a wallet-level "
            "split is available and split_by_wallet's optional group_of mapping is "
            "left unused rather than filled with a fabricated grouping heuristic "
            "(documented limitation, not a hard blocker -- see DECISIONS.md 2026-09-21)"
        )
    real_wallet_count = len(real_wallets)
    real_registry_record_count = real_wallet_count
    unreviewed_real_registry_record_count = sum(
        1 for w in real_wallets if w.review_state == "unreviewed"
    )
    accepted_real_registry_record_count = sum(
        1 for w in real_wallets if w.review_state == "accepted"
    )
    missing_saved_evidence_bundle_count = sum(
        1 for s in real_result.skipped if s.reason == "missing_evidence"
    )
    categories_with_zero_real_examples = sorted(
        CONTROL_CATEGORIES - set(counts_by_category)
    )

    status_reasons: list[str] = []
    if real_wallet_count == 0:
        status_reasons.append("0 real evaluation wallets on file")
    else:
        status_reasons.append(f"{real_wallet_count} real evaluation wallets on file")
    if unreviewed_real_registry_record_count:
        status_reasons.append(
            f"{unreviewed_real_registry_record_count} unreviewed real registry record(s) "
            "pending human decision"
        )
    if accepted_real_registry_record_count == 0:
        status_reasons.append("0 accepted real registry records")
    if len(real_result.rows) == 0:
        status_reasons.append("0 materialized real windows")
    status_reasons.append(
        f"{accepted_materialized_distinct_wallet_count} distinct accepted materialized real "
        "wallet(s) available; a wallet-separated train/evaluation split requires at least 2, "
        "so it cannot yet be formed"
        if accepted_materialized_distinct_wallet_count < 2
        else f"{accepted_materialized_distinct_wallet_count} distinct accepted materialized "
        "real wallets available"
    )
    status_reasons.append(
        f"materialization units are reported separately: {len(real_result.rows)} "
        f"materialized real window(s) across {materialized_distinct_wallet_count_real} "
        "distinct materialized real wallet(s) -- N windows is not N wallets"
    )
    if wallets_with_multiple_materialized_windows:
        status_reasons.append(
            f"{wallets_with_multiple_materialized_windows} wallet(s) contribute more than "
            f"one window; the most-represented wallet contributes "
            f"{maximum_windows_from_one_wallet} window(s)"
        )
    if not related_wallet_grouping_supplied:
        status_reasons.append(
            "no explicit related-wallet grouping supplied; only a wallet-level split can "
            "be formed, and no grouping is inferred"
        )
    else:
        status_reasons.append(
            "explicit related-wallet grouping supplied: "
            f"{materialized_distinct_group_count_real} group(s) among materialized wallets; "
            f"group-held-out split structurally feasible: {group_held_out_split_feasible}"
        )
    if missing_saved_evidence_bundle_count:
        status_reasons.append(
            f"{missing_saved_evidence_bundle_count} registry record(s) missing a saved "
            "evidence bundle"
        )
    if categories_with_zero_real_examples:
        status_reasons.append(
            "categories with zero real examples (coverage info, not a scientific-adequacy "
            f"threshold): {', '.join(categories_with_zero_real_examples)}"
        )
    status_reasons.append(
        "no numeric minimum sample size is treated as sufficient by policy; "
        "readiness is reported on the actual count plus named structural gaps only"
    )
    status_reasons.extend(unresolved_blockers)

    # unresolved_blockers is never empty by construction above (the
    # related-wallet-grouping gap always applies), so this report never
    # claims READY in this increment -- stated explicitly rather than left
    # to fall out of a boolean by accident.
    status = READINESS_NOT_READY

    registry_wallet_split_structurally_possible = (
        len({(w.network, w.address) for w in real_wallets}) >= 2
    )

    distinct_materialized_wallets = {row.wallet_id for row in real_result.rows}
    if len(distinct_materialized_wallets) < 2:
        model_dataset_split_feasible = False
        model_dataset_split_feasibility_reason = (
            f"only {len(distinct_materialized_wallets)} distinct MATERIALIZED real "
            "wallet(s) on file; at least 2 are required for a train/eval split by "
            "wallet -- a materialized window is required, not merely a registry record"
        )
    else:
        split_train, split_eval = split_by_wallet(
            real_result.rows, eval_fraction=0.5, seed=0
        )
        if not split_train or not split_eval:
            model_dataset_split_feasible = False
            model_dataset_split_feasibility_reason = (
                "splitting the materialized real rows by wallet produced an empty "
                "train or eval partition"
            )
        else:
            try:
                assert_no_within_wallet_time_leakage(split_train, split_eval)
            except TimeLeakageError as exc:
                model_dataset_split_feasible = False
                model_dataset_split_feasibility_reason = f"wallet leakage detected: {exc}"
            else:
                model_dataset_split_feasible = True
                model_dataset_split_feasibility_reason = (
                    f"{len(distinct_materialized_wallets)} distinct materialized real "
                    "wallets; split_by_wallet produces non-empty train and eval "
                    "partitions with no within-wallet time leakage. This is a "
                    "structural-computability statement only -- it makes no claim "
                    "about scientific adequacy of the sample size."
                )

    # split_feasible is kept for backward compatibility and is now defined
    # identically to model_dataset_split_feasible -- never the old
    # registry-count meaning.
    split_feasible = model_dataset_split_feasible
    split_feasibility_reason = model_dataset_split_feasibility_reason

    return ReadinessReport(
        generated_from_registry=str(registry_path),
        real_wallet_count=real_wallet_count,
        synthetic_wallet_count=len(synthetic_wallets),
        counts_by_category=dict(counts_by_category),
        counts_by_data_mode=dict(counts_by_data_mode),
        independent_source_count_real=independent_source_count_real,
        materialized_window_count_real=len(real_result.rows),
        materialized_window_count_synthetic=len(synthetic_result.rows),
        accepted_counts_by_category=dict(accepted_counts_by_category),
        accepted_independent_source_count=accepted_independent_source_count,
        accepted_materialized_distinct_wallet_count=accepted_materialized_distinct_wallet_count,
        feature_missingness=feature_missingness,
        duplicate_rows_found=duplicate_rows_found,
        leakage_check_passed=True,
        leakage_check_detail=(
            "duplicate-row and within-wallet time-leakage checks performed by the "
            "caller before calling this function; see "
            "app.services.feature_dataset.assert_no_within_wallet_time_leakage and "
            "dedupe_rows"
        ),
        split_feasible=split_feasible,
        split_feasibility_reason=split_feasibility_reason,
        registry_wallet_split_structurally_possible=registry_wallet_split_structurally_possible,
        model_dataset_split_feasible=model_dataset_split_feasible,
        model_dataset_split_feasibility_reason=model_dataset_split_feasibility_reason,
        unreviewed_real_registry_record_count=unreviewed_real_registry_record_count,
        accepted_real_registry_record_count=accepted_real_registry_record_count,
        missing_saved_evidence_bundle_count=missing_saved_evidence_bundle_count,
        categories_with_zero_real_examples=categories_with_zero_real_examples,
        related_wallet_grouping_is_hard_blocker=related_wallet_grouping_is_hard_blocker,
        snapshot_hash_real=real_result.snapshot_hash,
        snapshot_hash_synthetic=synthetic_result.snapshot_hash,
        feature_definition_version=real_result.feature_definition_version,
        unresolved_blockers=unresolved_blockers,
        status=status,
        status_reasons=status_reasons,
        real_registry_record_count=real_registry_record_count,
        materialized_distinct_wallet_count_real=materialized_distinct_wallet_count_real,
        materialized_windows_per_wallet=dict(windows_by_wallet),
        wallets_with_multiple_materialized_windows=(
            wallets_with_multiple_materialized_windows
        ),
        maximum_windows_from_one_wallet=maximum_windows_from_one_wallet,
        most_represented_wallet_window_fraction=most_represented_wallet_window_fraction,
        wallets_with_exactly_one_window=wallets_with_exactly_one_window,
        materialized_category_window_counts=dict(materialized_category_window_counts),
        materialized_category_wallet_counts=dict(materialized_category_wallet_counts),
        corpus_concentration=corpus_concentration,
        related_wallet_grouping_supplied=related_wallet_grouping_supplied,
        materialized_distinct_group_count_real=materialized_distinct_group_count_real,
        group_held_out_split_feasible=group_held_out_split_feasible,
    )


def render_readiness_html(report: ReadinessReport) -> str:
    import html as html_mod

    def esc(value: Any) -> str:
        return html_mod.escape(str(value))

    rows = "".join(
        f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>" for k, v in sorted(report.to_dict().items())
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Stage 3B evaluation-corpus readiness report</title></head><body>"
        f"<h1>Status: {esc(report.status)}</h1>"
        "<p>This report contains no model accuracy/precision/recall/AUC metric -- "
        "no model has been trained. It describes the evaluation corpus and pipeline "
        "only.</p>"
        f"<table border='1' cellpadding='4'>{rows}</table>"
        "</body></html>"
    )


def hash_registry_file(path: Path) -> str:
    if not path.is_file():
        return hashlib.sha256(b"").hexdigest()
    return hashlib.sha256(path.read_bytes()).hexdigest()
