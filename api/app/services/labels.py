"""Sourced service anchors, loaded from a data file.

Two sets can be read. ``from_csv`` reads one file, which is how the synthetic
fixture set is loaded. ``from_reviewed_sets`` reads the import-then-review
pipeline's output — ``verified_anchors.csv`` and ``deposit_candidates.csv`` —
and is the only source a live trace may use (D019).

``independent_review.csv`` is never read here. A lead is material for a human,
not a label for a tracer.

The algorithm never contains an address. Anchors live in CSV so that changing
the supplied example exercises the same tracer rather than a different branch
(Stage 1 gate).

Every row needs provenance. A row without a source reference and a retrieval
date is rejected, not imported with a blank.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from app.engine.result import LabelEvidence
from app.models.enums import AssertionType, ReviewState

REQUIRED_COLUMNS = {
    "network",
    "address",
    "entity_name",
    "entity_type",
    "assertion_type",
    "address_role",
    "review_state",
    "source_reference",
    "retrieval_date",
    "methodology",
    "label_set_version",
}


#: Files the tracer may read, and what a row in each may do.
TRACING_SETS = ("verified_anchors.csv", "deposit_candidates.csv")

#: A decision that took a claim out of use. Such a row is not loaded at all, so
#: it cannot terminate a branch or be displayed as a candidate.
WITHDRAWN_STATES = frozenset({ReviewState.rejected, ReviewState.quarantined})


class LabelRegistryError(ValueError):
    pass


@dataclass(frozen=True)
class FileFingerprint:
    """One label file as it was when the trace read it."""

    name: str
    sha256: str
    rows_loaded: int
    rows_withdrawn: int

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "sha256": self.sha256,
            "rows_loaded": self.rows_loaded,
            "rows_withdrawn": self.rows_withdrawn,
        }


def _parse_date(value: str | None) -> dt.datetime | None:
    if not value or not value.strip():
        return None
    parsed = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


@dataclass(frozen=True)
class Anchor:
    network_key: str
    address: str
    entity_name: str
    entity_type: str
    assertion_type: AssertionType
    address_role: str
    review_state: ReviewState
    source_reference: str
    retrieval_date: dt.datetime | None
    methodology: str
    reviewer: str | None
    valid_from: dt.datetime | None
    valid_to: dt.datetime | None
    last_verified_at: dt.datetime | None
    label_set_version: str
    source_hash: str | None = None
    source_file: str | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    label_source: str | None = None
    original_reference: str | None = None
    original_hash: str | None = None
    original_member: str | None = None
    original_row_locator: str | None = None

    def covers(self, moment: dt.datetime) -> bool:
        if self.valid_from is not None and moment < self.valid_from:
            return False
        return not (self.valid_to is not None and moment > self.valid_to)

    def can_terminate_trace(self, moment: dt.datetime) -> bool:
        """Only a reviewed, in-date service-control assertion ends a branch."""
        return (
            self.assertion_type is AssertionType.service_control
            and self.review_state is ReviewState.accepted
            and self.covers(moment)
        )

    def to_evidence(self) -> LabelEvidence:
        return LabelEvidence(
            entity_name=self.entity_name,
            entity_type=self.entity_type,
            assertion_type=self.assertion_type.value,
            address_role=self.address_role,
            review_state=self.review_state.value,
            source_reference=self.source_reference,
            retrieval_date=self.retrieval_date.isoformat() if self.retrieval_date else None,
            methodology=self.methodology,
            reviewer=self.reviewer,
            valid_from=self.valid_from.isoformat() if self.valid_from else None,
            valid_to=self.valid_to.isoformat() if self.valid_to else None,
            last_verified_at=(self.last_verified_at.isoformat() if self.last_verified_at else None),
            label_set_version=self.label_set_version,
            source_hash=self.source_hash,
            source_file=self.source_file,
            reviewed_by=self.reviewed_by,
            reviewed_at=self.reviewed_at,
            label_source=self.label_source,
            original_reference=self.original_reference,
            original_hash=self.original_hash,
            original_member=self.original_member,
            original_row_locator=self.original_row_locator,
        )


class LabelRegistry:
    """Network-scoped anchor lookup. Conflicting assertions are all preserved."""

    def __init__(
        self,
        anchors: list[Anchor],
        *,
        source: str = "unspecified",
        files: tuple[FileFingerprint, ...] = (),
    ) -> None:
        self.source = source
        self.files = files
        self._anchors = list(anchors)
        self._by_key: dict[tuple[str, str], list[Anchor]] = {}
        for anchor in anchors:
            self._by_key.setdefault((anchor.network_key, anchor.address), []).append(anchor)

    @classmethod
    def from_csv(cls, path: Path | str, *, source: str = "csv") -> LabelRegistry:
        path = Path(path)
        with path.open(newline="") as fh:
            reader = csv.DictReader(fh)
            missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
            if missing:
                raise LabelRegistryError(f"{path.name} is missing columns: {sorted(missing)}")
            anchors = [cls._row_to_anchor(path, i, row) for i, row in enumerate(reader, start=2)]
        return cls(
            anchors,
            source=source,
            files=(FileFingerprint(path.name, _digest(path), len(anchors), 0),),
        )

    @classmethod
    def from_reviewed_sets(cls, data_dir: Path | str) -> LabelRegistry:
        """Load the reviewed label sets, skipping claims a decision withdrew.

        A missing file is an empty set, not an error: the pipeline writes a file
        the first time something lands in it. An unreviewed row still loads —
        being unreviewed is already enough to stop it terminating a branch, and
        hiding it would hide a candidate a reviewer should see.
        """
        data_dir = Path(data_dir)
        anchors: list[Anchor] = []
        files: list[FileFingerprint] = []
        for name in TRACING_SETS:
            path = data_dir / name
            if not path.is_file():
                continue
            loaded: list[Anchor] = []
            withdrawn = 0
            with path.open(newline="") as fh:
                reader = csv.DictReader(fh)
                missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
                if missing:
                    raise LabelRegistryError(f"{name} is missing columns: {sorted(missing)}")
                for line, row in enumerate(reader, start=2):
                    anchor = cls._row_to_anchor(path, line, row)
                    if anchor.review_state in WITHDRAWN_STATES:
                        withdrawn += 1
                        continue
                    loaded.append(replace(anchor, label_source="reviewed_sets"))
            anchors.extend(loaded)
            files.append(FileFingerprint(name, _digest(path), len(loaded), withdrawn))
        return cls(anchors, source="reviewed_sets", files=tuple(files))

    def snapshot(self) -> dict[str, Any]:
        """What was read, so a saved result does not depend on today's files."""
        return {
            "source": self.source,
            "files": [f.to_json() for f in self.files],
            "claims_loaded": len(self),
            "accepted_service_claims": self.accepted_service_claim_count,
        }

    @property
    def accepted_service_claim_count(self) -> int:
        return sum(
            1
            for anchor in self._anchors
            if anchor.assertion_type is AssertionType.service_control
            and anchor.review_state is ReviewState.accepted
        )

    @staticmethod
    def _row_to_anchor(path: Path, line: int, row: dict[str, str]) -> Anchor:
        for column in ("address", "entity_name", "source_reference", "methodology"):
            if not (row.get(column) or "").strip():
                raise LabelRegistryError(f"{path.name}:{line} has an empty {column}")
        try:
            assertion_type = AssertionType(row["assertion_type"].strip())
            review_state = ReviewState(row["review_state"].strip())
        except ValueError as exc:
            raise LabelRegistryError(f"{path.name}:{line} {exc}") from exc
        return Anchor(
            network_key=row["network"].strip(),
            address=row["address"].strip(),
            entity_name=row["entity_name"].strip(),
            entity_type=row["entity_type"].strip(),
            assertion_type=assertion_type,
            address_role=row["address_role"].strip(),
            review_state=review_state,
            source_reference=row["source_reference"].strip(),
            retrieval_date=_parse_date(row.get("retrieval_date")),
            methodology=row["methodology"].strip(),
            reviewer=(row.get("reviewer") or "").strip() or None,
            valid_from=_parse_date(row.get("valid_from")),
            valid_to=_parse_date(row.get("valid_to")),
            last_verified_at=_parse_date(row.get("last_verified_at")),
            label_set_version=row["label_set_version"].strip(),
            source_hash=(row.get("source_hash") or "").strip() or None,
            source_file=(row.get("source_file") or "").strip() or None,
            reviewed_by=(row.get("reviewed_by") or "").strip() or None,
            reviewed_at=(row.get("reviewed_at") or "").strip() or None,
            original_reference=(row.get("original_reference") or "").strip() or None,
            original_hash=(row.get("original_hash") or "").strip() or None,
            original_member=(row.get("original_member") or "").strip() or None,
            original_row_locator=(row.get("original_row_locator") or "").strip() or None,
        )

    def lookup(self, network_key: str, address: str) -> list[Anchor]:
        return list(self._by_key.get((network_key, address), []))

    def terminating_anchor(
        self, network_key: str, address: str, moment: dt.datetime
    ) -> Anchor | None:
        """Return an eligible anchor only if active accepted claims agree.

        CSV row order must not choose an owner where reviewed evidence conflicts.
        Identical conclusions with independent citations can coexist; conflicting
        entity, entity type or wallet-role claims require a reviewer resolution.
        """
        anchors = [a for a in self.lookup(network_key, address) if a.can_terminate_trace(moment)]
        conclusions = {(a.entity_name.casefold().strip(), a.entity_type, a.address_role) for a in anchors}
        return anchors[0] if len(conclusions) == 1 else None

    def has_active_conflict(self, network_key: str, address: str, moment: dt.datetime) -> bool:
        active = [a for a in self.lookup(network_key, address) if a.can_terminate_trace(moment)]
        return len({(a.entity_name.casefold().strip(), a.entity_type, a.address_role) for a in active}) > 1

    def candidate_anchor(
        self, network_key: str, address: str, moment: dt.datetime
    ) -> Anchor | None:
        """A candidate is shown but never terminates a branch as verified."""
        for anchor in self.lookup(network_key, address):
            if anchor.assertion_type is AssertionType.deposit_candidate and anchor.covers(moment):
                return anchor
        return None

    def __len__(self) -> int:
        return sum(len(v) for v in self._by_key.values())


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
