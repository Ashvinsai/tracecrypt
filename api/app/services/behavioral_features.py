"""Deterministic behavioral/sweep features over SAVED, normalized behavioral
evidence only. No network access.

Every Feature carries its own source evidence ids, observation window, and
completeness status -- a truncated collection's zero or "no pairing found"
is never the same fact as a complete collection's, and this module never
lets the two collapse into one number (see TRUNCATED_ZERO_NOTE et al. and
test_behavioral_features.py).

Sweep/forwarding semantics (E): repeated forwarding and outgoing
concentration are behavioral observations only. Nothing in this module
computes or implies OKX ownership, customer-deposit status, service
ownership, fraud, common control, or a strong inference of any kind --
see NO_STRONG_INFERENCE_NOTE, attached to every feature that could
otherwise be misread that way.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter

from app.services.collect_behavioral_evidence import (
    DIRECTION_INCOMING,
    DIRECTION_OUTGOING,
    PreferredBehavioralRun,
)
from app.services.features import Feature

NO_STRONG_INFERENCE_NOTE = (
    "Behavioral evidence only. A high count or concentration here does not by "
    "itself imply OKX ownership, customer-deposit status, service ownership, "
    "fraud, common control, or a strong inference of any kind."
)

RESIDUE_CAVEAT = (
    "This is an arithmetic difference between observed incoming and outgoing "
    "amounts within the collection window only. It is not a wallet balance, "
    "not proof of token lineage, and not case-associated or victim-associated "
    "value; pre-existing balance before the window and any activity outside "
    "the window are both unknown."
)


#: verification_quality values (A). "receipt_verified" requires an actual
#: receipt/execution check (this collector's own --verify-execution, or a
#: separately verified fact cross-referenced in by tx_hash); a history-only
#: acquisition never earns it just by being acquisition-complete.
VERIFICATION_RECEIPT_VERIFIED = "receipt_verified"
VERIFICATION_HISTORY_ONLY = "history_only"
VERIFICATION_MIXED = "mixed"
VERIFICATION_UNKNOWN = "unknown"

EVENT_IDENTITY_RECEIPT_INDEX = "receipt_event_index"
EVENT_IDENTITY_OBSERVATION_ONLY = "observation_reference_only"
EVENT_IDENTITY_MIXED = "mixed"

ORDERING_PRECISE = "precise"
ORDERING_TIMESTAMP_ONLY = "timestamp_only"
ORDERING_AMBIGUOUS = "ambiguous"

ACQUISITION_VS_VERIFICATION_NOTE = (
    "Acquisition completeness and verification quality are independent facts: "
    "a collection can be acquisition-complete within its declared window while "
    "every row in it remains execution- and event-order-unverified. Neither "
    "status may be read as implying the other."
)


def _verification_and_identity_quality(rows: list[dict[str, str]]) -> tuple[str, str, str]:
    """Row-derived quality axes, independent of acquisition completeness (A).

    Returns (verification_quality, event_identity_quality, ordering_quality).
    """
    if not rows:
        return VERIFICATION_UNKNOWN, EVENT_IDENTITY_OBSERVATION_ONLY, ORDERING_AMBIGUOUS

    execution_values = {r.get("execution_status") for r in rows}
    if execution_values == {"success"}:
        verification_quality = VERIFICATION_RECEIPT_VERIFIED
    elif execution_values == {"unknown"}:
        verification_quality = VERIFICATION_HISTORY_ONLY
    else:
        verification_quality = VERIFICATION_MIXED

    has_index = [bool((r.get("event_index") or "").strip()) for r in rows]
    if all(has_index):
        event_identity_quality = EVENT_IDENTITY_RECEIPT_INDEX
    elif not any(has_index):
        event_identity_quality = EVENT_IDENTITY_OBSERVATION_ONLY
    else:
        event_identity_quality = EVENT_IDENTITY_MIXED

    ambiguous_values = {r.get("ordering_ambiguous") for r in rows}
    if ambiguous_values == {"false"}:
        ordering_quality = ORDERING_PRECISE
    elif ambiguous_values == {"true"}:
        ordering_quality = ORDERING_AMBIGUOUS
    else:
        ordering_quality = ORDERING_TIMESTAMP_ONLY

    return verification_quality, event_identity_quality, ordering_quality


def compute_behavioral_features_from_run(
    run: PreferredBehavioralRun,
    *,
    anchor_address: str | None,
    receipt_verified_tx_hashes: frozenset[str] = frozenset(),
) -> list[Feature]:
    """The preferred entry point: computes features from one specific,
    named collect_behavioral_evidence run bundle rather than from whichever
    rows happen to be sitting in data/behavioral_evidence.csv. Acquisition
    completeness comes from the run's own manifest; verification quality,
    event identity quality, and ordering quality are separate axes computed
    from the rows themselves and never conflated with acquisition
    completeness (A). ``receipt_verified_tx_hashes`` names transactions with
    separately verified execution evidence (e.g. a Stage 1 seed transfer);
    it marks exactly those rows without upgrading -- or being averaged
    into -- the run's own aggregate verification_quality."""
    features = compute_behavioral_features(
        list(run.rows),
        run.candidate_address,
        anchor_address=anchor_address,
        incoming_truncated=not run.incoming_complete,
        outgoing_truncated=not run.outgoing_complete,
    )
    features.extend(_provenance_features(run))
    features.extend(_quality_axis_features(run, receipt_verified_tx_hashes))
    return features


