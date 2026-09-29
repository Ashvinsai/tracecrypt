"""Stage 2 gate: the four-level comparison report is offline, deterministic,
and cannot be tricked into merging candidates, inventing a service label
from resource evidence alone, promoting current-state facts into historical
ones, or reading a truncated zero as confirmed absence.
"""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

from app.services.collect_behavioral_evidence import (
    BEHAVIORAL_EVIDENCE_COLUMNS,
    PreferredBehavioralRun,
    load_preferred_behavioral_run,
)
from app.services.collect_resource_evidence import EVIDENCE_COLUMNS
from app.services.evidence_comparison import (
    LEVEL_ANCHOR_ONLY,
    LEVEL_CHRONOLOGICAL_TRACING,
    LEVEL_TRACING_PLUS_BEHAVIORAL_RULES,
    LEVEL_TRACING_PLUS_BEHAVIORAL_RULES_PLUS_RESOURCE_EVIDENCE,
    build_comparison,
)

CANDIDATE = "TCANDIDATE"
OTHER_CANDIDATE = "TOTHERCANDIDATE"
ANCHOR = "TANCHOR"
SHARED_PROVIDER = "TSHAREDPROVIDER"

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_CANDIDATE = "TNtTcstZdy5vppwDMQuR9gy6n5rT4o7ptq"
REAL_PREFERRED_RUN_DIR = (
    REPO_ROOT / "var" / "collect-behavioral-evidence" / "20260920T165506Z-ee96cd"
)


def _resource_row(**overrides: str) -> dict[str, str]:
    row = dict.fromkeys(EVIDENCE_COLUMNS, "")
    row["network"] = "tron"
    row.update(overrides)
    return row


def _deposit_candidate_row(**overrides: str) -> dict[str, str]:
    row = {
        "network": "tron",
        "address": CANDIDATE,
        "review_state": "unreviewed",
        "anchor_address": ANCHOR,
        "anchor_entity_name": "OKX",
        "methodology": "fixture selection",
    }
    row.update(overrides)
    return row


def _anchor_row(**overrides: str) -> dict[str, str]:
    row = {
        "network": "tron",
        "address": ANCHOR,
        "entity_name": "OKX",
        "entity_type": "exchange",
        "assertion_type": "service_control",
        "address_role": "unknown",
        "review_state": "accepted",
        "source_reference": "https://example.invalid/por",
        "source_hash": "deadbeef",
        "valid_from": "2026-08-10T15:59:54+00:00",
        "valid_to": "2026-08-10T15:59:54+00:00",
    }
    row.update(overrides)
    return row


def _behavioral_row(**overrides: str) -> dict[str, str]:
    row = dict.fromkeys(BEHAVIORAL_EVIDENCE_COLUMNS, "")
    row["network"] = "tron"
    row["candidate_address"] = CANDIDATE
    row.update(overrides)
    return row


def _behavioral_run(rows: list[dict[str, str]], **overrides) -> PreferredBehavioralRun:
    kwargs = dict(
        run_id="test-run",
        candidate_address=CANDIDATE,
        rows=tuple(rows),
        behavioral_window_start=dt.datetime(2026, 8, 10, tzinfo=dt.UTC),
        behavioral_window_end=dt.datetime(2026, 8, 11, tzinfo=dt.UTC),
        incoming_complete=True,
        outgoing_complete=True,
        request_budget_truncated=False,
        page_limit_truncated=False,
        event_limit_truncated=False,
    )
    kwargs.update(overrides)
    return PreferredBehavioralRun(**kwargs)


def _base_kwargs(**overrides):
    kwargs = dict(
        deposit_candidate_row=_deposit_candidate_row(),
        anchor_rows=[_anchor_row()],
        resource_rows=[],
        request_budget_truncated=False,
        provider_limit_truncated=False,
        funder_limit_truncated=False,
    )
    kwargs.update(overrides)
    return kwargs


# --- shared resource provider does not merge candidates ----------------------


