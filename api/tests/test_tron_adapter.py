"""TronGrid adapter against the documented response shapes.

No network access. Every response body here uses only field names documented at
the three TRON reference pages cited in ``app/adapters/tron.py``.
"""

from __future__ import annotations

import datetime as dt

import httpx
import pytest
import respx

from app.adapters.base import AssetRef, Direction, ProviderError, ProviderErrorClass
from app.adapters.tron import TronGridAdapter
from app.core.settings import DataMode
from app.models.enums import EventKind, ExecutionStatus

BASE = "https://api.trongrid.io"
USDT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
ACCOUNT = "TEocPZsTTRAK9x5TR66GnEbxKKU8zrNxgM"
PEER_A = "TMrjWHAq1BPg9iG9ZaBTsG1AoxWERR29Mz"
PEER_B = "TRTqwgSLfUVziqWCyN6ZMThBkMgRvSaYtE"
CUTOFF = dt.datetime(2026, 9, 1, tzinfo=dt.UTC)
ASSET = AssetRef("tron", USDT, 6, "USDT")


def history_row(tx: str, frm: str, to: str, value: str, *, kind: str = "Transfer") -> dict:
    return {
        "transaction_id": tx,
        "block_timestamp": 1767225600000,
        "from": frm,
        "to": to,
        "type": kind,
        "value": value,
        "token_info": {"symbol": "USDT", "address": USDT, "decimals": 6, "name": "Tether USD"},
    }


def event_row(tx: str, index: int, frm: str, to: str, value: str) -> dict:
    return {
        "block_number": 71000010,
        "block_timestamp": 1767225600000,
        "contract_address": USDT,
        "event_index": index,
        "event_name": "Transfer",
        "transaction_id": tx,
        "result": {"from": frm, "to": to, "value": value},
        "result_type": {"from": "address", "to": "address", "value": "uint256"},
    }


def adapter(**kwargs) -> TronGridAdapter:
    return TronGridAdapter(BASE, api_key="test-key", **kwargs)


@respx.mock
async def test_multiple_transfers_in_one_transaction_get_distinct_indices() -> None:
    """The history endpoint has no event index; enrichment supplies the real one."""
    tx = "aa" * 32
    respx.get(f"{BASE}/v1/accounts/{ACCOUNT}/transactions/trc20").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    history_row(tx, ACCOUNT, PEER_A, "100000000"),
                    history_row(tx, ACCOUNT, PEER_B, "7000000"),
                ],
                "meta": {"at": 1767225600000, "page_size": 2},
            },
        )
    )
    respx.get(f"{BASE}/v1/transactions/{tx}/events").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    event_row(tx, 0, ACCOUNT, PEER_A, "100000000"),
                    event_row(tx, 1, ACCOUNT, PEER_B, "7000000"),
                ]
            },
        )
    )

    page = await adapter().fetch_transfers(
        address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
    )
    refs = {e.event_reference for e in page.events}
    assert refs == {f"tron:{tx}:0", f"tron:{tx}:1"}
    assert all(not e.ordering_ambiguous for e in page.events)
    assert sorted(e.amount_base_units for e in page.events) == [7_000_000, 100_000_000]


@respx.mock
async def test_missing_enrichment_yields_ambiguity_not_a_guessed_index() -> None:
    """D005: with no event index available, the position is unknown, not zero."""
    tx = "bb" * 32
    respx.get(f"{BASE}/v1/accounts/{ACCOUNT}/transactions/trc20").mock(
        return_value=httpx.Response(
            200, json={"data": [history_row(tx, ACCOUNT, PEER_A, "100000000")], "meta": {}}
        )
    )
    respx.get(f"{BASE}/v1/transactions/{tx}/events").mock(
        return_value=httpx.Response(500, json={"error": "upstream"})
    )

    page = await adapter().fetch_transfers(
        address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
    )
    event = page.events[0]
    assert event.ordering_ambiguous is True
    assert event.event_index is None
    assert event.chain_sequence is None
    assert event.event_reference.startswith(f"tron:{tx}:unindexed:")
    assert not event.event_reference.endswith(":0")


