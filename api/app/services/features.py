"""Deterministic features over SAVED, normalized resource-evidence rows only.

No network access: every function here takes rows already persisted in
data/resource_evidence.csv (or an equivalent in-memory list of the same
shape) plus the collection run's own truncation flags, and computes from
those alone. It never calls an adapter, never reads verified_anchors.csv,
deposit_candidates.csv's review fields, or review_log.csv, and never writes
anything.

Every Feature below carries its own source evidence ids, observation window,
and completeness status, because a truncated collection's zero is not the
same fact as a complete collection's zero (F: a zero count from truncated
evidence must never be read as confirmed absence -- see TRUNCATED_ZERO_NOTE).

Current-state resource evidence (temporal_status=current_state_only) and
historical resource evidence (temporal_status=historical) are kept as
separate feature families and are never combined into one "resource
provider existed at transfer time" feature -- current-state evidence says
only what is true right now, not what was true at any earlier moment.

This module computes no ownership, fraud, exchange-deposit, or probability
feature. Repeated delegate/undelegate operations between the same two
addresses become a count, never a claim of common control.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from app.services.collect_resource_evidence import (
    OPERATION_DELEGATE,
    OPERATION_UNDELEGATE,
    RELATIONSHIP_RESOURCE_DELEGATION,
    RELATIONSHIP_TOKEN_TRANSFER,
    RELATIONSHIP_TRX_FUNDING,
    TEMPORAL_CURRENT_STATE_ONLY,
    TEMPORAL_HISTORICAL,
)

TRUNCATED_ZERO_NOTE = (
    "A zero here does not confirm absence: collection for this candidate was "
    "truncated before it could exhaustively cover the window, so an event "
    "that happened outside what was fetched would also read as zero."
)


@dataclass(frozen=True)
class Feature:
    name: str
    value: Any
    source_evidence_ids: tuple[str, ...]
    observation_window_start: dt.datetime | None
    observation_window_end: dt.datetime | None
    #: "complete" or "truncated" -- never a probability or confidence score.
    completeness_status: str
    interpretation_note: str | None = None


def _parse_dt(value: str | None) -> dt.datetime | None:
    return dt.datetime.fromisoformat(value) if value else None


def _bounds(times: list[dt.datetime | None]) -> tuple[dt.datetime | None, dt.datetime | None]:
    present = [t for t in times if t is not None]
    if not present:
        return None, None
    return min(present), max(present)


def extract_features(
    rows: list[dict[str, str]],
    candidate_address: str,
    *,
    request_budget_truncated: bool,
    provider_limit_truncated: bool,
    funder_limit_truncated: bool,
) -> list[Feature]:
    """Compute the deterministic feature set for one candidate from rows
    already persisted for it. Calling this twice on the same rows and flags
    always returns equal output (see test_features.py::test_deterministic)."""
    candidate_rows = [r for r in rows if r["candidate_address"] == candidate_address]

    token_rows = [
        r for r in candidate_rows if r["relationship_type"] == RELATIONSHIP_TOKEN_TRANSFER
    ]
    hist_rows = [
        r
        for r in candidate_rows
        if r["relationship_type"] == RELATIONSHIP_RESOURCE_DELEGATION
        and r["temporal_status"] == TEMPORAL_HISTORICAL
    ]
    current_rows = [
        r
        for r in candidate_rows
        if r["relationship_type"] == RELATIONSHIP_RESOURCE_DELEGATION
        and r["temporal_status"] == TEMPORAL_CURRENT_STATE_ONLY
    ]
    funding_rows = [r for r in candidate_rows if r["relationship_type"] == RELATIONSHIP_TRX_FUNDING]

    resource_history_complete = not (provider_limit_truncated or request_budget_truncated)
    funding_observation_complete = not (funder_limit_truncated or request_budget_truncated)

    features: list[Feature] = []

    # -- token observations -----------------------------------------------
    token_ids = tuple(r["tx_or_operation_id"] for r in token_rows)
    token_start, token_end = _bounds([_parse_dt(r["block_time"]) for r in token_rows])
    token_amount = sum(int(r["amount_base_units"]) for r in token_rows if r["amount_base_units"])
    features += [
        Feature(
            "observed_token_transfer_count", len(token_rows), token_ids, token_start, token_end,
            "complete",
        ),
        Feature(
            "observed_token_amount_base_units", token_amount, token_ids, token_start, token_end,
            "complete",
        ),
        Feature(
            "distinct_anchor_count",
            len({r["counterparty_address"] for r in token_rows}),
            token_ids, token_start, token_end, "complete",
        ),
    ]

    # -- historical resource evidence --------------------------------------
    hist_ids = tuple(r["tx_or_operation_id"] for r in hist_rows)
    hist_start, hist_end = _bounds([_parse_dt(r["block_time"]) for r in hist_rows])
    hist_completeness = "complete" if resource_history_complete else "truncated"
    hist_note = None
    if not resource_history_complete:
        hist_note = (
            "Coverage is truncated (provider_limit and/or request budget); this "
            "count is a lower bound over the window scanned, not a confirmed total."
        )
    delegate_ids = tuple(
        r["tx_or_operation_id"] for r in hist_rows if r.get("operation_type") == OPERATION_DELEGATE
    )
    undelegate_ids = tuple(
        r["tx_or_operation_id"]
        for r in hist_rows
        if r.get("operation_type") == OPERATION_UNDELEGATE
    )
    features += [
        Feature(
            "historical_delegation_operation_count", len(hist_rows), hist_ids, hist_start, hist_end,
            hist_completeness, hist_note,
        ),
        Feature(
            "historical_delegate_count", len(delegate_ids), delegate_ids, hist_start, hist_end,
            hist_completeness, hist_note,
        ),
        Feature(
            "historical_undelegate_count", len(undelegate_ids), undelegate_ids,
            hist_start, hist_end, hist_completeness, hist_note,
        ),
        Feature(
            "distinct_historical_resource_counterparties",
            len({r["counterparty_address"] for r in hist_rows}),
            hist_ids, hist_start, hist_end, hist_completeness, hist_note,
        ),
        Feature(
            "first_historical_resource_time", hist_start, hist_ids, hist_start, hist_start,
            hist_completeness, hist_note,
        ),
        Feature(
            "last_historical_resource_time", hist_end, hist_ids, hist_end, hist_end,
            hist_completeness, hist_note,
        ),
    ]

    if hist_end is not None and token_end is not None:
        gap_seconds = (token_end - hist_end).total_seconds()
        gap_completeness = hist_completeness
        gap_note = hist_note
    else:
        gap_seconds = None
        gap_completeness = "unknown"
        gap_note = (
            "Not computable: this candidate has no historical resource operation "
            "and/or no token transfer on record."
        )
    features.append(
        Feature(
            "seconds_from_last_resource_operation_to_token_transfer",
            gap_seconds, hist_ids + token_ids, hist_end, token_end, gap_completeness, gap_note,
        )
    )

    # -- current-state evidence, kept separate from historical -------------
    current_ids = tuple(r["tx_or_operation_id"] for r in current_rows)
    current_start, current_end = _bounds([_parse_dt(r["coverage_start"]) for r in current_rows])
    features += [
        Feature(
            "current_resource_counterparty_count",
            len({r["counterparty_address"] for r in current_rows}),
            current_ids, current_start, current_end, "complete",
            "Reflects state at acquisition time only -- not evidence this "
            "relationship existed at the candidate's own historical token-transfer "
            "time or any other earlier moment.",
        ),
        Feature(
            "current_state_observed_at", current_start, current_ids, current_start, current_end,
            "complete", None,
        ),
    ]

    # -- funding evidence ---------------------------------------------------
    funding_ids = tuple(r["tx_or_operation_id"] for r in funding_rows)
    funding_start, funding_end = _bounds([_parse_dt(r["block_time"]) for r in funding_rows])
    funding_amount = sum(
        int(r["amount_base_units"]) for r in funding_rows if r["amount_base_units"]
    )
    funding_completeness = "complete" if funding_observation_complete else "truncated"
    funding_note = None if funding_observation_complete else TRUNCATED_ZERO_NOTE
    features += [
        Feature(
            "observed_incoming_trx_funding_count", len(funding_rows), funding_ids,
            funding_start, funding_end, funding_completeness, funding_note,
        ),
        Feature(
            "observed_incoming_trx_funding_amount_sun", funding_amount, funding_ids,
            funding_start, funding_end, funding_completeness, funding_note,
        ),
    ]

    # -- coverage / completeness flags, as features of their own ------------
    features += [
        Feature(
            "resource_history_complete", resource_history_complete, hist_ids + current_ids,
            None, None, "complete", None,
        ),
        Feature(
            "request_budget_truncated", request_budget_truncated, (), None, None, "complete", None,
        ),
        Feature(
            "provider_limit_truncated", provider_limit_truncated, (), None, None, "complete", None,
        ),
        Feature(
            "funding_observation_complete", funding_observation_complete, funding_ids,
            None, None, "complete", None,
        ),
    ]

    return features
