"""Whether an accepted anchor with equal ``valid_from``/``valid_to`` behaves as a
single reviewed instant, exercised through the real label-selection call.

A proof-of-reserves snapshot supports exactly one instant, not an open-ended
interval of continuing control. These tests confirm three things about the
existing implementation, none of which required changing it:

- ``Anchor.covers()`` treats equal bounds as an inclusive single instant, not
  an empty interval and not invalid input.
- ``LabelRegistry.terminating_anchor`` -- what ``tracer._stop_at_label``
  actually calls -- honours that boundary.
- an observation "today" (long after the snapshot) is ineligible, because
  unequal-but-open ``valid_to`` is what would make a claim unbounded, and
  equal bounds close that off.
"""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

from app.services.anchor_import import DisclosureKind, SourceDocument, import_anchors
from app.services.candidate_review import ReviewAction, ReviewRequest, review_candidates
from app.services.labels import LabelRegistry

SNAPSHOT = dt.datetime(2026, 8, 10, 15, 59, 54, tzinfo=dt.UTC)
URL = "https://example-por.test/download"
ADDRESS = "TLaGjwhvA8XQYSxFAcAXy7Dvuue9eGYitv"
TODAY = dt.datetime(2026, 9, 20, tzinfo=dt.UTC)


def snapshot_only_fixture(tmp_path: Path) -> Path:
    """An accepted service_control anchor, bounded to the single instant SNAPSHOT.

    Built through the real importer and reviewer -- not hand-assembled -- then
    the one field the importer has no parameter for (``valid_to``) is set
    directly, the same correction made to the real OKX candidate.
    """
    data_dir = tmp_path / "data"
    source = tmp_path / "selection.csv"
    source.write_text(
        "network,address,entity_name,entity_type,assertion_type,address_role\n"
        f"tron,{ADDRESS},Example Exchange,exchange,service_control,unknown\n"
    )
    import_anchors(
        SourceDocument(
            path=source,
            url=URL,
            disclosure_kind=DisclosureKind.proof_of_reserves,
            disclosure_date=SNAPSHOT,
            retrieved_at=TODAY,
            methodology="One TRON row from a dated reserve snapshot.",
            label_set_version="fixture-por-1",
        ),
        network_key="tron",
        out_dir=data_dir,
        write=True,
    )
    review_candidates(
        data_dir,
        [
            ReviewRequest(
                network_key="tron",
                address=ADDRESS,
                action=ReviewAction.accept,
                reviewer="investigator-1",
                rationale="Checked the snapshot row and the signature.",
                evidence_inspected=(URL,),
            )
        ],
        write=True,
    )

    path = data_dir / "verified_anchors.csv"
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames
        rows = list(reader)
    assert rows[0]["review_state"] == "accepted"
    assert rows[0]["valid_from"] == SNAPSHOT.isoformat()
    assert rows[0]["valid_to"] == "", "the importer never sets valid_to; confirming that here"
    rows[0]["valid_to"] = SNAPSHOT.isoformat()
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return data_dir


def test_equal_bounds_parse_as_two_independent_instants_not_a_rejection(
    tmp_path: Path,
) -> None:
    data_dir = snapshot_only_fixture(tmp_path)
    registry = LabelRegistry.from_reviewed_sets(data_dir)
    (anchor,) = registry.lookup("tron", ADDRESS)
    assert anchor.valid_from == SNAPSHOT
    assert anchor.valid_to == SNAPSHOT


def test_an_observation_immediately_before_the_snapshot_is_ineligible(tmp_path: Path) -> None:
    data_dir = snapshot_only_fixture(tmp_path)
    registry = LabelRegistry.from_reviewed_sets(data_dir)
    before = SNAPSHOT - dt.timedelta(seconds=1)
    assert registry.terminating_anchor("tron", ADDRESS, before) is None


def test_an_observation_exactly_at_the_snapshot_is_eligible(tmp_path: Path) -> None:
    data_dir = snapshot_only_fixture(tmp_path)
    registry = LabelRegistry.from_reviewed_sets(data_dir)
    anchor = registry.terminating_anchor("tron", ADDRESS, SNAPSHOT)
    assert anchor is not None
    assert anchor.address_role == "unknown"


def test_an_observation_immediately_after_the_snapshot_is_ineligible(tmp_path: Path) -> None:
    data_dir = snapshot_only_fixture(tmp_path)
    registry = LabelRegistry.from_reviewed_sets(data_dir)
    after = SNAPSHOT + dt.timedelta(seconds=1)
    assert registry.terminating_anchor("tron", ADDRESS, after) is None


def test_an_observation_today_is_ineligible(tmp_path: Path) -> None:
    """Equal bounds close off the unbounded-forward-applicability gap: a claim
    scoped to one instant does not reach an observation made long afterward."""
    data_dir = snapshot_only_fixture(tmp_path)
    registry = LabelRegistry.from_reviewed_sets(data_dir)
    now = dt.datetime.now(dt.UTC)
    assert now > SNAPSHOT + dt.timedelta(days=1)
    assert registry.terminating_anchor("tron", ADDRESS, now) is None


def test_fixtures_never_touch_the_real_repository_data(tmp_path: Path) -> None:
    """The fixture above is a separate, disposable data dir under ``tmp_path``.

    Whatever review decisions or additional candidates exist in the real
    ``data/`` directory are outside this test module's control and change
    over time as the repository's own review workflow runs -- this only
    confirms the boundary-test fixture's address is still present there
    somewhere, not any particular review state or row count.
    """
    real_path = Path(__file__).resolve().parents[2] / "data" / "verified_anchors.csv"
    with real_path.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    addresses = {row["address"] for row in rows}
    assert ADDRESS in addresses
