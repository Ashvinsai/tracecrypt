"""Generic EVM adapter against documented JSON-RPC response shapes.

Every test runs once per configured EVM network (``ethereum`` chain 1, ``bsc``
chain 56) through the same ``EvmRpcAdapter`` -- the ``network`` fixture below
swaps the module-level network, chain id and asset -- so a behavior that is
supposed to be generic is proven generic rather than copied per chain.

No network access: a small in-process fake node (``FakeEthNode``) answers
``eth_chainId``, ``eth_getBlockByNumber``, ``eth_getLogs``, and
``eth_getTransactionReceipt`` exactly as https://ethereum.org/en/developers/docs/apis/json-rpc/
documents them, wired in via ``respx`` the same way ``test_tron_adapter.py``
mocks TronGrid.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx

from app.adapters.base import AssetRef, Direction, ProviderError, ProviderErrorClass
from app.adapters.evm import TRANSFER_TOPIC, EvmRpcAdapter
from app.models.enums import ConfirmationState, ExecutionStatus

RPC_URL = "https://rpc.example.test/v1/secret-key-abc123"
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
ACCOUNT = "0x" + "11" * 19 + "1a"
PEER_A = "0x" + "22" * 19 + "2b"
PEER_B = "0x" + "33" * 19 + "3c"
CUTOFF = dt.datetime(2026, 9, 1, tzinfo=dt.UTC)
NETWORK = "ethereum"
CHAIN_ID = 1
ASSET = AssetRef(NETWORK, USDT, 6, "USDT")
NETWORK_CHAIN_IDS = {"ethereum": 1, "bsc": 56}


@pytest.fixture(params=sorted(NETWORK_CHAIN_IDS), autouse=True)
def network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Run the module's tests once per configured EVM network."""
    module = sys.modules[__name__]
    key = request.param
    monkeypatch.setattr(module, "NETWORK", key)
    monkeypatch.setattr(module, "CHAIN_ID", NETWORK_CHAIN_IDS[key])
    monkeypatch.setattr(module, "ASSET", AssetRef(key, USDT, 6, "USDT"))
    yield key


def topic(address: str) -> str:
    return "0x" + "0" * 24 + address[2:].lower()


def transfer_log(
    *,
    block_number: int,
    tx_index: int,
    log_index: int,
    tx_hash: str,
    frm: str,
    to: str,
    value: int,
    contract: str = USDT,
    removed: bool = False,
) -> dict[str, Any]:
    return {
        "address": contract,
        "topics": [TRANSFER_TOPIC, topic(frm), topic(to)],
        "data": "0x" + format(value, "064x"),
        "blockNumber": hex(block_number),
        "blockHash": "0x" + "aa" * 32,
        "transactionHash": tx_hash,
        "transactionIndex": hex(tx_index),
        "logIndex": hex(log_index),
        "removed": removed,
    }


