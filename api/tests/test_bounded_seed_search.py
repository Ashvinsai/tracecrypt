"""A supplied seed event is found through a bounded time window and a cheap
transaction-id match, without scanning a sender's full history or enriching
transactions the search never needed to enrich.

No network access; every response body uses only documented field names, same
as ``test_tron_adapter.py``. These tests exercise the whole path through
``trace_service.run_trace`` -- the real seed-search-then-tracer sequence --
rather than reaching into ``_find_seed_event`` directly.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import httpx
import pytest
import respx

from app.adapters.base import AssetRef
from app.adapters.tron import TronGridAdapter
from app.core.settings import AppEnv, DataMode, Settings
from app.services.anchor_import import DisclosureKind, SourceDocument, import_anchors
from app.services.candidate_review import ReviewAction, ReviewRequest, review_candidates
from app.services.trace_service import TraceUnavailable, run_trace

BASE = "https://api.trongrid.io"
USDT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
SENDER = "TEocPZsTTRAK9x5TR66GnEbxKKU8zrNxgM"
RECIPIENT = "TBvGC1Nd8i5wmj185HTdoTWAZPmRUTFBZz"
OTHER_PEER = "TRTqwgSLfUVziqWCyN6ZMThBkMgRvSaYtE"
ASSET = AssetRef("tron", USDT, 6, "USDT")

SNAPSHOT = dt.datetime(2026, 8, 10, 15, 59, 54, tzinfo=dt.UTC)
SNAPSHOT_MS = int(SNAPSHOT.timestamp() * 1000)
START = SNAPSHOT - dt.timedelta(seconds=1)
CUTOFF = SNAPSHOT + dt.timedelta(seconds=1)

TARGET_TX = "aa" * 32
OTHER_TX = "bb" * 32
SEED_REF = f"tron:{TARGET_TX}:0"


def history_row(tx: str, frm: str, to: str, value: str) -> dict:
    return {
        "transaction_id": tx,
        "block_timestamp": SNAPSHOT_MS,
        "from": frm,
        "to": to,
        "type": "Transfer",
        "value": value,
        "token_info": {"symbol": "USDT", "address": USDT, "decimals": 6, "name": "Tether USD"},
    }


def event_row(tx: str, index: int, frm: str, to: str, value: str) -> dict:
    return {
        "block_number": 85235532,
        "block_timestamp": SNAPSHOT_MS,
        "contract_address": USDT,
        "event_index": index,
        "event_name": "Transfer",
        "transaction_id": tx,
        "result": {"from": frm, "to": to, "value": value},
    }


def accepted_label_dir(tmp_path: Path) -> Path:
    """One accepted service_control claim for RECIPIENT, scoped to SNAPSHOT only."""
    data_dir = tmp_path / "data"
    source = tmp_path / "disclosure.csv"
    source.write_text(
        "network,address,entity_name,entity_type,assertion_type,address_role\n"
        f"tron,{RECIPIENT},Example Exchange,exchange,service_control,unknown\n"
    )
    import_anchors(
        SourceDocument(
            path=source,
            url="https://example.test/por",
            disclosure_kind=DisclosureKind.proof_of_reserves,
            disclosure_date=SNAPSHOT,
            retrieved_at=SNAPSHOT,
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
                address=RECIPIENT,
                action=ReviewAction.accept,
                reviewer="investigator-1",
                rationale="fixture",
                evidence_inspected=("https://example.test/por",),
            )
        ],
        write=True,
    )
    # The importer never sets valid_to; pin it to the snapshot instant so the
    # label covers exactly SNAPSHOT and nothing else (as the real candidate's
    # own scope does).
    import csv

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


def live_settings(tmp_path: Path, **overrides) -> Settings:
    kwargs = {
        "app_env": AppEnv.dev,
        "data_mode": DataMode.LIVE,
        "tron_api_base": BASE,
        "tron_api_key": "test-key-not-a-real-one",
    }
    if "label_dir" not in overrides:
        kwargs["label_dir"] = str(accepted_label_dir(tmp_path))
    kwargs.update(overrides)
    return Settings(**kwargs)


@respx.mock
async def test_a_supplied_seed_is_found_without_scanning_earlier_history(
    tmp_path: Path,
) -> None:
    """The bounded window means the server-side query itself, not client-side
    filtering, is what keeps a much larger real history out of the page."""
    history_route = respx.get(f"{BASE}/v1/accounts/{SENDER}/transactions/trc20").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    history_row(OTHER_TX, SENDER, OTHER_PEER, "1"),
                    history_row(TARGET_TX, SENDER, RECIPIENT, "72140000"),
                ],
                "meta": {},
            },
        )
    )
    other_events = respx.get(f"{BASE}/v1/transactions/{OTHER_TX}/events").mock(
        return_value=httpx.Response(
            200, json={"data": [event_row(OTHER_TX, 0, SENDER, OTHER_PEER, "1")]}
        )
    )
    target_events = respx.get(f"{BASE}/v1/transactions/{TARGET_TX}/events").mock(
        return_value=httpx.Response(
            200, json={"data": [event_row(TARGET_TX, 0, SENDER, RECIPIENT, "72140000")]}
        )
    )

    settings = live_settings(tmp_path)
    result = await run_trace(
        settings,
        seed_address=SENDER,
        asset=ASSET,
        seed_event_reference=SEED_REF,
        analysis_cutoff=CUTOFF,
        analysis_start=START,
        adapter=TronGridAdapter(settings.tron_api_base, api_key=settings.tron_api_key),
    )

    assert history_route.call_count == 1  # one page, bounded by start/cutoff
    assert int(history_route.calls[0].request.url.params["min_timestamp"]) == int(
        START.timestamp() * 1000
    )
    # The unrelated transaction sharing the page was never enriched: only the
    # matched transaction id paid for an events-endpoint call (B).
    assert other_events.call_count == 0
    assert target_events.call_count == 1

    services = [b for b in result.branch_endings if b.endpoint_class.value == "known_service"]
    (service,) = services
    assert service.address == RECIPIENT
    assert service.label is not None
    assert service.label.entity_name == "Example Exchange"


@respx.mock
async def test_the_label_is_evaluated_at_the_transfers_own_time_not_today(
    tmp_path: Path,
) -> None:
    """The accepted claim covers exactly SNAPSHOT. A cutoff far in the future
    must not make the transfer's own (in-scope) arrival time get treated as
    out of scope, and must not substitute 'now' for the transfer's time."""
    respx.get(f"{BASE}/v1/accounts/{SENDER}/transactions/trc20").mock(
        return_value=httpx.Response(
            200, json={"data": [history_row(TARGET_TX, SENDER, RECIPIENT, "72140000")], "meta": {}}
        )
    )
    respx.get(f"{BASE}/v1/transactions/{TARGET_TX}/events").mock(
        return_value=httpx.Response(
            200, json={"data": [event_row(TARGET_TX, 0, SENDER, RECIPIENT, "72140000")]}
        )
    )

    settings = live_settings(tmp_path)
    far_future_cutoff = SNAPSHOT + dt.timedelta(days=365)
    result = await run_trace(
        settings,
        seed_address=SENDER,
        asset=ASSET,
        seed_event_reference=SEED_REF,
        analysis_cutoff=far_future_cutoff,
        analysis_start=START,
        adapter=TronGridAdapter(settings.tron_api_base, api_key=settings.tron_api_key),
    )

    services = [b for b in result.branch_endings if b.endpoint_class.value == "known_service"]
    assert len(services) == 1, (
        "the transfer's own block_time (SNAPSHOT) is what the label is checked "
        "against, not the far-future cutoff -- and it is in scope"
    )


@respx.mock
async def test_seed_not_found_within_the_window_reports_the_bounded_result(
    tmp_path: Path,
) -> None:
    """No silent restart from genesis and no silent widening: an empty,
    successful page within the window is a clear, bounded 'not found'."""
    respx.get(f"{BASE}/v1/accounts/{SENDER}/transactions/trc20").mock(
        return_value=httpx.Response(200, json={"data": [], "meta": {}})
    )
    settings = live_settings(tmp_path)

    with pytest.raises(TraceUnavailable) as caught:
        await run_trace(
            settings,
            seed_address=SENDER,
            asset=ASSET,
            seed_event_reference=SEED_REF,
            analysis_cutoff=CUTOFF,
            analysis_start=START,
            adapter=TronGridAdapter(settings.tron_api_base, api_key=settings.tron_api_key),
        )
    message = str(caught.value)
    assert START.isoformat() in message
    assert CUTOFF.isoformat() in message
