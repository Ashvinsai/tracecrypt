"""Candidate review: the step where a human, not an importer, accepts a claim.

Stage 2's gate is that the team can open the exact source behind each anchor.
These tests are that gate stated as code: a decision that cannot name the source
it rests on does not get made, and behaviour never becomes provenance.
"""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

import pytest

from app.services.anchor_import import (
    Destination,
    DisclosureKind,
    SourceDocument,
    import_anchors,
)
from app.services.candidate_review import (
    ReviewAction,
    ReviewRequest,
    load_review_queue,
    review_candidates,
)
from app.services.labels import LabelRegistry

DISCLOSED = dt.datetime(2026, 6, 30, tzinfo=dt.UTC)
RETRIEVED = dt.datetime(2026, 9, 20, tzinfo=dt.UTC)
DECIDED = dt.datetime(2026, 9, 21, 9, 0, tzinfo=dt.UTC)

POR_URL = "https://www.okx.com/proof-of-reserves/download"
TAGPACK_URL = "https://github.com/graphsense/graphsense-tagpacks"

COLUMNS = "network,address,entity_name,entity_type,assertion_type,address_role\n"
COLD_ADDRESS = "TColdReserveOneXXXXXXXXXXXXXXXXXXX"
SWEEPER_ADDRESS = "TSweeperOneXXXXXXXXXXXXXXXXXXXXXXX"
LEAD_ADDRESS = "TLeadOneXXXXXXXXXXXXXXXXXXXXXXXXXX"
OTHER_ADDRESS = "TUntouchedOneXXXXXXXXXXXXXXXXXXXXX"


def build_sets(tmp_path: Path) -> Path:
    """A data directory with one anchor, one lead, one behavioural candidate."""
    out = tmp_path / "data"

    por = tmp_path / "por.csv"
    por.write_text(
        COLUMNS
        + f"tron,{COLD_ADDRESS},Example Exchange,exchange,service_control,cold_reserve\n"
        + f"tron,{OTHER_ADDRESS},Example Exchange,exchange,service_control,cold_reserve\n"
    )
    import_anchors(
        SourceDocument(
            path=por,
            url=POR_URL,
            disclosure_kind=DisclosureKind.proof_of_reserves,
            disclosure_date=DISCLOSED,
            retrieved_at=RETRIEVED,
            methodology="Read the TRON rows from the dated reserve file.",
            label_set_version="okx-por-2026-06",
        ),
        network_key="tron",
        out_dir=out,
        write=True,
    )

    tagpack = tmp_path / "tagpack.csv"
    tagpack.write_text(
        COLUMNS + f"tron,{LEAD_ADDRESS},Example Exchange,exchange,service_control,hot_wallet\n"
    )
    import_anchors(
        SourceDocument(
            path=tagpack,
            url=TAGPACK_URL,
            disclosure_kind=DisclosureKind.aggregator_tagpack,
            disclosure_date=DISCLOSED,
            retrieved_at=RETRIEVED,
            methodology="Followed the collection's TRON entries.",
            label_set_version="tagpack-2026-09",
            upstream_source="https://www.okx.com/proof-of-reserves",
            reuse_terms="CC-BY-4.0",
        ),
        network_key="tron",
        out_dir=out,
        write=True,
    )

    sweeps = tmp_path / "sweeps.csv"
    sweeps.write_text(
        COLUMNS + f"tron,{SWEEPER_ADDRESS},Example Exchange,exchange,deposit_candidate,deposit\n"
    )
    import_anchors(
        SourceDocument(
            path=sweeps,
            url="local: forwarding behaviour observed in the recorded window",
            disclosure_kind=DisclosureKind.authorized_observation,
            disclosure_date=DISCLOSED,
            retrieved_at=RETRIEVED,
            methodology="Sweep behaviour in a capped window. Behaviour, not a source.",
            label_set_version="candidates-2026-09",
        ),
        network_key="tron",
        out_dir=out,
        write=True,
    )
    return out