def _quality_axis_features(
    run: PreferredBehavioralRun, receipt_verified_tx_hashes: frozenset[str]
) -> list[Feature]:
    window = (run.behavioral_window_start, run.behavioral_window_end)
    rows = list(run.rows)
    verification_quality, event_identity_quality, ordering_quality = (
        _verification_and_identity_quality(rows)
    )
    all_ids = tuple(sorted(r.get("event_reference", "") for r in rows))

    features = [
        Feature(
            "acquisition_completeness",
            run.acquisition_completeness,
            all_ids,
            *window,
            "complete",
            ACQUISITION_VS_VERIFICATION_NOTE,
        ),
        Feature(
            "verification_quality",
            verification_quality,
            all_ids,
            *window,
            "complete",
            "Derived from this collection's own execution_status values only; a separately "
            "verified transaction (see receipt_verified_observation_count) does not change "
            "this aggregate. " + ACQUISITION_VS_VERIFICATION_NOTE,
        ),
        Feature(
            "event_identity_quality",
            event_identity_quality,
            all_ids,
            *window,
            "complete",
            "receipt_event_index requires a resolved event_index for every row; "
            "observation_reference_only means every row's identity is a content-derived "
            "reference instead (see event_index_missing_count).",
        ),
        Feature(
            "ordering_quality",
            ordering_quality,
            all_ids,
            *window,
            "complete",
            "ambiguous means intra-transaction position could not be established for at "
            "least one row and none could be established for any; it is preserved as "
            "ambiguous rather than invented (see ordering_ambiguous_observation_count).",
        ),
    ]

    verified_rows = [r for r in rows if r.get("tx_hash") in receipt_verified_tx_hashes]
    if receipt_verified_tx_hashes:
        note = (
            "These transaction(s) have separate, independently verified execution evidence "
            "(e.g. a Stage 1 seed transfer's own saved receipt). That verification is scoped "
            "to exactly these rows and is not generalized to any other observation in this "
            "run, and it does not change this run's own aggregate verification_quality above."
        )
    else:
        note = (
            "No transaction in this run has been cross-referenced against separate "
            "receipt evidence."
        )
    features.append(
        Feature(
            "receipt_verified_observation_count",
            len(verified_rows),
            tuple(sorted(r.get("event_reference", "") for r in verified_rows)),
            *window,
            "complete",
            note,
        )
    )
    return features


def _provenance_features(run: PreferredBehavioralRun) -> list[Feature]:
    window = (run.behavioral_window_start, run.behavioral_window_end)
    return [
        Feature(
            "preferred_behavioral_run_id",
            run.run_id,
            (),
            *window,
            "complete",
            "Identifies exactly which collect_behavioral_evidence run bundle these "
            "features were computed from.",
        ),
        Feature("behavioral_acquisition_mode", run.acquisition_mode, (), *window, "complete", None),
        Feature(
            "behavioral_window_start", run.behavioral_window_start, (), *window, "complete", None
        ),
        Feature("behavioral_window_end", run.behavioral_window_end, (), *window, "complete", None),
        Feature("incoming_complete", run.incoming_complete, (), *window, "complete", None),
        Feature("outgoing_complete", run.outgoing_complete, (), *window, "complete", None),
        Feature(
            "request_budget_truncated", run.request_budget_truncated, (), *window, "complete", None
        ),
        Feature("page_limit_truncated", run.page_limit_truncated, (), *window, "complete", None),
        Feature("event_limit_truncated", run.event_limit_truncated, (), *window, "complete", None),
    ]


