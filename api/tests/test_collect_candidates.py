"""Stage 2C: candidate deposit-address leads from one accepted anchor's own
incoming history.

No network access; every response body uses only documented field names.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
from pathlib import Path

import httpx
import pytest
import respx

from app.core.settings import AppEnv, DataMode, Settings
from app.services.anchor_import import (
    DisclosureKind,
    SourceDocument,
    import_anchors,
)
from app.services.candidate_review import ReviewAction, ReviewRequest, review_candidates
from app.services.collect_candidates import (
    Backfill,
    CandidateCollectionError,
    CollectionRequest,
    collect_candidates,
    write_anchor_snapshot,
    write_manifest,
)
from app.services.labels import LabelRegistry

BASE = "https://api.trongrid.io"
USDT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
ANCHOR = "TBvGC1Nd8i5wmj185HTdoTWAZPmRUTFBZz"
SENDER_A = "TEocPZsTTRAK9x5TR66GnEbxKKU8zrNxgM"
SENDER_B = "TRTqwgSLfUVziqWCyN6ZMThBkMgRvSaYtE"
SENDER_C = "TMrjWHAq1BPg9iG9ZaBTsG1AoxWERR29Mz"
START = dt.datetime(2026, 8, 1, tzinfo=dt.UTC)
CUTOFF = dt.datetime(2026, 8, 2, tzinfo=dt.UTC)


def history_row(tx: str, frm: str, to: str, value: str, ts: int) -> dict:
    return {
        "transaction_id": tx,
        "block_timestamp": ts,
        "from": frm,
        "to": to,
        "type": "Transfer",
        "value": value,
        "token_info": {"symbol": "USDT", "address": USDT, "decimals": 6, "name": "Tether USD"},
    }


def accepted_anchor_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    source = tmp_path / "disclosure.csv"
    source.write_text(
        "network,address,entity_name,entity_type,assertion_type,address_role\n"
        f"tron,{ANCHOR},Example Exchange,exchange,service_control,cold_reserve\n"
    )
    import_anchors(
        SourceDocument(
            path=source,
            url="https://example.test/por",
            disclosure_kind=DisclosureKind.proof_of_reserves,
            disclosure_date=dt.datetime(2026, 7, 1, tzinfo=dt.UTC),
            retrieved_at=dt.datetime(2026, 7, 1, tzinfo=dt.UTC),
            methodology="fixture",
            label_set_version="fixture-1",
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
                address=ANCHOR,
                action=ReviewAction.accept,
                reviewer="investigator-1",
                rationale="fixture",
                evidence_inspected=("https://example.test/por",),
            )
        ],
        write=True,
    )
    return data_dir


def unaccepted_anchor_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    source = tmp_path / "disclosure.csv"
    source.write_text(
        "network,address,entity_name,entity_type,assertion_type,address_role\n"
        f"tron,{ANCHOR},Example Exchange,exchange,service_control,cold_reserve\n"
    )
    import_anchors(
        SourceDocument(
            path=source,
            url="https://example.test/por",
            disclosure_kind=DisclosureKind.proof_of_reserves,
            disclosure_date=dt.datetime(2026, 7, 1, tzinfo=dt.UTC),
            retrieved_at=dt.datetime(2026, 7, 1, tzinfo=dt.UTC),
            methodology="fixture",
            label_set_version="fixture-1",
        ),
        network_key="tron",
        out_dir=data_dir,
        write=True,
    )
    return data_dir


def live_settings(**overrides) -> Settings:
    kwargs = {
        "app_env": AppEnv.dev,
        "data_mode": DataMode.LIVE,
        "tron_api_base": BASE,
        "tron_api_key": "test-key-not-a-real-one",
    }
    kwargs.update(overrides)
    return Settings(**kwargs)


def deposit_candidate_rows(data_dir: Path) -> list[dict[str, str]]:
    path = data_dir / "deposit_candidates.csv"
    if not path.exists():
        return []
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def verified_anchor_rows(data_dir: Path) -> list[dict[str, str]]:
    with (data_dir / "verified_anchors.csv").open(newline="") as fh:
        return list(csv.DictReader(fh))


@respx.mock
async def test_refuses_to_collect_for_an_address_without_an_accepted_claim(
    tmp_path: Path,
) -> None:
    data_dir = unaccepted_anchor_dir(tmp_path)
    settings = live_settings()
    request = CollectionRequest(
        anchor_address=ANCHOR, token_contract=USDT, analysis_start=START, analysis_cutoff=CUTOFF
    )

    with pytest.raises(CandidateCollectionError, match="no accepted claim"):
        await collect_candidates(
            settings, request, out_root=tmp_path / "out", data_dir=data_dir
        )


@respx.mock
async def test_finds_distinct_senders_and_writes_candidate_leads(tmp_path: Path) -> None:
    data_dir = accepted_anchor_dir(tmp_path)
    route = respx.get(f"{BASE}/v1/accounts/{ANCHOR}/transactions/trc20").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    history_row("11" * 32, SENDER_A, ANCHOR, "1000000", 1786000000000),
                    history_row("22" * 32, SENDER_B, ANCHOR, "2000000", 1786000010000),
                    # A repeat sender must not create a second candidate.
                    history_row("33" * 32, SENDER_A, ANCHOR, "500000", 1786000020000),
                ],
                "meta": {},
            },
        )
    )
    settings = live_settings()
    request = CollectionRequest(
        anchor_address=ANCHOR,
        token_contract=USDT,
        analysis_start=START,
        analysis_cutoff=CUTOFF,
        candidate_limit=50,
        run_id="test-run",
    )

    run = await collect_candidates(
        settings, request, out_root=tmp_path / "out", data_dir=data_dir, write=True
    )

    assert route.call_count == 1
    assert int(route.calls[0].request.url.params["min_timestamp"]) == int(START.timestamp() * 1000)
    assert int(route.calls[0].request.url.params["max_timestamp"]) == int(CUTOFF.timestamp() * 1000)
    assert route.calls[0].request.url.params["only_to"] == "true"

    assert {c["candidate_address"] for c in run.candidates} == {SENDER_A, SENDER_B}
    assert run.truncated_by_candidate_limit is False
    assert run.truncated_by_request_budget is False

    rows = deposit_candidate_rows(data_dir)
    assert {r["address"] for r in rows} == {SENDER_A, SENDER_B}
    for row in rows:
        assert row["assertion_type"] == "deposit_candidate"
        assert row["address_role"] == "unknown"
        assert row["review_state"] == "unreviewed"
        # The candidate's own entity is not established -- never the
        # anchor's. The anchor relationship is recorded separately, so a
        # reader cannot mistake this for an ownership claim.
        assert row["entity_name"] == "unknown"
        assert row["entity_type"] == "unknown"
        assert row["anchor_address"] == ANCHOR
        assert row["anchor_entity_name"] == "Example Exchange"

    # The one accepted anchor is completely unaffected.
    (anchor_row,) = verified_anchor_rows(data_dir)
    assert anchor_row["address"] == ANCHOR
    assert anchor_row["review_state"] == "accepted"

    # Raw evidence preserved before any row was written.
    raw_files = list((run.directory / "raw").glob("*.json"))
    assert len(raw_files) == 1
    candidates_json = json.loads((run.directory / "candidates.json").read_text())
    assert candidates_json["requests_used"] == 1
    assert {c["candidate_address"] for c in candidates_json["candidates"]} == {SENDER_A, SENDER_B}


@respx.mock
async def test_dry_run_finds_candidates_but_writes_nothing(tmp_path: Path) -> None:
    data_dir = accepted_anchor_dir(tmp_path)
    respx.get(f"{BASE}/v1/accounts/{ANCHOR}/transactions/trc20").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [history_row("44" * 32, SENDER_A, ANCHOR, "1000000", 1786000000000)],
                "meta": {},
            },
        )
    )
    settings = live_settings()
    request = CollectionRequest(
        anchor_address=ANCHOR, token_contract=USDT, analysis_start=START, analysis_cutoff=CUTOFF
    )

    run = await collect_candidates(
        settings, request, out_root=tmp_path / "out", data_dir=data_dir, write=False
    )

    assert len(run.candidates) == 1
    assert run.written is False
    assert deposit_candidate_rows(data_dir) == []


@respx.mock
async def test_candidate_limit_truncates_and_says_so(tmp_path: Path) -> None:
    data_dir = accepted_anchor_dir(tmp_path)
    respx.get(f"{BASE}/v1/accounts/{ANCHOR}/transactions/trc20").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    history_row("55" * 32, SENDER_A, ANCHOR, "1", 1786000000000),
                    history_row("66" * 32, SENDER_B, ANCHOR, "1", 1786000010000),
                    history_row("77" * 32, SENDER_C, ANCHOR, "1", 1786000020000),
                ],
                "meta": {"fingerprint": "MORE"},
            },
        )
    )
    settings = live_settings()
    request = CollectionRequest(
        anchor_address=ANCHOR,
        token_contract=USDT,
        analysis_start=START,
        analysis_cutoff=CUTOFF,
        candidate_limit=2,
    )

    run = await collect_candidates(
        settings, request, out_root=tmp_path / "out", data_dir=data_dir, write=True
    )

    assert len(run.candidates) == 2
    assert run.truncated_by_candidate_limit is True
    rows = deposit_candidate_rows(data_dir)
    assert len(rows) == 2


@respx.mock
async def test_request_budget_truncates_without_crashing(tmp_path: Path) -> None:
    data_dir = accepted_anchor_dir(tmp_path)
    tx1, tx2 = "88" * 32, "99" * 32

    def responder(request: httpx.Request) -> httpx.Response:
        if "fingerprint" not in request.url.params:
            return httpx.Response(
                200,
                json={
                    "data": [history_row(tx1, SENDER_A, ANCHOR, "1", 1786000000000)],
                    "meta": {"fingerprint": "PAGE-2"},
                },
            )
        return httpx.Response(
            200, json={"data": [history_row(tx2, SENDER_B, ANCHOR, "1", 1786000010000)], "meta": {}}
        )

    respx.get(f"{BASE}/v1/accounts/{ANCHOR}/transactions/trc20").mock(side_effect=responder)
    settings = live_settings()
    request = CollectionRequest(
        anchor_address=ANCHOR,
        token_contract=USDT,
        analysis_start=START,
        analysis_cutoff=CUTOFF,
        candidate_limit=50,
        max_requests=1,  # allows only the first page
    )

    run = await collect_candidates(
        settings, request, out_root=tmp_path / "out", data_dir=data_dir, write=True
    )

    assert run.requests_used == 1
    assert run.truncated_by_request_budget is True
    assert {c["candidate_address"] for c in run.candidates} == {SENDER_A}
    rows = deposit_candidate_rows(data_dir)
    assert {r["address"] for r in rows} == {SENDER_A}


@respx.mock
async def test_a_candidate_row_never_carries_the_anchors_entity_as_its_own(
    tmp_path: Path,
) -> None:
    """The exact ambiguity this module must not produce: entity_name=OKX on
    a candidate row would read as an ownership claim for the sender, when
    all that is known is that it sent value to OKX's anchor."""
    data_dir = accepted_anchor_dir(tmp_path)
    respx.get(f"{BASE}/v1/accounts/{ANCHOR}/transactions/trc20").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [history_row("bc" * 32, SENDER_A, ANCHOR, "1000000", 1786000000000)],
                "meta": {},
            },
        )
    )
    settings = live_settings()
    request = CollectionRequest(
        anchor_address=ANCHOR, token_contract=USDT, analysis_start=START, analysis_cutoff=CUTOFF
    )

    run = await collect_candidates(
        settings, request, out_root=tmp_path / "out", data_dir=data_dir, write=True
    )

    (row,) = deposit_candidate_rows(data_dir)
    assert row["entity_name"] != "Example Exchange"
    assert row["entity_name"] == "unknown"
    assert row["entity_type"] == "unknown"
    # The relationship is instead explicit and separate from the ownership
    # field: which anchor the sender transferred to, and that anchor's own
    # entity -- never presented as the sender's entity.
    assert row["anchor_address"] == ANCHOR
    assert row["anchor_entity_name"] == "Example Exchange"
    assert run.anchor_entity_name == "Example Exchange"  # the anchor's, not the candidate's