def abi_string(value: str) -> str:
    """ABI-encode one dynamic ``string`` return value (offset, length, data)."""
    data = value.encode()
    padded = data.hex().ljust(((len(data) + 31) // 32) * 64, "0")
    return "0x" + format(32, "064x") + format(len(data), "064x") + padded


class FakeEthNode:
    """A minimal, documented-shape-only Ethereum JSON-RPC node."""

    def __init__(
        self,
        *,
        chain_id: int | None = None,
        latest: int = 2_000_000,
        block_time_start: int = 1_700_000_000,
        block_step: int = 12,
        blocks_per_timestamp: int = 1,
        finalized: int | None = None,
        safe: int | None = None,
    ) -> None:
        self.chain_id = CHAIN_ID if chain_id is None else chain_id
        self.latest = latest
        self.block_time_start = block_time_start
        self.block_step = block_step
        #: >1 models a chain producing several blocks within one second, so
        #: consecutive blocks share a (second-resolution) timestamp.
        self.blocks_per_timestamp = blocks_per_timestamp
        self.finalized = finalized
        self.safe = safe
        self.logs: list[dict[str, Any]] = []
        self.receipts: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, list[Any]]] = []
        #: (from_block, to_block) pairs that should answer with a provider error,
        #: for exercising range-splitting.
        self.fail_ranges: set[tuple[int, int]] = set()
        #: Ranges answered with HTTP 413 instead, as a real BSC provider did for
        #: spans over its block limit. HTTP failures are never recorded.
        self.http_fail_ranges: set[tuple[int, int]] = set()
        #: Token contract bytecode and ``decimals()``/``symbol()``/``name()``
        #: answers, for read-only token verification (``eth_getCode``/``eth_call``).
        self.code: dict[str, str] = {USDT: "0x6080604052"}
        self.token_meta: dict[str, tuple[int, str, str]] = {USDT: (6, "USDT", "Tether USD")}

    def block_time(self, number: int) -> int:
        return self.block_time_start + (number // self.blocks_per_timestamp) * self.block_step

    def block(self, number: int | None) -> dict[str, Any] | None:
        if number is None or number > self.latest or number < 0:
            return None
        return {"number": hex(number), "timestamp": hex(self.block_time(number))}

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        method, params = body["method"], body["params"]
        self.calls.append((method, params))

        if method == "eth_chainId":
            result: Any = hex(self.chain_id)
        elif method == "eth_getBlockByNumber":
            tag = params[0]
            if tag == "latest":
                number = self.latest
            elif tag == "finalized":
                number = self.finalized
            elif tag == "safe":
                number = self.safe
            else:
                number = int(tag, 16)
            result = self.block(number)
        elif method == "eth_getLogs":
            query = params[0]
            frm, to = int(query["fromBlock"], 16), int(query["toBlock"], 16)
            if (frm, to) in self.http_fail_ranges:
                return httpx.Response(413, text="request entity too large")
            if (frm, to) in self.fail_ranges:
                return httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "id": body["id"],
                        "error": {"code": -32005, "message": "query returned more than limit"},
                    },
                )
            topics = query["topics"]
            address = query.get("address")
            matched = []
            for log in self.logs:
                if address and log["address"].lower() != address.lower():
                    continue
                block_number = int(log["blockNumber"], 16)
                if not (frm <= block_number <= to):
                    continue
                ok = True
                for i, wanted in enumerate(topics):
                    if wanted is None:
                        continue
                    if log["topics"][i].lower() != wanted.lower():
                        ok = False
                        break
                if ok:
                    matched.append(log)
            result = matched
        elif method == "eth_getTransactionReceipt":
            result = self.receipts.get(params[0])
        elif method == "eth_getCode":
            result = self.code.get(params[0].lower(), "0x")
        elif method == "eth_call":
            call = params[0]
            meta = self.token_meta.get(call["to"].lower())
            if meta is None:
                result = "0x"
            elif call["data"] == "0x313ce567":  # decimals()
                result = "0x" + format(meta[0], "064x")
            elif call["data"] == "0x95d89b41":  # symbol()
                result = abi_string(meta[1])
            elif call["data"] == "0x06fdde03":  # name()
                result = abi_string(meta[2])
            else:  # pragma: no cover - defensive
                result = "0x"
        else:  # pragma: no cover - defensive
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "error": {"code": -32601, "message": "method not found"},
                },
            )
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})


def adapter(node: FakeEthNode, **kwargs: Any) -> EvmRpcAdapter:
    respx.post(RPC_URL).mock(side_effect=node.handle)
    return EvmRpcAdapter(RPC_URL, network_key=NETWORK, **kwargs)


# -- decoding -----------------------------------------------------------------


@respx.mock
async def test_erc20_transfer_decoded_correctly() -> None:
    node = FakeEthNode()
    tx = "0x" + "aa" * 32
    node.logs.append(
        transfer_log(
            block_number=100,
            tx_index=1,
            log_index=2,
            tx_hash=tx,
            frm=ACCOUNT,
            to=PEER_A,
            value=1_000_000,
        )
    )
    page = await adapter(node).fetch_transfers(
        address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
    )
    assert len(page.events) == 1
    event = page.events[0]
    assert event.from_address == ACCOUNT
    assert event.to_address == PEER_A
    assert event.amount_base_units == 1_000_000
    assert event.event_reference == f"eip155:{CHAIN_ID}:{tx}:2"
    assert event.tx_hash == tx
    assert event.chain_sequence == "000000000100:000001:000002"
    assert event.block_time == dt.datetime.fromtimestamp(node.block_time(100), tz=dt.UTC)