def _parse_dt(value: str | None) -> dt.datetime | None:
    return dt.datetime.fromisoformat(value) if value else None


def _bounds(rows: list[dict[str, str]]) -> tuple[dt.datetime | None, dt.datetime | None]:
    times = [_parse_dt(r.get("block_time")) for r in rows]
    present = [t for t in times if t is not None]
    return (min(present), max(present)) if present else (None, None)


def compute_behavioral_features(
    rows: list[dict[str, str]],
    candidate_address: str,
    *,
    anchor_address: str | None,
    incoming_truncated: bool,
    outgoing_truncated: bool,
) -> list[Feature]:
    """Compute the deterministic behavioral feature set for one candidate
    from rows already persisted for it. Calling this twice on the same rows
    and flags always returns equal output."""
    candidate_rows = [r for r in rows if r.get("candidate_address") == candidate_address]
    incoming_rows = [r for r in candidate_rows if r.get("direction") == DIRECTION_INCOMING]
    outgoing_rows = [r for r in candidate_rows if r.get("direction") == DIRECTION_OUTGOING]

    incoming_completeness = "truncated" if incoming_truncated else "complete"
    outgoing_completeness = "truncated" if outgoing_truncated else "complete"
    incoming_note = (
        "More incoming transfers may exist beyond the collected page/event limits."
        if incoming_truncated
        else None
    )
    outgoing_note = (
        "More outgoing transfers may exist beyond the collected page/event limits."
        if outgoing_truncated
        else None
    )

    incoming_ids = tuple(sorted(r.get("event_reference", "") for r in incoming_rows))
    outgoing_ids = tuple(sorted(r.get("event_reference", "") for r in outgoing_rows))
    in_start, in_end = _bounds(incoming_rows)
    out_start, out_end = _bounds(outgoing_rows)

    incoming_amount = sum(
        int(r["amount_base_units"]) for r in incoming_rows if r.get("amount_base_units")
    )
    outgoing_amount = sum(
        int(r["amount_base_units"]) for r in outgoing_rows if r.get("amount_base_units")
    )

    features: list[Feature] = [
        Feature(
            "observed_incoming_transfer_count",
            len(incoming_rows),
            incoming_ids,
            in_start,
            in_end,
            incoming_completeness,
            incoming_note,
        ),
        Feature(
            "observed_outgoing_transfer_count",
            len(outgoing_rows),
            outgoing_ids,
            out_start,
            out_end,
            outgoing_completeness,
            outgoing_note,
        ),
        Feature(
            "distinct_incoming_counterparty_count",
            len({r.get("counterparty_address", "") for r in incoming_rows}),
            incoming_ids,
            in_start,
            in_end,
            incoming_completeness,
            incoming_note,
        ),
        Feature(
            "distinct_outgoing_counterparty_count",
            len({r.get("counterparty_address", "") for r in outgoing_rows}),
            outgoing_ids,
            out_start,
            out_end,
            outgoing_completeness,
            outgoing_note,
        ),
        Feature(
            "observed_incoming_amount_base_units",
            incoming_amount,
            incoming_ids,
            in_start,
            in_end,
            incoming_completeness,
            incoming_note,
        ),
        Feature(
            "observed_outgoing_amount_base_units",
            outgoing_amount,
            outgoing_ids,
            out_start,
            out_end,
            outgoing_completeness,
            outgoing_note,
        ),
    ]

    features.append(
        _concentration_feature(
            outgoing_rows, anchor_address, outgoing_truncated, out_start, out_end, outgoing_amount
        )
    )
    features.extend(
        _concentration_max_features(
            outgoing_rows, outgoing_truncated, out_start, out_end, outgoing_amount
        )
    )
    features.append(
        _repeated_forwarding_feature(
            outgoing_rows, outgoing_truncated, out_start, out_end, outgoing_note
        )
    )
    features.append(
        _repeated_counterparties_feature(outgoing_rows, outgoing_truncated, out_start, out_end)
    )
    features.extend(
        _timing_features(incoming_rows, outgoing_rows, incoming_truncated, outgoing_truncated)
    )
    features.append(
        _residue_feature(
            incoming_rows,
            outgoing_rows,
            incoming_amount,
            outgoing_amount,
            incoming_truncated,
            outgoing_truncated,
            incoming_ids,
            outgoing_ids,
            in_start,
            out_end,
        )
    )
    features.extend(_uncertainty_features(incoming_rows, outgoing_rows, in_start, out_end))
    return features