def test_a_chain_observation_can_never_route_to_verified_anchors(tmp_path: Path) -> None:
    """Defence in depth, independent of this module's own always-deposit_
    candidate rows: even a document of this kind claiming service_control
    is refused a path to the verified set (LEAD_ONLY)."""
    data_dir = tmp_path / "data"
    source = tmp_path / "attempt.csv"
    source.write_text(
        "network,address,entity_name,entity_type,assertion_type,address_role\n"
        f"tron,{SENDER_A},Some Entity,exchange,service_control,unknown\n"
    )
    report = import_anchors(
        SourceDocument(
            path=source,
            url="tron:chain-observation:incoming-to:x",
            disclosure_kind=DisclosureKind.chain_observation,
            disclosure_date=dt.datetime(2026, 8, 1, tzinfo=dt.UTC),
            retrieved_at=dt.datetime(2026, 8, 1, tzinfo=dt.UTC),
            methodology="fixture",
            label_set_version="fixture-1",
        ),
        network_key="tron",
        out_dir=data_dir,
        write=True,
    )
    assert not (data_dir / "verified_anchors.csv").exists()
    assert report.downgrades
    assert report.downgrades[0].to.value == "independent_review"


# --- temporal applicability ---------------------------------------------------

SNAPSHOT = dt.datetime(2026, 8, 10, 15, 59, 54, tzinfo=dt.UTC)


