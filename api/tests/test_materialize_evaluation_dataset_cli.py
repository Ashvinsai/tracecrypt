"""CLI regression tests for writing materialized evaluation rows."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "materialize_evaluation_dataset.py"


def _write_registry(path: Path, address: str) -> None:
    path.write_text(
        "network,address,control_category,source_reference,evidence_type,valid_from,"
        "valid_to,review_state,notes,upstream_source_id,reviewer,data_mode\n"
        f"tron,{address},other_operational_confounder,SOURCE,EVIDENCE,2026-01-01,,"
        "accepted,fixture,upstream,reviewer,RECORDED_PUBLIC\n"
    )


def _write_bundle(root: Path, address: str) -> None:
    run_dir = root / "tron" / address / "run-1"
    run_dir.mkdir(parents=True)
    manifest = {
        "run_id": "run-1",
        "query": {
            "candidate_address": address,
            "analysis_start": "2026-01-01T00:00:00+00:00",
            "analysis_cutoff": "2026-01-02T00:00:00+00:00",
        },
        "truncated_by_page_limit": {"incoming": False, "outgoing": False},
        "truncated_by_event_limit": {"incoming": False, "outgoing": False},
        "truncated_by_request_budget": False,
    }
    row = {
        "network": "tron",
        "candidate_address": address,
        "direction": "incoming",
        "counterparty_address": "TCOUNTERPARTY",
        "token_contract": "TCONTRACT",
        "tx_hash": "TX1",
        "event_index": "0",
        "event_reference": "tron:TX1:0",
        "amount_base_units": "100",
        "block_number": "1",
        "block_time": "2026-01-01T00:00:00+00:00",
        "execution_status": "success",
        "confirmation_state": "confirmed",
        "ordering_ambiguous": "false",
        "evidence_reference": "e1",
        "acquisition_window_start": "2026-01-01T00:00:00+00:00",
        "acquisition_window_end": "2026-01-02T00:00:00+00:00",
        "coverage_status": "complete_within_scope",
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest))
    (run_dir / "evidence.json").write_text(json.dumps({"rows": [row]}))


def test_materialize_cli_writes_datetime_features_as_iso_strings(tmp_path: Path) -> None:
    registry = tmp_path / "evaluation_wallets.csv"
    address = "TEVALUATIONWALLET"
    _write_registry(registry, address)
    evidence_root = tmp_path / "evidence"
    _write_bundle(evidence_root, address)
    output = tmp_path / "dataset"

    result = subprocess.run(  # noqa: S603 -- fixed local script and temp paths
        [
            sys.executable,
            str(SCRIPT),
            "--registry",
            str(registry),
            "--evidence-root",
            str(evidence_root),
            "--out",
            str(output),
            "--write",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads((output / "wallet_window_rows.json").read_text())
    row = payload["rows"][0]
    assert row["feature__behavioral_behavioral_window_start"] == "2026-01-01T00:00:00+00:00"
    assert row["feature__behavioral_behavioral_window_end"] == "2026-01-02T00:00:00+00:00"
