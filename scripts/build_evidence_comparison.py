"""Stage 2 gate: build the four-level evidence-comparison report offline.

    uv run python ../scripts/build_evidence_comparison.py --candidate TXXXX
    uv run python ../scripts/build_evidence_comparison.py --candidate TXXXX \\
        --behavioral-run-id 20260920T165506Z-ee96cd

Reads only what is already saved -- data/verified_anchors.csv,
data/deposit_candidates.csv, data/resource_evidence.csv, the most recently
finished collect_resource_evidence run bundle's manifest.json for this
candidate's resource-evidence truncation flags, and exactly one named
collect_behavioral_evidence run bundle (its own manifest.json and
evidence.json, never data/behavioral_evidence.csv) for level 3. Makes no
blockchain request. Writes var/evidence-comparison/<candidate>/
comparison.json and comparison.html.

By default the preferred behavioral run is the most recently *finished* one
for this candidate -- not necessarily the most complete one. Pass
--behavioral-run-id explicitly to name a specific run (e.g. after comparing
two runs' manifests and choosing the non-truncated one by hand).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "api"))

from app.reports.comparison import render_comparison_html  # noqa: E402
from app.services.collect_behavioral_evidence import load_preferred_behavioral_run  # noqa: E402
from app.services.evidence_comparison import build_comparison  # noqa: E402

DEFAULT_DATA = REPO_ROOT / "data"
DEFAULT_VAR = REPO_ROOT / "var"
DEFAULT_OUT = REPO_ROOT / "var" / "evidence-comparison"


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def _find_deposit_candidate_row(rows: list[dict[str, str]], address: str) -> dict[str, str] | None:
    for row in rows:
        if row.get("address") == address:
            return row
    return None


def _latest_manifest(run_root: Path, candidate_address: str) -> dict | None:
    """The most recently finished run bundle for this candidate under
    ``run_root``, read from disk only -- no network."""
    if not run_root.is_dir():
        return None
    matches = []
    for run_dir in sorted(run_root.iterdir()):
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("query", {}).get("candidate_address") == candidate_address:
            matches.append(manifest)
    if not matches:
        return None
    matches.sort(key=lambda m: m["provenance"]["run_finished_at"])
    return matches[-1]


def _latest_behavioral_run_dir(run_root: Path, candidate_address: str) -> Path | None:
    if not run_root.is_dir():
        return None
    matches = []
    for run_dir in sorted(run_root.iterdir()):
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("query", {}).get("candidate_address") == candidate_address:
            matches.append((manifest["provenance"]["run_finished_at"], run_dir))
    if not matches:
        return None
    matches.sort(key=lambda m: m[0])
    return matches[-1][1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--var-dir", type=Path, default=DEFAULT_VAR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--behavioral-run-id",
        default=None,
        help="an explicit collect_behavioral_evidence run id to prefer for level 3, "
        "under --var-dir/collect-behavioral-evidence/. Default: the most recently "
        "finished run for this candidate.",
    )
    args = parser.parse_args(argv)

    anchor_rows = _read_csv(args.data_dir / "verified_anchors.csv")
    deposit_rows = _read_csv(args.data_dir / "deposit_candidates.csv")
    resource_rows = _read_csv(args.data_dir / "resource_evidence.csv")
    deposit_candidate_row = _find_deposit_candidate_row(deposit_rows, args.candidate)

    resource_manifest = _latest_manifest(args.var_dir / "collect-resource-evidence", args.candidate)
    if resource_manifest is None:
        print(
            f"no collect_resource_evidence run found for {args.candidate}; "
            "truncation flags default to False",
            file=sys.stderr,
        )
    truncation = {
        "request_budget_truncated": bool(
            resource_manifest and resource_manifest.get("truncated_by_request_budget")
        ),
        "provider_limit_truncated": bool(
            resource_manifest and resource_manifest.get("truncated_by_provider_limit")
        ),
        "funder_limit_truncated": bool(
            resource_manifest and resource_manifest.get("truncated_by_funder_limit")
        ),
    }

    behavioral_run_root = args.var_dir / "collect-behavioral-evidence"
    if args.behavioral_run_id:
        behavioral_run_dir: Path | None = behavioral_run_root / args.behavioral_run_id
        if not behavioral_run_dir.is_dir():
            print(f"no such behavioral run directory: {behavioral_run_dir}", file=sys.stderr)
            return 2
    else:
        behavioral_run_dir = _latest_behavioral_run_dir(behavioral_run_root, args.candidate)

    behavioral_run = None
    if behavioral_run_dir is not None:
        behavioral_run = load_preferred_behavioral_run(behavioral_run_dir)
        print(f"using behavioral run {behavioral_run.run_id} for level 3", file=sys.stderr)
    else:
        print(
            f"no collect_behavioral_evidence run found for {args.candidate}; "
            "level 3 stays not_collected",
            file=sys.stderr,
        )

    report = build_comparison(
        args.candidate,
        deposit_candidate_row=deposit_candidate_row,
        anchor_rows=anchor_rows,
        resource_rows=resource_rows,
        behavioral_run=behavioral_run,
        **truncation,
    )

    out_dir = args.out_dir / args.candidate
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "comparison.json").write_text(json.dumps(asdict(report), indent=2, sort_keys=True))
    (out_dir / "comparison.html").write_text(render_comparison_html(report))

    print(f"wrote {out_dir / 'comparison.json'}")
    print(f"wrote {out_dir / 'comparison.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
