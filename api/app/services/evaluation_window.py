"""The human-selected analysis window for an evaluation-wallet capture.

A window is operator-supplied provenance, not something this module ever
chooses. It never derives a window from today's date, from another wallet's
capture, from chain activity, or from any outcome -- it only parses,
validates, and canonicalizes the exact bounds a human handed in. Choosing
"last 7 days" or "the window that looked interesting on chain" is
deliberately not possible here.

Datetime convention (inspected before choosing): the existing collector's
CLI (``scripts/collect_behavioral_evidence.py::parse_time``) accepts explicit
UTC offsets and silently treats a naive timestamp as UTC. This validator is
stricter: a naive timestamp is refused, and an explicit non-UTC offset is
normalized to UTC while preserving the exact instant. Normalizing an explicit
offset does not widen, shrink, or move a window; the printed canonical UTC is
what the capture uses. See docs/DECISIONS.md, 2026-09-21 entry.

The requested window is *not* evidence that observation was complete. The
collector's own acquisition/truncation fields remain authoritative; the
``window_selection`` manifest block this module describes says so explicitly
so the two are never conflated.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.feature_dataset import wallet_id


class EvaluationWindowError(ValueError):
    """The supplied window cannot be used. Never a silent default."""


#: Never claim more than this about the provenance of a set of bounds.
WINDOW_SELECTED_BY = "human_supplied"

_REQUESTED_WINDOW_CAVEAT = (
    "requested_window_* describe the requested scope only. Observed acquisition "
    "completeness and truncation are reported separately by the collector's "
    "truncated_by_* fields and are authoritative: a requested window does not "
    "imply complete observation."
)


def _parse_utc(value: str, field: str) -> dt.datetime:
    text = (value or "").strip()
    if not text:
        raise EvaluationWindowError(f"{field} is required and must not be blank")
    normalized = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise EvaluationWindowError(
            f"{field} is not a valid ISO8601 timestamp: {text!r}"
        ) from exc
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise EvaluationWindowError(
            f"{field} must be timezone-aware (e.g. ...Z or ...+00:00); naive "
            f"timestamp {text!r} refused"
        )
    return parsed.astimezone(dt.UTC)


@dataclass(frozen=True)
class EvaluationWindow:
    """One human-supplied, canonicalized (UTC) analysis window."""

    network: str
    address: str
    start: dt.datetime
    cutoff: dt.datetime
    rationale: str = ""
    policy: str = ""

    @property
    def duration_seconds(self) -> int:
        return int((self.cutoff - self.start).total_seconds())

    def render(self) -> str:
        lines = [
            "window (canonical UTC):",
            f"  requested_window_start:  {self.start.isoformat()}",
            f"  requested_window_cutoff: {self.cutoff.isoformat()}",
            f"  requested_window_duration_seconds: {self.duration_seconds}",
            f"  window_selected_by:      {WINDOW_SELECTED_BY}",
        ]
        if self.rationale.strip():
            lines.append(f"  evaluation_window_rationale: {self.rationale.strip()}")
        if self.policy.strip():
            lines.append(f"  evaluation_window_policy: {self.policy.strip()}")
        lines.append(f"  note: {_REQUESTED_WINDOW_CAVEAT}")
        return "\n".join(lines)

    def manifest_fields(self, *, run_id: str) -> dict[str, Any]:
        """The provenance block written into a capture bundle's manifest.

        Descriptive only: these fields record which window was requested and
        by whom (a human), never that the window is representative or that
        acquisition within it was complete.
        """
        return {
            "requested_window_start": self.start.isoformat(),
            "requested_window_cutoff": self.cutoff.isoformat(),
            "requested_window_duration_seconds": self.duration_seconds,
            "evaluation_window_rationale": self.rationale.strip(),
            "evaluation_window_policy": self.policy.strip(),
            "window_selected_by": WINDOW_SELECTED_BY,
            "wallet_id": wallet_id(self.network, self.address),
            "capture_run_id": run_id,
            "caveat": _REQUESTED_WINDOW_CAVEAT,
        }

    def canonical_env(self) -> str:
        """Shell-assignable canonical bounds, so a caller passes exactly the
        instants that were validated to the collector -- no re-parsing."""
        return (
            f"WINDOW_START_UTC={self.start.isoformat()}\n"
            f"WINDOW_CUTOFF_UTC={self.cutoff.isoformat()}\n"
        )


def parse_evaluation_window(
    *,
    network: str,
    address: str,
    start: str,
    cutoff: str,
    rationale: str = "",
    policy: str = "",
) -> EvaluationWindow:
    """Parse and validate a human-supplied window. Pure and deterministic:
    the same text always yields the same instants, and no bound is ever
    changed except an explicit offset being expressed in UTC."""
    parsed_start = _parse_utc(start, "WINDOW_START")
    parsed_cutoff = _parse_utc(cutoff, "WINDOW_CUTOFF")
    if parsed_cutoff == parsed_start:
        raise EvaluationWindowError(
            "WINDOW_CUTOFF equals WINDOW_START; a zero-duration window is refused"
        )
    if parsed_cutoff < parsed_start:
        raise EvaluationWindowError(
            f"WINDOW_CUTOFF {parsed_cutoff.isoformat()} is before WINDOW_START "
            f"{parsed_start.isoformat()}"
        )
    return EvaluationWindow(
        network=network,
        address=address,
        start=parsed_start,
        cutoff=parsed_cutoff,
        rationale=rationale,
        policy=policy,
    )


def classify_window_relation(
    *,
    existing_start: dt.datetime,
    existing_cutoff: dt.datetime,
    new_start: dt.datetime,
    new_cutoff: dt.datetime,
) -> str:
    """``identical`` | ``overlapping`` | ``distinct`` for a proposed capture
    against an already-saved preferred bundle's requested window. Reporting
    only: this never declares a window invalid, and never picks a grouping."""
    if existing_start == new_start and existing_cutoff == new_cutoff:
        return "identical"
    if new_cutoff <= existing_start or existing_cutoff <= new_start:
        return "distinct"
    return "overlapping"


def read_requested_window(run_dir: Path) -> tuple[dt.datetime, dt.datetime] | None:
    """The requested window recorded by an earlier capture bundle, or None if
    the bundle/manifest/marker is absent or unreadable. Prefers the
    ``window_selection`` block added for auditability and falls back to the
    older ``query.analysis_start``/``analysis_cutoff`` fields, which carry the
    same instants."""
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, ValueError):
        return None
    block = manifest.get("window_selection") or {}
    start_text = block.get("requested_window_start")
    cutoff_text = block.get("requested_window_cutoff")
    if not start_text or not cutoff_text:
        query = manifest.get("query") or {}
        start_text = query.get("analysis_start")
        cutoff_text = query.get("analysis_cutoff")
    if not start_text or not cutoff_text:
        return None
    try:
        return (
            dt.datetime.fromisoformat(start_text).astimezone(dt.UTC),
            dt.datetime.fromisoformat(cutoff_text).astimezone(dt.UTC),
        )
    except ValueError:
        return None
