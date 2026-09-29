"""Stage 3C: a small, deterministic Isolation Forest (scikit-learn) that
ranks wallet-window OBSERVATIONS for analyst review priority.

What this is
------------
Given already-materialized ``WalletWindowRow`` observations (see
app.services.feature_dataset), this module extracts a fixed, versioned set
of numeric behavioral features, fits an Isolation Forest on a caller-supplied
TRAINING set, and scores rows. A lower ``score_samples`` value means "more
isolated" within the training distribution, i.e. more review-worthy; scores
are NOT probabilities, NOT fraud likelihoods, and NOT attribution evidence.

What this is not
----------------
- Not service identification: a high rank never names or implies an exchange,
  a service, or an owner. It is carried alongside -- and never merged into --
  the Stage 3A service-outcome layer and the Stage 1 transfer evidence.
- Not a fraud signal: it ranks unusualness relative to the training sample
  only. Operational confounders (a marketplace's own address, a corporate
  treasury) can rank high purely on shape; that is expected and is not fraud.
- Not calibrated: no accuracy/precision/recall/AUC/probability is produced
  here. Held-out evaluation is a separate step (Stage 3C evaluation) and, until
  real accepted-and-materialized windows exist, can only be a SYNTHETIC
  pipeline demonstration.

Missing data
------------
A missing feature is missing data, never suspicious. Each feature's imputation
value is the median of that feature's non-missing TRAIN values (0.0 only if a
feature is entirely missing in train); an imputed cell therefore sits at the
"typical" value, and every score records exactly which features it imputed, so
missingness is visible rather than scored.

Isolation (must hold, and is grep-tested)
-----------------------------------------
This module never imports app.engine.tracer, app.services.evidence_*
app.services.service_outcome, or app.services.strong_inference_policy, and
nothing in the tracing/evidence path imports this module. Disabling the
ranker cannot change observed transfer evidence or service labels.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import statistics
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sklearn.ensemble import IsolationForest

from app.services.evaluation_experiment import (
    ExperimentKind,
    assert_model_eval_split_valid,
)
from app.services.feature_dataset import (
    DISALLOWED_FEATURE_NAME_FRAGMENTS,
    FEATURE_DEFINITION_VERSION,
    WalletWindowRow,
)

#: Bumped whenever the curated feature set or a feature's transform changes,
#: independently of FEATURE_DEFINITION_VERSION (which versions how the
#: *underlying* features are computed). A model stores both, so a change to
#: what the ranker sees is never hidden inside an unchanged feature version.
ANOMALY_FEATURE_VERSION = "anomaly-features-v1-2026-09-21"

#: Bumped when the model algorithm/hyperparameters change.
MODEL_VERSION = "iforest-sklearn-v1-2026-09-21"

TRANSFORM_IDENTITY = "identity"
TRANSFORM_LOG1P = "log1p"
#: sign(x) * log1p(|x|) -- for signed, heavy-tailed values (e.g. residue).
TRANSFORM_SIGNED_LOG1P = "signed_log1p"

#: The curated, NUMERIC-ONLY feature allowlist, as the keys they carry on a
#: WalletWindowRow (``behavioral_``/``resource_`` prefixed). Deliberately
#: excludes: every string provenance/quality feature, window timestamps,
#: booleans, and any address, case id, complaint/outcome field, or service
#: name. ``receipt_to_outflow_timing_seconds`` is excluded on purpose: it is
#: emitted once per matched outgoing row, so it collapses to a single
#: last-wins value in the row dict and is not a well-defined summary; the
#: min/median/count summaries are used instead.
ANOMALY_FEATURES: tuple[tuple[str, str], ...] = (
    ("behavioral_observed_incoming_transfer_count", TRANSFORM_LOG1P),
    ("behavioral_observed_outgoing_transfer_count", TRANSFORM_LOG1P),
    ("behavioral_distinct_incoming_counterparty_count", TRANSFORM_LOG1P),
    ("behavioral_distinct_outgoing_counterparty_count", TRANSFORM_LOG1P),
    ("behavioral_observed_incoming_amount_base_units", TRANSFORM_LOG1P),
    ("behavioral_observed_outgoing_amount_base_units", TRANSFORM_LOG1P),
    ("behavioral_outgoing_concentration_toward_accepted_anchor", TRANSFORM_IDENTITY),
    ("behavioral_outgoing_concentration_max_by_count", TRANSFORM_IDENTITY),
    ("behavioral_outgoing_concentration_max_by_amount", TRANSFORM_IDENTITY),
    ("behavioral_outgoing_counterparties_with_repeat_count", TRANSFORM_LOG1P),
    ("behavioral_repeated_forwarding_count", TRANSFORM_LOG1P),
    ("behavioral_receipt_to_outflow_observation_count", TRANSFORM_LOG1P),
    ("behavioral_receipt_to_outflow_ambiguous_count", TRANSFORM_LOG1P),
    ("behavioral_receipt_to_outflow_min_gap_seconds", TRANSFORM_LOG1P),
    ("behavioral_receipt_to_outflow_median_gap_seconds", TRANSFORM_LOG1P),
    ("behavioral_post_outflow_residue_base_units", TRANSFORM_SIGNED_LOG1P),
    ("behavioral_ordering_ambiguous_observation_count", TRANSFORM_LOG1P),
    ("behavioral_event_index_missing_count", TRANSFORM_LOG1P),
    ("behavioral_block_number_missing_count", TRANSFORM_LOG1P),
)

ANOMALY_FEATURE_NAMES: tuple[str, ...] = tuple(name for name, _ in ANOMALY_FEATURES)
_TRANSFORMS: dict[str, str] = dict(ANOMALY_FEATURES)

#: Absolute computability floor, NOT a scientific-adequacy threshold. Below
#: this an Isolation Forest is degenerate; at or above it nothing here claims
#: the sample is representative (that is what the readiness report is for).
MIN_TRAIN_ROWS = 2

SAMPLE_SELECTION_ALL_SUPPLIED = "all_supplied_training_rows"

SCORE_INTERPRETATION_NOTE = (
    "Lower score_samples = more isolated within the TRAINING sample. This is a "
    "review-priority ordering, not a probability, not a fraud likelihood, and "
    "not attribution evidence. Operational confounders may rank high on shape "
    "alone."
)


class AnomalyRankingError(RuntimeError):
    """A row, feature, or split violated the ranker's stated contract."""


