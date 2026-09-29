"""Stage 2 behavioral/sweep evidence collector.

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
from app.services.anchor_import import DisclosureKind, SourceDocument, import_anchors
from app.services.collect_behavioral_evidence import (
    DIRECTION_OUTGOING,
    BehavioralEvidenceError,
    BehavioralEvidenceRequest,
    collect_behavioral_evidence,
    load_preferred_behavioral_run,
)

BASE = "https://api.trongrid.io"
CANDIDATE = "TNtTcstZdy5vppwDMQuR9gy6n5rT4o7ptq"
ANCHOR = "TYfxtkCooUX7rzjRqBGLan9XkCxqkrCRir"
TOKEN_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
OTHER = "TMrjWHAq1BPg9iG9ZaBTsG1AoxWERR29Mz"
OTHER_2 = "TEocPZsTTRAK9x5TR66GnEbxKKU8zrNxgM"

START = dt.datetime(2026, 8, 10, tzinfo=dt.UTC)
CUTOFF = dt.datetime(2026, 8, 11, tzinfo=dt.UTC)
HISTORICAL_MS = int(dt.datetime(2026, 8, 10, 12, 0, tzinfo=dt.UTC).timestamp() * 1000)

TRC20_URL = f"{BASE}/v1/accounts/{CANDIDATE}/transactions/trc20"
SOLIDIFIED_RECEIPT_URL = f"{BASE}/walletsolidity/gettransactioninfobyid"
HEAD_RECEIPT_URL = f"{BASE}/wallet/gettransactioninfobyid"


def known_candidate_dir(tmp_path: Path) -> Path:
    """CANDIDATE exists as an (unreviewed) deposit candidate lead."""
    data_dir = tmp_path / "data"
    source = tmp_path / "candidates.csv"
    source.write_text(
        "network,address,entity_name,entity_type,assertion_type,address_role\n"
        f"tron,{CANDIDATE},unknown,unknown,deposit_candidate,unknown\n"
    )
    import_anchors(
        SourceDocument(
            path=source,
            url=f"tron:chain-observation:incoming-to:{ANCHOR}",
            disclosure_kind=DisclosureKind.chain_observation,
            disclosure_date=dt.datetime(2026, 8, 10, 15, 59, 54, tzinfo=dt.UTC),
            retrieved_at=dt.datetime(2026, 9, 20, tzinfo=dt.UTC),
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
    with (data_dir / "deposit_candidates.csv").open(newline="") as fh:
        return list(csv.DictReader(fh))


def verified_anchor_rows(data_dir: Path) -> list[dict[str, str]]:
    path = data_dir / "verified_anchors.csv"
    if not path.exists():
        return []
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def behavioral_evidence_rows(data_dir: Path) -> list[dict[str, str]]:
    path = data_dir / "behavioral_evidence.csv"
    if not path.exists():
        return []
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def trc20_row(
    tx_id: str,
    from_addr: str,
    to_addr: str,
    *,
    value: int = 1_000_000,
    event_type: str = "Transfer",
    block_ms: int = HISTORICAL_MS,
) -> dict:
    return {
        "transaction_id": tx_id,
        "token_info": {
            "symbol": "USDT",
            "address": TOKEN_CONTRACT,
            "decimals": 6,
            "name": "Tether USD",
        },
        "block_timestamp": block_ms,
        "from": from_addr,
        "to": to_addr,
        "type": event_type,
        "value": str(value),
    }


def route_by_direction(incoming_pages: list[list[dict]], outgoing_pages: list[list[dict]]):
    """Mocks the TRC-20 endpoint, paginating each direction independently by
    its own fingerprint cursor, and refusing to serve a request whose other
    filters (address is baked into the URL; only_to/only_from is checked
    here) changed between pages."""
    position = {"incoming": 0, "outgoing": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if params.get("only_to") == "true":
            key, pages = "incoming", incoming_pages
        elif params.get("only_from") == "true":
            key, pages = "outgoing", outgoing_pages
        else:
            return httpx.Response(200, json={"data": [], "meta": {}})

        index = position[key]
        rows = pages[index] if index < len(pages) else []
        position[key] = index + 1
        has_more = position[key] < len(pages)
        meta = {"fingerprint": f"{key}-page-{position[key]}"} if has_more else {}
        return httpx.Response(200, json={"data": rows, "meta": meta})

    return respx.get(TRC20_URL).mock(side_effect=handler)


def default_request(**overrides) -> BehavioralEvidenceRequest:
    kwargs = {
        "candidate_address": CANDIDATE,
        "token_contract": TOKEN_CONTRACT,
        "analysis_start": START,
        "analysis_cutoff": CUTOFF,
    }
    kwargs.update(overrides)
    return BehavioralEvidenceRequest(**kwargs)


# --- regression: a page landing exactly on event_limit must not read complete


@respx.mock
async def test_a_page_landing_exactly_on_event_limit_is_still_marked_truncated(
    tmp_path: Path,
) -> None:
    """A live run hit this: TronGrid returned exactly event_limit rows *and*
    a genuine continuation fingerprint on the same page. Nothing in that
    page's own event list ever exceeded the cap, so the per-event check
    never tripped -- only the end-of-page check does, and it must still
    record the truncation rather than reading a full page as "nothing more
    to see"."""
    data_dir = known_candidate_dir(tmp_path)
    route_by_direction(
        incoming_pages=[[]],
        outgoing_pages=[
            [trc20_row(f"aa{i:02d}" * 8, CANDIDATE, ANCHOR, value=i) for i in range(3)],
            [trc20_row("bb" * 32, CANDIDATE, ANCHOR, value=999)],  # only reached if we kept going
        ],
    )
    settings = live_settings()

    run = await collect_behavioral_evidence(
        settings,
        default_request(event_limit=3, page_limit=5),
        out_root=tmp_path / "out",
        data_dir=data_dir,
        write=True,
    )

    assert len(run.rows) == 3
    assert run.truncated_by_event_limit[DIRECTION_OUTGOING] is True
    assert run.truncated_by_page_limit[DIRECTION_OUTGOING] is False
    # The second page was never fetched: stopping at the cap costs nothing extra.
    assert run.requests_used == 2  # 1 incoming + 1 outgoing