@respx.mock
async def test_two_logs_in_one_transaction_remain_distinct() -> None:
    tx = "0x" + "bb" * 32
    node = FakeEthNode()
    node.logs.append(
        transfer_log(
            block_number=5, tx_index=0, log_index=0, tx_hash=tx, frm=ACCOUNT, to=PEER_A, value=1
        )
    )
    node.logs.append(
        transfer_log(
            block_number=5, tx_index=0, log_index=1, tx_hash=tx, frm=ACCOUNT, to=PEER_B, value=2
        )
    )
    page = await adapter(node).fetch_transfers(
        address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
    )
    refs = {e.event_reference for e in page.events}
    assert refs == {f"eip155:{CHAIN_ID}:{tx}:0", f"eip155:{CHAIN_ID}:{tx}:1"}


@respx.mock
async def test_duplicate_log_seen_via_incoming_and_outgoing_dedupes_to_one_event() -> None:
    """Constraint 4: never dedupe on tx hash, but the *same* log seen twice merges."""
    tx = "0x" + "cc" * 32
    node = FakeEthNode()
    # A self-transfer: ACCOUNT sends to ACCOUNT. The outgoing query (topic1) and
    # the incoming query (topic2) both return this exact same log.
    node.logs.append(
        transfer_log(
            block_number=5, tx_index=0, log_index=0, tx_hash=tx, frm=ACCOUNT, to=ACCOUNT, value=9
        )
    )
    page = await adapter(node).fetch_transfers(
        address=ACCOUNT, asset=ASSET, direction=Direction.both, analysis_cutoff=CUTOFF
    )
    assert len(page.events) == 1


@respx.mock
async def test_amount_above_javascript_safe_integer_range() -> None:
    tx = "0x" + "dd" * 32
    huge = 2**60 + 12345
    node = FakeEthNode()
    node.logs.append(
        transfer_log(
            block_number=5, tx_index=0, log_index=0, tx_hash=tx, frm=ACCOUNT, to=PEER_A, value=huge
        )
    )
    page = await adapter(node).fetch_transfers(
        address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
    )
    assert page.events[0].amount_base_units == huge
    assert isinstance(page.events[0].amount_base_units, int)


@respx.mock
async def test_zero_value_transfer_decoded_but_flagged() -> None:
    tx = "0x" + "ee" * 32
    node = FakeEthNode()
    node.logs.append(
        transfer_log(
            block_number=5, tx_index=0, log_index=0, tx_hash=tx, frm=ACCOUNT, to=PEER_A, value=0
        )
    )
    page = await adapter(node).fetch_transfers(
        address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
    )
    assert page.events[0].is_zero_value is True


@respx.mock
async def test_zero_address_participant_decoded() -> None:
    """A mint (from the zero address) is a syntactically valid address, not malformed."""
    tx = "0x" + "f0" * 32
    node = FakeEthNode()
    node.logs.append(
        transfer_log(
            block_number=5,
            tx_index=0,
            log_index=0,
            tx_hash=tx,
            frm="0x" + "00" * 20,
            to=PEER_A,
            value=1,
        )
    )
    page = await adapter(node).fetch_transfers(
        address=PEER_A, asset=ASSET, direction=Direction.incoming, analysis_cutoff=CUTOFF
    )
    assert page.events[0].from_address == "0x" + "00" * 20


@respx.mock
async def test_wrong_topic0_ignored() -> None:
    tx = "0x" + "12" * 32
    node = FakeEthNode()
    log = transfer_log(
        block_number=5, tx_index=0, log_index=0, tx_hash=tx, frm=ACCOUNT, to=PEER_A, value=1
    )
    log["topics"][0] = "0x" + "00" * 32  # not the Transfer signature
    node.logs.append(log)
    page = await adapter(node).fetch_transfers(
        address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
    )
    assert page.events == []