#: A predeclared analyst rubric: which independently-established categories
#: count as "review-worthy" (a ranker should surface them), which are known
#: operational confounders (a ranker should NOT surface them as fraud-like),
#: and which are independently-established non-review-worthy negatives. The
#: three sets must be disjoint. A row whose category is in none of them, or
#: whose category is unknown/None, is EXCLUDED from the metric and counted --
#: never silently treated as a negative (an unevaluated wallet is not "clean").
@dataclass(frozen=True)
class AnalystRubric:
    rubric_id: str
    description: str
    review_worthy_categories: frozenset[str]
    confounder_categories: frozenset[str]
    expected_negative_categories: frozenset[str]

    def __post_init__(self) -> None:
        sets = [
            self.review_worthy_categories,
            self.confounder_categories,
            self.expected_negative_categories,
        ]
        for i in range(len(sets)):
            for j in range(i + 1, len(sets)):
                overlap = sets[i] & sets[j]
                if overlap:
                    raise AnomalyRankingError(
                        f"rubric {self.rubric_id!r} has overlapping categories: {sorted(overlap)}"
                    )

    @property
    def known_categories(self) -> frozenset[str]:
        return (
            self.review_worthy_categories
            | self.confounder_categories
            | self.expected_negative_categories
        )


#: Synthetic-only category names and the demonstration rubric. These names
#: are deliberately NOT the real confounder vocabulary so a synthetic
#: demonstration can never be misread as a real evaluation.
SYNTHETIC_CATEGORY_REVIEW_WORTHY = "synthetic_review_worthy"
SYNTHETIC_CATEGORY_CONFOUNDER = "synthetic_confounder"
SYNTHETIC_CATEGORY_NEGATIVE = "synthetic_negative"

SYNTHETIC_DEMONSTRATION_RUBRIC = AnalystRubric(
    rubric_id="synthetic-demonstration-v1",
    description=(
        "Demonstration-only rubric for the synthetic pipeline run. Declares a "
        "review-worthy shape, an operational-confounder shape, and a negative "
        "shape purely so precision@k and the confounder check can be exercised "
        "end-to-end. It is not an analyst rubric for real wallets."
    ),
    review_worthy_categories=frozenset({SYNTHETIC_CATEGORY_REVIEW_WORTHY}),
    confounder_categories=frozenset({SYNTHETIC_CATEGORY_CONFOUNDER}),
    expected_negative_categories=frozenset({SYNTHETIC_CATEGORY_NEGATIVE}),
)

EVALUATION_KIND_PIPELINE_DEMONSTRATION = "pipeline_demonstration"
EVALUATION_KIND_HELD_OUT = "held_out_evaluation"

EVALUATION_CAVEAT = (
    "Review-prioritization only. This ranks observations for analyst attention "
    "against a predeclared rubric; it is not an accuracy claim, does not measure "
    "criminal guilt, and does not establish ownership, service identity, or fraud. "
    "A high-ranked confounder is a false positive to inspect, not a finding."
)


@dataclass(frozen=True)
class FeatureMatrix:
    """A numeric view of wallet-window rows, BEFORE imputation.

    ``values[i][j]`` is the transformed value of feature ``feature_names[j]``
    for row ``i``, or None when the feature was missing on that row.
    ``row_keys[i]`` is the row's dedupe key, so a caller can prove which rows
    were used for training.
    """

    feature_names: tuple[str, ...]
    transforms: dict[str, str]
    values: tuple[tuple[float | None, ...], ...]
    row_keys: tuple[tuple[str, str, str, str], ...]

    @property
    def n_rows(self) -> int:
        return len(self.values)


