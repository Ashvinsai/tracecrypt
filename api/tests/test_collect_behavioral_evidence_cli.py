"""CLI-level tests for scripts/collect_behavioral_evidence.py's
--subject-kind/--evaluation-registry wiring.

These only exercise the CLI's argument parsing and dispatch to the
already-tested service layer (see test_collect_behavioral_evidence_evaluation_wallet.py
for the service-level guarantees). No live network call is made -- every
HTTP call is respx-mocked -- and no CSV outside each test's own tmp_path is
touched.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest
import respx

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "collect_behavioral_evidence.py"

spec = importlib.util.spec_from_file_location("collect_behavioral_evidence_cli", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
cli = importlib.util.module_from_spec(spec)
sys.modules["collect_behavioral_evidence_cli"] = cli
spec.loader.exec_module(cli)

from app.services.anchor_import import DisclosureKind, SourceDocument, import_anchors  # noqa: E402
from app.services.evaluation_wallets import (  # noqa: E402
    EvaluationWallet,
    append_evaluation_wallet,
)


def _known_candidate_dir(tmp_path: Path, address: str) -> Path:
    """``address`` exists as an (unreviewed) deposit candidate lead, using the
    same helper pattern as test_collect_behavioral_evidence.py's
    known_candidate_dir."""
    data_dir = tmp_path / "data"
    source = tmp_path / "candidates.csv"
    source.write_text(
        "network,address,entity_name,entity_type,assertion_type,address_role\n"
        f"tron,{address},unknown,unknown,deposit_candidate,unknown\n"
    )
    import_anchors(
        SourceDocument(
            path=source,
            url="tron:chain-observation:fixture",
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

BASE = "https://api.trongrid.io"
TOKEN_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
EVAL_ADDRESS = "TGcwj4sP1iiSwMrMEPmDw43J1V3CehK7rM"
CANDIDATE_ADDRESS = "TNtTcstZdy5vppwDMQuR9gy6n5rT4o7ptq"


def _trc20_url(address: str) -> str:
    return f"{BASE}/v1/accounts/{address}/transactions/trc20"


def _empty_pages(address: str) -> None:
    respx.get(_trc20_url(address)).mock(
        side_effect=lambda request: httpx.Response(200, json={"data": [], "meta": {}})
    )


def _write_registry(data_dir: Path, *, review_state: str = "accepted", network: str = "tron",
                     address: str = EVAL_ADDRESS) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    registry_path = data_dir / "evaluation_wallets.csv"
    wallet = EvaluationWallet(
        network=network,
        address=address,
        control_category="other_operational_confounder",
        source_reference="https://example.com/disclosure",
        evidence_type="first-party disclosure",
        valid_from="2026-06-18",
        valid_to="",
        review_state=review_state,
        notes="fixture",
        upstream_source_id="fixture-source",
        reviewer="reviewer@tracecrypt.local",
        data_mode="RECORDED_PUBLIC",
    )
    append_evaluation_wallet(registry_path, wallet)
    return registry_path


def _protected_csv_paths(data_dir: Path) -> list[Path]:
    return [
        data_dir / name
        for name in (
            "verified_anchors.csv",
            "deposit_candidates.csv",
            "review_log.csv",
            "evaluation_wallets.csv",
            "evaluation_review_log.csv",
        )
    ]


def _hash_existing(paths: list[Path]) -> dict[Path, str | None]:
    return {
        p: (hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None) for p in paths
    }


def _base_argv(tmp_path: Path, *, candidate: str, out_dir: Path) -> list[str]:
    return [
        "--candidate",
        candidate,
        "--token-contract",
        TOKEN_CONTRACT,
        "--start",
        "2026-08-10T00:00:00Z",
        "--cutoff",
        "2026-08-11T00:00:00Z",
        "--out-dir",
        str(out_dir),
        "--data-dir",
        str(tmp_path / "data"),
    ]


# --- help text documents both modes -------------------------------------------


def test_help_documents_subject_kind_and_evaluation_registry(capsys: pytest.CaptureFixture) -> None:
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--help"])
    out = capsys.readouterr().out
    assert "--subject-kind" in out
    assert "--evaluation-registry" in out
    assert "candidate_or_anchor" in out
    assert "evaluation_wallet" in out
    assert "bundle-only" in out


# --- default candidate/anchor CLI behavior is unchanged -----------------------


@respx.mock
def test_default_subject_kind_cli_behavior_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    _empty_pages(CANDIDATE_ADDRESS)
    _known_candidate_dir(tmp_path, CANDIDATE_ADDRESS)
    out_dir = tmp_path / "out"

    argv = _base_argv(tmp_path, candidate=CANDIDATE_ADDRESS, out_dir=out_dir)
    # No --subject-kind/--evaluation-registry supplied: identical to pre-change usage.
    exit_code = cli.main(argv)
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "nothing written to behavioral_evidence.csv" in out

    manifests = list(out_dir.rglob("manifest.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text())
    assert manifest["subject_kind"] == "candidate_or_anchor"


# --- accepted evaluation wallet admitted via CLI -------------------------------


@respx.mock
def test_evaluation_wallet_admitted_via_cli(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    _empty_pages(EVAL_ADDRESS)
    data_dir = tmp_path / "data"
    registry_path = _write_registry(data_dir, review_state="accepted")
    protected = _protected_csv_paths(data_dir)
    before = _hash_existing(protected)
    out_dir = tmp_path / "out"

    argv = _base_argv(tmp_path, candidate=EVAL_ADDRESS, out_dir=out_dir) + [
        "--subject-kind",
        "evaluation_wallet",
        "--evaluation-registry",
        str(registry_path),
    ]
    exit_code = cli.main(argv)
    captured = capsys.readouterr().out
    assert exit_code == 0

    manifests = list(out_dir.rglob("manifest.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text())
    assert manifest["subject_kind"] == "evaluation_wallet"
    assert manifest["evaluation_wallet_registry_snapshot"]["review_state"] == "accepted"

    # Canonical layout: <evidence_root>/<network>/<address>/<run_id>/
    assert manifests[0].parent.parent == out_dir / "tron" / EVAL_ADDRESS
    # The CLI reports the real saved path; no caller has to reconstruct it.
    assert f"bundle_path={manifests[0].parent}\n" in captured

    after = _hash_existing(protected)
    assert before == after


# --- quarantined evaluation wallet refused via CLI -----------------------------


@respx.mock
def test_evaluation_wallet_quarantined_refused_via_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    _empty_pages(EVAL_ADDRESS)
    data_dir = tmp_path / "data"
    registry_path = _write_registry(data_dir, review_state="quarantined")
    protected = _protected_csv_paths(data_dir)
    before = _hash_existing(protected)
    out_dir = tmp_path / "out"

    argv = _base_argv(tmp_path, candidate=EVAL_ADDRESS, out_dir=out_dir) + [
        "--subject-kind",
        "evaluation_wallet",
        "--evaluation-registry",
        str(registry_path),
    ]
    exit_code = cli.main(argv)
    err = capsys.readouterr().err
    assert exit_code == 2
    assert "accepted evaluation-wallet record" in err
    assert not list(out_dir.rglob("manifest.json"))

    after = _hash_existing(protected)
    assert before == after


# --- --write refused for evaluation_wallet mode, before any network activity --


def test_evaluation_wallet_write_refused_before_network(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    data_dir = tmp_path / "data"
    registry_path = _write_registry(data_dir, review_state="accepted")
    protected = _protected_csv_paths(data_dir)
    before = _hash_existing(protected)
    out_dir = tmp_path / "out"

    argv = _base_argv(tmp_path, candidate=EVAL_ADDRESS, out_dir=out_dir) + [
        "--subject-kind",
        "evaluation_wallet",
        "--evaluation-registry",
        str(registry_path),
        "--write",
    ]
    # No respx.mock active here at all: if the CLI attempted any network
    # call it would raise (respx is not intercepting), proving refusal
    # happens before any HTTP activity.
    exit_code = cli.main(argv)
    err = capsys.readouterr().err
    assert exit_code == 2
    assert "bundle-only" in err
    assert not list(out_dir.rglob("manifest.json"))
    assert not (data_dir / "behavioral_evidence.csv").exists()

    after = _hash_existing(protected)
    assert before == after