@respx.mock
async def test_identical_transfers_in_one_transaction_stay_ambiguous() -> None:
    """Two content-identical events cannot be told apart, so neither is assigned."""
    tx = "cc" * 32
    respx.get(f"{BASE}/v1/accounts/{ACCOUNT}/transactions/trc20").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    history_row(tx, ACCOUNT, PEER_A, "5000000"),
                    history_row(tx, ACCOUNT, PEER_A, "5000000"),
                ],
                "meta": {},
            },
        )
    )
    respx.get(f"{BASE}/v1/transactions/{tx}/events").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    event_row(tx, 0, ACCOUNT, PEER_A, "5000000"),
                    event_row(tx, 1, ACCOUNT, PEER_A, "5000000"),
                ]
            },
        )
    )
    page = await adapter().fetch_transfers(
        address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
    )
    assert all(e.ordering_ambiguous for e in page.events)


@respx.mock
async def test_approval_is_not_a_transfer() -> None:
    tx = "dd" * 32
    respx.get(f"{BASE}/v1/accounts/{ACCOUNT}/transactions/trc20").mock(
        return_value=httpx.Response(
            200,
            json={"data": [history_row(tx, ACCOUNT, USDT, "0", kind="Approval")], "meta": {}},
        )
    )
    respx.get(f"{BASE}/v1/transactions/{tx}/events").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    page = await adapter().fetch_transfers(
        address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
    )
    assert page.events[0].event_kind is EventKind.approval


@respx.mock
async def test_execution_status_is_unknown_from_history_alone() -> None:
    """The history endpoint documents no status; claiming success would invent one."""
    tx = "ee" * 32
    respx.get(f"{BASE}/v1/accounts/{ACCOUNT}/transactions/trc20").mock(
        return_value=httpx.Response(
            200, json={"data": [history_row(tx, ACCOUNT, PEER_A, "1")], "meta": {}}
        )
    )
    respx.get(f"{BASE}/v1/transactions/{tx}/events").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    page = await adapter().fetch_transfers(
        address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
    )
    assert page.events[0].execution_status is ExecutionStatus.unknown


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, ProviderErrorClass.authentication),
        (403, ProviderErrorClass.authentication),
        (429, ProviderErrorClass.rate_limit),
        (402, ProviderErrorClass.quota),
        (500, ProviderErrorClass.http_error),
    ],
)
@respx.mock
async def test_provider_errors_are_classified_not_swallowed(
    status: int, expected: ProviderErrorClass
) -> None:
    """T3: an error is never a successful empty history."""
    respx.get(f"{BASE}/v1/accounts/{ACCOUNT}/transactions/trc20").mock(
        return_value=httpx.Response(status, json={"error": "nope"})
    )
    with pytest.raises(ProviderError) as caught:
        await adapter(enrich_events=False).fetch_transfers(
            address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
        )
    assert caught.value.error_class is expected


@respx.mock
async def test_timeout_is_classified() -> None:
    respx.get(f"{BASE}/v1/accounts/{ACCOUNT}/transactions/trc20").mock(
        side_effect=httpx.ConnectTimeout("timed out")
    )
    with pytest.raises(ProviderError) as caught:
        await adapter(enrich_events=False).fetch_transfers(
            address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
        )
    assert caught.value.error_class is ProviderErrorClass.timeout


