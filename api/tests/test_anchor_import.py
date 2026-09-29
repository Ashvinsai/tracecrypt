"""Anchor import: what a source is allowed to establish.

Stage 2 section A and B. The failure mode being designed against is a row that
arrives from an aggregator, or from a reserve file that says nothing about
deposit addresses, and ends up in the set the tracer treats as verified.
"""

from __future__ import annotations

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
from app.services.labels import LabelRegistry

DISCLOSED = dt.datetime(2026, 6, 30, tzinfo=dt.UTC)
RETRIEVED = dt.datetime(2026, 9, 20, tzinfo=dt.UTC)

COLUMNS = "network,address,entity_name,entity_type,assertion_type,address_role\n"
COLD_ADDRESS = "TColdReserveOneXXXXXXXXXXXXXXXXXXX"
DEPOSIT_ADDRESS = "TDepositOneXXXXXXXXXXXXXXXXXXXXXXX"
EXCHANGE = "Example Exchange,exchange,service_control"
COLD = f"tron,{COLD_ADDRESS},{EXCHANGE},cold_reserve\n"
DEPOSIT = f"tron,{DEPOSIT_ADDRESS},{EXCHANGE},deposit\n"


def write_source(tmp_path: Path, body: str, name: str = "por.csv") -> Path:
    path = tmp_path / name
    path.write_text(COLUMNS + body)
    return path


def por_document(path: Path, **overrides) -> SourceDocument:
    kwargs = {
        "path": path,
        "url": "https://www.okx.com/proof-of-reserves/download",
        "disclosure_kind": DisclosureKind.proof_of_reserves,
        "disclosure_date": DISCLOSED,
        "retrieved_at": RETRIEVED,
        "methodology": "Downloaded the dated reserve file and read the TRON rows.",
        "reviewer": "test",
        "label_set_version": "test-1",
    }
    kwargs.update(overrides)
    return SourceDocument(**kwargs)


def test_a_reserve_row_becomes_a_verified_anchor_with_its_hash(tmp_path: Path) -> None:
    source = write_source(tmp_path, COLD)
    out = tmp_path / "out"

    report = import_anchors(por_document(source), network_key="tron", out_dir=out, write=True)

    assert report.counts[Destination.verified_anchors] == 1
    assert not report.rejections
    (row,) = report.accepted
    assert row.destination is Destination.verified_anchors
    assert row.source_hash == hashlib.sha256(source.read_bytes()).hexdigest()
    # The original file is preserved next to the rows that came out of it.
    preserved = out / "sources" / f"{row.source_hash[:16]}-por.csv"
    assert preserved.read_bytes() == source.read_bytes()


def test_a_reserve_file_cannot_establish_a_deposit_address(tmp_path: Path) -> None:
    """A dated ownership claim is not a claim about customer deposit addresses."""
    source = write_source(tmp_path, DEPOSIT)

    report = import_anchors(por_document(source), network_key="tron", out_dir=tmp_path / "out")

    assert report.counts[Destination.verified_anchors] == 0
    (rejection,) = report.rejections
    assert rejection.code == "role_not_supported_by_source"
    assert "deposit" in rejection.message


def test_an_aggregator_row_is_a_lead_and_never_verified(tmp_path: Path) -> None:
    source = write_source(tmp_path, COLD, name="tagpack.csv")
    document = por_document(
        source,
        disclosure_kind=DisclosureKind.aggregator_tagpack,
        url="https://github.com/graphsense/graphsense-tagpacks",
        upstream_source="https://www.okx.com/proof-of-reserves",
        reuse_terms="CC-BY-4.0",
    )

    report = import_anchors(document, network_key="tron", out_dir=tmp_path / "out")

    assert report.counts[Destination.verified_anchors] == 0
    (row,) = report.accepted
    assert row.destination is Destination.independent_review
    assert row.review_state == "unreviewed"
    assert any(d.code == "aggregator_cannot_verify" for d in report.downgrades)


def test_two_aggregators_repeating_one_source_are_one_source(tmp_path: Path) -> None:
    upstream = "https://www.okx.com/proof-of-reserves"
    documents = [
        por_document(
            write_source(tmp_path, COLD, name=f"agg{i}.csv"),
            disclosure_kind=DisclosureKind.aggregator_tagpack,
            url=f"https://aggregator{i}.example.test/tags",
            upstream_source=upstream,
            reuse_terms="CC-BY-4.0",
        )
        for i in (1, 2)
    ]

    out = tmp_path / "out"
    reports = [import_anchors(d, network_key="tron", out_dir=out, write=True) for d in documents]

    corroboration = reports[-1].corroboration[("tron", COLD_ADDRESS)]
    assert corroboration.distinct_sources == 1
    assert corroboration.documents == 2
    assert "not independent" in corroboration.note


