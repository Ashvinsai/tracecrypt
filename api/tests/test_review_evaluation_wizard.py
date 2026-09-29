"""Orchestration tests for scripts/review_evaluation_wizard.sh.

The wizard is a bash script, so these tests drive the real script with a
piped stdin, a temporary evaluation registry, and a runner override
(``WIZARD_RUNNER``) that points at this interpreter instead of ``uv``. That
keeps the tests offline and fast without stubbing the tooling the wizard
branches on: the resume-check CLI, ingest dry-run, and review packet are all
the real scripts.
"""

from __future__ import annotations

import csv
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.services.evaluation_wallets import EVALUATION_WALLET_COLUMNS

REPO_ROOT = Path(__file__).resolve().parents[2]
WIZARD = REPO_ROOT / "scripts" / "review_evaluation_wizard.sh"
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None, reason="bash is not available")

ADDRESS = "TGcwj4sP1iiSwMrMEPmDw43J1V3CehK7rM"
CATEGORY = "other_operational_confounder"
PROTECTED = ("verified_anchors.csv", "deposit_candidates.csv", "review_log.csv")


def _row(**overrides: str) -> dict[str, str]:
    row = {
        "network": "tron",
        "address": ADDRESS,
        "control_category": CATEGORY,
        "source_reference": "https://tronbid.com/en/blog/tronscan-tronbid-com-and-energy",
        "evidence_type": "first-party disclosure",
        "valid_from": "2026-06-18",
        "valid_to": "",
        "review_state": "accepted",
        "notes": "operational marketplace address",
        "upstream_source_id": "tronbid-blog-2026-06-18",
        "reviewer": "reviewer@tracecrypt.local",
        "data_mode": "RECORDED_PUBLIC",
    }
    row.update(overrides)
    return row


def _write_registry(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=EVALUATION_WALLET_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _snapshot(root: Path) -> dict[str, str]:
    return {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class _Setup:
    def __init__(self, tmp_path: Path, rows: list[dict[str, str]]) -> None:
        self.tmp = tmp_path
        self.data = tmp_path / "data"
        self.registry = self.data / "evaluation_wallets.csv"
        _write_registry(self.registry, rows)
        for name in PROTECTED:
            (self.data / name).write_text("sentinel\n")
        env_file = tmp_path / "api.env"
        env_file.write_text("CFA_TRON_API_KEY=dummy-key\n")

        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        stub = bin_dir / "xdg-open"
        stub.write_text("#!/usr/bin/env bash\nexit 0\n")
        stub.chmod(0o755)

        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
                "WIZARD_RUNNER": sys.executable,
                "WIZARD_ENV_FILE": str(env_file),
                "EVAL_DATA_DIR": str(self.data),
                "EVAL_REGISTRY": str(self.registry),
                "EVAL_COLLECT_OUT": str(tmp_path / "collect"),
                "EVAL_EVIDENCE_ROOT": str(tmp_path / "collect" / "by-wallet"),
                "EVAL_DATASET_OUT": str(tmp_path / "dataset"),
                "EVAL_READINESS_OUT": str(tmp_path / "readiness" / "readiness.json"),
            }
        )
        self.env = env

    def before(self) -> dict[str, str]:
        return _snapshot(self.data)

    def run(self, lines: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 -- fixed local script path; input is test data
            [BASH, str(WIZARD)],
            input="\n".join(lines) + "\n",
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            env=self.env,
        )