@respx.mock
async def test_a_page_landing_exactly_on_event_limit_with_no_further_pages_is_complete(
    tmp_path: Path,
) -> None:
    """The mirror case: TronGrid's own response has no continuation
    fingerprint at all, so hitting the cap on the last real page is not a
    truncation -- there is genuinely nothing more."""
    data_dir = known_candidate_dir(tmp_path)
    route_by_direction(
        incoming_pages=[[]],
        outgoing_pages=[
            [trc20_row(f"cc{i:02d}" * 8, CANDIDATE, ANCHOR, value=i) for i in range(3)],
        ],
    )
    settings = live_settings()

    run = await collect_behavioral_evidence(
        settings,
        default_request(event_limit=3, page_limit=5),
        out_root=tmp_path / "out",
        data_dir=data_dir,
        write=True,
    )

    assert len(run.rows) == 3
    assert run.truncated_by_event_limit[DIRECTION_OUTGOING] is False


@respx.mock
async def test_refuses_an_address_that_is_not_a_known_candidate_or_anchor(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    settings = live_settings()

    with pytest.raises(BehavioralEvidenceError, match="not a known candidate"):
        await collect_behavioral_evidence(
            settings, default_request(), out_root=tmp_path / "out", data_dir=data_dir
        )


# --- 1: incoming and outgoing events remain distinct --------------------------


@respx.mock
async def test_incoming_and_outgoing_events_remain_distinct(tmp_path: Path) -> None:
    data_dir = known_candidate_dir(tmp_path)
    route_by_direction(
        incoming_pages=[[trc20_row("aa" * 32, OTHER, CANDIDATE, value=5_000_000)]],
        outgoing_pages=[[trc20_row("bb" * 32, CANDIDATE, ANCHOR, value=3_000_000)]],
    )
    settings = live_settings()

    run = await collect_behavioral_evidence(
        settings, default_request(), out_root=tmp_path / "out", data_dir=data_dir, write=True
    )

    assert len(run.rows) == 2
    by_direction = {r.direction: r for r in run.rows}
    assert by_direction["incoming"].counterparty_address == OTHER
    assert by_direction["incoming"].amount_base_units == 5_000_000
    assert by_direction["outgoing"].counterparty_address == ANCHOR
    assert by_direction["outgoing"].amount_base_units == 3_000_000
    assert by_direction["incoming"].event_reference != by_direction["outgoing"].event_reference

    rows = behavioral_evidence_rows(data_dir)
    assert {r["direction"] for r in rows} == {"incoming", "outgoing"}


# --- 2: multiple Transfer events in one tx keep unique identities -------------


@respx.mock
async def test_multiple_transfer_events_in_one_tx_keep_unique_identities(tmp_path: Path) -> None:
    data_dir = known_candidate_dir(tmp_path)
    same_tx = "cc" * 32
    route_by_direction(
        incoming_pages=[[]],
        outgoing_pages=[
            [
                trc20_row(same_tx, CANDIDATE, ANCHOR, value=1_000_000),
                trc20_row(same_tx, CANDIDATE, OTHER, value=2_000_000),
            ]
        ],
    )
    settings = live_settings()

    run = await collect_behavioral_evidence(
        settings, default_request(), out_root=tmp_path / "out", data_dir=data_dir, write=True
    )

    assert len(run.rows) == 2
    assert all(r.tx_hash == same_tx for r in run.rows)
    references = {r.event_reference for r in run.rows}
    assert len(references) == 2  # distinct despite sharing a transaction id
    amounts = {r.amount_base_units for r in run.rows}
    assert amounts == {1_000_000, 2_000_000}


# --- 3: failed transfers are excluded ------------------------------------------


@respx.mock
async def test_failed_transfers_are_excluded(tmp_path: Path) -> None:
    data_dir = known_candidate_dir(tmp_path)
    reverted_tx = "dd" * 32
    route_by_direction(
        incoming_pages=[[]],
        outgoing_pages=[[trc20_row(reverted_tx, CANDIDATE, ANCHOR, value=1_000_000)]],
    )
    respx.post(SOLIDIFIED_RECEIPT_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": reverted_tx,
                "blockNumber": 85000000,
                "blockTimeStamp": HISTORICAL_MS,
                "receipt": {"result": "REVERT"},
            },
        )
    )
    settings = live_settings()

    run = await collect_behavioral_evidence(
        settings,
        default_request(verify_execution=True),
        out_root=tmp_path / "out",
        data_dir=data_dir,
        write=True,
    )

    assert run.rows == []
    assert run.excluded_failed_or_reverted_count == 1
    assert behavioral_evidence_rows(data_dir) == []