def test_shared_resource_provider_does_not_merge_candidates() -> None:
    shared_hist_row_a = _resource_row(
        candidate_address=CANDIDATE,
        relationship_type="resource_delegation",
        temporal_status="historical",
        counterparty_address=SHARED_PROVIDER,
        tx_or_operation_id="txA",
        operation_type="delegate",
        block_time="2026-08-10T14:00:00+00:00",
    )
    shared_hist_row_b = _resource_row(
        candidate_address=OTHER_CANDIDATE,
        relationship_type="resource_delegation",
        temporal_status="historical",
        counterparty_address=SHARED_PROVIDER,
        tx_or_operation_id="txB",
        operation_type="delegate",
        block_time="2026-08-10T15:00:00+00:00",
    )
    all_rows = [shared_hist_row_a, shared_hist_row_b]

    report_a = build_comparison(
        CANDIDATE,
        **_base_kwargs(
            deposit_candidate_row=_deposit_candidate_row(address=CANDIDATE),
            resource_rows=all_rows,
        ),
    )
    report_b = build_comparison(
        OTHER_CANDIDATE,
        **_base_kwargs(
            deposit_candidate_row=_deposit_candidate_row(address=OTHER_CANDIDATE),
            resource_rows=all_rows,
        ),
    )

    level4_a = report_a.levels[3]
    level4_b = report_b.levels[3]
    assert "txA" in level4_a.source_evidence_ids
    assert "txB" not in level4_a.source_evidence_ids
    assert "txB" in level4_b.source_evidence_ids
    assert "txA" not in level4_b.source_evidence_ids

    full_text = " ".join(
        list(level4_a.observed_evidence)
        + level4_a.supported_conclusion.split()
        + list(level4_b.observed_evidence)
        + level4_b.supported_conclusion.split()
    )
    for banned in ("same owner", "same controller", "merged", "common control"):
        assert banned not in full_text.lower()
    assert any("anti-merging" in s.lower() for s in level4_a.additional_signals)
    assert any("anti-merging" in s.lower() for s in level4_b.additional_signals)


# --- resource evidence alone cannot create a supported service label ---------


def test_resource_evidence_alone_cannot_create_a_supported_service_label() -> None:
    resource_rows = [
        _resource_row(
            candidate_address=CANDIDATE,
            relationship_type="resource_delegation",
            temporal_status="historical",
            counterparty_address=SHARED_PROVIDER,
            tx_or_operation_id="tx1",
            operation_type="delegate",
            block_time="2026-08-10T14:00:00+00:00",
        )
        for _ in range(1)
    ] + [
        _resource_row(
            candidate_address=CANDIDATE,
            relationship_type="resource_delegation",
            temporal_status="historical",
            counterparty_address=SHARED_PROVIDER,
            tx_or_operation_id=f"tx-repeat-{i}",
            operation_type="delegate",
            block_time="2026-08-10T14:00:00+00:00",
        )
        for i in range(20)
    ]

    report = build_comparison(
        CANDIDATE,
        **_base_kwargs(
            deposit_candidate_row=None,  # no anchor/tracing link at all
            anchor_rows=[],
            resource_rows=resource_rows,
        ),
    )

    for level in report.levels:
        text = level.supported_conclusion.lower()
        assert "verified" not in text or "not a verified" in text
        assert "okx" not in text
        assert "customer-deposit" not in text or "not a" in text or "not" in text
    level4 = report.levels[3]
    assert "cannot by themselves create or support a service label" in level4.supported_conclusion


# --- current-state evidence does not become historical evidence --------------


def test_current_state_evidence_does_not_become_historical() -> None:
    old_current_state_row = _resource_row(
        candidate_address=CANDIDATE,
        relationship_type="resource_delegation",
        temporal_status="current_state_only",
        counterparty_address=SHARED_PROVIDER,
        tx_or_operation_id="current1",
        operation_type="current_index",
        coverage_start="1999-01-01T00:00:00+00:00",
    )
    real_historical_row = _resource_row(
        candidate_address=CANDIDATE,
        relationship_type="resource_delegation",
        temporal_status="historical",
        counterparty_address=SHARED_PROVIDER,
        tx_or_operation_id="hist1",
        operation_type="delegate",
        block_time="2026-08-10T14:54:18+00:00",
    )

    report = build_comparison(
        CANDIDATE,
        **_base_kwargs(resource_rows=[old_current_state_row, real_historical_row]),
    )
    level4 = report.levels[3]

    historical_bullet = next(
        b for b in level4.observed_evidence if "historical DelegateResource" in b
    )
    current_bullet = next(b for b in level4.observed_evidence if "Current-state" in b)
    assert "1999" not in historical_bullet
    assert "1 historical" in historical_bullet
    assert "2026-08-10T14:54:18" in historical_bullet
    assert "1999-01-01" in current_bullet
    assert "not evidence the relationship existed at any earlier moment" in current_bullet


# --- truncated zero funding remains unknown/incomplete ------------------------


def test_truncated_zero_funding_remains_incomplete() -> None:
    complete = build_comparison(CANDIDATE, **_base_kwargs())
    truncated = build_comparison(CANDIDATE, **_base_kwargs(funder_limit_truncated=True))

    level4_complete = complete.levels[3]
    level4_truncated = truncated.levels[3]

    assert level4_complete.completeness_status == "complete"
    assert not any("not confirmed" in u for u in level4_complete.unresolved)

    assert level4_truncated.completeness_status == "truncated"
    assert any("not confirmed zero" in u for u in level4_truncated.unresolved)
    assert any("not confirmed absence" in e for e in level4_truncated.observed_evidence)


