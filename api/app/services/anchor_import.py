"""Import address claims from a source document, and refuse what it cannot support.

Stage 2 sections A and B. Three sets, three files, never mixed:

``verified_anchors.csv``
    claims from a service's own disclosure. The tracer reads this set — after a
    human sets ``review_state=accepted``. The importer never sets it.

``deposit_candidates.csv``
    behavioural candidates. Shown, never trusted, never terminating a branch.

``independent_review.csv``
    leads and evaluation material: aggregator copies, authorized observations.

The routing rules come from what a document actually establishes:

- A proof-of-reserves file supports a dated claim that the service controlled an
  address. It does not say the address is a customer deposit address or a hot
  wallet, so those roles are rejected rather than imported with a shrug.
- A signed address verification supports the role the service itself states.
- An aggregator copy is a lead. Two aggregators repeating one upstream source
  are one source, and the corroboration count says so.
- An authorized observation of someone's own deposit address is evaluation
  material, not an anchor for tracing.

Nothing is imported at all until the document itself has a URL, a disclosure
date, a retrieval time and a methodology. A blank provenance field is a refusal,
not a default.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import shutil
from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from app.models.enums import AddressRole, AssertionType

#: Columns the source document must provide per row. Provenance is not among
#: them: it describes the document, and is supplied once by the human importing.
SOURCE_COLUMNS = {
    "network",
    "address",
    "entity_name",
    "entity_type",
    "assertion_type",
    "address_role",
}

#: The schema ``LabelRegistry.from_csv`` reads, plus the source columns it
#: ignores and a reviewer needs. The trailing review columns are empty on
#: import and filled by ``candidate_review``; ``reviewer`` is who prepared the
#: import, ``reviewed_by`` is who accepted the claim, and they are not the same
#: question.
OUTPUT_COLUMNS = [
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
    "reviewer",
    "valid_from",
    "valid_to",
    "last_verified_at",
    "label_set_version",
    "disclosure_kind",
    "source_hash",
    "source_file",
    "upstream_source",
    "reuse_terms",
    "reviewed_by",
    "reviewed_at",
    "review_rationale",
    "evidence_inspected",
    "promoted_to",
    # The document the selection was cut from. `source_*` above describes the
    # tabular file the importer was handed; these describe the upstream
    # archive it was derived from, and both are kept (D022).
    "original_reference",
    "original_hash",
    "original_member",
    "original_row_locator",
    # Set only on a deposit_candidate row found through collect_candidates:
    # which anchor the sender transferred to, and that anchor's entity. Never
    # the row's own entity_name/entity_type -- see SourceDocument.anchor_address.
    "anchor_address",
    "anchor_entity_name",
]

MANIFEST_COLUMNS = [
    "sha256",
    "original_filename",
    "preserved_as",
    "url",
    "disclosure_kind",
    "disclosure_date",
    "retrieved_at",
    "upstream_source",
    "reuse_terms",
    "rows_accepted",
    "rows_rejected",
    "original_reference",
    "original_hash",
    "original_member",
]


class AnchorImportError(ValueError):
    """The document cannot be imported at all. Raised before anything is written."""


class Destination(StrEnum):
    verified_anchors = "verified_anchors"
    deposit_candidates = "deposit_candidates"
    independent_review = "independent_review"


class DisclosureKind(StrEnum):
    proof_of_reserves = "proof_of_reserves"
    signed_address_verification = "signed_address_verification"
    aggregator_tagpack = "aggregator_tagpack"
    authorized_observation = "authorized_observation"
    #: Stage 2C: a sender discovered by directly querying an already-accepted
    #: anchor's own incoming history. Behavioural, not documentary -- it
    #: establishes that a transfer happened, never who controls the sender.
    chain_observation = "chain_observation"


#: Roles each kind of document can support. ``None`` means "whatever the
#: document states", which only a service's own signed verification earns.
SUPPORTED_ROLES: dict[DisclosureKind, frozenset[AddressRole] | None] = {
    DisclosureKind.proof_of_reserves: frozenset({AddressRole.cold_reserve, AddressRole.unknown}),
    DisclosureKind.signed_address_verification: None,
    DisclosureKind.aggregator_tagpack: None,
    DisclosureKind.authorized_observation: frozenset({AddressRole.deposit, AddressRole.unknown}),
    DisclosureKind.chain_observation: frozenset({AddressRole.unknown}),
}

#: Kinds that can never produce a verified anchor, and why.
LEAD_ONLY: dict[DisclosureKind, str] = {
    DisclosureKind.aggregator_tagpack: (
        "an aggregator repeats a source; follow the original before trusting it"
    ),
    DisclosureKind.authorized_observation: (
        "an authorized observation is evaluation material, not a tracing anchor"
    ),
    DisclosureKind.chain_observation: (
        "a sender to an anchor is a behavioural lead, not a claim of who controls it"
    ),
}


@dataclass(frozen=True)
class SourceDocument:
    """One downloaded file and everything known about where it came from."""

    path: Path
    url: str
    disclosure_kind: DisclosureKind
    disclosure_date: dt.datetime | None
    retrieved_at: dt.datetime
    methodology: str
    label_set_version: str
    reviewer: str | None = None
    upstream_source: str | None = None
    reuse_terms: str | None = None
    #: The archive or document this file was cut from, when the importer was
    #: handed a derived selection rather than the publication itself. A bulk
    #: disclosure cannot be fed to the importer directly, so the linkage back
    #: to it has to be recorded rather than described in prose (D022).
    original_file: Path | None = None
    original_member: str | None = None
    original_row_locator: str | None = None
    #: Set only for a ``chain_observation`` document: the already-accepted
    #: anchor a candidate sender was found through. Kept separate from
    #: ``entity_name``/``entity_type`` (a claim about the row's own address)
    #: so a candidate row can never be read as an ownership claim for this
    #: entity -- it names who the money went *to*, not who the sender is.
    anchor_address: str | None = None
    anchor_entity_name: str | None = None

    def validate(self) -> None:
        if not (self.url or "").strip():
            raise AnchorImportError("missing_source_reference: the document needs a URL or locator")
        if self.disclosure_date is None:
            raise AnchorImportError(
                "missing_disclosure_date: an undated claim cannot be dated later"
            )
        if not (self.methodology or "").strip():
            raise AnchorImportError(
                "missing_methodology: record how the rows were selected from the file"
            )
        if self.disclosure_kind is DisclosureKind.aggregator_tagpack:
            if not (self.reuse_terms or "").strip():
                raise AnchorImportError(
                    "missing reuse_terms: check what the collection permits before copying it"
                )
            if not (self.upstream_source or "").strip():
                raise AnchorImportError(
                    "missing_upstream_source: an aggregator row needs the source it copied"
                )
        if not self.path.is_file():
            raise AnchorImportError(f"source file not found: {self.path}")
        if self.original_file is not None:
            if not self.original_file.is_file():
                raise AnchorImportError(f"original_source_not_found: {self.original_file}")
            if not (self.original_member or "").strip():
                raise AnchorImportError(
                    "missing_original_member: name the file inside the archive the row "
                    "came from, or the linkage cannot be checked"
                )
            if not (self.original_row_locator or "").strip():
                raise AnchorImportError(
                    "missing_original_row_locator: record where in that file the row is"
                )
        elif self.original_member or self.original_row_locator:
            raise AnchorImportError(
                "original_source_unlinked: a member or locator was given without the "
                "original file they refer to"
            )

    def sha256(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def original_sha256(self) -> str | None:
        if self.original_file is None:
            return None
        return hashlib.sha256(self.original_file.read_bytes()).hexdigest()

    def original_display_path(self, data_dir: Path) -> str | None:
        """Stored relative to the data directory's parent where possible.

        A bulk archive is never copied into ``sources/`` — it is too large and
        it is the thing being preserved in place — so the row records where it
        is, and review re-hashes it there.
        """
        if self.original_file is None:
            return None
        resolved = self.original_file.resolve()
        root = data_dir.resolve().parent
        try:
            return str(resolved.relative_to(root))
        except ValueError:
            return str(resolved)

    @property
    def source_key(self) -> str:
        """What counts as one source for corroboration: the original, not the copy."""
        return (self.upstream_source or self.url).strip()


@dataclass(frozen=True)
class ImportedRow:
    network_key: str
    address: str
    entity_name: str
    entity_type: str
    assertion_type: AssertionType
    address_role: AddressRole
    destination: Destination
    review_state: str
    source_hash: str
    source_url: str
    upstream_source: str | None

    def to_csv_row(
        self, document: SourceDocument, preserved_name: str, data_dir: Path
    ) -> dict[str, str]:
        return {
            "network": self.network_key,
            "address": self.address,
            "entity_name": self.entity_name,
            "entity_type": self.entity_type,
            "assertion_type": self.assertion_type.value,
            "address_role": self.address_role.value,
            "review_state": self.review_state,
            "source_reference": self.source_url,
            "retrieval_date": document.retrieved_at.isoformat(),
            "methodology": document.methodology,
            "reviewer": document.reviewer or "",
            "valid_from": (
                document.disclosure_date.isoformat() if document.disclosure_date else ""
            ),
            "valid_to": "",
            "last_verified_at": "",
            "label_set_version": document.label_set_version,
            "disclosure_kind": document.disclosure_kind.value,
            "source_hash": self.source_hash,
            "source_file": preserved_name,
            "upstream_source": self.upstream_source or "",
            "reuse_terms": document.reuse_terms or "",
            "reviewed_by": "",
            "reviewed_at": "",
            "review_rationale": "",
            "evidence_inspected": "",
            "promoted_to": "",
            "original_reference": document.original_display_path(data_dir) or "",
            "original_hash": document.original_sha256() or "",
            "original_member": (document.original_member or "").strip(),
            "original_row_locator": (document.original_row_locator or "").strip(),
            "anchor_address": document.anchor_address or "",
            "anchor_entity_name": document.anchor_entity_name or "",
        }


@dataclass(frozen=True)
class Rejection:
    line: int
    code: str
    message: str
    address: str | None = None


@dataclass(frozen=True)
class Downgrade:
    line: int
    code: str
    message: str
    address: str
    to: Destination


@dataclass(frozen=True)
class Corroboration:
    """How many genuinely distinct sources name one address."""

    distinct_sources: int
    documents: int
    note: str


@dataclass
class ImportReport:
    document_hash: str
    accepted: list[ImportedRow] = field(default_factory=list)
    #: Rows already present that this run updated in place rather than
    #: duplicating: same address, same source document, added provenance.
    updated: list[str] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)
    downgrades: list[Downgrade] = field(default_factory=list)
    corroboration: dict[tuple[str, str], Corroboration] = field(default_factory=dict)
    written: bool = False

    @property
    def counts(self) -> dict[Destination, int]:
        counts = {destination: 0 for destination in Destination}
        for row in self.accepted:
            counts[row.destination] += 1
        return counts

    def summary(self) -> str:
        parts = [f"{d.value}: {n}" for d, n in self.counts.items()]
        if self.updated:
            parts.append(f"updated: {len(self.updated)}")
        parts.append(f"rejected: {len(self.rejections)}")
        parts.append(f"downgraded: {len(self.downgrades)}")
        return "  ".join(parts)


def _route(kind: DisclosureKind, assertion_type: AssertionType) -> tuple[Destination, str | None]:
    """Where the row goes, and the downgrade reason if it was not its first choice."""
    # A behavioural candidate is a candidate whatever document carried it: the
    # candidate set is already the set that is shown and never trusted, and
    # LEAD_ONLY exists to keep an ownership claim out of the anchors.
    if assertion_type is AssertionType.deposit_candidate:
        return Destination.deposit_candidates, None
    if kind in LEAD_ONLY:
        return Destination.independent_review, LEAD_ONLY[kind]
    if assertion_type is AssertionType.service_control:
        return Destination.verified_anchors, None
    return Destination.independent_review, None


def import_anchors(
    document: SourceDocument,
    *,
    network_key: str,
    out_dir: Path,
    write: bool = False,
) -> ImportReport:
    """Read ``document`` and route each row. ``write=False`` changes nothing on disk."""
    document.validate()
    digest = document.sha256()
    report = ImportReport(document_hash=digest)

    with document.path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        missing = SOURCE_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise AnchorImportError(f"{document.path.name} is missing columns: {sorted(missing)}")
        rows = list(enumerate(reader, start=2))

    for line, raw in rows:
        address = (raw.get("address") or "").strip()
        row_network = (raw.get("network") or "").strip()
        if not row_network:
            report.rejections.append(
                Rejection(
                    line,
                    "network_not_stated",
                    "the row does not say which network it is on; syntax does not decide it",
                    address or None,
                )
            )
            continue
        if row_network != network_key:
            report.rejections.append(
                Rejection(
                    line,
                    "network_mismatch",
                    f"row is on {row_network}, this import is for {network_key}",
                    address or None,
                )
            )
            continue
        if not address:
            report.rejections.append(Rejection(line, "missing_address", "empty address"))
            continue

        try:
            assertion_type = AssertionType((raw.get("assertion_type") or "").strip())
            address_role = AddressRole((raw.get("address_role") or "").strip())
        except ValueError as exc:
            report.rejections.append(Rejection(line, "unreadable_row", str(exc), address))
            continue

        entity_name = (raw.get("entity_name") or "").strip()
        if not entity_name:
            report.rejections.append(
                Rejection(line, "missing_entity", "a claim needs the entity it is about", address)
            )
            continue

        allowed = SUPPORTED_ROLES[document.disclosure_kind]
        if allowed is not None and address_role not in allowed:
            report.rejections.append(
                Rejection(
                    line,
                    "role_not_supported_by_source",
                    (
                        f"a {document.disclosure_kind.value} does not establish the "
                        f"{address_role.value} role; it supports "
                        f"{sorted(r.value for r in allowed)}"
                    ),
                    address,
                )
            )
            continue

        destination, downgrade_reason = _route(document.disclosure_kind, assertion_type)
        if downgrade_reason is not None and assertion_type is AssertionType.service_control:
            report.downgrades.append(
                Downgrade(
                    line,
                    code=(
                        "aggregator_cannot_verify"
                        if document.disclosure_kind is DisclosureKind.aggregator_tagpack
                        else "observation_is_not_an_anchor"
                    ),
                    message=downgrade_reason,
                    address=address,
                    to=destination,
                )
            )

        report.accepted.append(
            ImportedRow(
                network_key=row_network,
                address=address,
                entity_name=entity_name,
                entity_type=(raw.get("entity_type") or "unknown").strip(),
                assertion_type=assertion_type,
                address_role=address_role,
                destination=destination,
                # Never accepted by an importer. A human opens the source first.
                review_state="unreviewed",
                source_hash=digest,
                source_url=document.url,
                upstream_source=document.upstream_source,
            )
        )

    preserved_name = f"{digest[:16]}-{document.path.name}"
    if write:
        _write(report, document, out_dir, preserved_name)
        report.written = True

    report.corroboration = _corroboration(report, document, out_dir)
    return report


def _write(
    report: ImportReport, document: SourceDocument, out_dir: Path, preserved_name: str
) -> None:
    sources_dir = out_dir / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(document.path, sources_dir / preserved_name)

    by_destination: dict[Destination, list[ImportedRow]] = defaultdict(list)
    for row in report.accepted:
        by_destination[row.destination].append(row)

    for destination, rows in by_destination.items():
        path = out_dir / f"{destination.value}.csv"
        existing = _read_existing(path)
        index = {
            (r["address"], r["source_hash"], r["source_reference"]): i
            for i, r in enumerate(existing)
        }
        new: list[dict[str, str]] = []
        touched = False
        for row in rows:
            candidate = row.to_csv_row(document, preserved_name, out_dir)
            key = (row.address, row.source_hash, row.source_url)
            position = index.get(key)
            if position is None:
                new.append(candidate)
                continue
            # Re-importing the same row from the same document is not a second
            # claim. Fill in provenance the first import lacked, and never
            # touch a review decision: an importer does not un-review anything.
            current = existing[position]
            changed = False
            for column in (
                "original_reference",
                "original_hash",
                "original_member",
                "original_row_locator",
                "anchor_address",
                "anchor_entity_name",
            ):
                if candidate[column] and current.get(column, "") != candidate[column]:
                    current[column] = candidate[column]
                    changed = True
            if changed:
                touched = True
                report.updated.append(row.address)

        if touched:
            _rewrite(path, existing + new)
            continue
        if not new and path.exists():
            continue
        with path.open("a", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=OUTPUT_COLUMNS)
            if not existing and fh.tell() == 0:
                writer.writeheader()
            writer.writerows(new)

    manifest = out_dir / "sources" / "manifest.csv"
    exists = manifest.exists()
    with manifest.open("a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=MANIFEST_COLUMNS)
        if not exists:
            writer.writeheader()
        writer.writerow(
            {
                "sha256": report.document_hash,
                "original_filename": document.path.name,
                "preserved_as": preserved_name,
                "url": document.url,
                "disclosure_kind": document.disclosure_kind.value,
                "disclosure_date": (
                    document.disclosure_date.isoformat() if document.disclosure_date else ""
                ),
                "retrieved_at": document.retrieved_at.isoformat(),
                "upstream_source": document.upstream_source or "",
                "reuse_terms": document.reuse_terms or "",
                "rows_accepted": len(report.accepted),
                "rows_rejected": len(report.rejections),
                "original_reference": document.original_display_path(out_dir) or "",
                "original_hash": document.original_sha256() or "",
                "original_member": (document.original_member or "").strip(),
            }
        )


def _rewrite(path: Path, rows: list[dict[str, str]]) -> None:
    """Rewrite a set in place. Used only to fill in provenance columns."""
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in OUTPUT_COLUMNS})


def _read_existing(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def _corroboration(
    report: ImportReport, document: SourceDocument, out_dir: Path
) -> dict[tuple[str, str], Corroboration]:
    """Count distinct upstream sources per address, across every set written so far.

    Two aggregators copying one disclosure are one source. Counting documents
    instead would manufacture agreement out of a single claim.
    """
    sources: dict[tuple[str, str], set[str]] = defaultdict(set)
    documents: dict[tuple[str, str], set[str]] = defaultdict(set)

    for destination in Destination:
        for existing in _read_existing(out_dir / f"{destination.value}.csv"):
            key = (existing["network"], existing["address"])
            sources[key].add(existing.get("upstream_source") or existing["source_reference"])
            documents[key].add(f"{existing['source_hash']}@{existing['source_reference']}")

    for row in report.accepted:
        key = (row.network_key, row.address)
        sources[key].add(document.source_key)
        documents[key].add(f"{row.source_hash}@{row.source_url}")

    out: dict[tuple[str, str], Corroboration] = {}
    for key, source_set in sources.items():
        document_count = len(documents[key])
        note = f"{document_count} documents trace back to {len(source_set)} source(s)"
        if document_count > len(source_set):
            note += "; copies of one source are not independent corroboration"
        out[key] = Corroboration(
            distinct_sources=len(source_set), documents=document_count, note=note
        )
    return out
