"""Stage 4 resume check: scripts/evaluation_wallet_resume.py.

The CLI is read-only and its exit codes are the documented interface the
wizard branches on, so these tests pin both the codes and the guarantee that
no registry, review, attribution, or anchor file is written.
"""

from __future__ import annotations

import csv
import hashlib
import subprocess
import sys
from pathlib import Path

from app.services.evaluation_wallets import EVALUATION_WALLET_COLUMNS

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "evaluation_wallet_resume.py"

ADDRESS = "TGcwj4sP1iiSwMrMEPmDw43J1V3CehK7rM"
CATEGORY = "other_operational_confounder"

BASE_ROW = {
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

PROTECTED_FILES = ("verified_anchors.csv", "deposit_candidates.csv", "review_log.csv")


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed, local script path; no untrusted input
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT / "api",
    )


def _write_registry(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=EVALUATION_WALLET_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _hash(path: Path) -> str:
    if not path.is_file():
        return "absent"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _args(registry: Path, *, category: str = CATEGORY, address: str = ADDRESS) -> list[str]:
    return [
        "--network",
        "tron",
        "--address",
        address,
        "--category",
        category,
        "--registry",
        str(registry),
    ]


def test_accepted_record_is_resumable(tmp_path: Path) -> None:
    registry = tmp_path / "evaluation_wallets.csv"
    _write_registry(registry, [dict(BASE_ROW)])

    result = _run(_args(registry))

    assert result.returncode == 0, result.stderr
    assert "existing registry record found" in result.stdout
    assert "accepted" in result.stdout
    assert "registration and review can be skipped" in result.stdout


def test_not_found_is_a_fresh_wallet(tmp_path: Path) -> None:
    registry = tmp_path / "evaluation_wallets.csv"
    _write_registry(registry, [])

    result = _run(_args(registry))

    assert result.returncode == 10, result.stderr
    assert "fresh wallet" in result.stdout


def test_unreviewed_record_requires_review(tmp_path: Path) -> None:
    registry = tmp_path / "evaluation_wallets.csv"
    row = {**BASE_ROW, "review_state": "unreviewed", "reviewer": ""}
    _write_registry(registry, [row])

    result = _run(_args(registry))

    assert result.returncode == 11, result.stderr
    assert "unreviewed" in result.stdout
    assert "only review remains" in result.stdout


def test_rejected_and_quarantined_records_are_refused(tmp_path: Path) -> None:
    for state in ("rejected", "quarantined"):
        registry = tmp_path / f"{state}.csv"
        row = {**BASE_ROW, "review_state": state}
        _write_registry(registry, [row])

        result = _run(_args(registry))

        assert result.returncode == 14, result.stderr
        assert state in result.stderr
        assert "not auto-promoted" in result.stderr


def test_category_mismatch_is_refused(tmp_path: Path) -> None:
    registry = tmp_path / "evaluation_wallets.csv"
    _write_registry(registry, [dict(BASE_ROW)])

    result = _run(_args(registry, category="self_custody"))

    assert result.returncode == 12, result.stderr
    assert "control_category" in result.stderr
    assert "refusing to guess" in result.stderr


def test_accepted_but_blank_source_is_refused(tmp_path: Path) -> None:
    registry = tmp_path / "evaluation_wallets.csv"
    row = {**BASE_ROW, "source_reference": ""}
    _write_registry(registry, [row])

    result = _run(_args(registry))

    assert result.returncode == 13, result.stderr
    assert "source_reference" in result.stderr


def test_accepted_but_automation_reviewer_is_refused(tmp_path: Path) -> None:
    registry = tmp_path / "evaluation_wallets.csv"
    row = {**BASE_ROW, "reviewer": "claude"}
    _write_registry(registry, [row])

    result = _run(_args(registry))

    assert result.returncode == 13, result.stderr
    assert "reviewer" in result.stderr


def test_resume_check_writes_no_registry_or_protected_file(tmp_path: Path) -> None:
    registry = tmp_path / "evaluation_wallets.csv"
    _write_registry(registry, [dict(BASE_ROW)])
    for name in PROTECTED_FILES:
        (tmp_path / name).write_text("sentinel\n")

    before = {path: _hash(path) for path in tmp_path.iterdir() if path.is_file()}

    result = _run(_args(registry))

    assert result.returncode == 0, result.stderr
    after = {path: _hash(path) for path in tmp_path.iterdir() if path.is_file()}
    assert before == after
    assert not (tmp_path / "evaluation_review_log.csv").exists()
