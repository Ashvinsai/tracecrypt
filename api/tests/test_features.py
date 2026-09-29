"""Deterministic feature extraction over saved evidence only -- no network,
no ownership/fraud/probability features, no ability to touch the review
system's protected files.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from app.services.collect_resource_evidence import EVIDENCE_COLUMNS
from app.services.features import Feature, extract_features
from app.services.resource_evidence_report import load_persisted_rows

REAL_CANDIDATE = "TNtTcstZdy5vppwDMQuR9gy6n5rT4o7ptq"
REAL_DATA_CSV = Path(__file__).resolve().parents[2] / "data" / "resource_evidence.csv"
REAL_DATA_DIR = REAL_DATA_CSV.parent


def _row(**overrides: str) -> dict[str, str]:
    base = dict.fromkeys(EVIDENCE_COLUMNS, "")
    base["candidate_address"] = "TCANDIDATE"
    base.update(overrides)
    return base


def _feature(features: list[Feature], name: str) -> Feature:
    (match,) = [f for f in features if f.name == name]
    return match


def test_feature_schema_for_the_real_candidate() -> None:
    rows = load_persisted_rows(REAL_DATA_CSV, candidate_address=REAL_CANDIDATE)

    features = extract_features(
        rows, REAL_CANDIDATE,
        request_budget_truncated=True,
        provider_limit_truncated=True,
        funder_limit_truncated=False,
    )

    by_name = {f.name: f for f in features}
    assert by_name["observed_token_transfer_count"].value == 1
    assert by_name["observed_token_amount_base_units"].value == 72_140_000
    assert by_name["historical_delegation_operation_count"].value == 10
    assert by_name["historical_delegate_count"].value == 6
    assert by_name["historical_undelegate_count"].value == 4
    assert by_name["current_resource_counterparty_count"].value == 2
    assert by_name["observed_incoming_trx_funding_count"].value == 0
    # Truncated by provider_limit -> historical counts are a lower bound.
    assert by_name["historical_delegation_operation_count"].completeness_status == "truncated"
    assert by_name["historical_delegation_operation_count"].interpretation_note is not None
    # funder_limit was not truncated, but the whole run hit its request
    # budget, so funding completeness still cannot be asserted true.
    assert by_name["observed_incoming_trx_funding_count"].completeness_status == "truncated"
    assert by_name["observed_incoming_trx_funding_count"].interpretation_note is not None
    for f in features:
        assert isinstance(f.source_evidence_ids, tuple)
        assert f.completeness_status in {"complete", "truncated", "unknown"}


def test_truncated_zero_funding_is_not_confirmed_absence() -> None:
    rows = [
        _row(
            relationship_type="token_transfer", temporal_status="historical",
            tx_or_operation_id="t1",
        )
    ]

    complete = extract_features(
        rows, "TCANDIDATE", request_budget_truncated=False,
        provider_limit_truncated=False, funder_limit_truncated=False,
    )
    truncated = extract_features(
        rows, "TCANDIDATE", request_budget_truncated=False,
        provider_limit_truncated=False, funder_limit_truncated=True,
    )

    complete_funding = _feature(complete, "observed_incoming_trx_funding_count")
    truncated_funding = _feature(truncated, "observed_incoming_trx_funding_count")
    assert complete_funding.value == 0
    assert complete_funding.completeness_status == "complete"
    assert complete_funding.interpretation_note is None
    assert truncated_funding.value == 0
    assert truncated_funding.completeness_status == "truncated"
    assert truncated_funding.interpretation_note is not None
    assert "not confirm absence" in truncated_funding.interpretation_note


def test_current_state_is_not_counted_as_historical_resource_evidence() -> None:
    rows = [
        _row(
            relationship_type="resource_delegation", temporal_status="current_state_only",
            operation_type="current_index", tx_or_operation_id="ci1", counterparty_address="P",
        ),
        _row(
            relationship_type="resource_delegation", temporal_status="current_state_only",
            operation_type="current_detail", tx_or_operation_id="cd1", counterparty_address="P",
        ),
    ]

    features = extract_features(
        rows, "TCANDIDATE", request_budget_truncated=False,
        provider_limit_truncated=False, funder_limit_truncated=False,
    )

    assert _feature(features, "historical_delegation_operation_count").value == 0
    assert _feature(features, "current_resource_counterparty_count").value == 1
    note = _feature(features, "current_resource_counterparty_count").interpretation_note
    assert note is not None and "not evidence" in note


def test_repeated_delegate_undelegate_operations_produce_counts_not_ownership() -> None:
    rows = [
        _row(
            relationship_type="resource_delegation", temporal_status="historical",
            operation_type="delegate" if i % 2 == 0 else "undelegate",
            tx_or_operation_id=f"tx{i}", counterparty_address="PROVIDER",
            block_time=dt.datetime(2026, 8, 10, 14, 55, i, tzinfo=dt.UTC).isoformat(),
        )
        for i in range(8)
    ]

    features = extract_features(
        rows, "TCANDIDATE", request_budget_truncated=False,
        provider_limit_truncated=False, funder_limit_truncated=False,
    )

    assert _feature(features, "historical_delegation_operation_count").value == 8
    assert _feature(features, "distinct_historical_resource_counterparties").value == 1
    for f in features:
        assert "owner" not in f.name
        assert "control" not in f.name
        assert "fraud" not in f.name
        assert "probability" not in f.name
        if f.interpretation_note:
            assert "owns" not in f.interpretation_note
            assert "controlled by" not in f.interpretation_note


def test_feature_extraction_is_deterministic() -> None:
    rows = load_persisted_rows(REAL_DATA_CSV, candidate_address=REAL_CANDIDATE)
    kwargs = dict(
        rows=rows, candidate_address=REAL_CANDIDATE,
        request_budget_truncated=True, provider_limit_truncated=True, funder_limit_truncated=False,
    )

    first = extract_features(**kwargs)
    second = extract_features(**kwargs)

    assert first == second


def test_feature_extraction_requires_no_network_access() -> None:
    """extract_features is a plain sync function over in-memory rows -- it
    cannot make an HTTP request even accidentally, since it never imports an
    adapter or an event loop."""
    import inspect

    import app.services.features as features_module

    assert not inspect.iscoroutinefunction(extract_features)
    source = inspect.getsource(features_module)
    assert "adapters" not in source
    assert "httpx" not in source
    assert "respx" not in source


def test_feature_extraction_cannot_modify_the_review_system() -> None:
    protected = [
        REAL_DATA_DIR / "verified_anchors.csv",
        REAL_DATA_DIR / "deposit_candidates.csv",
        REAL_DATA_DIR / "review_log.csv",
    ]
    before = {p: p.read_bytes() for p in protected if p.exists()}

    rows = load_persisted_rows(REAL_DATA_CSV, candidate_address=REAL_CANDIDATE)
    extract_features(
        rows, REAL_CANDIDATE,
        request_budget_truncated=True, provider_limit_truncated=True, funder_limit_truncated=False,
    )

    for path, contents in before.items():
        assert path.read_bytes() == contents
    for p in protected:
        assert p.exists() == (p in before)
