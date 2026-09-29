"""The human-supplied evaluation window: parsing, validation, canonicalization,
relation reporting, and the validator CLI.

The window is never chosen by this code -- only parsed and checked.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.services.evaluation_window import (
    WINDOW_SELECTED_BY,
    EvaluationWindowError,
    classify_window_relation,
    parse_evaluation_window,
    read_requested_window,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "validate_evaluation_window.py"

ADDRESS = "TGcwj4sP1iiSwMrMEPmDw43J1V3CehK7rM"


def _window(**overrides):
    kwargs = {
        "network": "tron",
        "address": ADDRESS,
        "start": "2026-08-01T00:00:00Z",
        "cutoff": "2026-08-02T00:00:00Z",
    }
    kwargs.update(overrides)
    return parse_evaluation_window(**kwargs)


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed, local script path; no untrusted input
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT / "api",
    )


# --- A: valid UTC bounds preserve the exact instants --------------------------


def test_valid_utc_bounds_preserve_exact_instants() -> None:
    window = _window()

    assert window.start == dt.datetime(2026, 8, 1, tzinfo=dt.UTC)
    assert window.cutoff == dt.datetime(2026, 8, 2, tzinfo=dt.UTC)
    assert window.duration_seconds == 86_400
    assert window.start.tzinfo is dt.UTC
    assert window.cutoff.tzinfo is dt.UTC


# --- B: naive timestamps are refused ------------------------------------------


@pytest.mark.parametrize("field", ["start", "cutoff"])
def test_naive_timestamps_are_refused(field: str) -> None:
    with pytest.raises(EvaluationWindowError, match="timezone-aware"):
        _window(**{field: "2026-08-01T00:00:00"})


# --- C: explicit non-UTC offsets are normalized to UTC, instant preserved ------


def test_non_utc_offset_is_normalized_to_utc_preserving_instant() -> None:
    window = _window(start="2026-08-01T05:30:00+05:30")

    assert window.start == dt.datetime(2026, 8, 1, tzinfo=dt.UTC)
    assert window.start.isoformat() == "2026-08-01T00:00:00+00:00"


# --- D/E: ordering ------------------------------------------------------------


def test_cutoff_equal_to_start_is_refused() -> None:
    with pytest.raises(EvaluationWindowError, match="equals"):
        _window(start="2026-08-01T00:00:00Z", cutoff="2026-08-01T00:00:00Z")


def test_cutoff_before_start_is_refused() -> None:
    with pytest.raises(EvaluationWindowError, match="before"):
        _window(start="2026-08-02T00:00:00Z", cutoff="2026-08-01T00:00:00Z")


# --- F: blank and malformed values --------------------------------------------


@pytest.mark.parametrize("field", ["start", "cutoff"])
def test_blank_values_are_refused(field: str) -> None:
    with pytest.raises(EvaluationWindowError, match="must not be blank"):
        _window(**{field: "   "})


def test_malformed_timestamp_is_refused() -> None:
    with pytest.raises(EvaluationWindowError, match="not a valid ISO8601"):
        _window(start="not-a-date")


# --- manifest provenance + relation reporting ---------------------------------


def test_manifest_fields_are_descriptive_provenance_only() -> None:
    window = _window(rationale="predeclared window", policy="ops-24h")
    fields = window.manifest_fields(run_id="run-123")

    assert fields["requested_window_start"] == "2026-08-01T00:00:00+00:00"
    assert fields["requested_window_cutoff"] == "2026-08-02T00:00:00+00:00"
    assert fields["requested_window_duration_seconds"] == 86_400
    assert fields["evaluation_window_rationale"] == "predeclared window"
    assert fields["evaluation_window_policy"] == "ops-24h"
    assert fields["window_selected_by"] == WINDOW_SELECTED_BY == "human_supplied"
    assert fields["capture_run_id"] == "run-123"
    assert fields["wallet_id"]
    assert "not imply complete observation" in str(fields["caveat"])


def test_window_relation_classification() -> None:
    start = dt.datetime(2026, 8, 1, tzinfo=dt.UTC)
    cutoff = dt.datetime(2026, 8, 2, tzinfo=dt.UTC)

    assert (
        classify_window_relation(
            existing_start=start, existing_cutoff=cutoff, new_start=start, new_cutoff=cutoff
        )
        == "identical"
    )
    assert (
        classify_window_relation(
            existing_start=start,
            existing_cutoff=cutoff,
            new_start=start + dt.timedelta(hours=12),
            new_cutoff=cutoff + dt.timedelta(hours=12),
        )
        == "overlapping"
    )
    assert (
        classify_window_relation(
            existing_start=start,
            existing_cutoff=cutoff,
            new_start=cutoff,
            new_cutoff=cutoff + dt.timedelta(days=1),
        )
        == "distinct"
    )


def test_read_requested_window_prefers_window_selection_and_falls_back(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "window_selection": {
                    "requested_window_start": "2026-08-01T00:00:00+00:00",
                    "requested_window_cutoff": "2026-08-02T00:00:00+00:00",
                },
                "query": {"analysis_start": "1999-01-01T00:00:00+00:00"},
            }
        )
    )
    assert read_requested_window(tmp_path) == (
        dt.datetime(2026, 8, 1, tzinfo=dt.UTC),
        dt.datetime(2026, 8, 2, tzinfo=dt.UTC),
    )

    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "manifest.json").write_text(
        json.dumps(
            {
                "query": {
                    "analysis_start": "2026-08-01T00:00:00+00:00",
                    "analysis_cutoff": "2026-08-02T00:00:00+00:00",
                }
            }
        )
    )
    assert read_requested_window(legacy) == (
        dt.datetime(2026, 8, 1, tzinfo=dt.UTC),
        dt.datetime(2026, 8, 2, tzinfo=dt.UTC),
    )


# --- validator CLI ------------------------------------------------------------


def test_cli_valid_window_prints_canonical_and_writes_bounds(tmp_path: Path) -> None:
    canonical = tmp_path / "window.env"
    result = _run(
        [
            "--network",
            "tron",
            "--address",
            ADDRESS,
            "--start",
            "2026-08-01T05:30:00+05:30",
            "--cutoff",
            "2026-08-02T00:00:00Z",
            "--rationale",
            "predeclared",
            "--canonical-out",
            str(canonical),
        ]
    )

    assert result.returncode == 0, result.stderr
    assert "requested_window_start:  2026-08-01T00:00:00+00:00" in result.stdout
    assert "requested_window_duration_seconds: 86400" in result.stdout
    assert "predeclared" in result.stdout
    assert "WINDOW_START_UTC=2026-08-01T00:00:00+00:00" in canonical.read_text()
    assert "WINDOW_CUTOFF_UTC=2026-08-02T00:00:00+00:00" in canonical.read_text()


def test_cli_refuses_naive_and_leaves_no_bounds(tmp_path: Path) -> None:
    canonical = tmp_path / "window.env"
    result = _run(
        [
            "--network",
            "tron",
            "--address",
            ADDRESS,
            "--start",
            "2026-08-01T00:00:00",
            "--cutoff",
            "2026-08-02T00:00:00Z",
            "--canonical-out",
            str(canonical),
        ]
    )

    assert result.returncode == 2
    assert "REFUSED" in result.stderr
    assert not canonical.exists()


def test_cli_reports_relation_to_existing_bundle(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(
        json.dumps(
            {
                "window_selection": {
                    "requested_window_start": "2026-08-01T00:00:00+00:00",
                    "requested_window_cutoff": "2026-08-02T00:00:00+00:00",
                }
            }
        )
    )
    result = _run(
        [
            "--network",
            "tron",
            "--address",
            ADDRESS,
            "--start",
            "2026-08-01T00:00:00Z",
            "--cutoff",
            "2026-08-02T00:00:00Z",
            "--existing-bundle",
            str(bundle),
        ]
    )

    assert result.returncode == 0, result.stderr
    assert "relation to new request: identical" in result.stdout