def _assert_allowlist_is_safe(feature_names: tuple[str, ...] = ANOMALY_FEATURE_NAMES) -> None:
    """Fail loudly if the curated allowlist ever grows a disallowed name,
    reusing feature_dataset's own fragment guard rather than a second copy."""
    for name in feature_names:
        lowered = name.lower()
        for fragment in DISALLOWED_FEATURE_NAME_FRAGMENTS:
            if fragment in lowered:
                raise AnomalyRankingError(
                    f"anomaly feature {name!r} contains disallowed fragment {fragment!r}"
                )


def _coerce_numeric(name: str, value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        # A boolean is not one of the curated numeric features; surfacing this
        # rather than scoring True/False as 1/0 keeps the allowlist honest.
        raise AnomalyRankingError(f"feature {name!r} carried a boolean value, expected numeric")
    if isinstance(value, int | float):
        return float(value)
    raise AnomalyRankingError(
        f"feature {name!r} carried a non-numeric value of type {type(value).__name__}"
    )


def _apply_transform(value: float, kind: str) -> float:
    if kind == TRANSFORM_IDENTITY:
        return value
    if kind == TRANSFORM_LOG1P:
        return math.log1p(value) if value > 0 else 0.0
    if kind == TRANSFORM_SIGNED_LOG1P:
        return math.copysign(math.log1p(abs(value)), value) if value else 0.0
    raise AnomalyRankingError(f"unknown transform {kind!r}")


def extract_features(
    rows: list[WalletWindowRow],
    *,
    feature_names: tuple[str, ...] = ANOMALY_FEATURE_NAMES,
    transforms: dict[str, str] | None = None,
) -> FeatureMatrix:
    """Pull the curated numeric features out of already-built rows. Pure: no
    fitting, no imputation, no network, no database."""
    _assert_allowlist_is_safe(feature_names)
    active = transforms if transforms is not None else _TRANSFORMS
    for name in feature_names:
        if name not in active:
            raise AnomalyRankingError(f"feature {name!r} has no declared transform")

    values: list[tuple[float | None, ...]] = []
    for row in rows:
        cells: list[float | None] = []
        for name in feature_names:
            numeric = _coerce_numeric(name, row.features.get(name))
            cells.append(None if numeric is None else _apply_transform(numeric, active[name]))
        values.append(tuple(cells))
    return FeatureMatrix(
        feature_names=feature_names,
        transforms=dict(active),
        values=tuple(values),
        row_keys=tuple(row.dedupe_key for row in rows),
    )


def _median_or_none(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


@dataclass
class TrainedAnomalyModel:
    """A fitted ranker plus everything needed to reproduce or audit it. The
    sklearn estimator is held here but never serialized by this module."""

    model_version: str
    anomaly_feature_version: str
    feature_definition_version: str
    feature_names: tuple[str, ...]
    transforms: dict[str, str]
    imputation_values: dict[str, float]
    imputed_constant_features: tuple[str, ...]
    seed: int
    n_estimators: int
    max_samples: int
    sample_selection: str
    training_cutoff: dt.datetime | None
    training_row_keys: tuple[tuple[str, str, str, str], ...]
    training_wallet_ids: tuple[str, ...]
    estimator: IsolationForest = field(repr=False)

    @property
    def training_row_count(self) -> int:
        return len(self.training_row_keys)

    def metadata(self) -> dict[str, Any]:
        """Reproducibility metadata only -- deliberately no estimator, no
        score, and no metric that would imply validation."""
        return {
            "model_version": self.model_version,
            "anomaly_feature_version": self.anomaly_feature_version,
            "feature_definition_version": self.feature_definition_version,
            "feature_names": list(self.feature_names),
            "transforms": dict(sorted(self.transforms.items())),
            "imputation_values": dict(sorted(self.imputation_values.items())),
            "imputed_constant_features": list(self.imputed_constant_features),
            "seed": self.seed,
            "n_estimators": self.n_estimators,
            "max_samples": self.max_samples,
            "sample_selection": self.sample_selection,
            "training_cutoff": self.training_cutoff.isoformat() if self.training_cutoff else None,
            "training_row_count": self.training_row_count,
            "training_wallet_count": len(self.training_wallet_ids),
            "missing_data_policy": "per-feature TRAIN median; missing is never suspicious",
            "calibrated_probability": False,
            "metrics_reported": False,
        }


def train_anomaly(
    train_rows: list[WalletWindowRow],
    *,
    seed: int,
    training_cutoff: dt.datetime | None = None,
    feature_definition_version: str = FEATURE_DEFINITION_VERSION,
    n_estimators: int = 128,
    sample_selection: str = SAMPLE_SELECTION_ALL_SUPPLIED,
) -> TrainedAnomalyModel:
    """Fit an Isolation Forest on the supplied training rows.

    Deterministic: the same rows, seed, and hyperparameters always produce the
    same model (IsolationForest with a fixed ``random_state`` and ``n_jobs=1``).
    The caller owns sample selection and the train/holdout split -- this
    function fits whatever it is given and records exactly which rows those
    were, so "do not fit and evaluate on the same rows" can be enforced later.
    """
    if len(train_rows) < MIN_TRAIN_ROWS:
        raise AnomalyRankingError(
            f"{len(train_rows)} training row(s); at least {MIN_TRAIN_ROWS} are required to "
            "fit at all (a computability floor, not a claim of sample adequacy)"
        )
    if n_estimators < 1:
        raise AnomalyRankingError("n_estimators must be >= 1")

    if training_cutoff is not None:
        offenders = [row for row in train_rows if row.window_start >= training_cutoff]
        if offenders:
            raise AnomalyRankingError(
                f"{len(offenders)} training row(s) start at or after the declared "
                f"training_cutoff {training_cutoff.isoformat()}"
            )

    matrix = extract_features(train_rows)

    imputation: dict[str, float] = {}
    constant: list[str] = []
    for j, name in enumerate(matrix.feature_names):
        present = [row[j] for row in matrix.values if row[j] is not None]
        median = _median_or_none([v for v in present if v is not None])
        if median is None:
            imputation[name] = 0.0
            constant.append(name)
        else:
            imputation[name] = float(median)

    x = np.asarray(
        [
            [
                (imputation[name] if row[j] is None else row[j])
                for j, name in enumerate(matrix.feature_names)
            ]
            for row in matrix.values
        ],
        dtype=float,
    )

    estimator = IsolationForest(
        n_estimators=n_estimators,
        max_samples=min(len(train_rows), 256),
        random_state=seed,
        n_jobs=1,
    )
    estimator.fit(x)

    return TrainedAnomalyModel(
        model_version=MODEL_VERSION,
        anomaly_feature_version=ANOMALY_FEATURE_VERSION,
        feature_definition_version=feature_definition_version,
        feature_names=matrix.feature_names,
        transforms=matrix.transforms,
        imputation_values=imputation,
        imputed_constant_features=tuple(sorted(constant)),
        seed=seed,
        n_estimators=n_estimators,
        max_samples=min(len(train_rows), 256),
        sample_selection=sample_selection,
        training_cutoff=training_cutoff,
        training_row_keys=matrix.row_keys,
        training_wallet_ids=tuple(sorted({key[0] for key in matrix.row_keys})),
        estimator=estimator,
    )


@dataclass(frozen=True)
class AnomalyScore:
    """One scored observation. ``rank`` 1 is the most isolated. The raw
    observed feature values travel with the score so an analyst sees WHAT was
    observed; this is not a claimed explanation of the model."""

    wallet_id: str
    window_start: dt.datetime
    window_end: dt.datetime
    data_mode: str
    score: float
    rank: int
    is_outlier: bool
    observed_feature_values: dict[str, Any]
    imputed_features: tuple[str, ...]
    model_version: str
    feature_definition_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "wallet_id": self.wallet_id,
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "data_mode": self.data_mode,
            "score": self.score,
            "rank": self.rank,
            "is_outlier": self.is_outlier,
            "imputed_features": list(self.imputed_features),
            "observed_feature_values": dict(sorted(self.observed_feature_values.items())),
            "model_version": self.model_version,
            "feature_definition_version": self.feature_definition_version,
            "interpretation": SCORE_INTERPRETATION_NOTE,
        }


def assert_no_training_overlap(
    model: TrainedAnomalyModel, rows: list[WalletWindowRow]
) -> None:
    """Raise if any supplied row is one of the rows the model was fit on --
    the "never fit and evaluate on the same rows" guard, enforced on row
    identity (wallet + window + feature version), not on score."""
    train_keys = set(model.training_row_keys)
    overlap = [row for row in rows if row.dedupe_key in train_keys]
    if overlap:
        raise AnomalyRankingError(
            f"{len(overlap)} row(s) were used to train this model and cannot be "
            "evaluated against it"
        )


def _imputed_matrix(
    model: TrainedAnomalyModel, rows: list[WalletWindowRow]
) -> tuple[np.ndarray, list[tuple[tuple[str, str, str, str], tuple[str, ...]]]]:
    matrix = extract_features(rows, feature_names=model.feature_names, transforms=model.transforms)
    imputed_per_row: list[tuple[tuple[str, str, str, str], tuple[str, ...]]] = []
    x: list[list[float]] = []
    for key, cells in zip(matrix.row_keys, matrix.values, strict=True):
        row_values: list[float] = []
        imputed: list[str] = []
        for j, name in enumerate(matrix.feature_names):
            if cells[j] is None:
                row_values.append(model.imputation_values[name])
                imputed.append(name)
            else:
                row_values.append(float(cells[j]))  # type: ignore[arg-type]
        x.append(row_values)
        imputed_per_row.append((key, tuple(imputed)))
    return np.asarray(x, dtype=float), imputed_per_row


def score_anomaly(
    model: TrainedAnomalyModel,
    rows: list[WalletWindowRow],
    *,
    allow_training_rows: bool = True,
) -> list[AnomalyScore]:
    """Score rows and return them ordered most-isolated first (rank 1).

    By default training rows may be scored (useful for a training-set
    overview); pass ``allow_training_rows=False`` to forbid it. Evaluation
    always calls ``assert_no_training_overlap`` explicitly.
    """
    if not allow_training_rows:
        assert_no_training_overlap(model, rows)

    if not rows:
        return []

    x, imputed_per_row = _imputed_matrix(model, rows)
    raw_scores = model.estimator.score_samples(x).tolist()
    flags = (model.estimator.predict(x) == -1).tolist()

    scored: list[tuple[float, int, WalletWindowRow, tuple[str, ...]]] = []
    for index, row in enumerate(rows):
        _key, imputed = imputed_per_row[index]
        scored.append((float(raw_scores[index]), index, row, imputed))
    scored.sort(key=lambda item: (item[0], item[1]))

    results: list[AnomalyScore] = []
    for rank, (score, index, row, imputed) in enumerate(scored, start=1):
        observed = {name: row.features.get(name) for name in model.feature_names}
        results.append(
            AnomalyScore(
                wallet_id=row.wallet_id,
                window_start=row.window_start,
                window_end=row.window_end,
                data_mode=row.data_mode,
                score=score,
                rank=rank,
                is_outlier=bool(flags[index]),
                observed_feature_values=observed,
                imputed_features=imputed,
                model_version=model.model_version,
                feature_definition_version=model.feature_definition_version,
            )
        )
    return results


@dataclass(frozen=True)
class RankingMetrics:
    """Review-prioritization metrics for one held-out split. Review-worthy
    precision@k is computed over LABELED rows in the top k only; unlabeled
    rows are excluded, never counted as negatives. Every ratio is None when
    its denominator is empty -- never a fabricated 0.0."""

    at_k: int
    review_worthy_in_top_k: int
    labeled_in_top_k: int
    confounders_in_top_k: int
    review_worthy_precision_at_k: float | None
    random_ranking_baseline_precision_at_k: float | None
    confounder_fraction_at_k: float | None
    confounder_base_rate: float | None
    precision_improvement_over_random: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "at_k": self.at_k,
            "review_worthy_in_top_k": self.review_worthy_in_top_k,
            "labeled_in_top_k": self.labeled_in_top_k,
            "confounders_in_top_k": self.confounders_in_top_k,
            "review_worthy_precision_at_k": self.review_worthy_precision_at_k,
            "random_ranking_baseline_precision_at_k": (
                self.random_ranking_baseline_precision_at_k
            ),
            "confounder_fraction_at_k": self.confounder_fraction_at_k,
            "confounder_base_rate": self.confounder_base_rate,
            "precision_improvement_over_random": self.precision_improvement_over_random,
        }