def snapshot_anchor_dir(tmp_path: Path) -> Path:
    """An accepted claim applicable only at SNAPSHOT -- not review_state alone,
    a real single-instant scope, mirroring the actual OKX candidate's shape."""
    data_dir = tmp_path / "data"
    source = tmp_path / "disclosure.csv"
    source.write_text(
        "network,address,entity_name,entity_type,assertion_type,address_role\n"
        f"tron,{ANCHOR},OKX,exchange,service_control,unknown\n"
    )
    import_anchors(
        SourceDocument(
            path=source,
            url="https://example.test/por",
            disclosure_kind=DisclosureKind.proof_of_reserves,
            disclosure_date=SNAPSHOT,
            retrieved_at=dt.datetime(2026, 9, 20, tzinfo=dt.UTC),
            methodology="fixture",
            label_set_version="fixture-1",
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
                address=ANCHOR,
                action=ReviewAction.accept,
                reviewer="investigator-1",
                rationale="fixture",
                evidence_inspected=("https://example.test/por",),
            )
        ],
        write=True,
    )
    # The importer never sets valid_to; pin it to valid_from so the claim
    # covers exactly SNAPSHOT and nothing else.
    path = data_dir / "verified_anchors.csv"
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames
        rows = list(reader)
    rows[0]["valid_to"] = SNAPSHOT.isoformat()
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return data_dir