@respx.mock
async def test_pagination_keeps_parameters_stable_and_carries_the_fingerprint() -> None:
    """C02: only the cursor changes between pages."""
    seen: list[dict[str, str]] = []
    tx1, tx2 = "11" * 32, "22" * 32

    def responder(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        if "fingerprint" not in request.url.params:
            return httpx.Response(
                200,
                json={
                    "data": [history_row(tx1, ACCOUNT, PEER_A, "1")],
                    "meta": {"fingerprint": "CURSOR-1"},
                },
            )
        return httpx.Response(
            200, json={"data": [history_row(tx2, ACCOUNT, PEER_B, "2")], "meta": {}}
        )

    respx.get(f"{BASE}/v1/accounts/{ACCOUNT}/transactions/trc20").mock(side_effect=responder)
    tron = adapter(enrich_events=False)

    first = await tron.fetch_transfers(
        address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
    )
    assert first.next_cursor == "CURSOR-1"
    second = await tron.fetch_transfers(
        address=ACCOUNT,
        asset=ASSET,
        direction=Direction.outgoing,
        analysis_cutoff=CUTOFF,
        cursor=first.next_cursor,
    )
    assert second.next_cursor is None

    assert seen[1].pop("fingerprint") == "CURSOR-1"
    assert seen[0] == seen[1], "only the cursor may differ between pages"
    assert seen[0]["contract_address"] == USDT
    assert seen[0]["only_from"] == "true"
    assert seen[0]["only_confirmed"] == "true"
    assert int(seen[0]["max_timestamp"]) == int(CUTOFF.timestamp() * 1000)


@respx.mock
async def test_api_key_is_sent_as_a_header_not_a_query_parameter() -> None:
    captured: list[httpx.Request] = []

    def responder(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"data": [], "meta": {}})

    respx.get(f"{BASE}/v1/accounts/{ACCOUNT}/transactions/trc20").mock(side_effect=responder)
    await adapter(enrich_events=False).fetch_transfers(
        address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
    )
    assert captured[0].headers["TRON-PRO-API-KEY"] == "test-key"
    assert "test-key" not in str(captured[0].url)


def test_adapter_refuses_synthetic_mode() -> None:
    """D009: the live adapter must not be used to serve a synthetic demo."""
    with pytest.raises(ProviderError) as caught:
        adapter().assert_mode_allowed(DataMode.SYNTHETIC)
    assert caught.value.error_class is ProviderErrorClass.unsupported


# --- bounded seed search: time window, cheap-match-before-enrich, budget ----

START = dt.datetime(2026, 8, 10, 15, 59, 53, tzinfo=dt.UTC)