def _outcome(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


def test_accepted_wallet_skips_register_and_review(tmp_path: Path) -> None:
    setup = _Setup(tmp_path, [_row()])
    before = setup.before()

    result = setup.run(["", "", "", ADDRESS, CATEGORY, "", "", ""])

    stdout = result.stdout
    assert result.returncode == 1, _outcome(result)
    assert "existing registry record found" in stdout
    assert "Stage 2 (register) skipped" in stdout
    assert "existing accepted review found" in stdout
    assert "Stage 3 (review) skipped" in stdout
    assert "Capture a saved behavioral window" in stdout
    assert "Dry run only" not in stdout  # ingest never ran
    assert "Evaluation-wallet review packet" not in stdout  # review never ran
    assert setup.before() == before


def test_missing_window_stops_at_human_gate(tmp_path: Path) -> None:
    setup = _Setup(tmp_path, [_row()])

    result = setup.run(["", "", "", ADDRESS, CATEGORY, "", "", ""])

    assert result.returncode == 1, _outcome(result)
    assert "WINDOW_START and WINDOW_CUTOFF are human-supplied" in result.stdout
    assert "Stopping before any network capture" in result.stdout
    assert "Run the live capture now" not in result.stdout


def test_unreviewed_wallet_does_not_skip_human_review(tmp_path: Path) -> None:
    setup = _Setup(tmp_path, [_row(review_state="unreviewed", reviewer="")])
    before = setup.before()

    result = setup.run(
        ["", "", "", ADDRESS, CATEGORY, "Test Reviewer", "why", "tronbid-blog-2026-06-18", "n",
         "", "", ""]
    )

    stdout = result.stdout
    assert result.returncode == 1, _outcome(result)
    assert "still required" in stdout
    assert "Evaluation-wallet review packet" in stdout
    assert "Dry run only" not in stdout  # registration skipped (duplicate)
    assert setup.before() == before
    assert not (setup.data / "evaluation_review_log.csv").exists()


def test_quarantined_wallet_is_refused(tmp_path: Path) -> None:
    setup = _Setup(tmp_path, [_row(review_state="quarantined")])
    before = setup.before()

    result = setup.run(["", "", "", ADDRESS, CATEGORY])

    assert result.returncode == 14, _outcome(result)
    assert "resume refused" in result.stdout
    assert setup.before() == before


def test_category_mismatch_is_refused(tmp_path: Path) -> None:
    setup = _Setup(tmp_path, [_row(control_category="self_custody")])
    before = setup.before()

    result = setup.run(["", "", "", ADDRESS, CATEGORY])

    assert result.returncode == 12, _outcome(result)
    assert "resume refused" in result.stdout
    assert "Dry run only" not in result.stdout
    assert setup.before() == before


def test_wizard_validates_window_before_the_collector(tmp_path: Path) -> None:
    setup = _Setup(tmp_path, [_row()])
    before = setup.before()

    result = setup.run(
        [
            "",
            "",
            "",
            ADDRESS,
            CATEGORY,
            "",
            "2026-08-01T00:00:00Z",
            "2026-08-02T00:00:00Z",
            "predeclared 24h",
            "",
            "",
            "",
            "",
            "n",
            "n",
        ]
    )

    stdout = result.stdout
    assert result.returncode == 0, _outcome(result)
    assert "requested_window_start:  2026-08-01T00:00:00+00:00" in stdout
    assert "requested_window_duration_seconds: 86400" in stdout
    assert "predeclared 24h" in stdout
    assert stdout.index("requested_window_start") < stdout.index("Run the live capture now")
    assert "capture skipped" in stdout
    assert "window validation failed" not in stdout
    assert setup.before() == before


def test_invalid_window_stops_before_any_provider_call(tmp_path: Path) -> None:
    setup = _Setup(tmp_path, [_row()])
    before = setup.before()

    result = setup.run(["", "", "", ADDRESS, CATEGORY, "", "not-a-date", "2026-08-02T00:00:00Z"])

    assert result.returncode == 2, _outcome(result)
    assert "REFUSED" in _outcome(result)
    assert "window validation failed" in result.stdout
    assert "Run the live capture now" not in result.stdout
    assert "capture skipped" not in result.stdout
    assert setup.before() == before


def test_fresh_wallet_path_still_works(tmp_path: Path) -> None:
    setup = _Setup(tmp_path, [])
    before = setup.before()

    result = setup.run(
        [
            "",
            "",
            "",
            "TNewWalletAddressForWizardTest",
            CATEGORY,
            "https://example.invalid/independent-attestation",
            "first-party disclosure",
            "Test Reviewer",
            "",
            "n",
        ]
    )

    stdout = result.stdout
    assert result.returncode == 0, _outcome(result)
    assert "fresh wallet" in stdout
    assert "Dry run only" in stdout  # ingest ran
    assert "registration skipped" in stdout
    assert "existing registry record found" not in stdout
    assert setup.before() == before