def _collection_request(**overrides) -> CollectionRequest:
    kwargs = {
        "anchor_address": ANCHOR,
        "token_contract": USDT,
        "analysis_start": SNAPSHOT - dt.timedelta(seconds=5),
        "analysis_cutoff": SNAPSHOT + dt.timedelta(seconds=5),
        "candidate_limit": 50,
    }
    kwargs.update(overrides)
    return CollectionRequest(**kwargs)


@respx.mock
async def test_a_transfer_exactly_at_the_snapshot_instant_produces_a_candidate(
    tmp_path: Path,
) -> None:
    data_dir = snapshot_anchor_dir(tmp_path)
    snapshot_ms = int(SNAPSHOT.timestamp() * 1000)
    respx.get(f"{BASE}/v1/accounts/{ANCHOR}/transactions/trc20").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [history_row("aa" * 32, SENDER_A, ANCHOR, "72140000", snapshot_ms)],
                "meta": {},
            },
        )
    )
    settings = live_settings()

    run = await collect_candidates(
        settings, _collection_request(), out_root=tmp_path / "out", data_dir=data_dir, write=True
    )

    assert {c["candidate_address"] for c in run.candidates} == {SENDER_A}
    assert run.ineligible_events == []
    rows = deposit_candidate_rows(data_dir)
    assert {r["address"] for r in rows} == {SENDER_A}


@respx.mock
async def test_a_transfer_one_second_before_cannot_use_this_anchor_claim(
    tmp_path: Path,
) -> None:
    data_dir = snapshot_anchor_dir(tmp_path)
    before_ms = int((SNAPSHOT - dt.timedelta(seconds=1)).timestamp() * 1000)
    respx.get(f"{BASE}/v1/accounts/{ANCHOR}/transactions/trc20").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [history_row("bb" * 32, SENDER_A, ANCHOR, "1000000", before_ms)],
                "meta": {},
            },
        )
    )
    settings = live_settings()

    run = await collect_candidates(
        settings, _collection_request(), out_root=tmp_path / "out", data_dir=data_dir, write=True
    )

    assert run.candidates == []
    assert len(run.ineligible_events) == 1
    assert run.ineligible_events[0]["candidate_address"] == SENDER_A
    assert deposit_candidate_rows(data_dir) == []