@respx.mock
async def test_a_start_bound_reaches_the_first_and_subsequent_requests() -> None:
    """A: min_timestamp is a real query parameter, preserved across pagination,
    not a client-side filter applied after a wider page comes back."""
    seen: list[dict[str, str]] = []
    tx1, tx2 = "11" * 32, "22" * 32

    def responder(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        if "fingerprint" not in request.url.params:
            return httpx.Response(
                200,
                json={
                    "data": [history_row(tx1, ACCOUNT, PEER_A, "1")],
                    "meta": {"fingerprint": "CURSOR-1"},
                },
            )
        return httpx.Response(
            200, json={"data": [history_row(tx2, ACCOUNT, PEER_B, "2")], "meta": {}}
        )

    respx.get(f"{BASE}/v1/accounts/{ACCOUNT}/transactions/trc20").mock(side_effect=responder)
    tron = adapter(enrich_events=False)

    first = await tron.fetch_transfers(
        address=ACCOUNT,
        asset=ASSET,
        direction=Direction.outgoing,
        analysis_cutoff=CUTOFF,
        analysis_start=START,
    )
    await tron.fetch_transfers(
        address=ACCOUNT,
        asset=ASSET,
        direction=Direction.outgoing,
        analysis_cutoff=CUTOFF,
        analysis_start=START,
        cursor=first.next_cursor,
    )

    assert int(seen[0]["min_timestamp"]) == int(START.timestamp() * 1000)
    assert int(seen[1]["min_timestamp"]) == int(START.timestamp() * 1000)
    assert int(seen[0]["max_timestamp"]) == int(CUTOFF.timestamp() * 1000)


@respx.mock
async def test_no_start_bound_omits_min_timestamp_entirely() -> None:
    """Unset stays unset -- a default of 0 would silently narrow every other
    caller that never asked for a lower bound."""
    route = respx.get(f"{BASE}/v1/accounts/{ACCOUNT}/transactions/trc20").mock(
        return_value=httpx.Response(200, json={"data": [], "meta": {}})
    )
    await adapter(enrich_events=False).fetch_transfers(
        address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
    )
    assert "min_timestamp" not in route.calls.last.request.url.params


@respx.mock
async def test_resolve_seed_event_enriches_only_the_matched_transaction() -> None:
    """B: given a raw (unenriched) transfer, resolving it costs exactly one
    events-endpoint call for that one transaction, never a page-wide scan."""
    target_tx = "33" * 32
    events_route = respx.get(f"{BASE}/v1/transactions/{target_tx}/events").mock(
        return_value=httpx.Response(
            200, json={"data": [event_row(target_tx, 0, ACCOUNT, PEER_A, "500")]}
        )
    )

    tron = adapter(enrich_events=False)
    respx.get(f"{BASE}/v1/accounts/{ACCOUNT}/transactions/trc20").mock(
        return_value=httpx.Response(
            200, json={"data": [history_row(target_tx, ACCOUNT, PEER_A, "500")], "meta": {}}
        )
    )
    page = await tron.fetch_transfers(
        address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
    )
    (raw_transfer,) = page.events
    assert raw_transfer.ordering_ambiguous is True  # unenriched, as requested

    resolved = await tron.resolve_seed_event(raw_transfer, ASSET)

    assert events_route.call_count == 1
    assert resolved is not None
    assert resolved.event_index == 0
    assert resolved.ordering_ambiguous is False
    assert resolved.event_reference == f"tron:{target_tx}:0"


@respx.mock
async def test_resolve_seed_event_refuses_a_transaction_id_match_that_does_not_reconcile() -> (
    None
):
    """A shared transaction id is not enough by itself (D005): the decoded
    event detail must actually agree on participants and amount."""
    target_tx = "44" * 32
    respx.get(f"{BASE}/v1/transactions/{target_tx}/events").mock(
        return_value=httpx.Response(
            200, json={"data": [event_row(target_tx, 0, PEER_A, PEER_B, "999999")]}
        )
    )
    tron = adapter(enrich_events=False)
    respx.get(f"{BASE}/v1/accounts/{ACCOUNT}/transactions/trc20").mock(
        return_value=httpx.Response(
            200, json={"data": [history_row(target_tx, ACCOUNT, PEER_A, "500")], "meta": {}}
        )
    )
    page = await tron.fetch_transfers(
        address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
    )
    (raw_transfer,) = page.events

    resolved = await tron.resolve_seed_event(raw_transfer, ASSET)

    assert resolved is None


@respx.mock
async def test_budget_exhaustion_prevents_the_next_request() -> None:
    """C: the check happens before the request is sent -- a page needing
    enrichment stops at the cap rather than making one more call."""
    tx = "55" * 32
    history_route = respx.get(f"{BASE}/v1/accounts/{ACCOUNT}/transactions/trc20").mock(
        return_value=httpx.Response(
            200, json={"data": [history_row(tx, ACCOUNT, PEER_A, "500")], "meta": {}}
        )
    )
    events_route = respx.get(f"{BASE}/v1/transactions/{tx}/events").mock(
        return_value=httpx.Response(200, json={"data": [event_row(tx, 0, ACCOUNT, PEER_A, "500")]})
    )

    tron = adapter(enrich_events=True, max_requests=1)
    with pytest.raises(ProviderError) as caught:
        await tron.fetch_transfers(
            address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
        )

    assert caught.value.error_class is ProviderErrorClass.budget_exhausted
    assert history_route.call_count == 1  # the one request the budget allowed
    assert events_route.call_count == 0  # never attempted -- budget checked first
    assert tron.request_count == 1


@respx.mock
async def test_budget_of_zero_refuses_the_very_first_request() -> None:
    route = respx.get(f"{BASE}/v1/accounts/{ACCOUNT}/transactions/trc20").mock(
        return_value=httpx.Response(200, json={"data": [], "meta": {}})
    )
    tron = adapter(enrich_events=False, max_requests=0)
    with pytest.raises(ProviderError) as caught:
        await tron.fetch_transfers(
            address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
        )
    assert caught.value.error_class is ProviderErrorClass.budget_exhausted
    assert route.call_count == 0


@respx.mock
async def test_budget_exhaustion_during_enrichment_is_never_read_as_empty_history() -> None:
    """A caught-and-swallowed ProviderError inside enrichment must not turn
    exhaustion into a clean, ambiguous-but-successful event (C)."""
    tx = "66" * 32
    respx.get(f"{BASE}/v1/accounts/{ACCOUNT}/transactions/trc20").mock(
        return_value=httpx.Response(
            200, json={"data": [history_row(tx, ACCOUNT, PEER_A, "500")], "meta": {}}
        )
    )
    respx.get(f"{BASE}/v1/transactions/{tx}/events").mock(
        return_value=httpx.Response(200, json={"data": [event_row(tx, 0, ACCOUNT, PEER_A, "500")]})
    )

    tron = adapter(enrich_events=True, max_requests=1)
    with pytest.raises(ProviderError) as caught:
        await tron.fetch_transfers(
            address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
        )
    assert caught.value.error_class is ProviderErrorClass.budget_exhausted


@respx.mock
async def test_a_replay_client_is_never_budget_limited() -> None:
    """A cache read is not a network request (C): a caller-injected client --
    what replay always uses -- is exempt from max_requests entirely."""
    respx.get(f"{BASE}/v1/accounts/{ACCOUNT}/transactions/trc20").mock(
        return_value=httpx.Response(200, json={"data": [], "meta": {}})
    )
    injected_client = httpx.AsyncClient()
    tron = TronGridAdapter(
        BASE, api_key="test-key", client=injected_client, enrich_events=False, max_requests=0
    )
    page = await tron.fetch_transfers(
        address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
    )
    assert page.events == []
    await injected_client.aclose()


def _hex20(base58_address: str) -> str:
    """The events endpoint's own address encoding: 20-byte hex, no 0x41 prefix."""
    from app.services.addresses import _b58check_decode

    return _b58check_decode(base58_address)[1:].hex()


@respx.mock
async def test_enrichment_matches_across_the_events_endpoints_hex_addresses() -> None:
    """Real TronGrid returns base58 participants from the history endpoint and
    20-byte hex participants (no 0x41 prefix) from the events endpoint for the
    very same transfer. A raw string comparison between the two never matches;
    this is the regression case for that -- observed against real data, not
    hypothesized."""
    tx = "77" * 32
    respx.get(f"{BASE}/v1/accounts/{ACCOUNT}/transactions/trc20").mock(
        return_value=httpx.Response(
            200, json={"data": [history_row(tx, ACCOUNT, PEER_A, "72140000")], "meta": {}}
        )
    )
    respx.get(f"{BASE}/v1/transactions/{tx}/events").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "block_number": 85235532,
                        "block_timestamp": 1767225600000,
                        "contract_address": USDT,
                        "event_index": 0,
                        "event_name": "Transfer",
                        "transaction_id": tx,
                        "result": {
                            "from": f"0x{_hex20(ACCOUNT)}",
                            "to": f"0x{_hex20(PEER_A)}",
                            "value": "72140000",
                        },
                    }
                ]
            },
        )
    )

    tron = adapter(enrich_events=True)
    page = await tron.fetch_transfers(
        address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
    )
    (transfer,) = page.events
    assert transfer.event_index == 0
    assert transfer.ordering_ambiguous is False
    assert transfer.event_reference == f"tron:{tx}:0"