def request(address: str, **overrides) -> ReviewRequest:
    kwargs = {
        "network_key": "tron",
        "address": address,
        "action": ReviewAction.accept,
        "reviewer": "investigator-1",
        "rationale": "Opened the disclosure and found the address on the dated list.",
        "evidence_inspected": (POR_URL,),
        "decided_at": DECIDED,
    }
    kwargs.update(overrides)
    return ReviewRequest(**kwargs)


def rows_of(data_dir: Path, destination: Destination) -> list[dict[str, str]]:
    path = data_dir / f"{destination.value}.csv"
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def test_the_queue_hands_a_reviewer_the_source_behind_each_row(tmp_path: Path) -> None:
    data_dir = build_sets(tmp_path)

    queue = load_review_queue(data_dir)

    by_address = {item.address: item for item in queue}
    assert set(by_address) == {COLD_ADDRESS, OTHER_ADDRESS, LEAD_ADDRESS, SWEEPER_ADDRESS}
    anchor = by_address[COLD_ADDRESS]
    assert anchor.destination is Destination.verified_anchors
    assert anchor.source_reference == POR_URL
    assert len(anchor.source_hash) == 64
    # The preserved copy is on disk and the item points at it.
    assert (data_dir / "sources" / anchor.source_file).is_file()
    assert by_address[LEAD_ADDRESS].upstream_source == "https://www.okx.com/proof-of-reserves"


def test_accepting_needs_a_reviewer_and_a_rationale(tmp_path: Path) -> None:
    data_dir = build_sets(tmp_path)

    report = review_candidates(
        data_dir,
        [
            request(COLD_ADDRESS, reviewer="   "),
            request(OTHER_ADDRESS, rationale=""),
        ],
    )

    assert not report.applied
    assert {refusal.code for refusal in report.refusals} == {
        "reviewer_required",
        "rationale_required",
    }


def test_accepting_without_opening_the_source_is_refused(tmp_path: Path) -> None:
    data_dir = build_sets(tmp_path)

    report = review_candidates(
        data_dir, [request(COLD_ADDRESS, evidence_inspected=("a colleague said so",))]
    )

    (refusal,) = report.refusals
    assert refusal.code == "source_not_inspected"
    assert POR_URL in refusal.message


def test_a_changed_source_file_blocks_acceptance(tmp_path: Path) -> None:
    data_dir = build_sets(tmp_path)
    preserved = next((data_dir / "sources").glob("*-por.csv"))
    preserved.write_text(
        preserved.read_text() + "tron,TSmuggledIn,X,exchange,service_control,deposit\n"
    )

    report = review_candidates(data_dir, [request(COLD_ADDRESS)])

    (refusal,) = report.refusals
    assert refusal.code == "source_changed"


def test_accepting_an_anchor_is_what_lets_it_terminate_a_trace(tmp_path: Path) -> None:
    data_dir = build_sets(tmp_path)
    registry_before = LabelRegistry.from_csv(data_dir / "verified_anchors.csv")
    assert registry_before.terminating_anchor("tron", COLD_ADDRESS, RETRIEVED) is None

    report = review_candidates(data_dir, [request(COLD_ADDRESS)], write=True)

    assert not report.refusals
    (applied,) = report.applied
    assert applied.from_state == "unreviewed"
    assert applied.to_state == "accepted"
    registry_after = LabelRegistry.from_csv(data_dir / "verified_anchors.csv")
    assert registry_after.terminating_anchor("tron", COLD_ADDRESS, RETRIEVED) is not None


def test_a_behavioural_candidate_cannot_become_an_anchor_by_review(tmp_path: Path) -> None:
    """Sweeping is behaviour. No amount of review turns behaviour into a source."""
    data_dir = build_sets(tmp_path)

    report = review_candidates(
        data_dir,
        [
            request(
                SWEEPER_ADDRESS,
                promote=True,
                corroboration=("sourced_disclosure", "signed_ownership"),
                evidence_inspected=("local: forwarding behaviour observed in the recorded window",),
            )
        ],
        write=True,
    )

    (refusal,) = report.refusals
    assert refusal.code == "candidate_cannot_become_an_anchor"
    anchored = {row["address"] for row in rows_of(data_dir, Destination.verified_anchors)}
    assert SWEEPER_ADDRESS not in anchored


