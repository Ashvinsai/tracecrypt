"""Linkage from an imported row back to the publication it was cut from.

A bulk disclosure — a 38 MB archive holding a 74 MB CSV — cannot be handed to
the importer, which needs a small tabular file. So a human selects the rows and
imports the selection, and without linkage the recorded `source_hash` is the
hash of that derived selection: a file the publisher never issued.

These tests cover the linkage as a checked field rather than a sentence in the
methodology, and cover review refusing to accept a claim whose upstream
document has gone missing or changed underneath it.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
from pathlib import Path

import pytest

from app.services.anchor_import import (
    AnchorImportError,
    Destination,
    DisclosureKind,
    SourceDocument,
    import_anchors,
)
from app.services.candidate_review import ReviewAction, ReviewRequest, review_candidates
from app.services.labels import LabelRegistry

DISCLOSED = dt.datetime(2026, 8, 11, tzinfo=dt.UTC)
RETRIEVED = dt.datetime(2026, 9, 20, tzinfo=dt.UTC)
URL = "https://www.okx.com/proof-of-reserves/download"
ADDRESS = "TLaGjwhvA8XQYSxFAcAXy7Dvuue9eGYitv"
MEMBER = "okx_por_2026081100_V6.csv"
LOCATOR = "member=okx_por_2026081100_V6.csv;absolute_line=44282;section_row=44257"

COLUMNS = "network,address,entity_name,entity_type,assertion_type,address_role\n"


def selection(tmp_path: Path, name: str = "selection.csv") -> Path:
    path = tmp_path / name
    path.write_text(COLUMNS + f"tron,{ADDRESS},OKX,exchange,service_control,unknown\n")
    return path


def archive(tmp_path: Path, content: bytes = b"pretend zip bytes") -> Path:
    path = tmp_path / "por_csv_2026081100_V6.zip"
    path.write_bytes(content)
    return path


def document(tmp_path: Path, **overrides) -> SourceDocument:
    kwargs = {
        "path": selection(tmp_path),
        "url": URL,
        "disclosure_kind": DisclosureKind.proof_of_reserves,
        "disclosure_date": DISCLOSED,
        "retrieved_at": RETRIEVED,
        "methodology": "One TRON row selected from the dated reserve file.",
        "label_set_version": "okx-por-2026081100-V6",
        "original_file": archive(tmp_path),
        "original_member": MEMBER,
        "original_row_locator": LOCATOR,
    }
    kwargs.update(overrides)
    return SourceDocument(**kwargs)


def rows_of(data_dir: Path) -> list[dict[str, str]]:
    with (data_dir / f"{Destination.verified_anchors.value}.csv").open(newline="") as fh:
        return list(csv.DictReader(fh))


def accept_request(**overrides) -> ReviewRequest:
    kwargs = {
        "network_key": "tron",
        "address": ADDRESS,
        "action": ReviewAction.accept,
        "reviewer": "investigator-1",
        "rationale": "Opened the disclosure and checked the row.",
        "evidence_inspected": (URL,),
    }
    kwargs.update(overrides)
    return ReviewRequest(**kwargs)


# --- recording --------------------------------------------------------------


def test_both_hashes_are_recorded_and_neither_replaces_the_other(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    doc = document(tmp_path)

    import_anchors(doc, network_key="tron", out_dir=data_dir, write=True)

    (row,) = rows_of(data_dir)
    selection_hash = hashlib.sha256(doc.path.read_bytes()).hexdigest()
    original_hash = hashlib.sha256(doc.original_file.read_bytes()).hexdigest()

    assert row["source_hash"] == selection_hash
    assert row["source_file"].endswith("selection.csv")
    assert row["original_hash"] == original_hash
    assert row["original_reference"].endswith("por_csv_2026081100_V6.zip")
    assert row["original_member"] == MEMBER
    assert row["original_row_locator"] == LOCATOR
    # The two are different files and the row says so.
    assert row["source_hash"] != row["original_hash"]


def test_the_archive_is_not_copied_into_sources(tmp_path: Path) -> None:
    """A bulk publication is preserved where it is, not duplicated per import."""
    data_dir = tmp_path / "data"

    import_anchors(document(tmp_path), network_key="tron", out_dir=data_dir, write=True)

    preserved = list((data_dir / "sources").glob("*"))
    names = {p.name for p in preserved}
    assert any(name.endswith("selection.csv") for name in names)
    assert not any(name.endswith(".zip") for name in names)


def test_a_partial_linkage_is_refused(tmp_path: Path) -> None:
    with pytest.raises(AnchorImportError, match="missing_original_member"):
        import_anchors(
            document(tmp_path, original_member=None),
            network_key="tron",
            out_dir=tmp_path / "data",
        )

    with pytest.raises(AnchorImportError, match="missing_original_row_locator"):
        import_anchors(
            document(tmp_path, original_row_locator=""),
            network_key="tron",
            out_dir=tmp_path / "data",
        )

    with pytest.raises(AnchorImportError, match="original_source_unlinked"):
        import_anchors(
            document(tmp_path, original_file=None),
            network_key="tron",
            out_dir=tmp_path / "data",
        )


def test_a_missing_archive_refuses_the_import(tmp_path: Path) -> None:
    with pytest.raises(AnchorImportError, match="original_source_not_found"):
        import_anchors(
            document(tmp_path, original_file=tmp_path / "gone.zip"),
            network_key="tron",
            out_dir=tmp_path / "data",
        )


def test_a_claim_without_any_upstream_document_still_imports(tmp_path: Path) -> None:
    """Not every document is a selection; the linkage columns stay empty."""
    data_dir = tmp_path / "data"

    import_anchors(
        document(tmp_path, original_file=None, original_member=None, original_row_locator=None),
        network_key="tron",
        out_dir=data_dir,
        write=True,
    )

    (row,) = rows_of(data_dir)
    assert row["original_reference"] == ""
    assert row["original_hash"] == ""


# --- updating in place ------------------------------------------------------


def test_re_importing_with_provenance_updates_the_row_without_duplicating_it(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    bare = document(tmp_path, original_file=None, original_member=None, original_row_locator=None)
    import_anchors(bare, network_key="tron", out_dir=data_dir, write=True)
    assert rows_of(data_dir)[0]["original_hash"] == ""

    report = import_anchors(document(tmp_path), network_key="tron", out_dir=data_dir, write=True)

    rows = rows_of(data_dir)
    assert len(rows) == 1, "the same claim from the same document is not a second claim"
    assert rows[0]["original_member"] == MEMBER
    assert report.updated == [ADDRESS]
    assert report.counts[Destination.verified_anchors] == 1


def test_updating_provenance_never_changes_a_review_decision(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    import_anchors(document(tmp_path), network_key="tron", out_dir=data_dir, write=True)
    review_candidates(data_dir, [accept_request()], write=True)
    assert rows_of(data_dir)[0]["review_state"] == "accepted"

    import_anchors(document(tmp_path), network_key="tron", out_dir=data_dir, write=True)

    row = rows_of(data_dir)[0]
    assert row["review_state"] == "accepted"
    assert row["reviewed_by"] == "investigator-1"


# --- review checks both files ----------------------------------------------


def test_acceptance_verifies_the_archive_too(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    import_anchors(document(tmp_path), network_key="tron", out_dir=data_dir, write=True)

    report = review_candidates(data_dir, [accept_request()], write=True)

    assert not report.refusals
    assert rows_of(data_dir)[0]["review_state"] == "accepted"


def test_a_missing_archive_prevents_acceptance(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    doc = document(tmp_path)
    import_anchors(doc, network_key="tron", out_dir=data_dir, write=True)
    doc.original_file.unlink()

    report = review_candidates(data_dir, [accept_request()], write=True)

    (refusal,) = report.refusals
    assert refusal.code == "original_source_missing"
    assert rows_of(data_dir)[0]["review_state"] == "unreviewed"


def test_a_changed_archive_prevents_acceptance(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    doc = document(tmp_path)
    import_anchors(doc, network_key="tron", out_dir=data_dir, write=True)
    doc.original_file.write_bytes(b"pretend zip bytes, edited")

    report = review_candidates(data_dir, [accept_request()], write=True)

    (refusal,) = report.refusals
    assert refusal.code == "original_source_changed"
    assert rows_of(data_dir)[0]["review_state"] == "unreviewed"


def test_a_row_whose_linkage_was_hand_edited_to_be_partial_cannot_be_accepted(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    import_anchors(document(tmp_path), network_key="tron", out_dir=data_dir, write=True)
    path = data_dir / f"{Destination.verified_anchors.value}.csv"
    rows = rows_of(data_dir)
    fields = list(rows[0])
    rows[0]["original_hash"] = ""
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    report = review_candidates(data_dir, [accept_request()], write=True)

    (refusal,) = report.refusals
    assert refusal.code == "original_source_unlinked"


# --- the linkage reaches the evidence a report saves ------------------------


def test_the_linkage_reaches_the_label_evidence(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    doc = document(tmp_path)
    import_anchors(doc, network_key="tron", out_dir=data_dir, write=True)
    review_candidates(data_dir, [accept_request()], write=True)

    registry = LabelRegistry.from_reviewed_sets(data_dir)
    (anchor,) = registry.lookup("tron", ADDRESS)
    evidence = anchor.to_evidence().to_json()

    assert evidence["original_member"] == MEMBER
    assert evidence["original_row_locator"] == LOCATOR
    assert evidence["original_hash"] == hashlib.sha256(doc.original_file.read_bytes()).hexdigest()
    assert evidence["source_hash"] != evidence["original_hash"]
