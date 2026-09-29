from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest
import respx

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "discover_vasp_neighborhood.py"
spec = importlib.util.spec_from_file_location("discover_vasp_neighborhood_cli", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
cli = importlib.util.module_from_spec(spec)
sys.modules["discover_vasp_neighborhood_cli"] = cli
spec.loader.exec_module(cli)

from app.core.settings import AppEnv, DataMode, LabelSource, Settings  # noqa: E402
from app.services.vasp_neighborhood import NeighborhoodRequest  # noqa: E402
from app.services.vasp_neighborhood_runner import run_discovery  # noqa: E402

BASE = "https://api.trongrid.io"
ANCHOR = "TYfxtkCooUX7rzjRqBGLan9XkCxqkrCRir"
CUSTOMER = "TEocPZsTTRAK9x5TR66GnEbxKKU8zrNxgM"
UPSTREAM_ONE = "TNAswjFA1pwPKBzRpZkZrbRY2icoPKFmPw"
UPSTREAM_TWO = "TNra2hrZPeqP56HNMNVHvRpKVDCwkhxYhj"
TOKEN = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
SNAPSHOT = dt.datetime(2026, 8, 10, 15, 59, 54, tzinfo=dt.UTC)
TX1 = "11" * 32
TX2 = "22" * 32


def _settings(*, mode: DataMode, key: str | None) -> Settings:
    return Settings(
        app_env=AppEnv.test,
        data_mode=mode,
        label_source=LabelSource.reviewed_sets,
        label_dir="/unused-test-label-dir",
        secret_key="test-secret-key-that-is-long-enough-for-the-validator",
        tron_api_key=key,
        tron_api_base=BASE,
        _env_file=None,
    )


def _history_row(tx: str, *, source: str, target: str, timestamp: int, amount: str) -> dict:
    return {
        "transaction_id": tx,
        "block_timestamp": timestamp,
        "from": source,
        "to": target,
        "type": "Transfer",
        "value": amount,
        "token_info": {
            "symbol": "USDT",
            "address": TOKEN,
            "decimals": 6,
            "name": "Tether USD",
        },
    }


def _events(tx: str, *, source: str, target: str, timestamp: int, amount: str) -> dict:
    return {
        "data": [
            {
                "block_number": 85235532,
                "block_timestamp": timestamp,
                "contract_address": TOKEN,
                "event_index": 0,
                "event_name": "Transfer",
                "transaction_id": tx,
                "result": {"from": source, "to": target, "value": amount},
                "result_type": {"from": "address", "to": "address", "value": "uint256"},
            }
        ]
    }


def _anchor_dir(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    data.mkdir()
    (data / "verified_anchors.csv").write_text(
        "network,address,entity_name,entity_type,assertion_type,address_role,review_state,"
        "source_reference,retrieval_date,methodology,reviewer,valid_from,valid_to,"
        "last_verified_at,label_set_version,source_hash\n"
        f"tron,{ANCHOR},OKX,exchange,service_control,unknown,accepted,okx:source,"
        "2026-09-20T00:00:00+00:00,snapshot-only,reviewer,"
        "2026-08-10T15:59:54+00:00,2026-08-10T15:59:54+00:00,"
        "2026-09-20T00:00:00+00:00,test-labels,anchor-hash\n"
    )
    (data / "deposit_candidates.csv").write_text(
        "network,address,entity_name,entity_type,assertion_type,address_role,review_state,"
        "source_reference,retrieval_date,methodology,reviewer,valid_from,valid_to,"
        "last_verified_at,label_set_version,source_hash\n"
    )
    return data


def test_saved_live_discovery_reports_remain_candidates_and_preserve_zero_result() -> None:
    base = REPO_ROOT / "var" / "vasp-neighborhood"
    candidate = json.loads(
        (base / "20260926T142855Z-cc09f0" / "report.json").read_text()
    )
    zero = json.loads((base / "20260926T142326Z-8ac99c" / "report.json").read_text())

    assert candidate["anchor"]["assertion_type"] == "service_control"
    assert candidate["anchor"]["valid_from"] == SNAPSHOT.isoformat()
    assert candidate["anchor"]["valid_to"] == SNAPSHOT.isoformat()
    assert candidate["candidate_count"] == 1
    assert candidate["candidates"][0]["relationship_type"] == "deposit_candidate"
    assert candidate["candidates"][0]["review_status"] == "unreviewed"
    assert candidate["candidates"][0]["human_reviewed"] is False
    assert candidate["candidates"][0]["matched_rules"] == []
    assert zero["candidate_count"] == 0
    assert zero["candidates"] == []


def test_cli_requires_explicit_window_and_all_scan_budgets() -> None:
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--anchor", ANCHOR, "--contract", TOKEN])

    args = parser.parse_args(
        [
            "--anchor", ANCHOR,
            "--contract", TOKEN,
            "--start", "2026-08-10T15:00:00Z",
            "--cutoff", "2026-08-10T15:59:54Z",
            "--max-requests", "20",
            "--page-limit", "2",
            "--event-limit", "500",
            "--address-limit", "25",
            "--pages-per-address", "2",
        ]
    )
    assert args.start < args.cutoff
    assert args.max_requests == 20
    assert args.page_limit == 2
    assert args.event_limit == 500
    assert args.address_limit == 25
    assert args.pages_per_address == 2


@respx.mock
async def test_provider_failure_is_not_reported_as_zero_candidates(tmp_path: Path) -> None:
    data_dir = _anchor_dir(tmp_path)
    respx.get(f"{BASE}/v1/accounts/{ANCHOR}/transactions/trc20").mock(
        return_value=httpx.Response(500, json={"error": "provider unavailable"})
    )
    request = NeighborhoodRequest(
        anchor_address=ANCHOR,
        token_contract=TOKEN,
        network="tron",
        window_start=SNAPSHOT,
        window_end=SNAPSHOT,
        max_requests=2,
        page_limit=1,
        event_limit=10,
        address_limit=10,
    )

    run = await run_discovery(
        _settings(mode=DataMode.LIVE, key="test-key"), request,
        out_root=tmp_path / "runs", data_dir=data_dir,
    )
    report = json.loads((run.directory / "report.json").read_text())
    assert report["candidate_count"] == 0
    assert report["coverage"]["complete"] is False
    assert any("provider failure" in note for note in report["limitations"])
    assert (run.directory / "manifest.json").is_file()


@respx.mock
async def test_raw_bundle_replay_reproduces_candidate_relationships_without_network(
    tmp_path: Path,
) -> None:
    data_dir = _anchor_dir(tmp_path)
    timestamp = int(SNAPSHOT.timestamp() * 1000)
    history = [
        _history_row(
            TX1, source=CUSTOMER, target=ANCHOR, timestamp=timestamp, amount="2500000"
        ),
        _history_row(
            TX2, source=CUSTOMER, target=ANCHOR, timestamp=timestamp, amount="3000000"
        ),
    ]
    respx.get(f"{BASE}/v1/accounts/{ANCHOR}/transactions/trc20").mock(
        return_value=httpx.Response(200, json={"data": history, "meta": {"page_size": 4}})
    )
    for row in history:
        respx.get(f"{BASE}/v1/transactions/{row['transaction_id']}/events").mock(
            return_value=httpx.Response(
                200,
                json=_events(
                    row["transaction_id"], source=row["from"], target=row["to"],
                    timestamp=timestamp, amount=row["value"],
                ),
            )
        )
    candidate_in = [
        _history_row(
            "55" * 32,
            source=UPSTREAM_ONE,
            target=CUSTOMER,
            timestamp=timestamp - 60_000,
            amount="1000000",
        ),
        _history_row(
            "66" * 32,
            source=UPSTREAM_TWO,
            target=CUSTOMER,
            timestamp=timestamp - 30_000,
            amount="2000000",
        ),
    ]
    candidate_out = history
    respx.get(f"{BASE}/v1/accounts/{CUSTOMER}/transactions/trc20").mock(
        side_effect=[
            httpx.Response(200, json={"data": candidate_in, "meta": {"page_size": 2}}),
            httpx.Response(200, json={"data": candidate_out, "meta": {"page_size": 2}}),
        ]
    )
    for row in [*candidate_in, *candidate_out]:
        respx.get(f"{BASE}/v1/transactions/{row['transaction_id']}/events").mock(
            return_value=httpx.Response(
                200,
                json=_events(
                    row["transaction_id"], source=row["from"], target=row["to"],
                    timestamp=row["block_timestamp"], amount=row["value"],
                ),
            )
        )
    request = NeighborhoodRequest(
        anchor_address=ANCHOR, token_contract=TOKEN, network="tron",
        window_start=SNAPSHOT-dt.timedelta(minutes=2), window_end=SNAPSHOT,
        max_requests=12, page_limit=1, event_limit=10, address_limit=10,
        pages_per_address=1, verify_execution=False, enrich_events=True,
    )
    live = await run_discovery(
        _settings(mode=DataMode.LIVE, key="test-key"), request,
        out_root=tmp_path / "live", data_dir=data_dir,
    )

    replay = await run_discovery(
        _settings(mode=DataMode.RECORDED_PUBLIC, key=None), request,
        out_root=tmp_path / "replay", data_dir=data_dir,
        replay_from=live.directory,
    )

    assert replay.replayed is True
    assert replay.requests_used == 0
    assert replay.result.to_json()["candidates"] == live.result.to_json()["candidates"]
    assert (
        replay.result.to_json()["address_only_context"]
        == live.result.to_json()["address_only_context"]
    )
    replay_manifest = json.loads((replay.directory / "manifest.json").read_text())
    assert replay_manifest["data_mode"] == "RECORDED_PUBLIC"
    assert replay_manifest["mode"] == "replay"


@respx.mock
async def test_bounded_discovery_writes_candidate_report_without_registry_mutation(
    tmp_path: Path,
) -> None:
    data_dir = _anchor_dir(tmp_path)
    before = {
        name: (data_dir / name).read_bytes()
        for name in ("verified_anchors.csv", "deposit_candidates.csv")
    }
    timestamp = int(SNAPSHOT.timestamp() * 1000)
    anchor_history = [
        _history_row(
            TX1, source=CUSTOMER, target=ANCHOR, timestamp=timestamp, amount="2500000"
        ),
        _history_row(
            TX2, source=CUSTOMER, target=ANCHOR, timestamp=timestamp, amount="3000000"
        ),
    ]
    incoming = [
        _history_row(
            "55" * 32,
            source=UPSTREAM_ONE,
            target=CUSTOMER,
            timestamp=timestamp - 60_000,
            amount="1000000",
        ),
        _history_row(
            "66" * 32,
            source=UPSTREAM_TWO,
            target=CUSTOMER,
            timestamp=timestamp - 30_000,
            amount="2000000",
        ),
    ]
    respx.get(f"{BASE}/v1/accounts/{ANCHOR}/transactions/trc20").mock(
        return_value=httpx.Response(
            200, json={"data": anchor_history, "meta": {"page_size": len(anchor_history)}}
        )
    )
    respx.get(f"{BASE}/v1/accounts/{CUSTOMER}/transactions/trc20").mock(
        side_effect=[
            httpx.Response(200, json={"data": incoming, "meta": {"page_size": len(incoming)}}),
            httpx.Response(
                200,
                json={"data": anchor_history, "meta": {"page_size": len(anchor_history)}},
            ),
        ]
    )
    for row in [*anchor_history, *incoming]:
        respx.get(f"{BASE}/v1/transactions/{row['transaction_id']}/events").mock(
            return_value=httpx.Response(
                200,
                json=_events(
                    row["transaction_id"], source=row["from"], target=row["to"],
                    timestamp=row["block_timestamp"], amount=row["value"],
                ),
            )
        )

    request = NeighborhoodRequest(
        anchor_address=ANCHOR, token_contract=TOKEN, network="tron",
        window_start=SNAPSHOT - dt.timedelta(minutes=2), window_end=SNAPSHOT,
        max_requests=12, page_limit=1, event_limit=10, address_limit=10,
        pages_per_address=1, verify_execution=False, enrich_events=True,
    )
    run = await run_discovery(
        _settings(mode=DataMode.LIVE, key="test-key"), request,
        out_root=tmp_path / "runs", data_dir=data_dir,
    )

    report = json.loads((run.directory / "report.json").read_text())
    candidate, = report["candidates"]
    assert run.requests_used <= request.max_requests
    assert report["coverage"]["pages_used"] == 3
    assert report["coverage"]["pages_per_address"] == 1
    assert report["coverage"]["complete"] is True
    assert candidate["relationship_type"] == "collection_candidate"
    assert candidate["features"]["distinct_incoming_senders"] == 2
    assert data_dir.joinpath("verified_anchors.csv").read_bytes() == before["verified_anchors.csv"]
    assert (
        data_dir.joinpath("deposit_candidates.csv").read_bytes()
        == before["deposit_candidates.csv"]
    )
    assert (run.directory / "raw").is_dir()
    manifest = json.loads((run.directory / "manifest.json").read_text())
    assert manifest["configuration"]["data_mode"] == "LIVE"
    assert manifest["started_at"]
    assert manifest["provider_requests"] == run.requests_used