# --- 4: approvals are excluded -------------------------------------------------


@respx.mock
async def test_approvals_are_excluded(tmp_path: Path) -> None:
    data_dir = known_candidate_dir(tmp_path)
    route_by_direction(
        incoming_pages=[[]],
        outgoing_pages=[[trc20_row("ee" * 32, CANDIDATE, ANCHOR, event_type="Approval")]],
    )
    settings = live_settings()

    run = await collect_behavioral_evidence(
        settings, default_request(), out_root=tmp_path / "out", data_dir=data_dir, write=True
    )

    assert run.rows == []
    assert run.excluded_non_transfer_count == 1
    assert behavioral_evidence_rows(data_dir) == []


# --- 11: pagination preserves all filters --------------------------------------


@respx.mock
async def test_pagination_preserves_all_filters(tmp_path: Path) -> None:
    data_dir = known_candidate_dir(tmp_path)
    route = route_by_direction(
        incoming_pages=[[]],
        outgoing_pages=[
            [trc20_row("f1" * 16, CANDIDATE, ANCHOR, value=1)],
            [trc20_row("f2" * 16, CANDIDATE, ANCHOR, value=2)],
        ],
    )
    settings = live_settings()

    run = await collect_behavioral_evidence(
        settings,
        default_request(page_limit=5, event_limit=100),
        out_root=tmp_path / "out",
        data_dir=data_dir,
        write=True,
    )

    assert len(run.rows) == 2
    outgoing_calls = [
        call for call in route.calls if call.request.url.params.get("only_from") == "true"
    ]
    assert len(outgoing_calls) == 2
    first_params = dict(outgoing_calls[0].request.url.params)
    second_params = dict(outgoing_calls[1].request.url.params)
    first_params.pop("fingerprint", None)
    second_params.pop("fingerprint", None)
    assert first_params == second_params  # every other filter identical across pages
    assert "fingerprint" in dict(outgoing_calls[1].request.url.params)