def test_accepting_a_candidate_does_not_let_it_terminate_a_trace(tmp_path: Path) -> None:
    data_dir = build_sets(tmp_path)

    review_candidates(
        data_dir,
        [
            request(
                SWEEPER_ADDRESS,
                evidence_inspected=("local: forwarding behaviour observed in the recorded window",),
                rationale="Reviewed the observed sweeps; keeping it as a candidate.",
            )
        ],
        write=True,
    )

    registry = LabelRegistry.from_csv(data_dir / "deposit_candidates.csv")
    (anchor,) = registry.lookup("tron", SWEEPER_ADDRESS)
    assert anchor.review_state.value == "accepted"
    assert anchor.can_terminate_trace(RETRIEVED) is False


def test_promoting_a_lead_needs_evidence_independent_of_the_pattern(tmp_path: Path) -> None:
    data_dir = build_sets(tmp_path)
    inspected = (TAGPACK_URL, "https://www.okx.com/proof-of-reserves")

    refused = review_candidates(
        data_dir,
        [
            request(
                LEAD_ADDRESS,
                promote=True,
                corroboration=("repeated_sweeps", "shared_sponsor"),
                evidence_inspected=inspected,
            )
        ],
    )
    (refusal,) = refused.refusals
    assert refusal.code == "promotion_without_independent_evidence"

    allowed = review_candidates(
        data_dir,
        [
            request(
                LEAD_ADDRESS,
                promote=True,
                corroboration=("sourced_disclosure",),
                evidence_inspected=inspected,
                rationale="Followed the collection back to the exchange's own dated file.",
            )
        ],
        write=True,
    )
    (applied,) = allowed.applied
    assert applied.promoted_to is Destination.verified_anchors

    promoted = [
        r for r in rows_of(data_dir, Destination.verified_anchors) if r["address"] == LEAD_ADDRESS
    ]
    assert len(promoted) == 1
    assert promoted[0]["review_state"] == "accepted"
    # The lead itself stays where it was, marked and pointing at its promotion.
    (lead,) = [
        r for r in rows_of(data_dir, Destination.independent_review) if r["address"] == LEAD_ADDRESS
    ]
    assert lead["promoted_to"] == Destination.verified_anchors.value


def test_a_decision_changes_one_row_and_no_other(tmp_path: Path) -> None:
    data_dir = build_sets(tmp_path)
    before = rows_of(data_dir, Destination.verified_anchors)

    review_candidates(data_dir, [request(COLD_ADDRESS)], write=True)

    after = {row["address"]: row for row in rows_of(data_dir, Destination.verified_anchors)}
    untouched_before = next(r for r in before if r["address"] == OTHER_ADDRESS)
    assert after[OTHER_ADDRESS] == untouched_before
    assert after[COLD_ADDRESS]["review_state"] == "accepted"


def test_a_competing_claim_must_be_acknowledged_and_is_never_deleted(tmp_path: Path) -> None:
    data_dir = build_sets(tmp_path)
    rival = tmp_path / "rival.csv"
    rival.write_text(
        COLUMNS
        + f"tron,{COLD_ADDRESS},Southwind Custody,custodial_service,service_control,cold_reserve\n"
    )
    import_anchors(
        SourceDocument(
            path=rival,
            url="https://southwind.example.test/reserves",
            disclosure_kind=DisclosureKind.proof_of_reserves,
            disclosure_date=DISCLOSED,
            retrieved_at=RETRIEVED,
            methodology="A second disclosure naming the same address.",
            label_set_version="southwind-2026-06",
        ),
        network_key="tron",
        out_dir=data_dir,
        write=True,
    )

    refused = review_candidates(data_dir, [request(COLD_ADDRESS, source_reference=POR_URL)])
    (refusal,) = refused.refusals
    assert refusal.code == "conflict_unacknowledged"
    assert "Southwind Custody" in refusal.message

    resolved = review_candidates(
        data_dir,
        [request(COLD_ADDRESS, source_reference=POR_URL, conflict_acknowledged=True)],
        write=True,
    )
    assert not resolved.refusals

    rows = {
        row["source_reference"]: row
        for row in rows_of(data_dir, Destination.verified_anchors)
        if row["address"] == COLD_ADDRESS
    }
    assert rows[POR_URL]["review_state"] == "accepted"
    # The losing claim is preserved, marked, and still readable.
    assert rows["https://southwind.example.test/reserves"]["review_state"] == "conflicted"


