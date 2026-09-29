"""Stage 3B.3-ish: evaluation-wallet capture path for collect_behavioral_evidence.

This module never validates against deposit_candidates.csv/verified_anchors.csv
for subject_kind="evaluation_wallet" -- it validates against an ACCEPTED
evaluation_wallets.csv record instead, and is always bundle-only (never
appends to data/behavioral_evidence.csv, never writes deposit_candidates.csv,
verified_anchors.csv, review_log.csv, or evaluation_review_log.csv).
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import httpx
import pytest
import respx

from app.core.settings import AppEnv, DataMode, Settings
from app.services.collect_behavioral_evidence import (
    BehavioralEvidenceError,
    BehavioralEvidenceRequest,
    collect_behavioral_evidence,
    load_preferred_behavioral_run,
)
from app.services.evaluation_dataset import materialize_evaluation_dataset
from app.services.evaluation_wallets import (
    EvaluationWallet,
    append_evaluation_wallet,
)
from app.services.feature_dataset import DISALLOWED_FEATURE_NAME_FRAGMENTS

BASE = "https://api.trongrid.io"
TOKEN_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
EVAL_ADDRESS = "TGcwj4sP1iiSwMrMEPmDw43J1V3CehK7rM"

START = dt.datetime(2026, 8, 10, tzinfo=dt.UTC)
CUTOFF = dt.datetime(2026, 8, 11, tzinfo=dt.UTC)

TRC20_URL = f"{BASE}/v1/accounts/{EVAL_ADDRESS}/transactions/trc20"


def live_settings(**overrides) -> Settings:
    kwargs = {
        "app_env": AppEnv.dev,
        "data_mode": DataMode.LIVE,
        "tron_api_base": BASE,
        "tron_api_key": "test-key-not-a-real-one",
    }
    kwargs.update(overrides)
    return Settings(**kwargs)


def empty_pages() -> None:
    respx.get(TRC20_URL).mock(
        side_effect=lambda request: httpx.Response(200, json={"data": [], "meta": {}})
    )


def eval_wallet_request(**overrides) -> BehavioralEvidenceRequest:
    kwargs = {
        "candidate_address": EVAL_ADDRESS,
        "token_contract": TOKEN_CONTRACT,
        "analysis_start": START,
        "analysis_cutoff": CUTOFF,
        "subject_kind": "evaluation_wallet",
    }
    kwargs.update(overrides)
    return BehavioralEvidenceRequest(**kwargs)


def write_registry(
    data_dir: Path,
    *,
    review_state: str = "accepted",
    network: str = "tron",
    address: str = EVAL_ADDRESS,
) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    wallet = EvaluationWallet(
        network=network,
        address=address,
        control_category="other_operational_confounder",
        source_reference="https://tronbid.com/en/blog/tronscan-tronbid-com-and-energy",
        evidence_type="first-party disclosure: operator's own blog",
        valid_from="2026-06-18",
        valid_to="",
        review_state=review_state,
        notes="fixture",
        upstream_source_id="tronbid-blog-fixture",
        reviewer="reviewer@tracecrypt.local",
        data_mode="RECORDED_PUBLIC",
    )
    append_evaluation_wallet(data_dir / "evaluation_wallets.csv", wallet)


# --- A: existing candidate/anchor mode is unaffected (default subject_kind) --


def test_default_subject_kind_is_candidate_or_anchor() -> None:
    request = BehavioralEvidenceRequest(
        candidate_address="TXXX",
        token_contract=TOKEN_CONTRACT,
        analysis_start=START,
        analysis_cutoff=CUTOFF,
    )
    assert request.subject_kind == "candidate_or_anchor"


# --- B: an accepted evaluation record is accepted -----------------------------


@respx.mock
async def test_accepted_evaluation_wallet_is_accepted(tmp_path: Path) -> None:
    empty_pages()
    data_dir = tmp_path / "data"
    write_registry(data_dir, review_state="accepted")
    settings = live_settings()

    run = await collect_behavioral_evidence(
        settings,
        eval_wallet_request(),
        out_root=tmp_path / "out",
        data_dir=data_dir,
        write=False,
    )

    assert run.subject_kind == "evaluation_wallet"
    assert run.evaluation_wallet_snapshot is not None
    assert run.evaluation_wallet_snapshot["review_state"] == "accepted"


# --- C: refuses a quarantined evaluation record --------------------------------


@respx.mock
async def test_refuses_quarantined_evaluation_record(tmp_path: Path) -> None:
    empty_pages()
    data_dir = tmp_path / "data"
    write_registry(data_dir, review_state="quarantined")
    settings = live_settings()

    with pytest.raises(BehavioralEvidenceError, match="accepted evaluation-wallet record"):
        await collect_behavioral_evidence(
            settings, eval_wallet_request(), out_root=tmp_path / "out", data_dir=data_dir
        )


# --- D: refuses unreviewed/rejected/missing/wrong-network ---------------------


@respx.mock
@pytest.mark.parametrize("review_state", ["unreviewed", "rejected"])
async def test_refuses_non_accepted_review_states(tmp_path: Path, review_state: str) -> None:
    empty_pages()
    data_dir = tmp_path / "data"
    write_registry(data_dir, review_state=review_state)
    settings = live_settings()

    with pytest.raises(BehavioralEvidenceError, match="accepted evaluation-wallet record"):
        await collect_behavioral_evidence(
            settings, eval_wallet_request(), out_root=tmp_path / "out", data_dir=data_dir
        )


@respx.mock
async def test_refuses_missing_registry_record(tmp_path: Path) -> None:
    empty_pages()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    settings = live_settings()

    with pytest.raises(BehavioralEvidenceError, match="accepted evaluation-wallet record"):
        await collect_behavioral_evidence(
            settings, eval_wallet_request(), out_root=tmp_path / "out", data_dir=data_dir
        )


@respx.mock
async def test_refuses_wrong_network_record(tmp_path: Path) -> None:
    empty_pages()
    data_dir = tmp_path / "data"
    write_registry(data_dir, review_state="accepted", network="ethereum")
    settings = live_settings()

    with pytest.raises(BehavioralEvidenceError, match="accepted evaluation-wallet record"):
        await collect_behavioral_evidence(
            settings, eval_wallet_request(), out_root=tmp_path / "out", data_dir=data_dir
        )


# --- E: never promotes/labels; never writes registry/review CSVs --------------


@respx.mock
async def test_evaluation_capture_never_writes_registry_or_review_csvs(tmp_path: Path) -> None:
    empty_pages()
    data_dir = tmp_path / "data"
    write_registry(data_dir, review_state="accepted")
    settings = live_settings()

    await collect_behavioral_evidence(
        settings, eval_wallet_request(), out_root=tmp_path / "out", data_dir=data_dir
    )

    assert not (data_dir / "deposit_candidates.csv").exists()
    assert not (data_dir / "verified_anchors.csv").exists()
    assert not (data_dir / "review_log.csv").exists()
    assert not (data_dir / "evaluation_review_log.csv").exists()


# --- F: bundle-only -- write=True is refused, behavioral_evidence.csv untouched


@respx.mock
async def test_write_true_is_refused_for_evaluation_wallet(tmp_path: Path) -> None:
    empty_pages()
    data_dir = tmp_path / "data"
    write_registry(data_dir, review_state="accepted")
    settings = live_settings()

    with pytest.raises(BehavioralEvidenceError, match="bundle-only"):
        await collect_behavioral_evidence(
            settings,
            eval_wallet_request(),
            out_root=tmp_path / "out",
            data_dir=data_dir,
            write=True,
        )

    assert not (data_dir / "behavioral_evidence.csv").exists()


# --- G: manifest records subject_kind + registry snapshot for audit -----------


@respx.mock
async def test_manifest_records_subject_kind_and_registry_snapshot(tmp_path: Path) -> None:
    empty_pages()
    data_dir = tmp_path / "data"
    write_registry(data_dir, review_state="accepted")
    settings = live_settings()

    run = await collect_behavioral_evidence(
        settings, eval_wallet_request(), out_root=tmp_path / "out", data_dir=data_dir
    )

    manifest = json.loads((run.directory / "manifest.json").read_text())
    assert manifest["subject_kind"] == "evaluation_wallet"
    snapshot = manifest["evaluation_wallet_registry_snapshot"]
    assert snapshot["control_category"] == "other_operational_confounder"
    assert snapshot["source_reference"]
    assert snapshot["upstream_source_id"] == "tronbid-blog-fixture"
    assert snapshot["review_state"] == "accepted"
    assert snapshot["data_mode"] == "RECORDED_PUBLIC"


# --- H: the saved bundle is readable by load_preferred_behavioral_run and -----
# --- materialize_evaluation_dataset -------------------------------------------


@respx.mock
async def test_saved_bundle_is_readable_by_downstream_loaders(tmp_path: Path) -> None:
    empty_pages()
    data_dir = tmp_path / "data"
    write_registry(data_dir, review_state="accepted")
    settings = live_settings()

    run = await collect_behavioral_evidence(
        settings, eval_wallet_request(), out_root=tmp_path / "out", data_dir=data_dir
    )

    preferred = load_preferred_behavioral_run(run.directory)
    assert preferred.candidate_address == EVAL_ADDRESS

    evidence_root = tmp_path / "evidence-root"
    wallet_dir = evidence_root / "tron" / EVAL_ADDRESS / run.run_id
    wallet_dir.mkdir(parents=True)
    (wallet_dir / "manifest.json").write_bytes((run.directory / "manifest.json").read_bytes())
    (wallet_dir / "evidence.json").write_bytes((run.directory / "evidence.json").read_bytes())

    result = materialize_evaluation_dataset(
        registry_path=data_dir / "evaluation_wallets.csv",
        behavioral_evidence_root=evidence_root,
    )
    assert len(result.rows) == 1
    assert not result.skipped

    # --- I: materialized features never carry review state, service outcome,
    # strong-inference result, raw address, or source identity.
    row = result.rows[0]
    assert EVAL_ADDRESS not in row.wallet_id
    for name in row.features:
        lowered = name.lower()
        for fragment in DISALLOWED_FEATURE_NAME_FRAGMENTS:
            assert fragment not in lowered
    flat = row.to_flat_dict()
    assert EVAL_ADDRESS not in json.dumps(flat, default=str)