@respx.mock
async def test_resolve_seed_event_matches_hex_addresses_from_the_events_endpoint() -> None:
    """Same hex-vs-base58 case, through the single-transaction resolver B uses."""
    tx = "88" * 32
    events_route = respx.get(f"{BASE}/v1/transactions/{tx}/events").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "block_number": 85235532,
                        "block_timestamp": 1767225600000,
                        "contract_address": USDT,
                        "event_index": 0,
                        "event_name": "Transfer",
                        "transaction_id": tx,
                        "result": {
                            "from": f"0x{_hex20(ACCOUNT)}",
                            "to": f"0x{_hex20(PEER_A)}",
                            "value": "72140000",
                        },
                    }
                ]
            },
        )
    )
    respx.get(f"{BASE}/v1/accounts/{ACCOUNT}/transactions/trc20").mock(
        return_value=httpx.Response(
            200, json={"data": [history_row(tx, ACCOUNT, PEER_A, "72140000")], "meta": {}}
        )
    )
    tron = adapter(enrich_events=False)
    page = await tron.fetch_transfers(
        address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
    )
    (raw_transfer,) = page.events

    resolved = await tron.resolve_seed_event(raw_transfer, ASSET)

    assert events_route.call_count == 1
    assert resolved is not None
    assert resolved.event_index == 0
    assert resolved.event_reference == f"tron:{tx}:0"
