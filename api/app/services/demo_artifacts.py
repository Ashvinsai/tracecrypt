"""Read-only discovery of saved validation artifacts for the investigator console.

The local console already exposes saved *trace* presets (``demo_presets``) and
the fund-flow model (``reports.fund_flow``). Several real artifacts are on disk
that no read-only JSON route exposes yet: protocol-verifiable CCTP cross-chain
links, the System-1 routing shadow-validation bundles, candidate-neighborhood
reports, and evidence-export bundles.

This module only *reads and shapes* those files. It never recomputes an
attribution, promotes a candidate, contacts a network, or touches the database.
Every path is allow-listed under a known ``var/`` root and every run id must
match a strict pattern, so the console can never be pointed at an arbitrary
file. Missing artifacts are reported as missing, never as an empty success.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.core.settings import REPO_ROOT
from app.services.operational_status import verify_manifest_hashes

VAR = REPO_ROOT / "var"
LIVE_VALIDATION = VAR / "live-validation"
ROUTING_VALIDATION = VAR / "routing-validation"
VASP_NEIGHBORHOOD = VAR / "vasp-neighborhood"
EVIDENCE_EXPORT = VAR / "evidence-export"

#: One run id: letters, digits, dashes, underscores. No path separators, so a
#: run id can never escape its root even before ``_resolve_dir`` re-checks.
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")

CCTP_PROTOCOL = "circle_cctp_v2"


def _read_json(path: Path | None) -> Any:
    if path is None or not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _resolve_dir(root: Path, run_id: str) -> Path | None:
    """Resolve ``root/<run_id>`` and refuse anything outside ``root``."""

    if not RUN_ID.fullmatch(run_id):
        return None
    candidate = (root / run_id).resolve()
    if root.resolve() != candidate.parent:
        return None
    return candidate if candidate.is_dir() else None


def _integrity(manifest: Any, base_dir: Path | None) -> dict[str, Any]:
    return verify_manifest_hashes(manifest if isinstance(manifest, dict) else None, base_dir)


def _files_present(base_dir: Path, names: tuple[str, ...]) -> dict[str, bool]:
    return {name: (base_dir / name).is_file() for name in names}


# -- CCTP cross-chain bundles -------------------------------------------------


def list_cctp_bundles() -> list[dict[str, Any]]:
    """Saved CCTP V2 cross-chain validation bundles, newest first.

    A bundle qualifies when its directory holds a ``cross-chain-link.json`` and
    either its ``manifest.json`` or ``trace.json`` declares
    ``circle_cctp_v2``. The link file is returned verbatim; this module never
    re-links or re-derives the protocol transition.
    """

    if not LIVE_VALIDATION.is_dir():
        return []

    bundles: list[dict[str, Any]] = []
    for directory in sorted(LIVE_VALIDATION.iterdir()):
        if not directory.is_dir() or not RUN_ID.fullmatch(directory.name):
            continue
        link_path = directory / "cross-chain-link.json"
        if not link_path.is_file():
            continue
        manifest = _read_json(directory / "manifest.json")
        trace = _read_json(directory / "trace.json")
        protocol = ""
        if isinstance(manifest, dict):
            protocol = str(manifest.get("protocol") or "")
        if not protocol and isinstance(trace, dict):
            protocol = str(trace.get("protocol") or "")
        if protocol != CCTP_PROTOCOL:
            continue

        link = _read_json(link_path)
        if not isinstance(link, dict):
            continue

        bundles.append(
            {
                "run_id": directory.name,
                "protocol": protocol,
                "route": (manifest or {}).get("route")
                or (trace or {}).get("route")
                or link.get("protocol_family"),
                "link": link,
                "transfers": _read_json(directory / "normalized-transfers.json") or [],
                "receipts": _read_json(directory / "receipts.json"),
                "discovery": (trace or {}).get("discovery")
                if isinstance(trace, dict)
                else None,
                "manifest": manifest,
                "capture_data_mode": (manifest or {}).get("data_mode"),
                "presented_data_mode": "RECORDED_PUBLIC",
                "integrity": _integrity(manifest, directory),
                "files_present": _files_present(
                    directory,
                    (
                        "cross-chain-link.json",
                        "normalized-transfers.json",
                        "receipts.json",
                        "trace.json",
                        "report.html",
                        "manifest.json",
                    ),
                ),
            }
        )
    bundles.sort(key=lambda bundle: bundle["run_id"], reverse=True)
    return bundles


# -- System-1 routing validation bundles --------------------------------------


def list_routing_bundles() -> dict[str, Any]:
    """Saved System-1 routing shadow-validation bundles and comparisons.

    This is DECISION SUPPORT METADATA, never blockchain evidence: the bundle's
    own ``caveat`` and ``artifact_class`` are carried through untouched.
    """

    bundles: list[dict[str, Any]] = []
    if ROUTING_VALIDATION.is_dir():
        for directory in sorted(ROUTING_VALIDATION.iterdir()):
            if not directory.is_dir() or not RUN_ID.fullmatch(directory.name):
                continue
            manifest = _read_json(directory / "manifest.json")
            if not isinstance(manifest, dict):
                continue
            summary = _read_json(directory / "summary.json")
            bundles.append(
                {
                    "run_id": directory.name,
                    "manifest": manifest,
                    "summary": summary,
                    "scenarios": _read_json(directory / "scenario-results.json") or [],
                    "model_info": _read_json(directory / "model-info.json"),
                    "environment": _read_json(directory / "environment.json"),
                    "latencies": _read_json(directory / "latencies.json"),
                    "integrity": _integrity(manifest, directory),
                    "files_present": _files_present(
                        directory,
                        (
                            "summary.json",
                            "scenario-results.json",
                            "model-info.json",
                            "environment.json",
                            "latencies.json",
                            "README.md",
                            "manifest.json",
                        ),
                    ),
                }
            )
    bundles.sort(key=lambda bundle: bundle["run_id"], reverse=True)

    comparisons: list[dict[str, Any]] = []
    comparisons_dir = ROUTING_VALIDATION / "comparisons"
    if comparisons_dir.is_dir():
        for path in sorted(comparisons_dir.glob("*.json")):
            payload = _read_json(path)
            if isinstance(payload, dict):
                comparisons.append({"name": path.stem, "comparison": payload})

    return {"bundles": bundles, "comparisons": comparisons}


# -- VASP candidate-neighborhood reports --------------------------------------


def list_candidate_reports() -> list[dict[str, Any]]:
    """Saved candidate-neighborhood reports. Candidates are leads, not ownership."""

    reports: list[dict[str, Any]] = []
    if not VASP_NEIGHBORHOOD.is_dir():
        return reports
    for directory in sorted(VASP_NEIGHBORHOOD.iterdir()):
        if not directory.is_dir() or not RUN_ID.fullmatch(directory.name):
            continue
        report = _read_json(directory / "report.json")
        manifest = _read_json(directory / "manifest.json")
        if not isinstance(report, dict):
            continue
        if report.get("report_type") != "vasp_candidate_neighborhood":
            continue
        reports.append(
            {
                "run_id": directory.name,
                "report": report,
                "manifest": manifest,
                "integrity": _integrity(manifest, directory),
            }
        )
    reports.sort(key=lambda report: report["run_id"], reverse=True)
    return reports


# -- Evidence-export bundles --------------------------------------------------


def list_evidence_bundles() -> list[dict[str, Any]]:
    """Saved evidence-export bundles with a re-verified SHA-256 manifest."""

    bundles: list[dict[str, Any]] = []
    if not EVIDENCE_EXPORT.is_dir():
        return bundles
    for directory in sorted(EVIDENCE_EXPORT.iterdir()):
        if not directory.is_dir() or not RUN_ID.fullmatch(directory.name):
            continue
        manifest = _read_json(directory / "manifest.json")
        if not isinstance(manifest, dict):
            continue
        bundles.append(
            {
                "run_id": directory.name,
                "manifest": manifest,
                "integrity": _integrity(manifest, directory),
                "report_download": f"/console/evidence/{manifest.get('request_id')}"
                if manifest.get("request_id")
                else None,
            }
        )
    bundles.sort(key=lambda bundle: bundle["run_id"], reverse=True)
    return bundles
