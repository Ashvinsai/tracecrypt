"""Stage 2C2: resource-delegation and TRX-funding evidence for one candidate.

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
from app.services.collect_resource_evidence import (
    EVIDENCE_COLUMNS,
    OPERATION_CURRENT_DETAIL,
    OPERATION_CURRENT_INDEX,
    OPERATION_DELEGATE,
    OPERATION_UNDELEGATE,
    RELATIONSHIP_RESOURCE_DELEGATION,
    RELATIONSHIP_TOKEN_TRANSFER,
    RELATIONSHIP_TRX_FUNDING,
    TEMPORAL_CURRENT_STATE_ONLY,
    TEMPORAL_HISTORICAL,
    KnownTokenTransfer,
    ResourceEvidenceError,
    ResourceEvidenceRequest,
    backfill_operation_type,
    collect_resource_evidence,
)

BASE = "https://api.trongrid.io"
CANDIDATE = "TNtTcstZdy5vppwDMQuR9gy6n5rT4o7ptq"
ANCHOR = "TYfxtkCooUX7rzjRqBGLan9XkCxqkrCRir"
PROVIDER = "TRTqwgSLfUVziqWCyN6ZMThBkMgRvSaYtE"
FUNDER = "TMrjWHAq1BPg9iG9ZaBTsG1AoxWERR29Mz"
OTHER_FUNDER = "TEocPZsTTRAK9x5TR66GnEbxKKU8zrNxgM"

START = dt.datetime(2026, 8, 10, tzinfo=dt.UTC)
CUTOFF = dt.datetime(2026, 8, 11, tzinfo=dt.UTC)
HISTORICAL_MS = int(dt.datetime(2026, 8, 10, 12, 0, tzinfo=dt.UTC).timestamp() * 1000)

DELEGATION_INDEX_URL = f"{BASE}/wallet/getdelegatedresourceaccountindexv2"
DELEGATED_RESOURCE_URL = f"{BASE}/wallet/getdelegatedresourcev2"
TRANSACTIONS_URL = f"{BASE}/v1/accounts/{CANDIDATE}/transactions"


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


def resource_evidence_rows(data_dir: Path) -> list[dict[str, str]]:
    path = data_dir / "resource_evidence.csv"
    if not path.exists():
        return []
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def empty_index_response() -> httpx.Response:
    return httpx.Response(200, json={"account": CANDIDATE, "fromAccounts": [], "toAccounts": []})


def empty_transactions_response() -> httpx.Response:
    return httpx.Response(200, json={"data": [], "meta": {}})


def delegate_contract_tx(
    tx_id: str, owner: str, receiver: str, *, balance: int = 5_000_000
) -> dict:
    return {
        "txID": tx_id,
        "blockNumber": 85000000,
        "block_timestamp": HISTORICAL_MS,
        "ret": [{"contractRet": "SUCCESS"}],
        "raw_data": {
            "contract": [
                {
                    "type": "DelegateResourceContract",
                    "parameter": {
                        "value": {
                            "owner_address": owner,
                            "receiver_address": receiver,
                            "balance": balance,
                            "resource": "ENERGY",
                        }
                    },
                }
            ]
        },
    }


def undelegate_contract_tx(
    tx_id: str, owner: str, receiver: str, *, balance: int = 5_000_000
) -> dict:
    tx = delegate_contract_tx(tx_id, owner, receiver, balance=balance)
    tx["raw_data"]["contract"][0]["type"] = "UnDelegateResourceContract"
    return tx


def trx_transfer_tx(tx_id: str, sender: str, to_address: str, *, amount: int = 10_000_000) -> dict:
    return {
        "txID": tx_id,
        "blockNumber": 85000001,
        "block_timestamp": HISTORICAL_MS,
        "ret": [{"contractRet": "SUCCESS"}],
        "raw_data": {
            "contract": [
                {
                    "type": "TransferContract",
                    "parameter": {
                        "value": {
                            "owner_address": sender,
                            "to_address": to_address,
                            "amount": amount,
                        }
                    },
                }
            ]
        },
    }


def default_request(**overrides) -> ResourceEvidenceRequest:
    kwargs = {
        "candidate_address": CANDIDATE,
        "analysis_start": START,
        "analysis_cutoff": CUTOFF,
    }
    kwargs.update(overrides)
    return ResourceEvidenceRequest(**kwargs)


@respx.mock
async def test_refuses_an_address_that_is_not_a_known_candidate_or_anchor(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    settings = live_settings()

    with pytest.raises(ResourceEvidenceError, match="not a known candidate"):
        await collect_resource_evidence(
            settings, default_request(), out_root=tmp_path / "out", data_dir=data_dir
        )


# --- F1/F2: no promotion to an owner/service label --------------------------


@respx.mock
async def test_a_resource_provider_is_not_promoted_to_an_owner_or_service_label(
    tmp_path: Path,
) -> None:
    data_dir = known_candidate_dir(tmp_path)
    respx.post(DELEGATION_INDEX_URL).mock(
        return_value=httpx.Response(
            200, json={"account": CANDIDATE, "fromAccounts": [PROVIDER], "toAccounts": []}
        )
    )
    respx.post(DELEGATED_RESOURCE_URL).mock(
        return_value=httpx.Response(200, json={"delegatedResource": []})
    )
    respx.get(TRANSACTIONS_URL).mock(return_value=empty_transactions_response())
    settings = live_settings()

    await collect_resource_evidence(
        settings, default_request(), out_root=tmp_path / "out", data_dir=data_dir, write=True
    )

    verified = {r["address"] for r in verified_anchor_rows(data_dir)}
    candidates = {r["address"] for r in deposit_candidate_rows(data_dir)}
    assert PROVIDER not in verified
    assert PROVIDER not in candidates
    rows = resource_evidence_rows(data_dir)
    assert any(
        r["counterparty_address"] == PROVIDER and r["relationship_type"] == "resource_delegation"
        for r in rows
    )


@respx.mock
async def test_a_trx_funder_is_not_promoted_to_an_owner_or_service_label(tmp_path: Path) -> None:
    data_dir = known_candidate_dir(tmp_path)
    respx.post(DELEGATION_INDEX_URL).mock(return_value=empty_index_response())
    respx.get(TRANSACTIONS_URL).mock(
        return_value=httpx.Response(
            200, json={"data": [trx_transfer_tx("aa" * 32, FUNDER, CANDIDATE)], "meta": {}}
        )
    )
    settings = live_settings()

    await collect_resource_evidence(
        settings, default_request(), out_root=tmp_path / "out", data_dir=data_dir, write=True
    )

    verified = {r["address"] for r in verified_anchor_rows(data_dir)}
    candidates = {r["address"] for r in deposit_candidate_rows(data_dir)}
    assert FUNDER not in verified
    assert FUNDER not in candidates
    rows = resource_evidence_rows(data_dir)
    assert any(
        r["counterparty_address"] == FUNDER and r["relationship_type"] == "trx_funding"
        for r in rows
    )


# --- F3/F4: temporal correctness ---------------------------------------------


@respx.mock
async def test_current_delegation_state_does_not_become_a_historical_claim(tmp_path: Path) -> None:
    data_dir = known_candidate_dir(tmp_path)
    respx.post(DELEGATION_INDEX_URL).mock(
        return_value=httpx.Response(
            200, json={"account": CANDIDATE, "fromAccounts": [PROVIDER], "toAccounts": []}
        )
    )
    respx.post(DELEGATED_RESOURCE_URL).mock(
        return_value=httpx.Response(200, json={"delegatedResource": []})
    )
    respx.get(TRANSACTIONS_URL).mock(return_value=empty_transactions_response())
    settings = live_settings()
    known_transfer = KnownTokenTransfer(
        counterparty_address=ANCHOR,
        tx_hash="cc" * 32,
        event_reference=f"tron:{'cc' * 32}:0",
        amount_base_units=72_140_000,
        block_time=dt.datetime(2026, 8, 10, 15, 59, 54, tzinfo=dt.UTC),
    )

    run = await collect_resource_evidence(
        settings,
        default_request(known_token_transfer=known_transfer),
        out_root=tmp_path / "out",
        data_dir=data_dir,
        write=True,
    )

    (delegation_row,) = [
        r for r in run.rows if r.relationship_type == RELATIONSHIP_RESOURCE_DELEGATION
    ]
    assert delegation_row.temporal_status == TEMPORAL_CURRENT_STATE_ONLY
    # Not backdated to the candidate's own earlier token-transfer time.
    assert delegation_row.coverage_start != known_transfer.block_time
    assert delegation_row.coverage_start == delegation_row.coverage_end
    assert "not evidence that this relationship existed at any earlier moment" in (
        delegation_row.interpretation_limitations
    )


@respx.mock
async def test_historical_delegation_evidence_keeps_its_own_timestamp(tmp_path: Path) -> None:
    data_dir = known_candidate_dir(tmp_path)
    respx.post(DELEGATION_INDEX_URL).mock(return_value=empty_index_response())
    respx.get(TRANSACTIONS_URL).mock(
        return_value=httpx.Response(
            200,
            json={"data": [delegate_contract_tx("dd" * 32, PROVIDER, CANDIDATE)], "meta": {}},
        )
    )
    settings = live_settings()

    run = await collect_resource_evidence(
        settings, default_request(), out_root=tmp_path / "out", data_dir=data_dir, write=True
    )

    (row,) = [r for r in run.rows if r.relationship_type == RELATIONSHIP_RESOURCE_DELEGATION]
    assert row.temporal_status == TEMPORAL_HISTORICAL
    assert row.block_time == dt.datetime.fromtimestamp(HISTORICAL_MS / 1000, tz=dt.UTC)
    assert row.coverage_start == row.block_time
    assert row.amount_base_units == 5_000_000
    assert row.asset_or_resource_type == "ENERGY"


# --- F5: dedup without merging -----------------------------------------------


@respx.mock
async def test_duplicate_observations_dedup_without_merging_distinct_operations(
    tmp_path: Path,
) -> None:
    data_dir = known_candidate_dir(tmp_path)
    respx.post(DELEGATION_INDEX_URL).mock(return_value=empty_index_response())
    # Same tx twice (e.g. an overlapping page) plus one genuinely distinct tx
    # from the same funder.
    respx.get(TRANSACTIONS_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    trx_transfer_tx("ee" * 32, FUNDER, CANDIDATE, amount=1_000_000),
                    trx_transfer_tx("ee" * 32, FUNDER, CANDIDATE, amount=1_000_000),
                    trx_transfer_tx("ff" * 32, FUNDER, CANDIDATE, amount=2_000_000),
                ],
                "meta": {},
            },
        )
    )
    settings = live_settings()

    run = await collect_resource_evidence(
        settings, default_request(), out_root=tmp_path / "out", data_dir=data_dir, write=True
    )

    funding_rows = [r for r in run.rows if r.relationship_type == RELATIONSHIP_TRX_FUNDING]
    tx_ids = {r.tx_or_operation_id for r in funding_rows}
    assert tx_ids == {"ee" * 32, "ff" * 32}
    assert len(funding_rows) == 2  # the repeat of ee..ee collapsed, ff..ff kept distinct


# --- F6: provider errors are not silently "no evidence" ---------------------


@respx.mock
async def test_provider_errors_produce_incomplete_evidence_not_no_evidence(tmp_path: Path) -> None:
    data_dir = known_candidate_dir(tmp_path)
    respx.post(DELEGATION_INDEX_URL).mock(return_value=httpx.Response(500))
    respx.get(TRANSACTIONS_URL).mock(
        return_value=httpx.Response(
            200, json={"data": [trx_transfer_tx("11" * 32, FUNDER, CANDIDATE)], "meta": {}}
        )
    )
    settings = live_settings()

    run = await collect_resource_evidence(
        settings, default_request(), out_root=tmp_path / "out", data_dir=data_dir, write=True
    )

    assert run.delegation_index_error is not None
    assert "http_error" in run.delegation_index_error
    # The independent, still-successful phase is not discarded because
    # another phase failed.
    assert any(r.relationship_type == RELATIONSHIP_TRX_FUNDING for r in run.rows)
    evidence_json = json.loads((run.directory / "evidence.json").read_text())
    assert evidence_json["delegation_index_error"] is not None


# --- F7: budget exhaustion stops before the next request ---------------------


@respx.mock
async def test_budget_exhaustion_stops_before_the_next_request(tmp_path: Path) -> None:
    data_dir = known_candidate_dir(tmp_path)
    index_route = respx.post(DELEGATION_INDEX_URL).mock(
        return_value=httpx.Response(
            200, json={"account": CANDIDATE, "fromAccounts": [PROVIDER], "toAccounts": []}
        )
    )
    detail_route = respx.post(DELEGATED_RESOURCE_URL).mock(
        return_value=httpx.Response(200, json={"delegatedResource": []})
    )
    tx_route = respx.get(TRANSACTIONS_URL).mock(return_value=empty_transactions_response())
    settings = live_settings()

    run = await collect_resource_evidence(
        settings,
        default_request(max_requests=1),
        out_root=tmp_path / "out",
        data_dir=data_dir,
        write=True,
    )

    assert run.requests_used == 1
    assert run.truncated_by_request_budget is True
    assert index_route.call_count == 1
    assert detail_route.call_count == 0  # never attempted -- budget checked first
    assert tx_route.call_count == 0


# --- F8/F9: isolation from the anchor/review system --------------------------


@respx.mock
async def test_resource_evidence_cannot_modify_verified_anchors(tmp_path: Path) -> None:
    data_dir = known_candidate_dir(tmp_path)
    before_hash = None
    va_path = data_dir / "verified_anchors.csv"
    if va_path.exists():
        before_hash = va_path.read_bytes()

    respx.post(DELEGATION_INDEX_URL).mock(
        return_value=httpx.Response(
            200, json={"account": CANDIDATE, "fromAccounts": [PROVIDER], "toAccounts": []}
        )
    )
    respx.post(DELEGATED_RESOURCE_URL).mock(
        return_value=httpx.Response(200, json={"delegatedResource": []})
    )
    respx.get(TRANSACTIONS_URL).mock(
        return_value=httpx.Response(
            200, json={"data": [trx_transfer_tx("22" * 32, FUNDER, CANDIDATE)], "meta": {}}
        )
    )
    settings = live_settings()

    await collect_resource_evidence(
        settings, default_request(), out_root=tmp_path / "out", data_dir=data_dir, write=True
    )

    after_exists = va_path.exists()
    assert after_exists == (before_hash is not None)
    if before_hash is not None:
        assert va_path.read_bytes() == before_hash


@respx.mock
async def test_the_existing_deposit_candidate_remains_unreviewed(tmp_path: Path) -> None:
    data_dir = known_candidate_dir(tmp_path)
    respx.post(DELEGATION_INDEX_URL).mock(
        return_value=httpx.Response(
            200, json={"account": CANDIDATE, "fromAccounts": [PROVIDER], "toAccounts": []}
        )
    )
    respx.post(DELEGATED_RESOURCE_URL).mock(
        return_value=httpx.Response(200, json={"delegatedResource": []})
    )
    respx.get(TRANSACTIONS_URL).mock(
        return_value=httpx.Response(
            200, json={"data": [trx_transfer_tx("33" * 32, FUNDER, CANDIDATE)], "meta": {}}
        )
    )
    settings = live_settings()

    await collect_resource_evidence(
        settings, default_request(), out_root=tmp_path / "out", data_dir=data_dir, write=True
    )

    (row,) = [r for r in deposit_candidate_rows(data_dir) if r["address"] == CANDIDATE]
    assert row["review_state"] == "unreviewed"
    assert row["address_role"] == "unknown"


# --- F10: three relationship types stay distinct ------------------------------


@respx.mock
async def test_token_transfer_resource_delegation_and_trx_funding_stay_distinct(
    tmp_path: Path,
) -> None:
    data_dir = known_candidate_dir(tmp_path)
    respx.post(DELEGATION_INDEX_URL).mock(
        return_value=httpx.Response(
            200, json={"account": CANDIDATE, "fromAccounts": [PROVIDER], "toAccounts": []}
        )
    )
    respx.post(DELEGATED_RESOURCE_URL).mock(
        return_value=httpx.Response(200, json={"delegatedResource": []})
    )
    respx.get(TRANSACTIONS_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    delegate_contract_tx("44" * 32, PROVIDER, CANDIDATE),
                    trx_transfer_tx("55" * 32, FUNDER, CANDIDATE),
                    trx_transfer_tx("66" * 32, OTHER_FUNDER, CANDIDATE),
                ],
                "meta": {},
            },
        )
    )
    settings = live_settings()
    known_transfer = KnownTokenTransfer(
        counterparty_address=ANCHOR,
        tx_hash="77" * 32,
        event_reference=f"tron:{'77' * 32}:0",
        amount_base_units=72_140_000,
        block_time=dt.datetime(2026, 8, 10, 15, 59, 54, tzinfo=dt.UTC),
    )

    run = await collect_resource_evidence(
        settings,
        default_request(known_token_transfer=known_transfer),
        out_root=tmp_path / "out",
        data_dir=data_dir,
        write=True,
    )

    types = {r.relationship_type for r in run.rows}
    assert types == {
        RELATIONSHIP_TOKEN_TRANSFER,
        RELATIONSHIP_RESOURCE_DELEGATION,
        RELATIONSHIP_TRX_FUNDING,
    }

    (token_row,) = [r for r in run.rows if r.relationship_type == RELATIONSHIP_TOKEN_TRANSFER]
    assert token_row.counterparty_address == ANCHOR

    delegation_rows = [
        r for r in run.rows if r.relationship_type == RELATIONSHIP_RESOURCE_DELEGATION
    ]
    assert {r.counterparty_address for r in delegation_rows} == {PROVIDER}

    funding_rows = [r for r in run.rows if r.relationship_type == RELATIONSHIP_TRX_FUNDING]
    assert {r.counterparty_address for r in funding_rows} == {FUNDER, OTHER_FUNDER}

    rows = resource_evidence_rows(data_dir)
    assert {r["relationship_type"] for r in rows} == types


# --- operation_type: delegate/undelegate distinguishable structurally --------


@respx.mock
async def test_delegate_and_undelegate_are_distinguishable_without_parsing_text(
    tmp_path: Path,
) -> None:
    data_dir = known_candidate_dir(tmp_path)
    respx.post(DELEGATION_INDEX_URL).mock(return_value=empty_index_response())
    respx.get(TRANSACTIONS_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    delegate_contract_tx("dd" * 32, PROVIDER, CANDIDATE),
                    undelegate_contract_tx("ee" * 32, PROVIDER, CANDIDATE),
                ],
                "meta": {},
            },
        )
    )
    settings = live_settings()

    run = await collect_resource_evidence(
        settings, default_request(), out_root=tmp_path / "out", data_dir=data_dir, write=True
    )

    by_tx = {r.tx_or_operation_id: r for r in run.rows}
    assert by_tx["dd" * 32].operation_type == OPERATION_DELEGATE
    assert by_tx["ee" * 32].operation_type == OPERATION_UNDELEGATE
    # The field alone settles it -- no need to read interpretation_limitations.
    rows = resource_evidence_rows(data_dir)
    persisted = {r["tx_or_operation_id"]: r["operation_type"] for r in rows}
    assert persisted["dd" * 32] == OPERATION_DELEGATE
    assert persisted["ee" * 32] == OPERATION_UNDELEGATE


@respx.mock
async def test_current_state_rows_carry_their_own_operation_type(tmp_path: Path) -> None:
    data_dir = known_candidate_dir(tmp_path)
    respx.post(DELEGATION_INDEX_URL).mock(
        return_value=httpx.Response(
            200, json={"account": CANDIDATE, "fromAccounts": [PROVIDER], "toAccounts": []}
        )
    )
    respx.post(DELEGATED_RESOURCE_URL).mock(
        return_value=httpx.Response(
            200, json={"delegatedResource": [{"resource": "ENERGY", "balance": 1}]}
        )
    )
    respx.get(TRANSACTIONS_URL).mock(return_value=empty_transactions_response())
    settings = live_settings()

    run = await collect_resource_evidence(
        settings, default_request(), out_root=tmp_path / "out", data_dir=data_dir, write=True
    )

    index_row, detail_row = [
        r for r in run.rows if r.relationship_type == RELATIONSHIP_RESOURCE_DELEGATION
    ]
    assert index_row.operation_type == OPERATION_CURRENT_INDEX
    assert detail_row.operation_type == OPERATION_CURRENT_DETAIL


def test_operation_type_does_not_widen_relationship_type() -> None:
    """Additive only: resource_delegation stays the one relationship_type for
    all four operation_type kinds; it never becomes its own relationship."""
    assert {OPERATION_CURRENT_INDEX, OPERATION_CURRENT_DETAIL} <= {
        OPERATION_CURRENT_INDEX, OPERATION_CURRENT_DETAIL, OPERATION_DELEGATE, OPERATION_UNDELEGATE
    }
    assert RELATIONSHIP_RESOURCE_DELEGATION == "resource_delegation"


# --- backfill_operation_type: upgrading rows persisted before the field -----


def test_backfill_derives_operation_type_for_legacy_rows(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    legacy_columns = [c for c in EVIDENCE_COLUMNS if c != "operation_type"]
    csv_path = data_dir / "resource_evidence.csv"
    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=legacy_columns)
        writer.writeheader()
        writer.writerow(
            {
                "network": "tron", "candidate_address": CANDIDATE,
                "relationship_type": RELATIONSHIP_RESOURCE_DELEGATION,
                "counterparty_address": PROVIDER, "asset_or_resource_type": "unknown",
                "tx_or_operation_id": "delegation-index:x", "amount_base_units": "",
                "block_number": "", "block_time": "",
                "evidence_reference": "wallet/getdelegatedresourceaccountindexv2",
                "acquisition_mode": "delegation_index_current_state",
                "coverage_start": "2026-09-20T11:07:57+00:00",
                "coverage_end": "2026-09-20T11:07:57+00:00", "coverage_complete": "true",
                "temporal_status": TEMPORAL_CURRENT_STATE_ONLY,
                "interpretation_limitations": "Reflects state at acquisition time.",
            }
        )
        writer.writerow(
            {
                "network": "tron", "candidate_address": CANDIDATE,
                "relationship_type": RELATIONSHIP_RESOURCE_DELEGATION,
                "counterparty_address": PROVIDER, "asset_or_resource_type": "ENERGY",
                "tx_or_operation_id": "dd" * 32, "amount_base_units": "5000000",
                "block_number": "85000000", "block_time": "2026-08-10T12:00:00+00:00",
                "evidence_reference": "v1/accounts/.../transactions:dd" + "dd" * 31,
                "acquisition_mode": "historical_operation_scan",
                "coverage_start": "2026-08-10T12:00:00+00:00",
                "coverage_end": "2026-08-10T12:00:00+00:00", "coverage_complete": "true",
                "temporal_status": TEMPORAL_HISTORICAL,
                "interpretation_limitations": (
                    "DelegateResourceContract operation with its own execution result "
                    "(SUCCESS); a resource delegation is not a token payment and is not "
                    "evidence of shared ownership."
                ),
            }
        )
        writer.writerow(
            {
                "network": "tron", "candidate_address": CANDIDATE,
                "relationship_type": RELATIONSHIP_TOKEN_TRANSFER,
                "counterparty_address": ANCHOR, "asset_or_resource_type": "USDT",
                "tx_or_operation_id": "77" * 32, "amount_base_units": "72140000",
                "block_number": "", "block_time": "2026-08-10T15:59:54+00:00",
                "evidence_reference": f"tron:{'77' * 32}:0",
                "acquisition_mode": "known_prior_evidence",
                "coverage_start": "2026-08-10T15:59:54+00:00",
                "coverage_end": "2026-08-10T15:59:54+00:00", "coverage_complete": "true",
                "temporal_status": TEMPORAL_HISTORICAL,
                "interpretation_limitations": "Already established and verified.",
            }
        )

    upgraded = backfill_operation_type(data_dir)
    assert upgraded == 3

    with csv_path.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    by_tx = {r["tx_or_operation_id"]: r for r in rows}
    assert by_tx["delegation-index:x"]["operation_type"] == OPERATION_CURRENT_INDEX
    assert by_tx["dd" * 32]["operation_type"] == OPERATION_DELEGATE
    assert by_tx["77" * 32]["operation_type"] == ""

    # Idempotent: running it again does not re-derive or change anything.
    assert backfill_operation_type(data_dir) == 0


def test_backfill_is_a_noop_when_the_file_is_missing(tmp_path: Path) -> None:
    assert backfill_operation_type(tmp_path / "data") == 0