# --- unknown evidence remains unknown -----------------------------------------


def test_unknown_evidence_remains_unknown() -> None:
    anchor_row = _anchor_row(address_role="unknown")
    current_row = _resource_row(
        candidate_address=CANDIDATE,
        relationship_type="resource_delegation",
        temporal_status="current_state_only",
        counterparty_address=SHARED_PROVIDER,
        tx_or_operation_id="current1",
        operation_type="current_index",
        asset_or_resource_type="unknown",
        coverage_start="2026-09-20T00:00:00+00:00",
    )

    report = build_comparison(
        CANDIDATE, **_base_kwargs(anchor_rows=[anchor_row], resource_rows=[current_row])
    )

    level1 = report.levels[0]
    assert "unknown" in level1.supported_conclusion
    assert level1.supported_conclusion.count("unknown") >= 1
    # Never silently promoted to a guessed role such as "hot wallet" or "deposit".
    assert "hot wallet" not in level1.supported_conclusion
    assert "deposit" not in level1.supported_conclusion.lower().replace("deposit_candidate", "")


# --- comparison output is deterministic ---------------------------------------


def test_comparison_output_is_deterministic() -> None:
    resource_rows = [
        _resource_row(
            candidate_address=CANDIDATE,
            relationship_type="token_transfer",
            temporal_status="historical",
            counterparty_address=ANCHOR,
            tx_or_operation_id="tt1",
            amount_base_units="72140000",
            block_time="2026-08-10T15:59:54+00:00",
            evidence_reference="tron:tt1:0",
        ),
        _resource_row(
            candidate_address=CANDIDATE,
            relationship_type="resource_delegation",
            temporal_status="historical",
            counterparty_address=SHARED_PROVIDER,
            tx_or_operation_id="hist1",
            operation_type="delegate",
            block_time="2026-08-10T14:54:18+00:00",
        ),
        _resource_row(
            candidate_address=CANDIDATE,
            relationship_type="resource_delegation",
            temporal_status="current_state_only",
            counterparty_address=SHARED_PROVIDER,
            tx_or_operation_id="current1",
            operation_type="current_index",
            coverage_start="2026-09-20T11:07:57+00:00",
        ),
        _resource_row(
            candidate_address=CANDIDATE,
            relationship_type="trx_funding",
            temporal_status="historical",
            counterparty_address="TFUNDER",
            tx_or_operation_id="fund1",
            amount_base_units="1000000",
            block_time="2026-08-10T14:00:00+00:00",
        ),
    ]
    kwargs = _base_kwargs(
        resource_rows=resource_rows,
        request_budget_truncated=True,
        provider_limit_truncated=True,
        funder_limit_truncated=False,
    )

    first = build_comparison(CANDIDATE, **kwargs)
    second = build_comparison(CANDIDATE, **kwargs)

    assert first == second
    assert first.to_dict() == second.to_dict()


# --- level identity / structural sanity ---------------------------------------


def test_all_four_levels_are_present_in_order() -> None:
    report = build_comparison(CANDIDATE, **_base_kwargs())
    assert [level.level for level in report.levels] == [
        LEVEL_ANCHOR_ONLY,
        LEVEL_CHRONOLOGICAL_TRACING,
        LEVEL_TRACING_PLUS_BEHAVIORAL_RULES,
        LEVEL_TRACING_PLUS_BEHAVIORAL_RULES_PLUS_RESOURCE_EVIDENCE,
    ]


def test_report_never_labels_the_candidate_okx_or_a_customer_deposit() -> None:
    report = build_comparison(CANDIDATE, **_base_kwargs())
    forbidden_candidate_claims = [
        f"{CANDIDATE} is OKX",
        f"{CANDIDATE} belongs to OKX",
        f"{CANDIDATE} is a customer deposit",
    ]
    full_text = " ".join(
        c
        for level in report.levels
        for c in (
            *level.observed_evidence,
            level.supported_conclusion,
            *level.unresolved,
            *level.additional_signals,
        )
    )
    for claim in forbidden_candidate_claims:
        assert claim not in full_text
    assert "probability" not in full_text.lower()


# --- level 3 integration: behavioral evidence, when present, populates it ---


def test_level_3_stays_not_collected_without_behavioral_evidence() -> None:
    report = build_comparison(CANDIDATE, **_base_kwargs())
    level3 = report.levels[2]
    assert level3.completeness_status == "not_collected"