def _concentration_feature(
    outgoing_rows: list[dict[str, str]],
    anchor_address: str | None,
    outgoing_truncated: bool,
    out_start: dt.datetime | None,
    out_end: dt.datetime | None,
    outgoing_amount: int,
) -> Feature:
    if anchor_address is None:
        return Feature(
            "outgoing_concentration_toward_accepted_anchor",
            None,
            (),
            None,
            None,
            "unknown",
            "No accepted anchor address was supplied.",
        )
    if not outgoing_rows:
        return Feature(
            "outgoing_concentration_toward_accepted_anchor",
            None,
            (),
            None,
            None,
            "unknown" if not outgoing_truncated else "truncated",
            "No outgoing transfers are on record; concentration is unknown, not zero."
            if outgoing_truncated
            else "No outgoing transfers were observed within the collected window.",
        )
    anchor_rows = [r for r in outgoing_rows if r.get("counterparty_address") == anchor_address]
    anchor_amount = sum(
        int(r["amount_base_units"]) for r in anchor_rows if r.get("amount_base_units")
    )
    ratio = (anchor_amount / outgoing_amount) if outgoing_amount else None
    note = (
        "Computed only over the outgoing transfers actually observed. " + NO_STRONG_INFERENCE_NOTE
    )
    if outgoing_truncated:
        note += " Coverage is truncated; more outgoing history may exist beyond page/event limits."
    return Feature(
        "outgoing_concentration_toward_accepted_anchor",
        ratio,
        tuple(sorted(r.get("event_reference", "") for r in anchor_rows)),
        out_start,
        out_end,
        "truncated" if outgoing_truncated else "complete",
        note,
    )


def _concentration_max_features(
    outgoing_rows: list[dict[str, str]],
    outgoing_truncated: bool,
    out_start: dt.datetime | None,
    out_end: dt.datetime | None,
    outgoing_amount: int,
) -> list[Feature]:
    """The single most-favored outgoing counterparty, by transfer count and
    (separately, possibly a different counterparty) by amount. Neither
    identifies an owner, a controller, or a service -- see
    NO_STRONG_INFERENCE_NOTE."""
    completeness = "truncated" if outgoing_truncated else "complete"
    if not outgoing_rows:
        note = (
            "No outgoing transfers are on record; concentration is unknown, not zero."
            if outgoing_truncated
            else "No outgoing transfers were observed within the collected window."
        )
        empty = Feature(
            "outgoing_concentration_max_by_count",
            None,
            (),
            None,
            None,
            "unknown" if not outgoing_truncated else "truncated",
            note,
        )
        return [
            empty,
            Feature(
                "outgoing_concentration_max_by_amount",
                None,
                (),
                None,
                None,
                empty.completeness_status,
                note,
            ),
        ]

    count_by_counterparty = Counter(
        r.get("counterparty_address", "") for r in outgoing_rows if r.get("counterparty_address")
    )
    amount_by_counterparty: Counter[str] = Counter()
    for r in outgoing_rows:
        counterparty = r.get("counterparty_address", "")
        if counterparty and r.get("amount_base_units"):
            amount_by_counterparty[counterparty] += int(r["amount_base_units"])

    note = (
        "Computed only over the outgoing transfers actually observed. " + NO_STRONG_INFERENCE_NOTE
    )
    if outgoing_truncated:
        note += " Coverage is truncated; more outgoing history may exist beyond page/event limits."

    top_by_count, count_value = count_by_counterparty.most_common(1)[0]
    count_ratio = count_value / len(outgoing_rows)
    count_ids = tuple(
        sorted(
            r.get("event_reference", "")
            for r in outgoing_rows
            if r.get("counterparty_address") == top_by_count
        )
    )
    by_count = Feature(
        "outgoing_concentration_max_by_count",
        count_ratio,
        count_ids,
        out_start,
        out_end,
        completeness,
        note,
    )

    if outgoing_amount and amount_by_counterparty:
        top_by_amount, amount_value = amount_by_counterparty.most_common(1)[0]
        amount_ratio = amount_value / outgoing_amount
        amount_ids = tuple(
            sorted(
                r.get("event_reference", "")
                for r in outgoing_rows
                if r.get("counterparty_address") == top_by_amount
            )
        )
        by_amount = Feature(
            "outgoing_concentration_max_by_amount",
            amount_ratio,
            amount_ids,
            out_start,
            out_end,
            completeness,
            note,
        )
    else:
        by_amount = Feature(
            "outgoing_concentration_max_by_amount",
            None,
            (),
            out_start,
            out_end,
            completeness,
            "Total observed outgoing amount is zero; a ratio is not computable.",
        )

    return [by_count, by_amount]