@dataclass(frozen=True)
class AnomalyEvaluation:
    """One held-out evaluation of a trained ranker against a predeclared
    rubric. Reported separately from attribution evidence; this measures
    review-prioritization only, never criminal guilt."""

    evaluation_kind: str
    #: Which experiment this evaluation represents -- one of ExperimentKind.
    #: Kept separate from evaluation_kind (the SYNTHETIC-vs-real label) so a
    #: future_window experiment can never be read as an independent-wallet
    #: holdout.
    experiment_kind: str
    rubric_id: str
    rubric_description: str
    k: int
    split_description: str
    eval_row_count: int
    labeled_row_count: int
    unlabeled_excluded: int
    outside_rubric_excluded: int
    review_worthy_total: int
    confounder_total: int
    expected_negative_total: int
    data_modes: tuple[str, ...]
    metrics: RankingMetrics
    confounder_ranks: tuple[tuple[str, int], ...]
    review_worthy_ranks: tuple[tuple[str, int], ...]
    top_k: tuple[dict[str, Any], ...]
    model_metadata: dict[str, Any]
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_kind": self.evaluation_kind,
            "experiment_kind": self.experiment_kind,
            "rubric_id": self.rubric_id,
            "rubric_description": self.rubric_description,
            "k": self.k,
            "split_description": self.split_description,
            "eval_row_count": self.eval_row_count,
            "labeled_row_count": self.labeled_row_count,
            "unlabeled_excluded": self.unlabeled_excluded,
            "outside_rubric_excluded": self.outside_rubric_excluded,
            "review_worthy_total": self.review_worthy_total,
            "confounder_total": self.confounder_total,
            "expected_negative_total": self.expected_negative_total,
            "data_modes": list(self.data_modes),
            "metrics": self.metrics.to_dict(),
            "confounder_ranks": [
                {"wallet_id": w, "rank": r} for w, r in self.confounder_ranks
            ],
            "review_worthy_ranks": [
                {"wallet_id": w, "rank": r} for w, r in self.review_worthy_ranks
            ],
            "top_k": list(self.top_k),
            "model": self.model_metadata,
            "notes": list(self.notes),
            "measures_criminal_guilt": False,
            "is_probability": False,
        }

    def to_json(self) -> str:
        """Deterministic: sorted keys, fixed separators, no timestamp."""
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


