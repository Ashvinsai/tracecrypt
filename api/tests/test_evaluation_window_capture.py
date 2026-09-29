"""The requested-window provenance recorded by an evaluation-wallet capture.

I: requested-window fields appear in the saved manifest.
J: acquisition truncation never rewrites the requested window.
K: two captures with distinct windows get distinct run identities/bundles.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import httpx
import respx

from app.core.settings import AppEnv, DataMode, Settings
from app.services.collect_behavioral_evidence import (
    BehavioralEvidenceRequest,
    collect_behavioral_evidence,
)
from app.services.evaluation_wallets import EvaluationWallet, append_evaluation_wallet

BASE = "https://api.trongrid.io"
TOKEN_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
EVAL_ADDRESS = "TGcwj4sP1iiSwMrMEPmDw43J1V3CehK7rM"
TRC20_URL = f"{BASE}/v1/accounts/{EVAL_ADDRESS}/transactions/trc20"

START = dt.datetime(2026, 8, 10, tzinfo=dt.UTC)
CUTOFF = dt.datetime(2026, 8, 11, tzinfo=dt.UTC)


def live_settings() -> Settings:
    return Settings(
        app_env=AppEnv.dev,
        data_mode=DataMode.LIVE,
        tron_api_base=BASE,
        tron_api_key="test-key-not-a-real-one",
    )


def write_registry(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    append_evaluation_wallet(
        data_dir / "evaluation_wallets.csv",
        EvaluationWallet(
            network="tron",
            address=EVAL_ADDRESS,
            control_category="other_operational_confounder",
            source_reference="https://tronbid.com/en/blog/tronscan-tronbid-com-and-energy",
            evidence_type="first-party disclosure: operator's own blog",
            valid_from="2026-06-18",
            valid_to="",
            review_state="accepted",
            notes="fixture",
            upstream_source_id="tronbid-blog-fixture",
            reviewer="reviewer@tracecrypt.local",
            data_mode="RECORDED_PUBLIC",
        ),
    )


def eval_request(**overrides) -> BehavioralEvidenceRequest:
    kwargs = {
        "candidate_address": EVAL_ADDRESS,
        "token_contract": TOKEN_CONTRACT,
        "analysis_start": START,
        "analysis_cutoff": CUTOFF,
        "subject_kind": "evaluation_wallet",
    }
    kwargs.update(overrides)
    return BehavioralEvidenceRequest(**kwargs)


def empty_pages() -> None:
    respx.get(TRC20_URL).mock(
        side_effect=lambda request: httpx.Response(200, json={"data": [], "meta": {}})
    )


def _outgoing_row(tx_id: str) -> dict:
    return {
        "transaction_id": tx_id,
        "token_info": {
            "symbol": "USDT",
            "address": TOKEN_CONTRACT,
            "decimals": 6,
            "name": "Tether USD",
        },
        "block_timestamp": int(dt.datetime(2026, 8, 10, 12, tzinfo=dt.UTC).timestamp() * 1000),
        "from": EVAL_ADDRESS,
        "to": "TYfxtkCooUX7rzjRqBGLan9XkCxqkrCRir",
        "type": "Transfer",
        "value": "1000000",
    }


# --- I: requested-window fields appear in manifest.json ------------------------


@respx.mock
async def test_manifest_records_requested_window_provenance(tmp_path: Path) -> None:
    empty_pages()
    data_dir = tmp_path / "data"
    write_registry(data_dir)

    run = await collect_behavioral_evidence(
        live_settings(),
        eval_request(
            evaluation_window_rationale="Predeclared 24-hour operational observation window",
            evaluation_window_policy="ops-24h",
        ),
        out_root=tmp_path / "out",
        data_dir=data_dir,
    )

    manifest = json.loads((run.directory / "manifest.json").read_text())
    window = manifest["window_selection"]
    assert window["requested_window_start"] == START.isoformat()
    assert window["requested_window_cutoff"] == CUTOFF.isoformat()
    assert window["requested_window_duration_seconds"] == 86_400
    assert window["window_selected_by"] == "human_supplied"
    assert window["evaluation_window_rationale"] == (
        "Predeclared 24-hour operational observation window"
    )
    assert window["evaluation_window_policy"] == "ops-24h"
    assert window["capture_run_id"] == run.run_id
    assert window["wallet_id"]


# --- J: truncation does not rewrite the requested window -----------------------


@respx.mock
async def test_truncation_does_not_rewrite_requested_window(tmp_path: Path) -> None:
    position = {"incoming": 0, "outgoing": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if params.get("only_from") == "true":
            key = "outgoing"
        elif params.get("only_to") == "true":
            key = "incoming"
        else:
            return httpx.Response(200, json={"data": [], "meta": {}})
        index = position[key]
        position[key] = index + 1
        if key == "outgoing" and index == 0:
            return httpx.Response(
                200, json={"data": [_outgoing_row("ab" * 32)], "meta": {"fingerprint": "next"}}
            )
        return httpx.Response(200, json={"data": [], "meta": {}})

    respx.get(TRC20_URL).mock(side_effect=handler)
    data_dir = tmp_path / "data"
    write_registry(data_dir)

    run = await collect_behavioral_evidence(
        live_settings(),
        eval_request(page_limit=1),
        out_root=tmp_path / "out",
        data_dir=data_dir,
    )

    manifest = json.loads((run.directory / "manifest.json").read_text())
    assert manifest["truncated_by_page_limit"]["outgoing"] is True
    window = manifest["window_selection"]
    assert window["requested_window_start"] == START.isoformat()
    assert window["requested_window_cutoff"] == CUTOFF.isoformat()
    assert window["requested_window_duration_seconds"] == 86_400


# --- K: distinct windows get distinct run identities/bundles -------------------


@respx.mock
async def test_distinct_windows_get_distinct_bundles(tmp_path: Path) -> None:
    empty_pages()
    data_dir = tmp_path / "data"
    write_registry(data_dir)
    settings = live_settings()
    out_root = tmp_path / "out"

    first = await collect_behavioral_evidence(
        settings, eval_request(), out_root=out_root, data_dir=data_dir
    )
    second = await collect_behavioral_evidence(
        settings,
        eval_request(
            analysis_start=dt.datetime(2026, 8, 20, tzinfo=dt.UTC),
            analysis_cutoff=dt.datetime(2026, 8, 21, tzinfo=dt.UTC),
        ),
        out_root=out_root,
        data_dir=data_dir,
    )

    assert first.directory != second.directory
    assert (first.directory / "manifest.json").is_file()
    assert (second.directory / "manifest.json").is_file()

    first_window = json.loads((first.directory / "manifest.json").read_text())["window_selection"]
    second_window = json.loads((second.directory / "manifest.json").read_text())["window_selection"]
    assert first_window["requested_window_start"] != second_window["requested_window_start"]
    # Same wallet, different capture -- enough for downstream overlap reasoning.
    assert first_window["wallet_id"] == second_window["wallet_id"]
    assert first_window["capture_run_id"] != second_window["capture_run_id"]