def _repeated_counterparties_feature(
    outgoing_rows: list[dict[str, str]],
    outgoing_truncated: bool,
    out_start: dt.datetime | None,
    out_end: dt.datetime | None,
) -> Feature:
    """How many distinct outgoing counterparties received more than one
    observed transfer -- a count of repeat relationships, separate from
    repeated_forwarding_count's single busiest counterparty."""
    counts = Counter(
        r.get("counterparty_address", "") for r in outgoing_rows if r.get("counterparty_address")
    )
    repeated = {counterparty for counterparty, n in counts.items() if n > 1}
    ids = tuple(
        sorted(
            r.get("event_reference", "")
            for r in outgoing_rows
            if r.get("counterparty_address") in repeated
        )
    )
    note = (
        "Number of distinct outgoing counterparties that received more than one "
        "observed transfer, within the outgoing transfers actually observed. "
        + NO_STRONG_INFERENCE_NOTE
    )
    return Feature(
        "outgoing_counterparties_with_repeat_count",
        len(repeated),
        ids,
        out_start,
        out_end,
        "truncated" if outgoing_truncated else "complete",
        note,
    )


def _repeated_forwarding_feature(
    outgoing_rows: list[dict[str, str]],
    outgoing_truncated: bool,
    out_start: dt.datetime | None,
    out_end: dt.datetime | None,
    outgoing_note: str | None,
) -> Feature:
    counts = Counter(
        r.get("counterparty_address", "") for r in outgoing_rows if r.get("counterparty_address")
    )
    if counts:
        top_counterparty, top_count = counts.most_common(1)[0]
        top_ids = tuple(
            sorted(
                r.get("event_reference", "")
                for r in outgoing_rows
                if r.get("counterparty_address") == top_counterparty
            )
        )
    else:
        top_count = 0
        top_ids = ()
    note = (
        "Counts repeats only within the outgoing transfers actually observed. "
        + NO_STRONG_INFERENCE_NOTE
    )
    if outgoing_note:
        note += " " + outgoing_note
    return Feature(
        "repeated_forwarding_count",
        top_count,
        top_ids,
        out_start,
        out_end,
        "truncated" if outgoing_truncated else "complete",
        note,
    )