@respx.mock
async def test_wrong_contract_ignored() -> None:
    tx = "0x" + "13" * 32
    node = FakeEthNode()
    other_contract = "0x" + "77" * 20
    node.logs.append(
        transfer_log(
            block_number=5,
            tx_index=0,
            log_index=0,
            tx_hash=tx,
            frm=ACCOUNT,
            to=PEER_A,
            value=1,
            contract=other_contract,
        )
    )
    page = await adapter(node).fetch_transfers(
        address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
    )
    assert page.events == []


@respx.mock
async def test_malformed_topic_length_rejected() -> None:
    tx = "0x" + "14" * 32
    node = FakeEthNode()
    log = transfer_log(
        block_number=5, tx_index=0, log_index=0, tx_hash=tx, frm=ACCOUNT, to=PEER_A, value=1
    )
    log["topics"][1] = "0x1234"  # not a 32-byte word
    node.logs.append(log)
    page = await adapter(node).fetch_transfers(
        address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
    )
    assert page.events == []


@respx.mock
async def test_only_three_topics_treated_as_erc20_transfer() -> None:
    """A log with the Transfer topic0 but a different topic count is not assumed
    to be a plain ERC-20 transfer (constraint 5)."""
    tx = "0x" + "15" * 32
    node = FakeEthNode()
    log = transfer_log(
        block_number=5, tx_index=0, log_index=0, tx_hash=tx, frm=ACCOUNT, to=PEER_A, value=1
    )
    log["topics"].append(topic(PEER_B))  # four topics: not standard Transfer
    node.logs.append(log)
    page = await adapter(node).fetch_transfers(
        address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
    )
    assert page.events == []


@respx.mock
async def test_mixed_case_query_address_still_matches() -> None:
    tx = "0x" + "16" * 32
    node = FakeEthNode()
    node.logs.append(
        transfer_log(
            block_number=5, tx_index=0, log_index=0, tx_hash=tx, frm=ACCOUNT, to=PEER_A, value=7
        )
    )
    mixed = "0x" + ACCOUNT[2:8].upper() + ACCOUNT[8:]
    page = await adapter(node).fetch_transfers(
        address=mixed, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
    )
    assert len(page.events) == 1


# -- ordering -------------------------------------------------------------


@respx.mock
async def test_later_block_sorts_after_earlier_block() -> None:
    node = FakeEthNode()
    node.logs.append(
        transfer_log(
            block_number=10,
            tx_index=0,
            log_index=0,
            tx_hash="0x" + "20" * 32,
            frm=ACCOUNT,
            to=PEER_A,
            value=1,
        )
    )
    node.logs.append(
        transfer_log(
            block_number=5,
            tx_index=0,
            log_index=0,
            tx_hash="0x" + "21" * 32,
            frm=ACCOUNT,
            to=PEER_A,
            value=1,
        )
    )
    page = await adapter(node).fetch_transfers(
        address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
    )
    assert [e.block_height for e in page.events] == [5, 10]


@respx.mock
async def test_same_block_later_transaction_index_sorts_after() -> None:
    node = FakeEthNode()
    node.logs.append(
        transfer_log(
            block_number=5,
            tx_index=3,
            log_index=0,
            tx_hash="0x" + "22" * 32,
            frm=ACCOUNT,
            to=PEER_A,
            value=1,
        )
    )
    node.logs.append(
        transfer_log(
            block_number=5,
            tx_index=1,
            log_index=0,
            tx_hash="0x" + "23" * 32,
            frm=ACCOUNT,
            to=PEER_A,
            value=1,
        )
    )
    page = await adapter(node).fetch_transfers(
        address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
    )
    assert [e.index_in_block for e in page.events] == [1, 3]


@respx.mock
async def test_same_transaction_later_log_index_sorts_after() -> None:
    tx = "0x" + "24" * 32
    node = FakeEthNode()
    node.logs.append(
        transfer_log(
            block_number=5, tx_index=0, log_index=3, tx_hash=tx, frm=ACCOUNT, to=PEER_A, value=1
        )
    )
    node.logs.append(
        transfer_log(
            block_number=5, tx_index=0, log_index=1, tx_hash=tx, frm=ACCOUNT, to=PEER_A, value=1
        )
    )
    page = await adapter(node).fetch_transfers(
        address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
    )
    assert [e.event_index for e in page.events] == [1, 3]


