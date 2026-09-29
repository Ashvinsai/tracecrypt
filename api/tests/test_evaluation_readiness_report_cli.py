"""Stage 3B.3: the readiness-report CLI script (scripts/evaluation_readiness_report.py)
actually works end-to-end offline, against a real subprocess invocation --
no guessed missing-argument call is left undemonstrated (item J)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "evaluation_readiness_report.py"


def test_readiness_cli_runs_offline_against_real_registry() -> None:
    """Runs against the repository's real data/evaluation_wallets.csv
    (read-only) and a real (possibly-empty) evidence root -- no network
    access, no --write flag, nothing mutated."""
    result = subprocess.run(  # noqa: S603 -- fixed, local script path; no untrusted input
        [
            sys.executable,
            str(SCRIPT),
            "--registry",
            str(REPO_ROOT / "data" / "evaluation_wallets.csv"),
            "--evidence-root",
            str(REPO_ROOT / "var" / "collect-behavioral-evidence" / "by-wallet"),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["model_metrics_reported"] is False
    assert report["no_model_trained_in_this_report"] is True
    assert "status" in report


def test_readiness_cli_runs_offline_against_synthetic_fixture(tmp_path: Path) -> None:
    """A fully synthetic, offline registry + saved bundle -- demonstrates the
    pipeline works without any live call (item L, via the CLI path)."""
    registry = tmp_path / "evaluation_wallets.csv"
    registry.write_text(
        "network,address,control_category,source_reference,evidence_type,valid_from,"
        "valid_to,review_state,notes,upstream_source_id,reviewer,data_mode\n"
        'tron,TSYNTHETICCLIWALLET,self_custody,"SYNTHETIC-source","SYNTHETIC fixture",'
        '2026-01-01,,accepted,"SYNTHETIC fixture only",,SYNTHETIC-reviewer,SYNTHETIC\n'
    )
    evidence_root = tmp_path / "evidence"
    run_dir = evidence_root / "tron" / "TSYNTHETICCLIWALLET" / "SYNTHETIC-run"
    run_dir.mkdir(parents=True)
    manifest = {
        "run_id": "SYNTHETIC-run",
        "query": {
            "candidate_address": "TSYNTHETICCLIWALLET",
            "analysis_start": "2026-01-01T00:00:00+00:00",
            "analysis_cutoff": "2026-01-02T00:00:00+00:00",
        },
        "truncated_by_page_limit": {"incoming": False, "outgoing": False},
        "truncated_by_event_limit": {"incoming": False, "outgoing": False},
        "truncated_by_request_budget": False,
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest))
    (run_dir / "evidence.json").write_text(json.dumps({"rows": []}))

    result = subprocess.run(  # noqa: S603 -- fixed, local script path; no untrusted input
        [
            sys.executable,
            str(SCRIPT),
            "--registry",
            str(registry),
            "--evidence-root",
            str(evidence_root),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["materialized_window_count_synthetic"] == 1
    assert report["materialized_window_count_real"] == 0
    assert report["real_wallet_count"] == 0