def _split(
    numerator: int, denominator: int
) -> float | None:
    return (numerator / denominator) if denominator else None


def _resolve_experiment_kind(
    declared: ExperimentKind | str | None,
    model: TrainedAnomalyModel,
    eval_rows: list[WalletWindowRow],
) -> ExperimentKind:
    """Pick the experiment kind a report will declare.

    When the caller declares one, it is used (and validated). Otherwise it is
    inferred conservatively: an all-SYNTHETIC split is a demonstration; a real
    split whose wallets are disjoint from training is a wallet_held_out; a
    real split that shares a wallet with training is ambiguous and is REFUSED
    rather than silently labelled -- such a split must be an explicitly
    declared future_window (or group_held_out) experiment.
    """
    if declared is not None:
        return ExperimentKind(declared)

    modes = {row.data_mode for row in eval_rows}
    if modes and modes == {"SYNTHETIC"}:
        return ExperimentKind.synthetic_pipeline_demonstration

    train_wallets = {key[0] for key in model.training_row_keys}
    eval_wallets = {row.wallet_id for row in eval_rows}
    if train_wallets.isdisjoint(eval_wallets):
        return ExperimentKind.wallet_held_out

    raise AnomalyRankingError(
        "evaluation split shares wallet id(s) with training and no experiment kind "
        "was declared; declare ExperimentKind.future_window (strictly later windows) "
        "or group_held_out explicitly. A shared-wallet split is never labelled an "
        "independent-wallet holdout"
    )