# -- execution / receipts --------------------------------------------------


@respx.mock
async def test_successful_receipt_accepted() -> None:
    tx = "0x" + "30" * 32
    node = FakeEthNode(finalized=1_999_000)
    node.receipts[tx] = {
        "status": "0x1",
        "blockNumber": hex(100),
        "gasUsed": "0x5208",
        "effectiveGasPrice": "0x3b9aca00",
    }
    receipt = await adapter(node).fetch_receipt(tx)
    assert receipt.execution_status is ExecutionStatus.success
    assert receipt.fee == 0x5208 * 0x3B9ACA00


@respx.mock
async def test_reverted_receipt_rejected() -> None:
    tx = "0x" + "31" * 32
    node = FakeEthNode()
    node.receipts[tx] = {"status": "0x0", "blockNumber": hex(100)}
    receipt = await adapter(node).fetch_receipt(tx)
    assert receipt.execution_status is ExecutionStatus.reverted


@respx.mock
async def test_unavailable_receipt_is_unknown_not_absent() -> None:
    tx = "0x" + "32" * 32
    node = FakeEthNode()
    receipt = await adapter(node).fetch_receipt(tx)
    assert receipt.execution_status is ExecutionStatus.unknown
    assert receipt.confirmation_state is ConfirmationState.unknown


# -- finality ---------------------------------------------------------------


@respx.mock
async def test_finalized_block_classified_finalized() -> None:
    tx = "0x" + "40" * 32
    node = FakeEthNode(finalized=200, safe=250)
    node.receipts[tx] = {"status": "0x1", "blockNumber": hex(100)}
    receipt = await adapter(node).fetch_receipt(tx)
    assert receipt.finality_detail == "finalized"
    assert receipt.solidified is True
    assert receipt.confirmation_state is ConfirmationState.confirmed


@respx.mock
async def test_safe_but_not_finalized_block_classified_safe() -> None:
    tx = "0x" + "41" * 32
    node = FakeEthNode(finalized=50, safe=150)
    node.receipts[tx] = {"status": "0x1", "blockNumber": hex(100)}
    receipt = await adapter(node).fetch_receipt(tx)
    assert receipt.finality_detail == "safe"
    assert receipt.solidified is False
    assert receipt.confirmation_state is ConfirmationState.provisional


@respx.mock
async def test_head_block_classified_unfinalized() -> None:
    tx = "0x" + "42" * 32
    node = FakeEthNode(finalized=10, safe=20)
    node.receipts[tx] = {"status": "0x1", "blockNumber": hex(1000)}
    receipt = await adapter(node).fetch_receipt(tx)
    assert receipt.finality_detail == "head_unfinalized"
    assert receipt.confirmation_state is ConfirmationState.provisional


@respx.mock
async def test_unsupported_finality_tags_yield_unknown_never_a_confirmation_fallback() -> None:
    tx = "0x" + "43" * 32
    node = FakeEthNode(finalized=None, safe=None)
    node.receipts[tx] = {"status": "0x1", "blockNumber": hex(100)}
    receipt = await adapter(node).fetch_receipt(tx)
    assert receipt.finality_detail == "unknown"
    assert receipt.confirmation_state is ConfirmationState.unknown


# -- chain identity ---------------------------------------------------------


@respx.mock
async def test_matching_chain_id_allows_acquisition() -> None:
    node = FakeEthNode(chain_id=CHAIN_ID)
    a = adapter(node)
    await a.fetch_transfers(
        address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
    )
    assert a.observed_chain_id == CHAIN_ID


@respx.mock
async def test_mismatched_chain_id_refuses_acquisition() -> None:
    """Constraint 3: a Sepolia/other endpoint is never treated as Ethereum
    Mainnet merely because it was configured under the Ethereum RPC url."""
    node = FakeEthNode(chain_id=11155111)  # Sepolia
    a = adapter(node)
    with pytest.raises(ProviderError) as exc_info:
        await a.fetch_transfers(
            address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
        )
    assert exc_info.value.error_class is ProviderErrorClass.unsupported
    assert [c for c in node.calls if c[0] == "eth_getLogs"] == []