def test_rejecting_keeps_the_row_and_its_source(tmp_path: Path) -> None:
    data_dir = build_sets(tmp_path)

    review_candidates(
        data_dir,
        [
            request(
                COLD_ADDRESS,
                action=ReviewAction.reject,
                rationale="The dated file does not list this address after all.",
            )
        ],
        write=True,
    )

    (row,) = [
        r for r in rows_of(data_dir, Destination.verified_anchors) if r["address"] == COLD_ADDRESS
    ]
    assert row["review_state"] == "rejected"
    assert row["source_reference"] == POR_URL


def test_every_decision_is_appended_to_the_log(tmp_path: Path) -> None:
    data_dir = build_sets(tmp_path)

    review_candidates(data_dir, [request(COLD_ADDRESS)], write=True)
    review_candidates(
        data_dir,
        [
            request(
                COLD_ADDRESS,
                action=ReviewAction.quarantine,
                reviewer="investigator-2",
                rationale="The disclosure was withdrawn by the publisher.",
                decided_at=DECIDED + dt.timedelta(days=1),
            )
        ],
        write=True,
    )

    with (data_dir / "review_log.csv").open(newline="") as fh:
        log = list(csv.DictReader(fh))

    assert len(log) == 2
    assert [entry["to_state"] for entry in log] == ["accepted", "quarantined"]
    assert log[1]["from_state"] == "accepted"
    assert log[1]["reviewer"] == "investigator-2"
    assert log[0]["evidence_inspected"] == POR_URL
    assert log[0]["source_hash"]


def test_nothing_is_written_without_write(tmp_path: Path) -> None:
    data_dir = build_sets(tmp_path)
    before = rows_of(data_dir, Destination.verified_anchors)

    report = review_candidates(data_dir, [request(COLD_ADDRESS)])

    assert report.applied and not report.refusals
    assert rows_of(data_dir, Destination.verified_anchors) == before
    assert not (data_dir / "review_log.csv").exists()


def test_an_unknown_address_is_refused_not_invented(tmp_path: Path) -> None:
    data_dir = build_sets(tmp_path)

    report = review_candidates(data_dir, [request("TNotInAnySetXXXXXXXXXXXXXXXXXXXXXX")])

    (refusal,) = report.refusals
    assert refusal.code == "no_such_claim"


def test_queue_filters_by_state_so_reviewed_rows_leave_it(tmp_path: Path) -> None:
    data_dir = build_sets(tmp_path)
    review_candidates(data_dir, [request(COLD_ADDRESS)], write=True)

    remaining = {item.address for item in load_review_queue(data_dir)}
    accepted = {item.address for item in load_review_queue(data_dir, states=("accepted",))}

    assert COLD_ADDRESS not in remaining
    assert accepted == {COLD_ADDRESS}


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        (ReviewAction.accept, "accepted"),
        (ReviewAction.reject, "rejected"),
        (ReviewAction.quarantine, "quarantined"),
        (ReviewAction.needs_evidence, "unreviewed"),
    ],
)
def test_each_action_maps_to_one_review_state(
    tmp_path: Path, action: ReviewAction, expected: str
) -> None:
    data_dir = build_sets(tmp_path)

    report = review_candidates(
        data_dir,
        [request(COLD_ADDRESS, action=action, rationale="Recorded for the audit trail.")],
        write=True,
    )

    assert not report.refusals
    (row,) = [
        r for r in rows_of(data_dir, Destination.verified_anchors) if r["address"] == COLD_ADDRESS
    ]
    assert row["review_state"] == expected