@respx.mock
async def test_a_transfer_one_second_after_cannot_use_this_anchor_claim(
    tmp_path: Path,
) -> None:
    data_dir = snapshot_anchor_dir(tmp_path)
    after_ms = int((SNAPSHOT + dt.timedelta(seconds=1)).timestamp() * 1000)
    respx.get(f"{BASE}/v1/accounts/{ANCHOR}/transactions/trc20").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [history_row("cc" * 32, SENDER_A, ANCHOR, "1000000", after_ms)],
                "meta": {},
            },
        )
    )
    settings = live_settings()

    run = await collect_candidates(
        settings, _collection_request(), out_root=tmp_path / "out", data_dir=data_dir, write=True
    )

    assert run.candidates == []
    assert len(run.ineligible_events) == 1
    assert deposit_candidate_rows(data_dir) == []


@respx.mock
async def test_an_accepted_but_temporally_inapplicable_anchor_yields_no_candidates(
    tmp_path: Path,
) -> None:
    """review_state=accepted alone is not enough (the original gap): every
    transfer here is outside the claim's covered instant."""
    data_dir = snapshot_anchor_dir(tmp_path)
    before_ms = int((SNAPSHOT - dt.timedelta(seconds=2)).timestamp() * 1000)
    after_ms = int((SNAPSHOT + dt.timedelta(seconds=2)).timestamp() * 1000)
    respx.get(f"{BASE}/v1/accounts/{ANCHOR}/transactions/trc20").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    history_row("dd" * 32, SENDER_A, ANCHOR, "1000000", before_ms),
                    history_row("ee" * 32, SENDER_B, ANCHOR, "1000000", after_ms),
                ],
                "meta": {},
            },
        )
    )
    settings = live_settings()

    run = await collect_candidates(
        settings, _collection_request(), out_root=tmp_path / "out", data_dir=data_dir, write=True
    )

    assert run.candidates == []
    assert len(run.ineligible_events) == 2
    assert deposit_candidate_rows(data_dir) == []
    # The accepted anchor itself is confirmed present and accepted, so this
    # is genuinely the temporal check doing the work, not a missing claim.
    (anchor_row,) = verified_anchor_rows(data_dir)
    assert anchor_row["review_state"] == "accepted"


@respx.mock
async def test_a_mixed_response_keeps_only_the_eligible_event_and_records_scope_honestly(
    tmp_path: Path,
) -> None:
    data_dir = snapshot_anchor_dir(tmp_path)
    snapshot_ms = int(SNAPSHOT.timestamp() * 1000)
    after_ms = int((SNAPSHOT + dt.timedelta(seconds=1)).timestamp() * 1000)
    respx.get(f"{BASE}/v1/accounts/{ANCHOR}/transactions/trc20").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    history_row("ff" * 32, SENDER_A, ANCHOR, "72140000", snapshot_ms),
                    history_row("10" * 32, SENDER_B, ANCHOR, "1000000", after_ms),
                ],
                "meta": {},
            },
        )
    )
    settings = live_settings()

    run = await collect_candidates(
        settings,
        _collection_request(run_id="mixed-test"),
        out_root=tmp_path / "out",
        data_dir=data_dir,
        write=True,
    )

    assert {c["candidate_address"] for c in run.candidates} == {SENDER_A}
    assert [e["candidate_address"] for e in run.ineligible_events] == [SENDER_B]

    rows = deposit_candidate_rows(data_dir)
    assert {r["address"] for r in rows} == {SENDER_A}

    candidates_json = json.loads((run.directory / "candidates.json").read_text())
    assert candidates_json["candidates"][0]["candidate_address"] == SENDER_A
    assert candidates_json["candidates"][0]["amount_base_units"] == 72140000
    assert candidates_json["ineligible_events"][0]["candidate_address"] == SENDER_B
    # The acquisition window actually searched is recorded honestly, wider
    # than what the anchor claim itself covers.
    assert candidates_json["analysis_start"] == (SNAPSHOT - dt.timedelta(seconds=5)).isoformat()
    assert candidates_json["analysis_cutoff"] == (SNAPSHOT + dt.timedelta(seconds=5)).isoformat()
    assert candidates_json["anchor_valid_from"] == SNAPSHOT.isoformat()
    assert candidates_json["anchor_valid_to"] == SNAPSHOT.isoformat()