def test_level_3_is_populated_from_saved_behavioral_evidence() -> None:
    behavioral_rows = [
        _behavioral_row(
            direction="outgoing",
            counterparty_address=ANCHOR,
            event_reference="beh-out-1",
            amount_base_units="1000",
            block_time="2026-08-10T14:00:00+00:00",
        ),
        _behavioral_row(
            direction="incoming",
            counterparty_address=SHARED_PROVIDER,
            event_reference="beh-in-1",
            amount_base_units="1000",
            block_time="2026-08-10T10:00:00+00:00",
        ),
    ]

    report = build_comparison(
        CANDIDATE,
        **_base_kwargs(),
        behavioral_run=_behavioral_run(behavioral_rows),
    )
    level3 = report.levels[2]
    level4 = report.levels[3]

    assert level3.completeness_status == "complete"
    assert level3.source_evidence_ids == ("beh-in-1", "beh-out-1")
    assert "does not establish OKX ownership" in " ".join(level3.unresolved) or any(
        "does not establish OKX ownership" in note for note in level3.unresolved
    )
    # Resource evidence (level 4) is untouched by behavioral evidence.
    assert level4.level == LEVEL_TRACING_PLUS_BEHAVIORAL_RULES_PLUS_RESOURCE_EVIDENCE
    assert "beh-out-1" not in level4.source_evidence_ids


def test_behavioral_evidence_alone_does_not_create_a_supported_service_destination() -> None:
    behavioral_rows = [
        _behavioral_row(
            direction="outgoing",
            counterparty_address=ANCHOR,
            event_reference=f"beh-out-{i}",
            amount_base_units="1000",
            block_time="2026-08-10T14:00:00+00:00",
        )
        for i in range(20)
    ]

    report = build_comparison(
        CANDIDATE,
        **_base_kwargs(deposit_candidate_row=None, anchor_rows=[]),
        behavioral_run=_behavioral_run(behavioral_rows),
    )
    level3 = report.levels[2]
    text = level3.supported_conclusion.lower()

    assert "is okx" not in text
    assert "belongs to okx" not in text
    assert "is a verified" not in text
    assert "is a customer-deposit" not in text
    assert "behavioral evidence only" in text


# --- F9/F10: full pipeline against the real preferred run and real evidence --


def _read_real_csv(name: str) -> list[dict[str, str]]:
    path = REPO_ROOT / "data" / name
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def test_level_3_is_populated_from_the_real_preferred_run() -> None:
    deposit_rows = _read_real_csv("deposit_candidates.csv")
    deposit_row = next(r for r in deposit_rows if r["address"] == REAL_CANDIDATE)
    anchor_rows = _read_real_csv("verified_anchors.csv")
    resource_rows = _read_real_csv("resource_evidence.csv")
    behavioral_run = load_preferred_behavioral_run(REAL_PREFERRED_RUN_DIR)

    report = build_comparison(
        REAL_CANDIDATE,
        deposit_candidate_row=deposit_row,
        anchor_rows=anchor_rows,
        resource_rows=resource_rows,
        request_budget_truncated=True,
        provider_limit_truncated=True,
        funder_limit_truncated=False,
        behavioral_run=behavioral_run,
    )

    level3 = report.levels[2]
    level4 = report.levels[3]
    assert level3.level == LEVEL_TRACING_PLUS_BEHAVIORAL_RULES
    assert level3.completeness_status == "complete"
    # A: acquisition completeness and verification quality are stated as
    # two separate facts, not collapsed into one "complete" status.
    assert level3.observed_evidence[0] == (
        "Acquisition complete within the bounded window; execution and fine "
        "event ordering not verified."
    )
    assert "1 incoming and 235 outgoing" in level3.observed_evidence[1]
    assert "acquisition_completeness=complete_within_scope" in level3.completeness_notes
    assert "verification_quality=history_only" in level3.completeness_notes
    assert "event_identity_quality=observation_reference_only" in level3.completeness_notes
    assert "ordering_quality=ambiguous" in level3.completeness_notes

    # Resource evidence (level 4) still declines any ownership/service
    # upgrade, unaffected by level 3 now being populated.
    assert level4.level == LEVEL_TRACING_PLUS_BEHAVIORAL_RULES_PLUS_RESOURCE_EVIDENCE
    assert "cannot by themselves create or support a service label" in level4.supported_conclusion
    for level in report.levels:
        assert "is okx" not in level.supported_conclusion.lower()
        assert "is a customer-deposit" not in level.supported_conclusion.lower()
    assert report.candidate_status.startswith("deposit_candidate")