# -- budgets and range splitting --------------------------------------------


@respx.mock
async def test_request_budget_exhausted_stops_acquisition() -> None:
    node = FakeEthNode()
    a = adapter(node, max_requests=1)  # only eth_chainId fits
    with pytest.raises(ProviderError) as exc_info:
        await a.fetch_transfers(
            address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
        )
    assert exc_info.value.error_class is ProviderErrorClass.budget_exhausted


@respx.mock
async def test_log_range_splits_and_recovers_events_on_provider_failure() -> None:
    node = FakeEthNode(latest=100)
    tx = "0x" + "50" * 32
    node.logs.append(
        transfer_log(
            block_number=10, tx_index=0, log_index=0, tx_hash=tx, frm=ACCOUNT, to=PEER_A, value=5
        )
    )
    # The whole-range query fails; only a split recovers the event.
    node.fail_ranges.add((0, 100))
    page = await adapter(node).fetch_transfers(
        address=ACCOUNT,
        asset=ASSET,
        direction=Direction.outgoing,
        analysis_start=dt.datetime.fromtimestamp(node.block_time(0), tz=dt.UTC),
        analysis_cutoff=dt.datetime.fromtimestamp(node.block_time(100), tz=dt.UTC),
    )
    assert len(page.events) == 1
    assert page.events[0].tx_hash == tx


@respx.mock
async def test_log_range_split_gives_up_at_minimum_span_and_marks_incomplete() -> None:
    node = FakeEthNode(latest=8)
    # Every possible sub-range down to a single block fails: the split must
    # terminate (constraint 8), never recurse forever.
    for lo in range(0, 9):
        for hi in range(lo, 9):
            node.fail_ranges.add((lo, hi))
    a = adapter(node)
    page = await a.fetch_transfers(
        address=ACCOUNT,
        asset=ASSET,
        direction=Direction.outgoing,
        analysis_start=dt.datetime.fromtimestamp(node.block_time(0), tz=dt.UTC),
        analysis_cutoff=dt.datetime.fromtimestamp(node.block_time(8), tz=dt.UTC),
    )
    assert page.events == []
    assert a.incomplete_ranges  # honest partial coverage, not silent emptiness
    from app.models.enums import CoverageStatus

    assert page.acquisition is not None
    assert page.acquisition.coverage_status is CoverageStatus.partial


# -- security / evidence privacy --------------------------------------------


@respx.mock
async def test_recorded_exchange_never_contains_the_rpc_url() -> None:
    node = FakeEthNode()
    captured: list[dict[str, Any]] = []
    a = adapter(node, recorder=captured.append)
    await a.fetch_transfers(
        address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
    )
    dumped = json.dumps(captured)
    assert RPC_URL not in dumped
    assert "secret-key-abc123" not in dumped


@respx.mock
async def test_recorded_exchange_contains_no_authorization_header_field() -> None:
    node = FakeEthNode()
    captured: list[dict[str, Any]] = []
    a = adapter(node, recorder=captured.append)
    await a.fetch_transfers(
        address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
    )
    for record in captured:
        assert "headers" not in record
        assert "authorization" not in json.dumps(record).lower()


# -- reference / seed resolution ---------------------------------------------


def test_tx_hash_from_reference_parses_well_formed_reference() -> None:
    ref = "eip155:1:0x" + "aa" * 32 + ":3"
    assert EvmRpcAdapter.tx_hash_from_reference(ref) == "0x" + "aa" * 32


@pytest.mark.parametrize(
    "reference",
    [
        "tron:0xabc:0",
        "eip155:1:0xabc",
        "eip155:notanumber:0xabc:0",
        "eip155:1::0",
        "not-a-reference",
    ],
)
def test_tx_hash_from_reference_rejects_malformed(reference: str) -> None:
    assert EvmRpcAdapter.tx_hash_from_reference(reference) is None


