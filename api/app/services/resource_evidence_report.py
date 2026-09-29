"""Deterministic counts over persisted resource-evidence rows.

Counts here are derived only from the rows themselves -- never composed by
hand into a narrative -- so a category breakdown can always be checked to
sum back to the same total row count. This module reads; it never writes
data/resource_evidence.csv, verified_anchors.csv, deposit_candidates.csv, or
review_log.csv.
"""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from app.services.collect_resource_evidence import (
    OPERATION_DELEGATE,
    OPERATION_UNDELEGATE,
    RELATIONSHIP_RESOURCE_DELEGATION,
    RELATIONSHIP_TOKEN_TRANSFER,
    RELATIONSHIP_TRX_FUNDING,
    TEMPORAL_CURRENT_STATE_ONLY,
    TEMPORAL_HISTORICAL,
)


@dataclass(frozen=True)
class ResourceEvidenceCounts:
    total_rows: int
    #: (relationship_type, temporal_status) -> row count. The single source
    #: every other count on this object is drawn from.
    by_category: dict[tuple[str, str], int]
    historical_token_transfer: int
    historical_delegation_operations: int
    historical_delegate_operations: int
    historical_undelegate_operations: int
    current_state_resource_relationships: int
    incoming_trx_funding: int
    #: counterparty address -> the set of relationship_types seen for it.
    distinct_counterparties: dict[str, set[str]]

    def reconciles(self) -> bool:
        """True only if the category breakdown sums exactly to total_rows --
        the invariant a narrative summary can silently violate but this
        object cannot, because every field above is read out of by_category
        or a direct pass over the same rows."""
        return sum(self.by_category.values()) == self.total_rows


def load_persisted_rows(
    csv_path: Path, candidate_address: str | None = None
) -> list[dict[str, str]]:
    with csv_path.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    if candidate_address is not None:
        rows = [r for r in rows if r.get("candidate_address") == candidate_address]
    return rows


def summarize(rows: list[dict[str, str]]) -> ResourceEvidenceCounts:
    by_category: Counter[tuple[str, str]] = Counter()
    op_counts: Counter[str] = Counter()
    counterparties: dict[str, set[str]] = defaultdict(set)

    for row in rows:
        rel = row["relationship_type"]
        temporal = row["temporal_status"]
        by_category[(rel, temporal)] += 1
        op = row.get("operation_type") or ""
        if op:
            op_counts[op] += 1
        counterparties[row["counterparty_address"]].add(rel)

    return ResourceEvidenceCounts(
        total_rows=len(rows),
        by_category=dict(by_category),
        historical_token_transfer=by_category.get(
            (RELATIONSHIP_TOKEN_TRANSFER, TEMPORAL_HISTORICAL), 0
        ),
        historical_delegation_operations=by_category.get(
            (RELATIONSHIP_RESOURCE_DELEGATION, TEMPORAL_HISTORICAL), 0
        ),
        historical_delegate_operations=op_counts.get(OPERATION_DELEGATE, 0),
        historical_undelegate_operations=op_counts.get(OPERATION_UNDELEGATE, 0),
        current_state_resource_relationships=by_category.get(
            (RELATIONSHIP_RESOURCE_DELEGATION, TEMPORAL_CURRENT_STATE_ONLY), 0
        ),
        incoming_trx_funding=by_category.get((RELATIONSHIP_TRX_FUNDING, TEMPORAL_HISTORICAL), 0),
        distinct_counterparties=dict(counterparties),
    )
