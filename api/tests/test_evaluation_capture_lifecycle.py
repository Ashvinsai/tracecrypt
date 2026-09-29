"""Evaluation-wallet capture lifecycle: staging -> validated -> atomic final.

A failed, interrupted, or malformed capture must never be materializable, and
a bounded-but-truncated capture must finalize as a valid partial run without
being called a failure.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import httpx
import pytest
import respx

from app.core.settings import AppEnv, DataMode, Settings
from app.services import collect_behavioral_evidence as cbe
from app.services.collect_behavioral_evidence import (
    BehavioralEvidenceError,
    BehavioralEvidenceRequest,
    CaptureBundleValidation,
    collect_behavioral_evidence,
    evaluation_rejected_root,
    evaluation_staging_dir,
    run_dirs_in,
    validate_evaluation_capture_bundle,
)
from app.services.evaluation_dataset import materialize_evaluation_dataset
from app.services.evaluation_review import (
    ACCEPTED_BUT_NO_MATERIALIZABLE_WINDOW,
    domain_eligibility_for_wallet,
)
from app.services.evaluation_wallets import EvaluationWallet, append_evaluation_wallet

BASE = "https://api.trongrid.io"
TOKEN_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
ADDRESS = "TGcwj4sP1iiSwMrMEPmDw43J1V3CehK7rM"
TRC20_URL = f"{BASE}/v1/accounts/{ADDRESS}/transactions/trc20"

START = dt.datetime(2026, 8, 10, tzinfo=dt.UTC)
CUTOFF = dt.datetime(2026, 8, 11, tzinfo=dt.UTC)
FAKE_SECRET = "FAKE-TRONGRID-SECRET-9999"


def _settings(*, key: str = "test-key-not-a-real-one") -> Settings:
    return Settings(
        app_env=AppEnv.dev,
        data_mode=DataMode.LIVE,
        tron_api_base=BASE,
        tron_api_key=key,
    )


def _registry(data_dir: Path) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    registry = data_dir / "evaluation_wallets.csv"
    append_evaluation_wallet(
        registry,
        EvaluationWallet(
            network="tron",
            address=ADDRESS,
            control_category="other_operational_confounder",
            source_reference="https://tronbid.com/en/blog/tronscan-tronbid-com-and-energy",
            evidence_type="first-party disclosure",
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


def _request(**overrides) -> BehavioralEvidenceRequest:
    kwargs = {
        "candidate_address": ADDRESS,
        "token_contract": TOKEN_CONTRACT,
        "analysis_start": START,
        "analysis_cutoff": CUTOFF,
        "subject_kind": "evaluation_wallet",
    }
    kwargs.update(overrides)
    return BehavioralEvidenceRequest(**kwargs)


def _empty_pages() -> None:
    respx.get(TRC20_URL).mock(
        side_effect=lambda request: httpx.Response(200, json={"data": [], "meta": {}})
    )


def _scan_for_secret(root: Path, secret: str) -> list[Path]:
    hits: list[Path] = []
    for path in root.rglob("*"):
        if path.is_file() and secret.encode() in path.read_bytes():
            hits.append(path)
    return hits


# --- successful capture: staging -> atomic final -------------------------------


@respx.mock
async def test_successful_capture_finalizes_atomically(tmp_path: Path) -> None:
    _empty_pages()
    data_dir = tmp_path / "data"
    registry = _registry(data_dir)
    evidence_root = tmp_path / "by-wallet"

    run = await collect_behavioral_evidence(
        _settings(), _request(), out_root=evidence_root, data_dir=data_dir
    )

    wallet_dir = evidence_root / "tron" / ADDRESS
    final_dir = wallet_dir / run.run_id
    assert run.directory == final_dir
    assert final_dir.is_dir()
    assert (final_dir / "manifest.json").is_file()
    assert (final_dir / "evidence.json").is_file()
    # staging is gone; no .staging-* child survives anywhere
    assert not evaluation_staging_dir(evidence_root, "tron", ADDRESS, run.run_id).exists()
    assert not [p for p in evidence_root.rglob(".staging-*")]

    manifest = json.loads((final_dir / "manifest.json").read_text())
    assert manifest["run_id"] == run.run_id
    assert manifest["run_status"] == "complete"
    assert manifest["acquisition_completeness"] == "complete_within_scope"
    assert manifest["capture_started_at"] and manifest["capture_completed_at"]

    assert run_dirs_in(wallet_dir) == [final_dir]

    result = materialize_evaluation_dataset(
        registry_path=registry, behavioral_evidence_root=evidence_root
    )
    assert len(result.rows) == 1
    assert not result.skipped


# --- staging is never materializable -------------------------------------------


def test_staging_directory_is_ignored_by_readers(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _registry(data_dir)
    evidence_root = tmp_path / "by-wallet"
    staging = evaluation_staging_dir(evidence_root, "tron", ADDRESS, "abc")
    staging.mkdir(parents=True)
    (staging / "manifest.json").write_text("{}")
    (staging / "evidence.json").write_text("{}")

    assert run_dirs_in(evidence_root / "tron" / ADDRESS) == []

    eligibility = domain_eligibility_for_wallet(data_dir, evidence_root, "tron", ADDRESS)
    assert eligibility == ACCEPTED_BUT_NO_MATERIALIZABLE_WINDOW

    result = materialize_evaluation_dataset(
        registry_path=data_dir / "evaluation_wallets.csv", behavioral_evidence_root=evidence_root
    )
    assert result.rows == []
    assert any(s.reason == "missing_evidence" for s in result.skipped)


# --- failure preservation ------------------------------------------------------


@respx.mock
async def test_failed_capture_is_preserved_and_never_materialized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _empty_pages()
    data_dir = tmp_path / "data"
    registry = _registry(data_dir)
    evidence_root = tmp_path / "by-wallet"

    def _fail_validation(path: Path) -> CaptureBundleValidation:
        return CaptureBundleValidation(
            path=path,
            ok=False,
            missing=("evidence.json",),
            errors=(),
            run_id=None,
            subject_kind="evaluation_wallet",
            network="tron",
            address=ADDRESS,
            data_mode="LIVE",
            acquisition_completeness=None,
            run_status=None,
        )

    monkeypatch.setattr(cbe, "validate_evaluation_capture_bundle", _fail_validation)

    with pytest.raises(BehavioralEvidenceError, match="finalize validation"):
        await collect_behavioral_evidence(
            _settings(), _request(run_id="runX"), out_root=evidence_root, data_dir=data_dir
        )

    wallet_dir = evidence_root / "tron" / ADDRESS
    assert not (wallet_dir / "runX").exists()
    assert not evaluation_staging_dir(evidence_root, "tron", ADDRESS, "runX").exists()

    rejected = evaluation_rejected_root(evidence_root)
    failure_dirs = sorted(rejected.glob("*runX*invalid"))
    assert len(failure_dirs) == 1
    record = json.loads((failure_dirs[0] / "FAILED.json").read_text())
    assert record["run_status"] == "failed"
    assert record["run_id"] == "runX"
    assert record["requested_window_start"] == START.isoformat()
    assert record["requests_completed"] >= 1
    assert record["raw_responses_present"] is True
    assert failure_dirs[0].joinpath("raw").is_dir()

    result = materialize_evaluation_dataset(
        registry_path=registry, behavioral_evidence_root=evidence_root
    )
    assert result.rows == []
    assert any(s.reason == "missing_evidence" for s in result.skipped)


# --- truncation is a valid partial run, not a failure --------------------------


@respx.mock
async def test_truncated_capture_finalizes_as_partial(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if params.get("only_from") == "true":
            return httpx.Response(200, json={"data": [], "meta": {"fingerprint": "next"}})
        return httpx.Response(200, json={"data": [], "meta": {}})

    respx.get(TRC20_URL).mock(side_effect=handler)
    data_dir = tmp_path / "data"
    registry = _registry(data_dir)
    evidence_root = tmp_path / "by-wallet"

    run = await collect_behavioral_evidence(
        _settings(),
        _request(page_limit=1),
        out_root=evidence_root,
        data_dir=data_dir,
    )

    manifest = json.loads((run.directory / "manifest.json").read_text())
    assert manifest["run_status"] == "partial"
    assert manifest["acquisition_completeness"] == "truncated"
    assert manifest["truncated_by_page_limit"]["outgoing"] is True

    result = materialize_evaluation_dataset(
        registry_path=registry, behavioral_evidence_root=evidence_root
    )
    assert len(result.rows) == 1
    assert result.rows[0].acquisition_completeness == "truncated"


# --- validator contract --------------------------------------------------------


@respx.mock
async def test_validator_accepts_a_real_bundle_and_reports_missing(tmp_path: Path) -> None:
    _empty_pages()
    data_dir = tmp_path / "data"
    _registry(data_dir)
    evidence_root = tmp_path / "by-wallet"
    run = await collect_behavioral_evidence(
        _settings(), _request(), out_root=evidence_root, data_dir=data_dir
    )

    good = validate_evaluation_capture_bundle(run.directory)
    assert good.ok is True
    assert good.run_id == run.run_id
    assert good.subject_kind == "evaluation_wallet"
    assert good.network == "tron"
    assert good.address == ADDRESS

    partial = tmp_path / "bad"
    partial.mkdir()
    (partial / "manifest.json").write_text("{}")
    bad = validate_evaluation_capture_bundle(partial)
    assert bad.ok is False
    assert "evidence.json" in bad.missing
    assert "raw/" in bad.missing


# --- secret hygiene ------------------------------------------------------------


@respx.mock
async def test_provider_secret_never_appears_anywhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _empty_pages()
    data_dir = tmp_path / "data"
    _registry(data_dir)
    evidence_root = tmp_path / "by-wallet"

    # A successful bundle...
    await collect_behavioral_evidence(
        _settings(key=FAKE_SECRET),
        _request(run_id="ok"),
        out_root=evidence_root,
        data_dir=data_dir,
    )
    # ...and a failed one, both configured with the same secret.
    monkeypatch.setattr(
        cbe,
        "validate_evaluation_capture_bundle",
        lambda path: CaptureBundleValidation(
            path=path,
            ok=False,
            missing=("evidence.json",),
            errors=(),
            run_id=None,
            subject_kind="evaluation_wallet",
            network="tron",
            address=ADDRESS,
            data_mode="LIVE",
            acquisition_completeness=None,
            run_status=None,
        ),
    )
    with pytest.raises(BehavioralEvidenceError):
        await collect_behavioral_evidence(
            _settings(key=FAKE_SECRET),
            _request(run_id="bad"),
            out_root=evidence_root,
            data_dir=data_dir,
        )

    assert _scan_for_secret(tmp_path, FAKE_SECRET) == []