@respx.mock
async def test_resolve_seed_event_is_a_no_op_because_logs_are_already_exact() -> None:
    node = FakeEthNode()
    tx = "0x" + "60" * 32
    node.logs.append(
        transfer_log(
            block_number=5, tx_index=0, log_index=0, tx_hash=tx, frm=ACCOUNT, to=PEER_A, value=1
        )
    )
    a = adapter(node)
    page = await a.fetch_transfers(
        address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
    )
    resolved = await a.resolve_seed_event(page.events[0], ASSET)
    assert resolved == page.events[0]


# -- network identity and cross-network safety (Task 06) ---------------------


@respx.mock
async def test_asset_from_another_network_is_refused_not_relabelled() -> None:
    """An ``AssetRef`` names its own network. A BSC adapter handed an Ethereum
    asset (or the reverse) must refuse, never rewrite the evidence identity."""
    other = "ethereum" if NETWORK == "bsc" else "bsc"
    node = FakeEthNode()
    node.logs.append(
        transfer_log(
            block_number=5,
            tx_index=0,
            log_index=0,
            tx_hash="0x" + "80" * 32,
            frm=ACCOUNT,
            to=PEER_A,
            value=1,
        )
    )
    a = adapter(node)
    with pytest.raises(ProviderError) as exc_info:
        await a.fetch_transfers(
            address=ACCOUNT,
            asset=AssetRef(other, USDT, 6, "USDT"),
            direction=Direction.outgoing,
            analysis_cutoff=CUTOFF,
        )
    assert exc_info.value.error_class is ProviderErrorClass.unsupported
    assert [c for c in node.calls if c[0] == "eth_getLogs"] == []


# -- timestamp -> block resolution bounds ------------------------------------


@respx.mock
async def test_future_cutoff_is_bounded_at_chain_head_and_reported() -> None:
    node = FakeEthNode(latest=100)
    a = adapter(node)
    future = dt.datetime.fromtimestamp(node.block_time(100) + 10_000, tz=dt.UTC)
    resolution = await a._resolve_block_range(None, future)
    assert resolution.to_block == 100
    assert resolution.truncated_reason and "after the latest observed block" in (
        resolution.truncated_reason
    )


@respx.mock
async def test_start_resolution_never_skips_blocks_sharing_the_start_timestamp() -> None:
    """Several blocks can share one second-resolution timestamp (observed on BSC
    Mainnet). A window starting at that second must include all of them --
    resolving the lower bound to the *last* such block silently skipped the
    earlier ones while still reporting the range complete."""
    node = FakeEthNode(latest=3_000, block_step=1, blocks_per_timestamp=3)
    a = adapter(node)
    await a._ensure_chain_id()
    at = dt.datetime.fromtimestamp(node.block_time(300), tz=dt.UTC)  # blocks 300, 301, 302
    resolution = await a._resolve_block_range(at, at)
    assert resolution.from_block <= 300
    assert resolution.to_block == 302
    assert node.block_time(resolution.from_block - 1) < node.block_time(300) or (
        resolution.from_block == 0
    )


@respx.mock
async def test_start_resolution_is_at_most_one_block_early_with_unique_timestamps() -> None:
    node = FakeEthNode(latest=2_000)
    a = adapter(node)
    await a._ensure_chain_id()
    between = dt.datetime.fromtimestamp(node.block_time(500) + 5, tz=dt.UTC)
    exact = dt.datetime.fromtimestamp(node.block_time(700), tz=dt.UTC)
    assert (await a._resolve_block_range(between, CUTOFF)).from_block == 500
    assert (await a._resolve_block_range(exact, CUTOFF)).from_block == 699


@respx.mock
async def test_block_resolution_is_bounded_and_counts_against_the_budget() -> None:
    node = FakeEthNode(latest=50_000_000)
    a = adapter(node, max_requests=6)
    start = dt.datetime.fromtimestamp(node.block_time(1_000), tz=dt.UTC)
    cutoff = dt.datetime.fromtimestamp(node.block_time(2_000), tz=dt.UTC)
    await a._ensure_chain_id()
    resolution = await a._resolve_block_range(start, cutoff)
    assert a.request_count <= 6
    assert resolution.truncated_reason == (
        "provider request budget exhausted during block resolution"
    )
    # Never a scan from genesis: only binary-search probes were issued.
    assert len([c for c in node.calls if c[0] == "eth_getBlockByNumber"]) <= 5


