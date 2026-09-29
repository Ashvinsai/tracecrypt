"""Acceptance tests A/B/D for the Stage 3B safe local ingestion CLI."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ingest_evaluation_wallet.py"


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed, local script path; no untrusted input
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT / "api",
    )


def _sha(path: Path) -> str:
    if not path.is_file():
        return hashlib.sha256(b"").hexdigest()
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- A: dry-run validates, --write actually appends ---------------------------


def test_dry_run_validates_and_writes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "evaluation_wallets.csv"

    result = _run(
        [
            "--network",
            "tron",
            "--address",
            "TCLIROW",
            "--category",
            "self_custody",
            "--source-reference",
            "https://example.invalid/attestation",
            "--evidence-type",
            "self-attested and independently corroborated wallet",
            "--path",
            str(path),
        ]
    )

    assert result.returncode == 0, result.stderr
    assert "Dry run only" in result.stdout
    assert not path.exists()


def test_explicit_write_actually_appends(tmp_path: Path) -> None:
    path = tmp_path / "evaluation_wallets.csv"

    result = _run(
        [
            "--network",
            "tron",
            "--address",
            "TCLIROW",
            "--category",
            "self_custody",
            "--source-reference",
            "https://example.invalid/attestation",
            "--evidence-type",
            "self-attested and independently corroborated wallet",
            "--path",
            str(path),
            "--write",
        ]
    )

    assert result.returncode == 0, result.stderr
    assert path.exists()
    content = path.read_text()
    assert "TCLIROW" in content


# --- B: missing provenance is refused ------------------------------------------


def test_missing_source_reference_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "evaluation_wallets.csv"

    result = _run(
        [
            "--network",
            "tron",
            "--address",
            "TCLIROW",
            "--category",
            "self_custody",
            "--source-reference",
            "",
            "--evidence-type",
            "self-attested and independently corroborated wallet",
            "--path",
            str(path),
            "--write",
        ]
    )

    assert result.returncode != 0
    assert "REFUSED" in result.stderr
    assert not path.exists()


def test_duplicate_network_address_category_is_refused_not_double_appended(tmp_path: Path) -> None:
    path = tmp_path / "evaluation_wallets.csv"
    common = [
        "--network",
        "tron",
        "--address",
        "TCLIROW",
        "--category",
        "self_custody",
        "--source-reference",
        "https://example.invalid/attestation",
        "--evidence-type",
        "self-attested and independently corroborated wallet",
        "--path",
        str(path),
        "--write",
    ]
    first = _run(common)
    assert first.returncode == 0
    row_count_after_first = len(path.read_text().splitlines())

    second = _run(common)

    assert second.returncode != 0
    assert "REFUSED" in second.stderr
    assert len(path.read_text().splitlines()) == row_count_after_first


# --- D: writing an evaluation record never touches other data files -----------


def test_ingestion_never_touches_protected_data_files(tmp_path: Path) -> None:
    data_dir = REPO_ROOT / "data"
    protected = [
        data_dir / "verified_anchors.csv",
        data_dir / "deposit_candidates.csv",
        data_dir / "review_log.csv",
        data_dir / "independent_review.csv",
    ]
    before = {p: _sha(p) for p in protected}

    path = tmp_path / "evaluation_wallets.csv"
    result = _run(
        [
            "--network",
            "tron",
            "--address",
            "TCLIROW",
            "--category",
            "self_custody",
            "--source-reference",
            "https://example.invalid/attestation",
            "--evidence-type",
            "self-attested and independently corroborated wallet",
            "--path",
            str(path),
            "--write",
        ]
    )
    assert result.returncode == 0

    after = {p: _sha(p) for p in protected}
    assert before == after


def test_preserves_pre_existing_rows_byte_for_byte_on_append(tmp_path: Path) -> None:
    path = tmp_path / "evaluation_wallets.csv"
    first = _run(
        [
            "--network",
            "tron",
            "--address",
            "TFIRST",
            "--category",
            "self_custody",
            "--source-reference",
            "https://example.invalid/a",
            "--evidence-type",
            "attested",
            "--path",
            str(path),
            "--write",
        ]
    )
    assert first.returncode == 0
    before_lines = path.read_text().splitlines()

    second = _run(
        [
            "--network",
            "tron",
            "--address",
            "TSECOND",
            "--category",
            "self_custody",
            "--source-reference",
            "https://example.invalid/b",
            "--evidence-type",
            "attested",
            "--path",
            str(path),
            "--write",
        ]
    )
    assert second.returncode == 0
    after_lines = path.read_text().splitlines()

    assert after_lines[: len(before_lines)] == before_lines
