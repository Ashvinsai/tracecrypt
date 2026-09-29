"""The canonical evaluation-wallet evidence layout:

    <evidence_root>/<network>/<address>/<run_id>/{manifest.json,evidence.json}

Writer and readers must agree: capture writes there, and materialization,
readiness, and domain eligibility discover every saved run child. Distinct
windows for one wallet coexist; no earlier capture is overwritten.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import httpx
import pytest
import respx

from app.core.settings import AppEnv, DataMode, Settings
from app.services.collect_behavioral_evidence import (
    BehavioralEvidenceError,
    BehavioralEvidenceRequest,
    collect_behavioral_evidence,
    evaluation_capture_dir,
    evaluation_wallet_evidence_dir,
    run_dirs_in,
    wallet_run_dirs,
)
from app.services.evaluation_dataset import materialize_evaluation_dataset
from app.services.evaluation_review import domain_eligibility_for_wallet
from app.services.evaluation_wallets import EvaluationWallet, append_evaluation_wallet

BASE = "https://api.trongrid.io"
TOKEN_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
EVAL_ADDRESS = "TGcwj4sP1iiSwMrMEPmDw43J1V3CehK7rM"
TRC20_URL = f"{BASE}/v1/accounts/{EVAL_ADDRESS}/transactions/trc20"


def _settings() -> Settings:
    return Settings(
        app_env=AppEnv.dev,
        data_mode=DataMode.LIVE,
        tron_api_base=BASE,
        tron_api_key="test-key-not-a-real-one",
    )


def _write_registry(data_dir: Path) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    registry = data_dir / "evaluation_wallets.csv"
    append_evaluation_wallet(
        registry,
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
    return registry


def _request(start: dt.datetime, cutoff: dt.datetime) -> BehavioralEvidenceRequest:
    return BehavioralEvidenceRequest(
        candidate_address=EVAL_ADDRESS,
        token_contract=TOKEN_CONTRACT,
        analysis_start=start,
        analysis_cutoff=cutoff,
        subject_kind="evaluation_wallet",
    )


# --- path helper safety --------------------------------------------------------


@pytest.mark.parametrize("bad", ["", ".", "..", "../escape", "a/b", "a\\b"])
def test_capture_dir_rejects_unsafe_run_id(tmp_path: Path, bad: str) -> None:
    with pytest.raises(BehavioralEvidenceError, match="unsafe run_id"):
        evaluation_capture_dir(tmp_path, "tron", EVAL_ADDRESS, bad)


@pytest.mark.parametrize("bad", ["", "..", "a/b", "a\\b"])
def test_wallet_dir_rejects_unsafe_network_or_address(tmp_path: Path, bad: str) -> None:
    with pytest.raises(BehavioralEvidenceError, match="unsafe network"):
        evaluation_wallet_evidence_dir(tmp_path, bad, EVAL_ADDRESS)
    with pytest.raises(BehavioralEvidenceError, match="unsafe address"):
        evaluation_wallet_evidence_dir(tmp_path, "tron", bad)


# --- capture writes the canonical layout ---------------------------------------


@respx.mock
async def test_capture_writes_canonical_nested_layout(tmp_path: Path) -> None:
    respx.get(TRC20_URL).mock(
        side_effect=lambda request: httpx.Response(200, json={"data": [], "meta": {}})
    )
    data_dir = tmp_path / "data"
    _write_registry(data_dir)
    evidence_root = tmp_path / "by-wallet"

    run = await collect_behavioral_evidence(
        _settings(),
        _request(dt.datetime(2026, 8, 10, tzinfo=dt.UTC), dt.datetime(2026, 8, 11, tzinfo=dt.UTC)),
        out_root=evidence_root,
        data_dir=data_dir,
    )

    expected = evidence_root / "tron" / EVAL_ADDRESS / run.run_id
    assert run.directory == expected
    assert (expected / "manifest.json").is_file()
    assert (expected / "evidence.json").is_file()
    assert run_dirs_in(evidence_root / "tron" / EVAL_ADDRESS) == [expected]


# --- distinct windows coexist and both materialize -----------------------------


@respx.mock
async def test_two_windows_coexist_and_both_materialize(tmp_path: Path) -> None:
    respx.get(TRC20_URL).mock(
        side_effect=lambda request: httpx.Response(200, json={"data": [], "meta": {}})
    )
    data_dir = tmp_path / "data"
    registry = _write_registry(data_dir)
    evidence_root = tmp_path / "by-wallet"

    first = await collect_behavioral_evidence(
        _settings(),
        _request(dt.datetime(2026, 8, 10, tzinfo=dt.UTC), dt.datetime(2026, 8, 11, tzinfo=dt.UTC)),
        out_root=evidence_root,
        data_dir=data_dir,
    )
    second = await collect_behavioral_evidence(
        _settings(),
        _request(dt.datetime(2026, 8, 20, tzinfo=dt.UTC), dt.datetime(2026, 8, 21, tzinfo=dt.UTC)),
        out_root=evidence_root,
        data_dir=data_dir,
    )

    # Same wallet directory, separate capture run directories -- neither
    # overwrites the other.
    wallet_dir = evidence_root / "tron" / EVAL_ADDRESS
    assert first.directory.parent == second.directory.parent == wallet_dir
    assert first.directory != second.directory
    assert sorted(p.name for p in wallet_run_dirs(evidence_root, "tron", EVAL_ADDRESS)) == sorted(
        [first.run_id, second.run_id]
    )

    eligibility = domain_eligibility_for_wallet(data_dir, evidence_root, "tron", EVAL_ADDRESS)
    assert eligibility == "materializable_window_present"

    result = materialize_evaluation_dataset(
        registry_path=registry, behavioral_evidence_root=evidence_root
    )
    assert len(result.rows) == 2
    assert len({row.wallet_id for row in result.rows}) == 1  # one wallet
    assert len({(r.window_start, r.window_end) for r in result.rows}) == 2  # two windows
    assert not result.skipped


async def test_unreadable_run_child_is_ignored(tmp_path: Path) -> None:
    wallet_dir = tmp_path / "by-wallet" / "tron" / EVAL_ADDRESS
    (wallet_dir / "not-a-bundle").mkdir(parents=True)
    (wallet_dir / "not-a-bundle" / "manifest.json").write_text("{}")
    assert run_dirs_in(wallet_dir) == []
