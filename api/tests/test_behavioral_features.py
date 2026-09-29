"""Deterministic behavioral/sweep feature computation over saved evidence
only -- chronology-correct timing, scope-honest concentration, and no
strong-inference language anywhere in the output.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from app.services.behavioral_features import (
    compute_behavioral_features,
    compute_behavioral_features_from_run,
)
from app.services.collect_behavioral_evidence import (
    BEHAVIORAL_EVIDENCE_COLUMNS,
    PreferredBehavioralRun,
    load_preferred_behavioral_run,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_CANDIDATE = "TNtTcstZdy5vppwDMQuR9gy6n5rT4o7ptq"
REAL_ANCHOR = "TYfxtkCooUX7rzjRqBGLan9XkCxqkrCRir"
REAL_PREFERRED_RUN_DIR = (
    REPO_ROOT / "var" / "collect-behavioral-evidence" / "20260920T165506Z-ee96cd"
)
REAL_DATA_DIR = REPO_ROOT / "data"

CANDIDATE = "TCANDIDATE"
OTHER_CANDIDATE = "TOTHERCANDIDATE"
ANCHOR = "TANCHOR"
COUNTERPARTY_A = "TCOUNTERPARTY_A"
COUNTERPARTY_B = "TCOUNTERPARTY_B"


def _row(**overrides: str) -> dict[str, str]:
    row = dict.fromkeys(BEHAVIORAL_EVIDENCE_COLUMNS, "")
    row["network"] = "tron"
    row["candidate_address"] = CANDIDATE
    row.update(overrides)
    return row


def _run(rows: list[dict[str, str]], **overrides) -> PreferredBehavioralRun:
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


def _feature(features, name: str):
    matches = [f for f in features if f.name == name]
    return matches


def _one(features, name: str):
    (match,) = _feature(features, name)
    return match


# --- 5: chronology prevents pre-receipt outgoing events from being paired ----


def test_chronology_prevents_pairing_an_outgoing_event_with_a_later_incoming_one() -> None:
    rows = [
        _row(
            direction="incoming",
            counterparty_address=COUNTERPARTY_A,
            event_reference="in-late",
            amount_base_units="1000",
            block_time="2026-08-10T16:00:00+00:00",
        ),
        _row(
            direction="outgoing",
            counterparty_address=ANCHOR,
            event_reference="out-early",
            amount_base_units="500",
            block_time="2026-08-10T14:00:00+00:00",
        ),
    ]

    features = compute_behavioral_features(
        rows,
        CANDIDATE,
        anchor_address=ANCHOR,
        incoming_truncated=False,
        outgoing_truncated=False,
    )

    timing = _feature(features, "receipt_to_outflow_timing_seconds")
    assert timing == []  # the only incoming event is chronologically after the outgoing one
    ambiguous = _one(features, "receipt_to_outflow_ambiguous")
    assert ambiguous.source_evidence_ids == ("out-early",)
    assert "not assumed absent" in ambiguous.interpretation_note
    assert _one(features, "receipt_to_outflow_observation_count").value == 0
    assert _one(features, "receipt_to_outflow_ambiguous_count").value == 1


def test_timing_pairs_with_the_nearest_preceding_receipt_not_an_arbitrary_one() -> None:
    rows = [
        _row(
            direction="incoming",
            counterparty_address=COUNTERPARTY_A,
            event_reference="in-1",
            amount_base_units="1000",
            block_time="2026-08-10T10:00:00+00:00",
        ),
        _row(
            direction="incoming",
            counterparty_address=COUNTERPARTY_B,
            event_reference="in-2-nearest",
            amount_base_units="2000",
            block_time="2026-08-10T13:00:00+00:00",
        ),
        _row(
            direction="outgoing",
            counterparty_address=ANCHOR,
            event_reference="out-1",
            amount_base_units="1500",
            block_time="2026-08-10T14:00:00+00:00",
        ),
    ]

    features = compute_behavioral_features(
        rows,
        CANDIDATE,
        anchor_address=ANCHOR,
        incoming_truncated=False,
        outgoing_truncated=False,
    )

    (timing,) = _feature(features, "receipt_to_outflow_timing_seconds")
    assert timing.source_evidence_ids == ("in-2-nearest", "out-1")
    assert timing.value == 3600.0  # 13:00 -> 14:00
    assert timing.completeness_status == "complete"


# --- 6: repeated forwarding count is deterministic -----------------------------


def test_repeated_forwarding_count_is_deterministic() -> None:
    rows = [
        _row(
            direction="outgoing",
            counterparty_address=ANCHOR,
            event_reference=f"out-{i}",
            amount_base_units="1",
            block_time="2026-08-10T14:00:00+00:00",
        )
        for i in range(4)
    ] + [
        _row(
            direction="outgoing",
            counterparty_address=COUNTERPARTY_A,
            event_reference="out-other",
            amount_base_units="1",
            block_time="2026-08-10T14:00:00+00:00",
        )
    ]

    first = compute_behavioral_features(
        rows,
        CANDIDATE,
        anchor_address=ANCHOR,
        incoming_truncated=False,
        outgoing_truncated=False,
    )
    second = compute_behavioral_features(
        rows,
        CANDIDATE,
        anchor_address=ANCHOR,
        incoming_truncated=False,
        outgoing_truncated=False,
    )

    assert _one(first, "repeated_forwarding_count").value == 4
    assert first == second
    note = _one(first, "repeated_forwarding_count").interpretation_note
    assert "does not by itself imply" in note


# --- 7: concentration is computed only over observed scope ---------------------


def test_concentration_is_computed_only_over_observed_scope() -> None:
    rows = [
        _row(
            direction="outgoing",
            counterparty_address=ANCHOR,
            event_reference="out-anchor",
            amount_base_units="3000",
            block_time="2026-08-10T14:00:00+00:00",
        ),
        _row(
            direction="outgoing",
            counterparty_address=COUNTERPARTY_A,
            event_reference="out-other",
            amount_base_units="1000",
            block_time="2026-08-10T14:00:00+00:00",
        ),
    ]

    features = compute_behavioral_features(
        rows,
        CANDIDATE,
        anchor_address=ANCHOR,
        incoming_truncated=False,
        outgoing_truncated=False,
    )

    concentration = _one(features, "outgoing_concentration_toward_accepted_anchor")
    assert concentration.value == 0.75
    assert concentration.source_evidence_ids == ("out-anchor",)
    assert concentration.completeness_status == "complete"


# --- 8: truncated history marks concentration/timing incomplete where needed --


def test_truncated_outgoing_history_marks_concentration_and_timing_truncated() -> None:
    rows = [
        _row(
            direction="incoming",
            counterparty_address=COUNTERPARTY_A,
            event_reference="in-1",
            amount_base_units="1000",
            block_time="2026-08-10T10:00:00+00:00",
        ),
        _row(
            direction="outgoing",
            counterparty_address=ANCHOR,
            event_reference="out-1",
            amount_base_units="500",
            block_time="2026-08-10T14:00:00+00:00",
        ),
    ]

    features = compute_behavioral_features(
        rows,
        CANDIDATE,
        anchor_address=ANCHOR,
        incoming_truncated=False,
        outgoing_truncated=True,
    )

    concentration = _one(features, "outgoing_concentration_toward_accepted_anchor")
    assert concentration.completeness_status == "truncated"
    assert "truncated" in concentration.interpretation_note.lower()
    timing = _one(features, "receipt_to_outflow_timing_seconds")
    assert timing.completeness_status == "truncated"
    forwarding = _one(features, "repeated_forwarding_count")
    assert forwarding.completeness_status == "truncated"


# --- 9: no incoming evidence means timing remains unknown, not zero -----------


def test_no_incoming_evidence_means_timing_is_unknown_not_zero() -> None:
    rows = [
        _row(
            direction="outgoing",
            counterparty_address=ANCHOR,
            event_reference="out-1",
            amount_base_units="500",
            block_time="2026-08-10T14:00:00+00:00",
        ),
    ]

    features = compute_behavioral_features(
        rows,
        CANDIDATE,
        anchor_address=ANCHOR,
        incoming_truncated=False,
        outgoing_truncated=False,
    )

    ambiguous = _one(features, "receipt_to_outflow_ambiguous")
    assert ambiguous.completeness_status == "unknown"
    assert "timing is unknown, not zero" in ambiguous.interpretation_note
    assert _one(features, "receipt_to_outflow_observation_count").value == 0
    residue = _one(features, "post_outflow_residue_base_units")
    assert residue.value is None
    assert residue.completeness_status == "unknown"
    assert "no incoming evidence recorded" in residue.interpretation_note


# --- 10: mixed balances do not become assumed victim-associated value --------


def test_residue_is_never_framed_as_victim_associated_value() -> None:
    rows = [
        _row(
            direction="incoming",
            counterparty_address=COUNTERPARTY_A,
            event_reference="in-1",
            amount_base_units="10000",
            block_time="2026-08-10T10:00:00+00:00",
        ),
        _row(
            direction="outgoing",
            counterparty_address=ANCHOR,
            event_reference="out-1",
            amount_base_units="15000",
            block_time="2026-08-10T14:00:00+00:00",
        ),
    ]

    features = compute_behavioral_features(
        rows,
        CANDIDATE,
        anchor_address=ANCHOR,
        incoming_truncated=False,
        outgoing_truncated=False,
    )

    residue = _one(features, "post_outflow_residue_base_units")
    # Outgoing exceeds observed incoming -- expected when pre-existing
    # balance is possible, and never treated as an error or as fraud.
    assert residue.value == -5000
    assert residue.completeness_status == "complete"
    assert "not a wallet balance" in residue.interpretation_note
    assert "not case-associated or victim-associated value" in residue.interpretation_note
    for feature in features:
        if feature.interpretation_note:
            assert (
                "victim" not in feature.interpretation_note
                or "not case-associated" in feature.interpretation_note
            )


# --- 14: shared behavior between two candidates does not merge them ----------


def test_shared_high_concentration_toward_same_anchor_does_not_merge_candidates() -> None:
    shared_rows = [
        _row(
            candidate_address=CANDIDATE,
            direction="outgoing",
            counterparty_address=ANCHOR,
            event_reference="a-out-1",
            amount_base_units="1000",
            block_time="2026-08-10T14:00:00+00:00",
        ),
        _row(
            candidate_address=OTHER_CANDIDATE,
            direction="outgoing",
            counterparty_address=ANCHOR,
            event_reference="b-out-1",
            amount_base_units="2000",
            block_time="2026-08-10T15:00:00+00:00",
        ),
    ]

    features_a = compute_behavioral_features(
        shared_rows,
        CANDIDATE,
        anchor_address=ANCHOR,
        incoming_truncated=False,
        outgoing_truncated=False,
    )
    features_b = compute_behavioral_features(
        shared_rows,
        OTHER_CANDIDATE,
        anchor_address=ANCHOR,
        incoming_truncated=False,
        outgoing_truncated=False,
    )

    concentration_a = _one(features_a, "outgoing_concentration_toward_accepted_anchor")
    concentration_b = _one(features_b, "outgoing_concentration_toward_accepted_anchor")
    assert concentration_a.value == 1.0
    assert concentration_b.value == 1.0
    assert concentration_a.source_evidence_ids == ("a-out-1",)
    assert concentration_b.source_evidence_ids == ("b-out-1",)
    assert "a-out-1" not in concentration_b.source_evidence_ids
    assert "b-out-1" not in concentration_a.source_evidence_ids

    # Neither candidate's report references the other candidate at all.
    ids_a = {ref for f in features_a for ref in f.source_evidence_ids}
    ids_b = {ref for f in features_b for ref in f.source_evidence_ids}
    assert ids_a.isdisjoint(ids_b)
    assert CANDIDATE not in " ".join(f.interpretation_note or "" for f in features_b)
    assert OTHER_CANDIDATE not in " ".join(f.interpretation_note or "" for f in features_a)


# --- deterministic overall --------------------------------------------------


def test_feature_computation_is_deterministic_over_saved_evidence() -> None:
    rows = [
        _row(
            direction="incoming",
            counterparty_address=COUNTERPARTY_A,
            event_reference="in-1",
            amount_base_units="1000",
            block_time="2026-08-10T10:00:00+00:00",
        ),
        _row(
            direction="outgoing",
            counterparty_address=ANCHOR,
            event_reference="out-1",
            amount_base_units="500",
            block_time="2026-08-10T14:00:00+00:00",
        ),
    ]
    kwargs = dict(
        rows=rows,
        candidate_address=CANDIDATE,
        anchor_address=ANCHOR,
        incoming_truncated=True,
        outgoing_truncated=False,
    )

    first = compute_behavioral_features(**kwargs)
    second = compute_behavioral_features(**kwargs)

    assert first == second


# --- F1: preferred-run completeness flags, not stale row coverage_status -----


def test_feature_computation_uses_preferred_run_flags_not_row_coverage_status() -> None:
    row = _row(
        direction="outgoing",
        counterparty_address=ANCHOR,
        event_reference="out-1",
        amount_base_units="500",
        block_time="2026-08-10T14:00:00+00:00",
        coverage_status="partial",  # stale value from an earlier truncated run
    )

    run = _run([row], outgoing_complete=True)  # this run's own manifest says complete
    features = compute_behavioral_features_from_run(run, anchor_address=ANCHOR)

    assert _one(features, "observed_outgoing_transfer_count").completeness_status == "complete"
    assert _one(features, "outgoing_complete").value is True


# --- F2: real preferred run produces the expected incoming/outgoing counts ---


def test_real_preferred_run_produces_expected_incoming_outgoing_counts() -> None:
    run = load_preferred_behavioral_run(REAL_PREFERRED_RUN_DIR)
    features = compute_behavioral_features_from_run(run, anchor_address=REAL_ANCHOR)

    assert run.candidate_address == REAL_CANDIDATE
    assert run.incoming_complete is True
    assert run.outgoing_complete is True
    assert _one(features, "observed_incoming_transfer_count").value == 1
    assert _one(features, "observed_outgoing_transfer_count").value == 235


# --- F3: concentration uses only observations inside the declared run -------


def test_concentration_uses_only_observations_inside_the_declared_run() -> None:
    run_a_rows = [
        _row(
            candidate_address=CANDIDATE, direction="outgoing", counterparty_address=ANCHOR,
            event_reference="a-out-1", amount_base_units="1000",
            block_time="2026-08-10T14:00:00+00:00",
        )
    ]
    run_b_rows = [
        _row(
            candidate_address=CANDIDATE, direction="outgoing", counterparty_address=COUNTERPARTY_A,
            event_reference="b-out-1", amount_base_units="9000",
            block_time="2026-08-10T15:00:00+00:00",
        )
    ]

    features_a = compute_behavioral_features_from_run(_run(run_a_rows), anchor_address=ANCHOR)
    features_b = compute_behavioral_features_from_run(_run(run_b_rows), anchor_address=ANCHOR)

    # Run A's concentration is computed only from run A's own rows: 100% to
    # the anchor, unaffected by run B's much larger, differently-addressed
    # outgoing transfer existing elsewhere.
    assert _one(features_a, "outgoing_concentration_toward_accepted_anchor").value == 1.0
    assert _one(features_a, "observed_outgoing_amount_base_units").value == 1000
    assert _one(features_b, "outgoing_concentration_toward_accepted_anchor").value == 0.0
    assert _one(features_b, "observed_outgoing_amount_base_units").value == 9000


# --- F4: later outgoing observations do not become token-lineage claims -----


def test_later_outgoing_observations_do_not_claim_token_lineage() -> None:
    rows = [
        _row(
            direction="incoming", counterparty_address=COUNTERPARTY_A, event_reference="in-1",
            amount_base_units="1000", block_time="2026-08-10T10:00:00+00:00",
        ),
        _row(
            direction="outgoing", counterparty_address=ANCHOR, event_reference="out-1",
            amount_base_units="500", block_time="2026-08-10T14:00:00+00:00",
        ),
    ]

    features = compute_behavioral_features_from_run(_run(rows), anchor_address=ANCHOR)

    timing = _one(features, "receipt_to_outflow_timing_seconds")
    for text in (timing.interpretation_note or "",) + tuple(
        f.interpretation_note or "" for f in features
    ):
        assert "same units" not in text.lower()
        assert "same tokens" not in text.lower()
        assert "moved the same" not in text.lower()
    # The residue caveat explicitly denies a lineage/victim-value claim.
    residue_note = _one(features, "post_outflow_residue_base_units").interpretation_note
    assert "not proof of token lineage" in residue_note


# --- F5: execution_status=unknown prevents execution-verified feature claims -


def test_unknown_execution_status_prevents_verified_claims() -> None:
    rows = [
        _row(
            direction="outgoing", counterparty_address=ANCHOR, event_reference="out-1",
            amount_base_units="500", block_time="2026-08-10T14:00:00+00:00",
            execution_status="unknown",
        ),
    ]
    features = compute_behavioral_features_from_run(_run(rows), anchor_address=ANCHOR)

    status = _one(features, "execution_verification_status")
    assert status.value == "not_verified"
    assert status.completeness_status == "unknown"
    assert "must not be read as confirmed successful execution" in status.interpretation_note


def test_all_success_execution_status_is_reported_distinctly() -> None:
    rows = [
        _row(
            direction="outgoing", counterparty_address=ANCHOR, event_reference="out-1",
            amount_base_units="500", block_time="2026-08-10T14:00:00+00:00",
            execution_status="success",
        ),
    ]
    features = compute_behavioral_features_from_run(_run(rows), anchor_address=ANCHOR)

    status = _one(features, "execution_verification_status")
    assert status.value == "verified_by_collection"
    assert status.completeness_status == "complete"


# --- F6: ordering_ambiguous remains visible in feature provenance -----------


def test_ordering_ambiguous_remains_visible_in_feature_provenance() -> None:
    rows = [
        _row(
            direction="outgoing", counterparty_address=ANCHOR, event_reference="out-1",
            amount_base_units="500", block_time="2026-08-10T14:00:00+00:00",
            ordering_ambiguous="true",
        ),
        _row(
            direction="outgoing", counterparty_address=ANCHOR, event_reference="out-2",
            amount_base_units="500", block_time="2026-08-10T15:00:00+00:00",
            ordering_ambiguous="false",
        ),
    ]
    features = compute_behavioral_features_from_run(_run(rows), anchor_address=ANCHOR)

    ambiguous = _one(features, "ordering_ambiguous_observation_count")
    assert ambiguous.value == 1
    assert ambiguous.source_evidence_ids == ("out-1",)
    assert "not a chain-confirmed position" in ambiguous.interpretation_note


# --- F7: missing event_index/block_number are preserved as missing ----------


def test_missing_event_index_and_block_number_are_preserved_as_missing() -> None:
    rows = [
        _row(
            direction="outgoing", counterparty_address=ANCHOR, event_reference="out-1",
            amount_base_units="500", block_time="2026-08-10T14:00:00+00:00",
            event_index="", block_number="",
        ),
    ]
    features = compute_behavioral_features_from_run(_run(rows), anchor_address=ANCHOR)

    assert _one(features, "event_index_missing_count").value == 1
    block_feature = _one(features, "block_number_missing_count")
    assert block_feature.value == 1
    assert "endpoint limitation" in block_feature.interpretation_note


# --- F8: repeated-counterparty features are deterministic -------------------


def test_repeated_counterparty_features_are_deterministic() -> None:
    rows = [
        _row(
            direction="outgoing", counterparty_address=ANCHOR, event_reference=f"out-{i}",
            amount_base_units="100", block_time="2026-08-10T14:00:00+00:00",
        )
        for i in range(3)
    ] + [
        _row(
            direction="outgoing", counterparty_address=COUNTERPARTY_A, event_reference="out-solo",
            amount_base_units="100", block_time="2026-08-10T14:00:00+00:00",
        )
    ]

    first = compute_behavioral_features_from_run(_run(rows), anchor_address=ANCHOR)
    second = compute_behavioral_features_from_run(_run(rows), anchor_address=ANCHOR)

    assert _one(first, "outgoing_counterparties_with_repeat_count").value == 1
    assert _one(first, "outgoing_concentration_max_by_count").value == 0.75
    assert first == second


# --- F11: no network access is required -------------------------------------


def test_behavioral_features_module_requires_no_network_access() -> None:
    import inspect

    import app.services.behavioral_features as behavioral_features_module

    assert not inspect.iscoroutinefunction(compute_behavioral_features)
    assert not inspect.iscoroutinefunction(compute_behavioral_features_from_run)
    source = inspect.getsource(behavioral_features_module)
    assert "adapters" not in source
    assert "httpx" not in source
    assert "respx" not in source


# --- F12: computing features never modifies the review system ---------------


def test_computing_features_does_not_modify_verified_anchors_or_review_log() -> None:
    protected = [
        REAL_DATA_DIR / "verified_anchors.csv",
        REAL_DATA_DIR / "review_log.csv",
        REAL_DATA_DIR / "deposit_candidates.csv",
    ]
    before = {p: p.read_bytes() for p in protected if p.exists()}

    run = load_preferred_behavioral_run(REAL_PREFERRED_RUN_DIR)
    compute_behavioral_features_from_run(run, anchor_address=REAL_ANCHOR)

    for path, contents in before.items():
        assert path.read_bytes() == contents
    for p in protected:
        assert p.exists() == (p in before)
