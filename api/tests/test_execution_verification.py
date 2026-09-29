"""Execution receipts: what a transfer's status is, and when we may claim it.

The history endpoint documents no execution status, so every transfer starts
`unknown`. That is a fallback, not an answer. These tests cover turning it into
an answer from the receipt endpoints — and refusing to, when the receipt does
not say.

Response shapes use only fields documented at the two reference pages cited in
`app/adapters/tron.py`, checked 2026-09-20. No network access.
"""

from __future__ import annotations

import datetime as dt

import httpx
import pytest
import respx

from app.adapters.base import AssetRef, ProviderError, ProviderErrorClass
from app.adapters.tron import (
    HEAD_RECEIPT_PATH,
    SOLIDIFIED_RECEIPT_PATH,
    TronGridAdapter,
    reconcile_event,
)
from app.models.enums import ConfirmationState, EventKind, ExecutionStatus

BASE = "https://api.trongrid.io"
USDT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
PEER_A = "TMrjWHAq1BPg9iG9ZaBTsG1AoxWERR29Mz"
PEER_B = "TRTqwgSLfUVziqWCyN6ZMThBkMgRvSaYtE"
TX = "abc123"
ASSET = AssetRef("tron", USDT, 6, "USDT")


def adapter(**kwargs) -> TronGridAdapter:
    return TronGridAdapter(BASE, api_key="test-key", **kwargs)


def receipt_body(result: str | None, *, tx: str = TX) -> dict:
    """A receipt as the endpoint documents it: id, blockNumber, blockTimeStamp…"""
    body: dict = {
        "id": tx,
        "fee": 1_100_000,
        "blockNumber": 71_000_010,
        "blockTimeStamp": 1767225600000,
        "contractResult": [""],
        "receipt": {"net_fee": 0},
    }
    if result is not None:
        body["receipt"]["result"] = result
    return body


def transfer(**overrides):
    from app.adapters.base import NormalizedTransfer

    kwargs = {
        "event_reference": f"tron:{TX}:0",
        "tx_hash": TX,
        "event_kind": EventKind.transfer,
        "asset": ASSET,
        "from_address": PEER_A,
        "to_address": PEER_B,
        "amount_base_units": 95_000_000,
        "execution_status": ExecutionStatus.unknown,
        "confirmation_state": ConfirmationState.unknown,
        "block_time": dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        "event_index": 0,
    }
    kwargs.update(overrides)
    return NormalizedTransfer(**kwargs)


@respx.mock
async def test_a_solidified_receipt_gives_execution_and_finality() -> None:
    respx.post(f"{BASE}{SOLIDIFIED_RECEIPT_PATH}").mock(
        return_value=httpx.Response(200, json=receipt_body("SUCCESS"))
    )

    receipt = await adapter().fetch_receipt(TX)

    assert receipt.execution_status is ExecutionStatus.success
    assert receipt.confirmation_state is ConfirmationState.confirmed
    assert receipt.solidified is True
    assert receipt.source_path == SOLIDIFIED_RECEIPT_PATH
    assert receipt.block_number == 71_000_010


@respx.mock
async def test_an_unsolidified_transaction_is_executed_but_not_final() -> None:
    """Execution success and finality are different questions with one answer each."""
    respx.post(f"{BASE}{SOLIDIFIED_RECEIPT_PATH}").mock(return_value=httpx.Response(200, json={}))
    respx.post(f"{BASE}{HEAD_RECEIPT_PATH}").mock(
        return_value=httpx.Response(200, json=receipt_body("SUCCESS"))
    )

    receipt = await adapter().fetch_receipt(TX)

    assert receipt.execution_status is ExecutionStatus.success
    assert receipt.confirmation_state is ConfirmationState.provisional
    assert receipt.solidified is False
    assert "not solidified" in receipt.note


@respx.mock
async def test_a_reverted_contract_is_not_a_successful_transfer() -> None:
    respx.post(f"{BASE}{SOLIDIFIED_RECEIPT_PATH}").mock(
        return_value=httpx.Response(200, json=receipt_body("REVERT"))
    )

    receipt = await adapter().fetch_receipt(TX)

    assert receipt.execution_status is ExecutionStatus.reverted
    assert receipt.receipt_result == "REVERT"


@respx.mock
async def test_an_unrecognised_receipt_result_is_never_read_as_success() -> None:
    """The schema does not enumerate the values, so anything but SUCCESS fails closed."""
    respx.post(f"{BASE}{SOLIDIFIED_RECEIPT_PATH}").mock(
        return_value=httpx.Response(200, json=receipt_body("OUT_OF_ENERGY"))
    )

    receipt = await adapter().fetch_receipt(TX)

    assert receipt.execution_status is ExecutionStatus.failed
    assert receipt.receipt_result == "OUT_OF_ENERGY"