def evaluate_anomaly(
    model: TrainedAnomalyModel,
    eval_rows: list[WalletWindowRow],
    *,
    rubric: AnalystRubric,
    k: int,
    split_description: str = "",
    experiment_kind: ExperimentKind | str | None = None,
    group_of: dict[str, str] | None = None,
) -> AnomalyEvaluation:
    """Score a held-out split and compare the ranking against a predeclared
    rubric and a random-ranking baseline.

    Enforces "do not fit and evaluate on the same rows" via
    ``assert_no_training_overlap`` before scoring, and additionally validates
    the split against the declared (or safely inferred) ``experiment_kind``:
    wallet_held_out refuses wallet overlap, group_held_out refuses group
    overlap, future_window refuses backward temporal leakage, and SYNTHETIC
    rows never enter a real metric. Rows whose control_category is unknown
    (None) or outside the rubric are EXCLUDED from every ratio and counted
    explicitly, so an unevaluated wallet can never inflate or deflate the
    metric by being assumed clean.
    """
    if k < 1:
        raise AnomalyRankingError("k must be >= 1")
    assert_no_training_overlap(model, eval_rows)
    resolved_kind = _resolve_experiment_kind(experiment_kind, model, eval_rows)
    assert_model_eval_split_valid(
        resolved_kind, model.training_row_keys, eval_rows, group_of=group_of
    )

    scores = score_anomaly(model, eval_rows, allow_training_rows=False)
    category_of = {row.wallet_id: row.control_category for row in eval_rows}
    known = rubric.known_categories

    def category(score: AnomalyScore) -> str | None:
        return category_of.get(score.wallet_id)

    labeled = [s for s in scores if category(s) in known]
    unlabeled_excluded = sum(1 for s in scores if category(s) is None)
    outside_rubric_excluded = sum(
        1 for s in scores if category(s) is not None and category(s) not in known
    )

    review_worthy_total = sum(
        1 for s in labeled if category(s) in rubric.review_worthy_categories
    )
    confounder_total = sum(
        1 for s in labeled if category(s) in rubric.confounder_categories
    )
    expected_negative_total = sum(
        1 for s in labeled if category(s) in rubric.expected_negative_categories
    )

    top_k = scores[:k]
    labeled_top = [s for s in top_k if category(s) in known]
    review_worthy_in_top_k = sum(
        1 for s in labeled_top if category(s) in rubric.review_worthy_categories
    )
    confounders_in_top_k = sum(
        1 for s in labeled_top if category(s) in rubric.confounder_categories
    )

    # A class absent from the whole evaluation split cannot be "surfaced", so
    # its precision@k is null (not computable), never a fabricated 0.0.
    precision = (
        _split(review_worthy_in_top_k, len(labeled_top))
        if review_worthy_total
        else None
    )
    baseline = _split(review_worthy_total, len(labeled)) if review_worthy_total else None
    confounder_fraction = _split(confounders_in_top_k, len(labeled_top))
    confounder_base_rate = _split(confounder_total, len(labeled))
    improvement = (precision - baseline) if precision is not None and baseline is not None else None

    metrics = RankingMetrics(
        at_k=k,
        review_worthy_in_top_k=review_worthy_in_top_k,
        labeled_in_top_k=len(labeled_top),
        confounders_in_top_k=confounders_in_top_k,
        review_worthy_precision_at_k=precision,
        random_ranking_baseline_precision_at_k=baseline,
        confounder_fraction_at_k=confounder_fraction,
        confounder_base_rate=confounder_base_rate,
        precision_improvement_over_random=improvement,
    )

    confounder_ranks = tuple(
        sorted(
            (
                (s.wallet_id, s.rank)
                for s in labeled
                if category(s) in rubric.confounder_categories
            ),
            key=lambda pair: pair[1],
        )
    )
    review_worthy_ranks = tuple(
        sorted(
            (
                (s.wallet_id, s.rank)
                for s in labeled
                if category(s) in rubric.review_worthy_categories
            ),
            key=lambda pair: pair[1],
        )
    )

    modes = tuple(sorted({row.data_mode for row in eval_rows}))
    evaluation_kind = (
        EVALUATION_KIND_PIPELINE_DEMONSTRATION
        if modes and modes == ("SYNTHETIC",)
        else EVALUATION_KIND_HELD_OUT
    )

    notes: list[str] = [EVALUATION_CAVEAT]
    if resolved_kind is ExperimentKind.future_window:
        notes.append(
            "Experiment: future_window -- evaluation uses strictly later windows of "
            "wallets already present in training. This is NOT an independent-wallet "
            "holdout and must never be reported as one."
        )
    elif resolved_kind is ExperimentKind.group_held_out:
        notes.append(
            "Experiment: group_held_out -- whole externally supplied related-wallet "
            "groups are held out together; grouping was operator-supplied, never "
            "inferred from behavior."
        )
    elif resolved_kind is ExperimentKind.wallet_held_out:
        notes.append(
            "Experiment: wallet_held_out -- training and evaluation contain disjoint "
            "wallet ids."
        )
    if evaluation_kind == EVALUATION_KIND_PIPELINE_DEMONSTRATION:
        notes.append(
            "SYNTHETIC-only evaluation: this is a PIPELINE DEMONSTRATION that the "
            "metric computes, not validation of the ranker on real wallets."
        )
    if not eval_rows:
        notes.append("No evaluation rows were supplied; every metric is null by construction.")
    if labeled and review_worthy_total == 0:
        notes.append(
            "No review-worthy labeled rows in the evaluation split, so "
            "review_worthy_precision_at_k is null (not computable) rather than a "
            "fabricated 0.0. A ranker cannot be shown to surface a class that is "
            "absent from the split."
        )
    if unlabeled_excluded or outside_rubric_excluded:
        notes.append(
            f"{unlabeled_excluded} row(s) had no independent evaluation label and "
            f"{outside_rubric_excluded} row(s) carried a category outside the rubric; "
            "both were excluded from every ratio, never counted as negatives."
        )
    if confounder_total:
        notes.append(
            f"{confounder_total} known operational confounder(s) are in the split; their "
            "ranks are recorded so a high rank on a legitimate pattern is visible."
        )

    return AnomalyEvaluation(
        evaluation_kind=evaluation_kind,
        experiment_kind=resolved_kind.value,
        rubric_id=rubric.rubric_id,
        rubric_description=rubric.description,
        k=k,
        split_description=split_description,
        eval_row_count=len(eval_rows),
        labeled_row_count=len(labeled),
        unlabeled_excluded=unlabeled_excluded,
        outside_rubric_excluded=outside_rubric_excluded,
        review_worthy_total=review_worthy_total,
        confounder_total=confounder_total,
        expected_negative_total=expected_negative_total,
        data_modes=modes,
        metrics=metrics,
        confounder_ranks=confounder_ranks,
        review_worthy_ranks=review_worthy_ranks,
        top_k=tuple(s.to_dict() for s in top_k),
        model_metadata=model.metadata(),
        notes=tuple(notes),
    )