# -- provider error redaction ---------------------------------------------------

SECRET_URL = "https://provider.example/v2/SECRET_KEY?token=ANOTHER_SECRET"


@pytest.mark.parametrize(
    "exc_factory",
    [
        lambda: httpx.ConnectError(f"cannot connect to {SECRET_URL}"),
        lambda: httpx.ReadTimeout(f"timed out reading {SECRET_URL}"),
        lambda: httpx.ConnectError("provider.example refused /v2/SECRET_KEY token=ANOTHER_SECRET"),
        lambda: httpx.InvalidURL(f"Invalid URL {SECRET_URL!r}"),
    ],
)
@respx.mock
async def test_provider_error_text_never_carries_the_rpc_url(exc_factory: Any) -> None:
    respx.post(SECRET_URL).mock(side_effect=exc_factory())
    a = EvmRpcAdapter(SECRET_URL, network_key=NETWORK)
    with pytest.raises(ProviderError) as exc_info:
        await a.fetch_transfers(
            address=ACCOUNT, asset=ASSET, direction=Direction.outgoing, analysis_cutoff=CUTOFF
        )
    error = exc_info.value
    text = f"{error} {error!r}"
    for secret in (SECRET_URL, "provider.example", "SECRET_KEY", "ANOTHER_SECRET"):
        assert secret not in text
    # The original httpx exception (whose own text carries the URL) is not
    # chained onto the ProviderError, so a printed traceback cannot leak it.
    assert error.__cause__ is None
    assert error.__suppress_context__ is True


@respx.mock
async def test_json_rpc_error_message_echoing_the_url_is_redacted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "error": {"code": -32000, "message": f"key rejected for {SECRET_URL}"},
            },
        )

    respx.post(SECRET_URL).mock(side_effect=handler)
    a = EvmRpcAdapter(SECRET_URL, network_key=NETWORK)
    with pytest.raises(ProviderError) as exc_info:
        await a._rpc("eth_chainId", [])
    text = str(exc_info.value)
    for secret in (SECRET_URL, "provider.example", "SECRET_KEY", "ANOTHER_SECRET"):
        assert secret not in text


# -- read-only token verification ---------------------------------------------


@respx.mock
async def test_token_verification_reads_code_decimals_symbol_and_name() -> None:
    node = FakeEthNode()
    captured: list[dict[str, Any]] = []
    a = adapter(node, recorder=captured.append)
    facts = await a.verify_token_contract(USDT)
    assert facts["network"] == NETWORK
    assert facts["chain_id"] == CHAIN_ID
    assert facts["contract"] == USDT
    assert facts["code_present"] is True
    assert facts["decimals"] == 6
    assert facts["symbol"] == "USDT"
    assert facts["name"] == "Tether USD"
    methods = [record["payload"]["method"] for record in captured]
    assert methods[0] == "eth_chainId"
    assert set(methods[1:]) == {"eth_getCode", "eth_call"}
    # Read-only: never a transaction-sending method.
    assert not any("send" in m.lower() for m in methods)


@respx.mock
async def test_token_verification_reports_missing_code() -> None:
    node = FakeEthNode()
    node.code = {}
    facts = await adapter(node).verify_token_contract(USDT)
    assert facts["code_present"] is False


@respx.mock
async def test_legacy_start_policy_reproduces_pre_fix_resolution_for_old_bundles() -> None:
    """Bundles recorded before the shared-timestamp fix replay under the policy
    they were captured with, or their recorded eth_getLogs ranges would not match."""
    from app.adapters.evm import BLOCK_RESOLUTION_LEGACY

    node = FakeEthNode(latest=2_000)
    a = adapter(node, block_resolution_policy=BLOCK_RESOLUTION_LEGACY)
    await a._ensure_chain_id()
    exact = dt.datetime.fromtimestamp(node.block_time(700), tz=dt.UTC)
    assert (await a._resolve_block_range(exact, CUTOFF)).from_block == 700