# --- 12: budget exhaustion stops before the next request -----------------------


@respx.mock
async def test_budget_exhaustion_stops_before_the_next_request(tmp_path: Path) -> None:
    data_dir = known_candidate_dir(tmp_path)
    route = route_by_direction(
        incoming_pages=[[trc20_row("aa" * 32, OTHER, CANDIDATE)]],
        outgoing_pages=[[trc20_row("bb" * 32, CANDIDATE, ANCHOR)]],
    )
    settings = live_settings()

    run = await collect_behavioral_evidence(
        settings,
        default_request(max_requests=1),
        out_root=tmp_path / "out",
        data_dir=data_dir,
        write=True,
    )

    assert run.requests_used == 1
    assert run.truncated_by_request_budget is True
    assert route.call_count == 1  # the outgoing-direction call never happened
    outgoing_calls = [
        call for call in route.calls if call.request.url.params.get("only_from") == "true"
    ]
    assert len(outgoing_calls) == 0


# --- 13: behavioral evidence cannot change verified anchors or review state ---


@respx.mock
async def test_behavioral_evidence_cannot_modify_verified_anchors(tmp_path: Path) -> None:
    data_dir = known_candidate_dir(tmp_path)
    before_hash = None
    va_path = data_dir / "verified_anchors.csv"
    if va_path.exists():
        before_hash = va_path.read_bytes()

    route_by_direction(
        incoming_pages=[[trc20_row("aa" * 32, OTHER, CANDIDATE)]],
        outgoing_pages=[
            [trc20_row("bb" * 32, CANDIDATE, ANCHOR)] for _ in range(5)
        ],
    )
    settings = live_settings()

    await collect_behavioral_evidence(
        settings, default_request(), out_root=tmp_path / "out", data_dir=data_dir, write=True
    )

    after_exists = va_path.exists()
    assert after_exists == (before_hash is not None)
    if before_hash is not None:
        assert va_path.read_bytes() == before_hash


@respx.mock
async def test_the_existing_deposit_candidate_remains_unreviewed(tmp_path: Path) -> None:
    data_dir = known_candidate_dir(tmp_path)
    route_by_direction(
        incoming_pages=[[trc20_row("aa" * 32, OTHER, CANDIDATE)]],
        outgoing_pages=[[trc20_row("bb" * 32, CANDIDATE, ANCHOR)] for _ in range(5)],
    )
    settings = live_settings()

    await collect_behavioral_evidence(
        settings, default_request(), out_root=tmp_path / "out", data_dir=data_dir, write=True
    )

    (row,) = [r for r in deposit_candidate_rows(data_dir) if r["address"] == CANDIDATE]
    assert row["review_state"] == "unreviewed"
    assert row["address_role"] == "unknown"


# --- 14: shared behavior between two candidates does not merge them -----------