def _timing_features(
    incoming_rows: list[dict[str, str]],
    outgoing_rows: list[dict[str, str]],
    incoming_truncated: bool,
    outgoing_truncated: bool,
) -> list[Feature]:
    incoming_timed = sorted(
        (r for r in incoming_rows if r.get("block_time")),
        key=lambda r: r["block_time"],
    )
    outgoing_timed = sorted(
        (r for r in outgoing_rows if r.get("block_time")),
        key=lambda r: r["block_time"],
    )

    features: list[Feature] = []
    matched_pairs: list[tuple[float, tuple[str, str], dt.datetime, dt.datetime]] = []
    ambiguous = 0
    for out_row in outgoing_timed:
        out_time = _parse_dt(out_row["block_time"])
        prior = [r for r in incoming_timed if _parse_dt(r["block_time"]) < out_time]  # type: ignore[operator]
        if not prior:
            ambiguous += 1
            if not incoming_rows:
                status, reason = (
                    "unknown",
                    "No incoming evidence exists for this candidate; timing is unknown, not zero.",
                )
            elif incoming_truncated:
                status, reason = (
                    "truncated",
                    "Incoming coverage is truncated; an earlier receipt may exist "
                    "outside what was collected.",
                )
            else:
                status, reason = (
                    "unknown",
                    "No incoming event was observed before this outgoing event "
                    "within the collected window; timing is ambiguous, not "
                    "assumed absent.",
                )
            features.append(
                Feature(
                    "receipt_to_outflow_ambiguous",
                    None,
                    (out_row.get("event_reference", ""),),
                    None,
                    out_time,
                    status,
                    reason,
                )
            )
            continue

        nearest = max(prior, key=lambda r: r["block_time"])
        in_time = _parse_dt(nearest["block_time"])
        seconds = (out_time - in_time).total_seconds()  # type: ignore[operator]
        pair_ids = (nearest.get("event_reference", ""), out_row.get("event_reference", ""))
        features.append(
            Feature(
                "receipt_to_outflow_timing_seconds",
                seconds,
                pair_ids,
                in_time,
                out_time,
                "truncated" if (incoming_truncated or outgoing_truncated) else "complete",
                None,
            )
        )
        matched_pairs.append((seconds, pair_ids, in_time, out_time))  # type: ignore[arg-type]

    summary_completeness = "truncated" if (incoming_truncated or outgoing_truncated) else "complete"
    features.append(
        Feature(
            "receipt_to_outflow_observation_count",
            len(matched_pairs),
            (),
            None,
            None,
            summary_completeness,
            None,
        )
    )
    features.append(
        Feature(
            "receipt_to_outflow_ambiguous_count",
            ambiguous,
            (),
            None,
            None,
            summary_completeness,
            None,
        )
    )
    features.append(_min_gap_feature(matched_pairs, summary_completeness))
    features.append(_median_gap_feature(matched_pairs, summary_completeness))
    return features


def _min_gap_feature(
    matched_pairs: list[tuple[float, tuple[str, str], dt.datetime, dt.datetime]],
    completeness: str,
) -> Feature:
    if not matched_pairs:
        return Feature(
            "receipt_to_outflow_min_gap_seconds",
            None,
            (),
            None,
            None,
            "unknown",
            "No incoming-to-later-outgoing pairing exists to measure a minimum gap from.",
        )
    seconds, ids, in_time, out_time = min(matched_pairs, key=lambda p: p[0])
    return Feature(
        "receipt_to_outflow_min_gap_seconds",
        seconds,
        ids,
        in_time,
        out_time,
        completeness,
        None,
    )


