"""Human review of imported claims: the only step that can accept one.

``import_anchors`` writes every row ``unreviewed`` whatever the source, so the
label sets arrive inert — nothing an importer produces can terminate a trace.
This module is where that changes, and it changes only on a decision that can
show its work.

Stage 2's gate is that the team can open the exact source behind each anchor.
So an acceptance must name the source the reviewer opened, and the preserved
copy is re-hashed at decision time: a file that changed since import cannot be
the file anyone read. Two further limits come from what the sets mean:

- A ``deposit_candidate`` is behaviour. Sweeping, a shared sponsor and a
  repeated rule are the same observation restated, and no quantity of them is a
  source naming the address, so a candidate never becomes an anchor by review.
  It takes a document, which is an import.
- A lead can be promoted, but only on evidence independent of the pattern that
  produced it — the same ``INDEPENDENT_EVIDENCE_KINDS`` policy the resource
  module applies to sponsors (D015), because it is the same question.

Nothing here deletes anything. A decision rewrites ``review_state`` in place, a
promotion copies the row forward and marks the original, a losing claim in a
conflict is preserved as ``conflicted``, and every decision appends to
``review_log.csv`` with the state it moved from.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from app.engine.resources import INDEPENDENT_EVIDENCE_KINDS
from app.services.anchor_import import OUTPUT_COLUMNS, Destination

REVIEW_LOG = "review_log.csv"

REVIEW_LOG_COLUMNS = [
    "decided_at",
    "reviewer",
    "network",
    "address",
    "destination",
    "source_reference",
    "source_hash",
    "action",
    "from_state",
    "to_state",
    "rationale",
    "evidence_inspected",
    "corroboration",
    "promoted_to",
]


class ReviewAction(StrEnum):
    accept = "accept"
    reject = "reject"
    quarantine = "quarantine"
    #: Stays in the queue. Recorded so that "we looked and it was not enough"
    #: is distinguishable from "nobody has looked".
    needs_evidence = "needs_evidence"


ACTION_STATES: dict[ReviewAction, str] = {
    ReviewAction.accept: "accepted",
    ReviewAction.reject: "rejected",
    ReviewAction.quarantine: "quarantined",
    ReviewAction.needs_evidence: "unreviewed",
}

#: Assertion types that no review can turn into a tracing anchor.
BEHAVIOURAL_ASSERTIONS = frozenset({"deposit_candidate"})


@dataclass(frozen=True)
class ReviewItem:
    """One claim awaiting a decision, with everything needed to check it."""

    network_key: str
    address: str
    entity_name: str
    entity_type: str
    assertion_type: str
    address_role: str
    review_state: str
    destination: Destination
    source_reference: str
    source_hash: str
    source_file: str
    upstream_source: str
    retrieval_date: str
    valid_from: str
    label_set_version: str
    methodology: str
    disclosure_kind: str
    row_index: int
    raw: dict[str, str] = field(repr=False, default_factory=dict)

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.network_key, self.address, self.source_reference)

    def describe(self) -> str:
        return (
            f"{self.address} — {self.entity_name} ({self.address_role}), "
            f"{self.assertion_type} from {self.disclosure_kind}, "
            f"{self.review_state}, source {self.source_reference}"
        )


@dataclass(frozen=True)
class ReviewRequest:
    network_key: str
    address: str
    action: ReviewAction
    reviewer: str
    rationale: str
    evidence_inspected: tuple[str, ...] = ()
    corroboration: tuple[str, ...] = ()
    conflict_acknowledged: bool = False
    promote: bool = False
    #: Names which claim, when one address carries several.
    source_reference: str | None = None
    decided_at: dt.datetime | None = None


@dataclass(frozen=True)
class Refusal:
    code: str
    message: str
    address: str
    source_reference: str | None = None


@dataclass(frozen=True)
class AppliedDecision:
    address: str
    destination: Destination
    action: ReviewAction
    from_state: str
    to_state: str
    reviewer: str
    decided_at: dt.datetime
    promoted_to: Destination | None = None
    conflicts_marked: tuple[str, ...] = ()


@dataclass
class ReviewReport:
    applied: list[AppliedDecision] = field(default_factory=list)
    refusals: list[Refusal] = field(default_factory=list)
    written: bool = False

    def summary(self) -> str:
        return f"applied: {len(self.applied)}  refused: {len(self.refusals)}"


def _read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def _write(path: Path, rows: Sequence[dict[str, str]]) -> None:
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _item(destination: Destination, index: int, row: dict[str, str]) -> ReviewItem:
    return ReviewItem(
        network_key=row.get("network", ""),
        address=row.get("address", ""),
        entity_name=row.get("entity_name", ""),
        entity_type=row.get("entity_type", ""),
        assertion_type=row.get("assertion_type", ""),
        address_role=row.get("address_role", ""),
        review_state=row.get("review_state", ""),
        destination=destination,
        source_reference=row.get("source_reference", ""),
        source_hash=row.get("source_hash", ""),
        source_file=row.get("source_file", ""),
        upstream_source=row.get("upstream_source", ""),
        retrieval_date=row.get("retrieval_date", ""),
        valid_from=row.get("valid_from", ""),
        label_set_version=row.get("label_set_version", ""),
        methodology=row.get("methodology", ""),
        disclosure_kind=row.get("disclosure_kind", ""),
        row_index=index,
        raw=dict(row),
    )


def load_review_queue(
    data_dir: Path,
    *,
    network_key: str | None = None,
    states: Iterable[str] = ("unreviewed",),
) -> list[ReviewItem]:
    """Claims awaiting a decision, across all three sets, newest file order."""
    wanted = set(states)
    queue: list[ReviewItem] = []
    for destination in Destination:
        for index, row in enumerate(_read(data_dir / f"{destination.value}.csv")):
            if row.get("review_state") not in wanted:
                continue
            if network_key is not None and row.get("network") != network_key:
                continue
            queue.append(_item(destination, index, row))
    return queue


def _find(
    data_dir: Path, request: ReviewRequest
) -> tuple[Destination, list[dict[str, str]], int] | None:
    for destination in Destination:
        rows = _read(data_dir / f"{destination.value}.csv")
        for index, row in enumerate(rows):
            if row.get("network") != request.network_key or row.get("address") != request.address:
                continue
            if (
                request.source_reference is not None
                and row.get("source_reference") != request.source_reference
            ):
                continue
            return destination, rows, index
    return None


def _competing_claims(
    data_dir: Path, request: ReviewRequest, chosen: dict[str, str]
) -> list[tuple[Destination, int, dict[str, str]]]:
    """Other live claims about this address naming a different entity."""
    out: list[tuple[Destination, int, dict[str, str]]] = []
    for destination in Destination:
        rows = _read(data_dir / f"{destination.value}.csv")
        for index, row in enumerate(rows):
            if row.get("network") != request.network_key or row.get("address") != request.address:
                continue
            if row.get("source_reference") == chosen.get("source_reference"):
                continue
            if row.get("review_state") in {"rejected", "conflicted"}:
                continue
            if (row.get("entity_name") or "").strip() != (chosen.get("entity_name") or "").strip():
                out.append((destination, index, row))
    return out


def _source_intact(data_dir: Path, row: dict[str, str]) -> bool:
    """Is the preserved copy still the file whose hash was recorded at import?"""
    preserved = data_dir / "sources" / (row.get("source_file") or "")
    recorded = row.get("source_hash") or ""
    if not recorded or not preserved.is_file():
        return False
    return hashlib.sha256(preserved.read_bytes()).hexdigest() == recorded


def _original_intact(data_dir: Path, row: dict[str, str]) -> tuple[bool, str]:
    """Is the upstream archive still present and still the file we imported?

    Returns (ok, refusal_code). A row with no original linkage is fine — not
    every document is a selection cut from a bulk archive — but a partial
    linkage is not, because it cannot be checked.
    """
    reference = (row.get("original_reference") or "").strip()
    recorded = (row.get("original_hash") or "").strip()
    member = (row.get("original_member") or "").strip()
    locator = (row.get("original_row_locator") or "").strip()

    if not any((reference, recorded, member, locator)):
        return True, ""
    if not (reference and recorded and member and locator):
        return False, "original_source_unlinked"

    path = Path(reference)
    if not path.is_absolute():
        path = (data_dir.resolve().parent / reference).resolve()
    if not path.is_file():
        return False, "original_source_missing"
    if hashlib.sha256(path.read_bytes()).hexdigest() != recorded:
        return False, "original_source_changed"
    return True, ""


def _names_source(evidence: Iterable[str], row: dict[str, str]) -> bool:
    identifiers = {
        (row.get("source_reference") or "").strip(),
        (row.get("source_hash") or "").strip(),
        (row.get("source_file") or "").strip(),
    } - {""}
    return any((item or "").strip() in identifiers for item in evidence)


def review_candidates(
    data_dir: Path,
    requests: Sequence[ReviewRequest],
    *,
    write: bool = False,
) -> ReviewReport:
    """Apply review decisions. ``write=False`` changes nothing on disk."""
    report = ReviewReport()
    log_rows: list[dict[str, str]] = []
    # Each request re-reads the files, so a decision sees what earlier ones did.
    for request in requests:
        outcome = _apply_one(data_dir, request, write=write)
        if isinstance(outcome, Refusal):
            report.refusals.append(outcome)
            continue
        applied, log_row = outcome
        report.applied.append(applied)
        log_rows.append(log_row)

    if write and log_rows:
        _append_log(data_dir / REVIEW_LOG, log_rows)
        report.written = True
    return report


def _apply_one(
    data_dir: Path, request: ReviewRequest, *, write: bool
) -> Refusal | tuple[AppliedDecision, dict[str, str]]:
    if not (request.reviewer or "").strip():
        return Refusal(
            "reviewer_required",
            "a decision needs the person who made it",
            request.address,
            request.source_reference,
        )
    if not (request.rationale or "").strip():
        return Refusal(
            "rationale_required",
            "record why, not only what",
            request.address,
            request.source_reference,
        )

    found = _find(data_dir, request)
    if found is None:
        return Refusal(
            "no_such_claim",
            f"no imported claim for {request.address} on {request.network_key}",
            request.address,
            request.source_reference,
        )
    destination, rows, index = found
    row = rows[index]
    from_state = row.get("review_state", "")
    decided_at = request.decided_at or dt.datetime.now(dt.UTC)
    promoting = request.promote and destination is not Destination.verified_anchors

    if request.action is ReviewAction.accept:
        if not _names_source(request.evidence_inspected, row):
            return Refusal(
                "source_not_inspected",
                (
                    "accepting a claim means having opened its source; "
                    f"name {row.get('source_reference')} (or its hash) in evidence_inspected"
                ),
                request.address,
                row.get("source_reference"),
            )
        if not _source_intact(data_dir, row):
            return Refusal(
                "source_changed",
                (
                    f"{row.get('source_file')} no longer matches the hash recorded at "
                    "import, so it is not the file anyone reviewed; re-import it"
                ),
                request.address,
                row.get("source_reference"),
            )
        original_ok, original_code = _original_intact(data_dir, row)
        if not original_ok:
            messages = {
                "original_source_unlinked": (
                    "the row names an upstream document but not all of reference, hash, "
                    "member and row locator, so the linkage cannot be checked"
                ),
                "original_source_missing": (
                    f"the upstream document {row.get('original_reference')} is not where "
                    "the row says it is; acceptance needs the original, not only the "
                    "selection cut from it"
                ),
                "original_source_changed": (
                    f"{row.get('original_reference')} no longer matches the hash recorded "
                    "at import, so the selection can no longer be checked against it"
                ),
            }
            return Refusal(
                original_code,
                messages[original_code],
                request.address,
                row.get("source_reference"),
            )

    if promoting:
        if row.get("assertion_type") in BEHAVIOURAL_ASSERTIONS:
            return Refusal(
                "candidate_cannot_become_an_anchor",
                (
                    "a deposit candidate is observed behaviour; an anchor needs a source "
                    "naming the address, which is an import and not a review decision"
                ),
                request.address,
                row.get("source_reference"),
            )
        independent = set(request.corroboration) & INDEPENDENT_EVIDENCE_KINDS
        if not independent:
            return Refusal(
                "promotion_without_independent_evidence",
                (
                    "promotion needs evidence independent of the pattern that produced the "
                    f"lead; one of {sorted(INDEPENDENT_EVIDENCE_KINDS)}"
                ),
                request.address,
                row.get("source_reference"),
            )

    conflicts = (
        _competing_claims(data_dir, request, row) if request.action is ReviewAction.accept else []
    )
    if conflicts and not request.conflict_acknowledged:
        names = ", ".join(sorted({c[2].get("entity_name", "") for c in conflicts}))
        return Refusal(
            "conflict_unacknowledged",
            (
                f"another live claim names {names} for this address; acknowledge the "
                "conflict so the decision records which source was preferred"
            ),
            request.address,
            row.get("source_reference"),
        )

    to_state = ACTION_STATES[request.action]
    evidence = "; ".join(request.evidence_inspected)
    updated = dict(row)
    updated.update(
        {
            "review_state": to_state,
            "reviewed_by": request.reviewer.strip(),
            "reviewed_at": decided_at.isoformat(),
            "review_rationale": request.rationale.strip(),
            "evidence_inspected": evidence,
            "last_verified_at": decided_at.isoformat()
            if request.action is ReviewAction.accept
            else row.get("last_verified_at", ""),
        }
    )
    promoted_to = Destination.verified_anchors if promoting else None
    if promoted_to is not None:
        updated["promoted_to"] = promoted_to.value

    if write:
        rows[index] = updated
        _write(data_dir / f"{destination.value}.csv", rows)
        for conflict_destination, conflict_index, _ in conflicts:
            conflict_rows = _read(data_dir / f"{conflict_destination.value}.csv")
            conflict_rows[conflict_index]["review_state"] = "conflicted"
            conflict_rows[conflict_index]["review_rationale"] = (
                f"superseded at review by {row.get('source_reference')}; preserved, not deleted"
            )
            _write(data_dir / f"{conflict_destination.value}.csv", conflict_rows)
        if promoted_to is not None:
            _promote(data_dir, updated, promoted_to, decided_at, request)

    applied = AppliedDecision(
        address=request.address,
        destination=destination,
        action=request.action,
        from_state=from_state,
        to_state=to_state,
        reviewer=request.reviewer.strip(),
        decided_at=decided_at,
        promoted_to=promoted_to,
        conflicts_marked=tuple(c[2].get("source_reference", "") for c in conflicts),
    )
    log_row = {
        "decided_at": decided_at.isoformat(),
        "reviewer": request.reviewer.strip(),
        "network": request.network_key,
        "address": request.address,
        "destination": destination.value,
        "source_reference": row.get("source_reference", ""),
        "source_hash": row.get("source_hash", ""),
        "action": request.action.value,
        "from_state": from_state,
        "to_state": to_state,
        "rationale": request.rationale.strip(),
        "evidence_inspected": evidence,
        "corroboration": "; ".join(request.corroboration),
        "promoted_to": promoted_to.value if promoted_to else "",
    }
    return applied, log_row


def _promote(
    data_dir: Path,
    row: dict[str, str],
    target: Destination,
    decided_at: dt.datetime,
    request: ReviewRequest,
) -> None:
    """Copy a reviewed lead into the anchor set. The lead itself stays put."""
    path = data_dir / f"{target.value}.csv"
    rows = _read(path)
    key = (row.get("address"), row.get("source_reference"))
    if any((r.get("address"), r.get("source_reference")) == key for r in rows):
        return
    promoted = dict(row)
    promoted["promoted_to"] = ""
    promoted["review_rationale"] = (
        f"{request.rationale.strip()} [promoted from {Destination.independent_review.value} "
        f"on {decided_at.isoformat()} with {', '.join(request.corroboration)}]"
    )
    rows.append(promoted)
    _write(path, rows)


def _append_log(path: Path, log_rows: Sequence[dict[str, str]]) -> None:
    exists = path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=REVIEW_LOG_COLUMNS)
        if not exists:
            writer.writeheader()
        writer.writerows(log_rows)