@respx.mock
async def test_shared_counterparty_behavior_does_not_merge_two_candidates(tmp_path: Path) -> None:
    """Both candidates forward heavily to the same anchor; each collection is
    independent and neither run's output references the other."""
    data_dir = known_candidate_dir(tmp_path)
    second_candidate = "TRTqwgSLfUVziqWCyN6ZMThBkMgRvSaYtE"
    source = tmp_path / "second.csv"
    source.write_text(
        "network,address,entity_name,entity_type,assertion_type,address_role\n"
        f"tron,{second_candidate},unknown,unknown,deposit_candidate,unknown\n"
    )
    import_anchors(
        SourceDocument(
            path=source,
            url=f"tron:chain-observation:incoming-to:{ANCHOR}:second",
            disclosure_kind=DisclosureKind.chain_observation,
            disclosure_date=dt.datetime(2026, 8, 10, 15, 59, 54, tzinfo=dt.UTC),
            retrieved_at=dt.datetime(2026, 9, 20, tzinfo=dt.UTC),
            methodology="fixture",
            label_set_version="fixture-1",
        ),
        network_key="tron",
        out_dir=data_dir,
        write=True,
    )

    route_by_direction(
        incoming_pages=[[]],
        outgoing_pages=[[trc20_row("11" * 32, CANDIDATE, ANCHOR, value=1_000_000)]],
    )
    settings = live_settings()
    run_a = await collect_behavioral_evidence(
        settings, default_request(), out_root=tmp_path / "out_a", data_dir=data_dir, write=True
    )

    second_url = f"{BASE}/v1/accounts/{second_candidate}/transactions/trc20"
    respx.get(second_url).mock(
        side_effect=lambda request: httpx.Response(
            200,
            json={
                "data": (
                    [trc20_row("22" * 32, second_candidate, ANCHOR, value=9_000_000)]
                    if request.url.params.get("only_from") == "true"
                    else []
                ),
                "meta": {},
            },
        )
    )
    run_b = await collect_behavioral_evidence(
        settings,
        default_request(candidate_address=second_candidate),
        out_root=tmp_path / "out_b",
        data_dir=data_dir,
        write=True,
    )

    a_refs = {r.event_reference for r in run_a.rows}
    b_refs = {r.event_reference for r in run_b.rows}
    assert a_refs.isdisjoint(b_refs)
    assert {r.candidate_address for r in run_a.rows} == {CANDIDATE}
    assert {r.candidate_address for r in run_b.rows} == {second_candidate}

    rows = behavioral_evidence_rows(data_dir)
    assert {r["candidate_address"] for r in rows} == {CANDIDATE, second_candidate}


# --- load_preferred_behavioral_run trusts the manifest, not row coverage_status


def test_load_preferred_behavioral_run_uses_manifest_flags_not_row_coverage_status(
    tmp_path: Path,
) -> None:
    """A row's own coverage_status can be stale -- e.g. carried over from an
    earlier, truncated run that a later, complete run's rows happened to
    reproduce identically. The loader must derive completeness only from
    this run's own manifest.json, never by reading rows' coverage_status."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    manifest = {
        "run_id": "test-run",
        "query": {
            "candidate_address": CANDIDATE,
            "analysis_start": "2026-08-10T13:59:54+00:00",
            "analysis_cutoff": "2026-08-10T16:59:54+00:00",
        },
        "truncated_by_page_limit": {"incoming": False, "outgoing": False},
        "truncated_by_event_limit": {"incoming": False, "outgoing": False},
        "truncated_by_request_budget": False,
    }
    evidence = {
        "rows": [
            {
                "network": "tron", "candidate_address": CANDIDATE, "direction": "outgoing",
                "counterparty_address": ANCHOR, "token_contract": TOKEN_CONTRACT,
                "tx_hash": "aa" * 32, "event_index": "", "event_reference": "tron:aa:unindexed:1",
                "amount_base_units": "1000", "block_number": "", "block_time": HISTORICAL_MS,
                "execution_status": "unknown", "confirmation_state": "confirmed",
                "ordering_ambiguous": "true", "evidence_reference": "x",
                "acquisition_window_start": "2026-08-10T13:59:54+00:00",
                "acquisition_window_end": "2026-08-10T16:59:54+00:00",
                # Stale: this row was first captured by an earlier, truncated
                # run and still says "partial" even though this run's own
                # manifest above says outgoing is fully complete.
                "coverage_status": "partial",
            }
        ]
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest))
    (run_dir / "evidence.json").write_text(json.dumps(evidence))

    run = load_preferred_behavioral_run(run_dir)

    assert run.incoming_complete is True
    assert run.outgoing_complete is True
    assert run.rows[0]["coverage_status"] == "partial"  # the stale row value is preserved verbatim
    assert run.run_id == "test-run"
