"""Regression coverage for the 12-vs-10 counting inconsistency: category
counts must always reconcile exactly to the persisted row count, and must be
derived from the rows themselves rather than composed by hand.
"""

from __future__ import annotations

import csv
from pathlib import Path

from app.services.collect_resource_evidence import EVIDENCE_COLUMNS
from app.services.resource_evidence_report import load_persisted_rows, summarize

REAL_CANDIDATE = "TNtTcstZdy5vppwDMQuR9gy6n5rT4o7ptq"
REAL_DATA_CSV = Path(__file__).resolve().parents[2] / "data" / "resource_evidence.csv"


def _row(
    *,
    relationship_type: str,
    temporal_status: str,
    counterparty: str,
    tx_id: str,
    operation_type: str = "",
) -> dict[str, str]:
    base = dict.fromkeys(EVIDENCE_COLUMNS, "")
    base.update(
        candidate_address="TCANDIDATE",
        relationship_type=relationship_type,
        temporal_status=temporal_status,
        counterparty_address=counterparty,
        tx_or_operation_id=tx_id,
        operation_type=operation_type,
    )
    return base


def test_category_counts_reconcile_against_the_real_persisted_file() -> None:
    rows = load_persisted_rows(REAL_DATA_CSV, candidate_address=REAL_CANDIDATE)
    counts = summarize(rows)

    assert counts.reconciles()
    assert counts.total_rows == 15
    assert counts.historical_token_transfer == 1
    assert counts.historical_delegation_operations == 10
    assert counts.historical_delegate_operations == 6
    assert counts.historical_undelegate_operations == 4
    assert counts.current_state_resource_relationships == 4
    assert counts.incoming_trx_funding == 0
    # exactly reproduces the discrepancy the user reported: 10, not 12.
    assert counts.historical_delegation_operations != 12


def test_category_counts_reconcile_for_an_arbitrary_synthetic_mix() -> None:
    rows = [
        _row(
            relationship_type="token_transfer", temporal_status="historical",
            counterparty="A", tx_id="t1",
        ),
        _row(
            relationship_type="resource_delegation", temporal_status="current_state_only",
            counterparty="B", tx_id="ci1", operation_type="current_index",
        ),
        _row(
            relationship_type="resource_delegation", temporal_status="current_state_only",
            counterparty="B", tx_id="cd1", operation_type="current_detail",
        ),
        _row(
            relationship_type="resource_delegation", temporal_status="historical",
            counterparty="C", tx_id="h1", operation_type="delegate",
        ),
        _row(
            relationship_type="resource_delegation", temporal_status="historical",
            counterparty="C", tx_id="h2", operation_type="undelegate",
        ),
        _row(
            relationship_type="resource_delegation", temporal_status="historical",
            counterparty="C", tx_id="h3", operation_type="delegate",
        ),
        _row(
            relationship_type="trx_funding", temporal_status="historical",
            counterparty="D", tx_id="f1",
        ),
    ]

    counts = summarize(rows)

    assert counts.reconciles()
    assert counts.total_rows == 7
    assert counts.historical_delegation_operations == 3
    assert counts.historical_delegate_operations == 2
    assert counts.historical_undelegate_operations == 1
    assert counts.current_state_resource_relationships == 2
    assert counts.incoming_trx_funding == 1
    assert counts.historical_token_transfer == 1


def test_current_state_rows_are_not_counted_as_historical() -> None:
    rows = [
        _row(
            relationship_type="resource_delegation", temporal_status="current_state_only",
            counterparty="B", tx_id="ci1", operation_type="current_index",
        ),
        _row(
            relationship_type="resource_delegation", temporal_status="current_state_only",
            counterparty="B", tx_id="cd1", operation_type="current_detail",
        ),
    ]

    counts = summarize(rows)

    assert counts.historical_delegation_operations == 0
    assert counts.current_state_resource_relationships == 2
    assert counts.reconciles()


def test_repeated_operations_between_the_same_pair_produce_counts_not_ownership() -> None:
    rows = [
        _row(
            relationship_type="resource_delegation", temporal_status="historical",
            counterparty="PROVIDER", tx_id=f"tx{i}",
            operation_type="delegate" if i % 2 == 0 else "undelegate",
        )
        for i in range(6)
    ]

    counts = summarize(rows)

    assert counts.historical_delegation_operations == 6
    assert counts.distinct_counterparties == {"PROVIDER": {"resource_delegation"}}
    # No field on ResourceEvidenceCounts asserts or names ownership/control.
    assert not hasattr(counts, "owner")
    assert not hasattr(counts, "controls")
    assert counts.reconciles()


def test_the_real_persisted_csv_has_the_operation_type_column() -> None:
    with REAL_DATA_CSV.open(newline="") as fh:
        header = next(csv.reader(fh))
    assert "operation_type" in header