@respx.mock
async def test_a_receipt_without_a_result_field_stays_unknown() -> None:
    respx.post(f"{BASE}{SOLIDIFIED_RECEIPT_PATH}").mock(
        return_value=httpx.Response(200, json=receipt_body(None))
    )

    receipt = await adapter().fetch_receipt(TX)

    assert receipt.execution_status is ExecutionStatus.unknown
    assert receipt.confirmation_state is ConfirmationState.confirmed
    assert receipt.receipt_result is None


@respx.mock
async def test_no_receipt_anywhere_is_unknown_not_absent() -> None:
    respx.post(f"{BASE}{SOLIDIFIED_RECEIPT_PATH}").mock(return_value=httpx.Response(200, json={}))
    respx.post(f"{BASE}{HEAD_RECEIPT_PATH}").mock(return_value=httpx.Response(200, json={}))

    receipt = await adapter().fetch_receipt(TX)

    assert receipt.execution_status is ExecutionStatus.unknown
    assert receipt.confirmation_state is ConfirmationState.unknown
    assert "no receipt" in receipt.note


@respx.mock
async def test_an_error_body_with_http_200_is_an_error() -> None:
    """The endpoint documents that a failure can arrive as HTTP 200 plus Error."""
    respx.post(f"{BASE}{SOLIDIFIED_RECEIPT_PATH}").mock(
        return_value=httpx.Response(200, json={"Error": "class java.lang.NullPointerException"})
    )

    with pytest.raises(ProviderError) as excinfo:
        await adapter().fetch_receipt(TX)

    assert excinfo.value.error_class is ProviderErrorClass.provider_error


@respx.mock
async def test_verification_asks_once_per_transaction() -> None:
    route = respx.post(f"{BASE}{SOLIDIFIED_RECEIPT_PATH}").mock(
        return_value=httpx.Response(200, json=receipt_body("SUCCESS"))
    )
    events = [
        transfer(event_reference=f"tron:{TX}:0", event_index=0),
        transfer(event_reference=f"tron:{TX}:1", event_index=1, amount_base_units=5),
    ]

    verification = await adapter().verify_execution(events)

    assert route.call_count == 1
    assert len(verification.events) == 2
    assert all(e.execution_status is ExecutionStatus.success for e in verification.events)
    assert all(e.confirmation_state is ConfirmationState.confirmed for e in verification.events)
    assert not verification.unverified


@respx.mock
async def test_a_provider_failure_leaves_the_event_unknown_and_says_so() -> None:
    respx.post(f"{BASE}{SOLIDIFIED_RECEIPT_PATH}").mock(return_value=httpx.Response(503))

    verification = await adapter().verify_execution([transfer()])

    (event,) = verification.events
    assert event.execution_status is ExecutionStatus.unknown
    assert event.confirmation_state is ConfirmationState.unknown
    (unverified,) = verification.unverified
    assert unverified.event_reference == f"tron:{TX}:0"
    assert "503" in unverified.reason or "http_error" in unverified.reason


@respx.mock
async def test_verification_keeps_a_failed_transfer_failed() -> None:
    respx.post(f"{BASE}{SOLIDIFIED_RECEIPT_PATH}").mock(
        return_value=httpx.Response(200, json=receipt_body("REVERT"))
    )

    verification = await adapter().verify_execution([transfer()])

    (event,) = verification.events
    assert event.execution_status is ExecutionStatus.reverted
    assert verification.receipts[TX].receipt_result == "REVERT"


def test_reconciliation_matches_the_event_the_receipt_describes() -> None:
    rows = [
        {
            "contract_address": USDT,
            "event_name": "Transfer",
            "event_index": 0,
            "result": {"from": PEER_A, "to": PEER_B, "value": "95000000"},
        }
    ]

    outcome = reconcile_event(transfer(), rows, ASSET)

    assert outcome.matched is True
    assert outcome.reason == "contract, participants and amount agree"


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("contract_address", "TOtherContractXXXXXXXXXXXXXXXXXXXXX", "no matching event"),
        ("value", "94999999", "no matching event"),
        ("to", "TSomeoneElseXXXXXXXXXXXXXXXXXXXXXXX", "no matching event"),
    ],
)
def test_reconciliation_refuses_a_near_miss(field: str, value: str, expected: str) -> None:
    result = {"from": PEER_A, "to": PEER_B, "value": "95000000"}
    row = {
        "contract_address": USDT,
        "event_name": "Transfer",
        "event_index": 0,
        "result": result,
    }
    if field == "contract_address":
        row["contract_address"] = value
    else:
        result[field] = value

    outcome = reconcile_event(transfer(), [row], ASSET)

    assert outcome.matched is False
    assert expected in outcome.reason


def test_reconciliation_without_event_detail_is_not_a_match() -> None:
    outcome = reconcile_event(transfer(), [], ASSET)

    assert outcome.matched is False
    assert "no event detail" in outcome.reason