# --- backfill provenance -----------------------------------------------------


@respx.mock
async def test_a_normal_runs_manifest_is_not_marked_backfilled(tmp_path: Path) -> None:
    data_dir = accepted_anchor_dir(tmp_path)
    respx.get(f"{BASE}/v1/accounts/{ANCHOR}/transactions/trc20").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [history_row("13" * 32, SENDER_A, ANCHOR, "1000000", 1786000000000)],
                "meta": {},
            },
        )
    )
    settings = live_settings()
    request = CollectionRequest(
        anchor_address=ANCHOR, token_contract=USDT, analysis_start=START, analysis_cutoff=CUTOFF
    )

    run = await collect_candidates(
        settings, request, out_root=tmp_path / "out", data_dir=data_dir, write=True
    )

    manifest = json.loads((run.directory / "manifest.json").read_text())
    assert manifest["provenance"]["backfilled"] is False
    assert manifest["provenance"]["backfill_note"] is None
    assert manifest["provenance"]["run_started_at"] is not None
    assert manifest["provenance"]["run_finished_at"] is not None
    assert manifest["configuration"]["data_mode"] == "LIVE"

    snapshot = json.loads((run.directory / "accepted-anchor-snapshot.json").read_text())
    assert "backfilled" not in snapshot


@respx.mock
async def test_a_backfilled_manifest_preserves_the_original_run_time_and_reports_live(
    tmp_path: Path,
) -> None:
    """The core B requirement: regenerating manifest.json later, from settings
    that do not themselves describe a live run, must not silently relabel the
    original run's own data_mode, and must not fabricate a new acquisition
    time -- only record when this artifact itself was (re)written."""
    data_dir = accepted_anchor_dir(tmp_path)
    respx.get(f"{BASE}/v1/accounts/{ANCHOR}/transactions/trc20").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [history_row("14" * 32, SENDER_A, ANCHOR, "1000000", 1786000000000)],
                "meta": {},
            },
        )
    )
    live = live_settings()
    request = CollectionRequest(
        anchor_address=ANCHOR, token_contract=USDT, analysis_start=START, analysis_cutoff=CUTOFF
    )

    run = await collect_candidates(
        live, request, out_root=tmp_path / "out", data_dir=data_dir, write=True
    )
    original_manifest = json.loads((run.directory / "manifest.json").read_text())
    original_started_at = original_manifest["provenance"]["run_started_at"]
    original_finished_at = original_manifest["provenance"]["run_finished_at"]
    original_artifact_created_at = original_manifest["provenance"]["artifact_created_at"]

    # The backfill "process" has its own, different ambient settings -- not
    # LIVE -- the way a later, offline local script naturally would.
    offline = live_settings(data_mode=DataMode.RECORDED_PUBLIC)
    registry = LabelRegistry.from_reviewed_sets(data_dir)
    anchor = registry.lookup("tron", ANCHOR)[0]
    write_anchor_snapshot(
        run.directory,
        registry,
        anchor,
        backfill=Backfill(original_data_mode="LIVE"),
    )
    write_manifest(run, offline, request, backfill=Backfill(original_data_mode="LIVE"))

    backfilled_manifest = json.loads((run.directory / "manifest.json").read_text())
    assert backfilled_manifest["provenance"]["backfilled"] is True
    assert "already-saved local evidence" in backfilled_manifest["provenance"]["backfill_note"]
    assert "Zero additional network requests" in backfilled_manifest["provenance"]["backfill_note"]
    # The original acquisition window is untouched by the backfill.
    assert backfilled_manifest["provenance"]["run_started_at"] == original_started_at
    assert backfilled_manifest["provenance"]["run_finished_at"] == original_finished_at
    # But the manifest file itself was regenerated later.
    assert (
        backfilled_manifest["provenance"]["artifact_created_at"] != original_artifact_created_at
    )
    # data_mode reports the ORIGINAL run, not the offline backfill process's
    # own ambient settings (which are RECORDED_PUBLIC here).
    assert backfilled_manifest["configuration"]["data_mode"] == "LIVE"

    backfilled_snapshot = json.loads((run.directory / "accepted-anchor-snapshot.json").read_text())
    assert backfilled_snapshot["backfilled"] is True
    assert "already-saved local evidence" in backfilled_snapshot["backfill_note"]