# ---------------------------------------------------------------------------
# SYNTHETIC pipeline demonstration only
# ---------------------------------------------------------------------------
#
# There are no accepted-and-materialized REAL evaluation windows yet (see
# docs/PROGRESS.md Stage 3C and docs/DECISIONS.md 2026-09-21). Until there are,
# the only honest end-to-end run is against synthetic rows, clearly labelled
# SYNTHETIC, and reported as a PIPELINE DEMONSTRATION -- never as validation.


def synthetic_demonstration_rows() -> list[WalletWindowRow]:
    """A tiny, deterministic SYNTHETIC wallet-window set used ONLY to show the
    fit/score pipeline runs end-to-end. Shape-only patterns: ordinary wallets,
    two documented-style operational confounders (marketplace-like fan-out, a
    treasury-like high-volume wallet), and a few burst-and-forward shapes. No
    address, category, or score here is a claim about any real wallet."""
    window_start = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    window_end = dt.datetime(2026, 1, 31, tzinfo=dt.UTC)

    def row(
        index: int,
        *,
        incoming_count: int,
        outgoing_count: int,
        in_counterparties: int,
        out_counterparties: int,
        in_amount: int,
        out_amount: int,
        max_count_concentration: float | None,
        max_amount_concentration: float | None,
        repeats: int,
        repeated_forwarding: int,
        observation_count: int,
        min_gap: float | None,
        median_gap: float | None,
        residue: int | None,
        category: str,
    ) -> WalletWindowRow:
        features: dict[str, Any] = {
            "behavioral_observed_incoming_transfer_count": incoming_count,
            "behavioral_observed_outgoing_transfer_count": outgoing_count,
            "behavioral_distinct_incoming_counterparty_count": in_counterparties,
            "behavioral_distinct_outgoing_counterparty_count": out_counterparties,
            "behavioral_observed_incoming_amount_base_units": in_amount,
            "behavioral_observed_outgoing_amount_base_units": out_amount,
            "behavioral_outgoing_concentration_toward_accepted_anchor": None,
            "behavioral_outgoing_concentration_max_by_count": max_count_concentration,
            "behavioral_outgoing_concentration_max_by_amount": max_amount_concentration,
            "behavioral_outgoing_counterparties_with_repeat_count": repeats,
            "behavioral_repeated_forwarding_count": repeated_forwarding,
            "behavioral_receipt_to_outflow_observation_count": observation_count,
            "behavioral_receipt_to_outflow_ambiguous_count": max(
                0, outgoing_count - observation_count
            ),
            "behavioral_receipt_to_outflow_min_gap_seconds": min_gap,
            "behavioral_receipt_to_outflow_median_gap_seconds": median_gap,
            "behavioral_post_outflow_residue_base_units": residue,
            "behavioral_ordering_ambiguous_observation_count": 0,
            "behavioral_event_index_missing_count": 0,
            "behavioral_block_number_missing_count": 0,
        }
        return WalletWindowRow(
            wallet_id=f"synth-{index:03d}",
            network="tron",
            window_start=window_start,
            window_end=window_end,
            features=features,
            missingness={name: value is None for name, value in features.items()},
            acquisition_completeness="complete_within_scope",
            verification_quality="history_only",
            source_run_ids=(f"SYNTHETIC-demo-{index:03d}",),
            control_category=category,
            data_mode="SYNTHETIC",
        )

    rows: list[WalletWindowRow] = []
    for i in range(20):
        rows.append(
            row(
                i,
                incoming_count=3 + (i % 4),
                outgoing_count=2 + (i % 3),
                in_counterparties=2 + (i % 3),
                out_counterparties=2 + (i % 2),
                in_amount=1_000_000 + i * 50_000,
                out_amount=900_000 + i * 40_000,
                max_count_concentration=0.4 + (i % 3) * 0.05,
                max_amount_concentration=0.45 + (i % 3) * 0.05,
                repeats=0,
                repeated_forwarding=1 if i % 4 else 2,
                observation_count=2 + (i % 3),
                min_gap=3_600.0 + i * 120,
                median_gap=7_200.0 + i * 180,
                residue=100_000 + i * 10_000,
                category=SYNTHETIC_CATEGORY_NEGATIVE,
            )
        )
    # marketplace-like confounder: high fan-out, many counterparties
    for i in range(20, 24):
        rows.append(
            row(
                i,
                incoming_count=400 + i,
                outgoing_count=380 + i,
                in_counterparties=350 + i,
                out_counterparties=340 + i,
                in_amount=5_000_000_000 + i * 1_000_000,
                out_amount=4_900_000_000 + i * 1_000_000,
                max_count_concentration=0.02,
                max_amount_concentration=0.03,
                repeats=200,
                repeated_forwarding=6,
                observation_count=380 + i,
                min_gap=30.0,
                median_gap=120.0,
                residue=100_000_000,
                category=SYNTHETIC_CATEGORY_CONFOUNDER,
            )
        )
    # treasury-like confounder: high volume, low counterparty count
    for i in range(24, 28):
        rows.append(
            row(
                i,
                incoming_count=25,
                outgoing_count=20,
                in_counterparties=4,
                out_counterparties=3,
                in_amount=90_000_000_000_000 + i * 1_000_000_000,
                out_amount=88_000_000_000_000 + i * 1_000_000_000,
                max_count_concentration=0.5,
                max_amount_concentration=0.55,
                repeats=5,
                repeated_forwarding=8,
                observation_count=20,
                min_gap=86_400.0,
                median_gap=172_800.0,
                residue=2_000_000_000_000,
                category=SYNTHETIC_CATEGORY_CONFOUNDER,
            )
        )
    # burst-and-forward: rapid receipt then near-total forwarding
    for i in range(28, 40):
        rows.append(
            row(
                i,
                incoming_count=1,
                outgoing_count=1,
                in_counterparties=1,
                out_counterparties=1,
                in_amount=500_000_000,
                out_amount=499_000_000,
                max_count_concentration=1.0,
                max_amount_concentration=0.998,
                repeats=0,
                repeated_forwarding=1,
                observation_count=1,
                min_gap=45.0,
                median_gap=45.0,
                residue=1_000_000,
                category=SYNTHETIC_CATEGORY_REVIEW_WORTHY,
            )
        )
    return rows