def _median_gap_feature(
    matched_pairs: list[tuple[float, tuple[str, str], dt.datetime, dt.datetime]],
    completeness: str,
) -> Feature:
    """Only reported when it resolves to one real observed pair. With an
    even number of observations, the statistical median averages the two
    middle gaps -- a value no single observed pair actually produced -- so
    it is reported as not computed rather than attributed to any one of
    them (D: never invent a supporting observation)."""
    if not matched_pairs:
        return Feature(
            "receipt_to_outflow_median_gap_seconds",
            None,
            (),
            None,
            None,
            "unknown",
            "No incoming-to-later-outgoing pairing exists to measure a median gap from.",
        )
    ordered = sorted(matched_pairs, key=lambda p: p[0])
    n = len(ordered)
    if n % 2 == 0:
        return Feature(
            "receipt_to_outflow_median_gap_seconds",
            None,
            (),
            None,
            None,
            "not_applicable",
            f"Median is not reported for an even number of observations ({n}): averaging the "
            "two middle gaps would not correspond to any single observed event pair.",
        )
    seconds, ids, in_time, out_time = ordered[n // 2]
    return Feature(
        "receipt_to_outflow_median_gap_seconds",
        seconds,
        ids,
        in_time,
        out_time,
        completeness,
        None,
    )


def _residue_feature(
    incoming_rows: list[dict[str, str]],
    outgoing_rows: list[dict[str, str]],
    incoming_amount: int,
    outgoing_amount: int,
    incoming_truncated: bool,
    outgoing_truncated: bool,
    incoming_ids: tuple[str, ...],
    outgoing_ids: tuple[str, ...],
    in_start: dt.datetime | None,
    out_end: dt.datetime | None,
) -> Feature:
    incomplete_reasons: list[str] = []
    if not incoming_rows:
        incomplete_reasons.append("no incoming evidence recorded")
    if not outgoing_rows:
        incomplete_reasons.append("no outgoing evidence recorded")
    if incoming_truncated:
        incomplete_reasons.append("incoming coverage truncated")
    if outgoing_truncated:
        incomplete_reasons.append("outgoing coverage truncated")

    if incomplete_reasons:
        note = "Residue is unknown: " + ", ".join(incomplete_reasons) + ". " + RESIDUE_CAVEAT
        return Feature(
            "post_outflow_residue_base_units",
            None,
            incoming_ids + outgoing_ids,
            None,
            None,
            "unknown",
            note,
        )

    residue = incoming_amount - outgoing_amount
    return Feature(
        "post_outflow_residue_base_units",
        residue,
        incoming_ids + outgoing_ids,
        in_start,
        out_end,
        "complete",
        RESIDUE_CAVEAT,
    )


EXECUTION_NOT_VERIFIED_NOTE = (
    "These observations were collected without --verify-execution; execution_status is "
    "honestly unknown for all of them and must not be read as confirmed successful "
    "execution. A separately verified seed/anchor transfer, if one exists for this "
    "candidate, carries its own Stage 1 receipt evidence recorded elsewhere and that "
    "verification is not generalized to these observations."
)


def _uncertainty_features(
    incoming_rows: list[dict[str, str]],
    outgoing_rows: list[dict[str, str]],
    in_start: dt.datetime | None,
    out_end: dt.datetime | None,
) -> list[Feature]:
    """Makes the collection's own honesty about execution/ordering/identity
    visible as features in their own right, not just prose in a docstring --
    so a caller reading the feature list alone (without the module source)
    still cannot mistake these rows for verified, precisely-ordered events."""
    all_rows = incoming_rows + outgoing_rows
    all_ids = tuple(sorted(r.get("event_reference", "") for r in all_rows))
    if not all_rows:
        return [
            Feature(
                "execution_verification_status",
                "not_applicable",
                (),
                None,
                None,
                "not_applicable",
                "No behavioral rows are on record for this candidate.",
            )
        ]

    verified_count = sum(1 for r in all_rows if r.get("execution_status") == "success")
    unverified_count = len(all_rows) - verified_count
    execution_status = "not_verified" if unverified_count else "verified_by_collection"
    execution_note = (
        EXECUTION_NOT_VERIFIED_NOTE
        if unverified_count
        else (
            "Every observation in this set carries execution_status=success from the "
            "collection itself."
        )
    )

    ambiguous_count = sum(1 for r in all_rows if r.get("ordering_ambiguous") == "true")
    ambiguous_ids = tuple(
        sorted(
            r.get("event_reference", "") for r in all_rows if r.get("ordering_ambiguous") == "true"
        )
    )

    missing_index = sum(1 for r in all_rows if not (r.get("event_index") or "").strip())
    missing_block = sum(1 for r in all_rows if not (r.get("block_number") or "").strip())

    return [
        Feature(
            "execution_verification_status",
            execution_status,
            all_ids,
            in_start,
            out_end,
            "unknown" if unverified_count else "complete",
            execution_note,
        ),
        Feature(
            "ordering_ambiguous_observation_count",
            ambiguous_count,
            ambiguous_ids,
            in_start,
            out_end,
            "complete",
            "A row's event_reference is a content-derived identity (transaction plus "
            "canonicalized sender/recipient/amount) when ordering is ambiguous, not a "
            "chain-confirmed position within its transaction.",
        ),
        Feature(
            "event_index_missing_count",
            missing_index,
            (),
            in_start,
            out_end,
            "complete",
            "Absent, not invented, for every row collected without --enrich-events."
            if missing_index
            else None,
        ),
        Feature(
            "block_number_missing_count",
            missing_block,
            (),
            in_start,
            out_end,
            "complete",
            "TronGrid's TRC-20 history endpoint does not return a block number field at "
            "all; this is an endpoint limitation, not a parsing gap."
            if missing_block
            else None,
        ),
    ]