def test_a_signed_verification_supports_the_role_it_states(tmp_path: Path) -> None:
    source = write_source(tmp_path, DEPOSIT, name="signed.csv")
    document = por_document(
        source,
        disclosure_kind=DisclosureKind.signed_address_verification,
        url="https://www.okx.com/proof-of-reserves",
    )

    report = import_anchors(document, network_key="tron", out_dir=tmp_path / "out")

    assert report.counts[Destination.verified_anchors] == 1
    assert not report.rejections


def test_an_authorized_observation_is_evaluation_material_not_an_anchor(tmp_path: Path) -> None:
    source = write_source(tmp_path, DEPOSIT, name="observed.csv")
    document = por_document(
        source,
        disclosure_kind=DisclosureKind.authorized_observation,
        url="local note: deposit address shown to its own account holder, with consent",
    )

    report = import_anchors(document, network_key="tron", out_dir=tmp_path / "out")

    (row,) = report.accepted
    assert row.destination is Destination.independent_review
    assert report.counts[Destination.verified_anchors] == 0


def test_a_row_on_another_network_is_rejected_not_assumed(tmp_path: Path) -> None:
    source = write_source(
        tmp_path,
        f"ethereum,0x{'1' * 40},{EXCHANGE},cold_reserve\n"
        f",TNoNetworkXXXXXXXXXXXXXXXXXXXXXXXXX,{EXCHANGE},cold_reserve\n",
    )

    report = import_anchors(por_document(source), network_key="tron", out_dir=tmp_path / "out")

    assert report.counts[Destination.verified_anchors] == 0
    assert {r.code for r in report.rejections} == {"network_mismatch", "network_not_stated"}


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("url", "", "missing_source_reference"),
        ("disclosure_date", None, "missing_disclosure_date"),
        ("methodology", "  ", "missing_methodology"),
    ],
)
def test_provenance_is_required_before_anything_is_imported(
    tmp_path: Path, field: str, value: object, expected: str
) -> None:
    source = write_source(tmp_path, COLD)

    with pytest.raises(AnchorImportError, match=expected):
        import_anchors(
            por_document(source, **{field: value}), network_key="tron", out_dir=tmp_path / "out"
        )


def test_aggregator_rows_require_reuse_terms(tmp_path: Path) -> None:
    source = write_source(tmp_path, COLD)
    document = por_document(
        source,
        disclosure_kind=DisclosureKind.aggregator_tagpack,
        upstream_source="https://example.test/upstream",
        reuse_terms=None,
    )

    with pytest.raises(AnchorImportError, match="reuse_terms"):
        import_anchors(document, network_key="tron", out_dir=tmp_path / "out")


def test_the_three_sets_are_written_to_three_separate_files(tmp_path: Path) -> None:
    out = tmp_path / "out"
    import_anchors(
        por_document(write_source(tmp_path, COLD)), network_key="tron", out_dir=out, write=True
    )
    import_anchors(
        por_document(
            write_source(tmp_path, DEPOSIT, name="agg.csv"),
            disclosure_kind=DisclosureKind.aggregator_tagpack,
            upstream_source="https://example.test/upstream",
            reuse_terms="CC-BY-4.0",
        ),
        network_key="tron",
        out_dir=out,
        write=True,
    )

    verified = (out / "verified_anchors.csv").read_text()
    review = (out / "independent_review.csv").read_text()
    assert "TColdReserveOne" in verified
    assert "TDepositOne" not in verified
    assert "TDepositOne" in review
    # Untouched: the importer never writes into the tracer's own anchor file.
    assert not (out / "anchors.csv").exists()


def test_the_verified_file_is_loadable_by_the_tracer_registry(tmp_path: Path) -> None:
    out = tmp_path / "out"
    import_anchors(
        por_document(write_source(tmp_path, COLD)), network_key="tron", out_dir=out, write=True
    )

    registry = LabelRegistry.from_csv(out / "verified_anchors.csv")
    anchors = registry.lookup("tron", COLD_ADDRESS)

    assert len(anchors) == 1
    # Imported, not reviewed. A human accepts it; an importer does not.
    assert anchors[0].review_state.value == "unreviewed"
    assert anchors[0].can_terminate_trace(RETRIEVED) is False


def test_a_behavioural_candidate_lands_in_the_candidate_set(tmp_path: Path) -> None:
    """Whatever document carried it. It is shown there, and never trusted there."""
    body = f"tron,{DEPOSIT_ADDRESS},Example Exchange,exchange,deposit_candidate,deposit\n"
    source = write_source(tmp_path, body, name="sweeps.csv")
    document = por_document(
        source,
        disclosure_kind=DisclosureKind.authorized_observation,
        url="local: forwarding behaviour observed in the recorded window",
    )

    report = import_anchors(document, network_key="tron", out_dir=tmp_path / "out", write=True)

    (row,) = report.accepted
    assert row.destination is Destination.deposit_candidates
    assert report.counts[Destination.verified_anchors] == 0
    assert not report.downgrades
