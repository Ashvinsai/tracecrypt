"""Validate a human-supplied evaluation-wallet analysis window before any
network capture.

This CLI chooses nothing. The operator supplies WINDOW_START and WINDOW_CUTOFF
(or they are refused); this tool only parses, validates, canonicalizes to UTC,
and reports. It makes no provider calls.

    uv run python ../scripts/validate_evaluation_window.py \
        --network tron --address TXXXX \
        --start 2026-08-01T00:00:00Z --cutoff 2026-09-01T00:00:00Z \
        --rationale "Predeclared 24-hour operational observation window"

Optional:
    --policy NAME             a named window policy (descriptive provenance)
    --existing-bundle PATH    a previously saved by-wallet run directory; if it
                             has a manifest, report whether the new window is
                             identical / overlapping / distinct
    --canonical-out PATH      write shell assignments of the canonical UTC
                             bounds, so the caller passes the exact validated
                             instants on to the collector

Exit codes:
    0  valid window (any identical/overlapping/distinct relation is reported,
       not treated as an error)
    2  invalid window (blank, naive, malformed, or cutoff <= start)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "api"))

from app.services.collect_behavioral_evidence import run_dirs_in  # noqa: E402
from app.services.evaluation_window import (  # noqa: E402
    EvaluationWindowError,
    classify_window_relation,
    parse_evaluation_window,
    read_requested_window,
)


def _resolve_bundle(path: Path) -> Path | None:
    """Accept either one run directory (has manifest.json) or a wallet
    directory whose children are per-capture run directories; return the
    newest saved capture, or None if there is nothing to compare against."""
    if (path / "manifest.json").is_file():
        return path
    runs = run_dirs_in(path)
    return runs[-1] if runs else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--network", required=True)
    parser.add_argument("--address", required=True)
    parser.add_argument("--start", required=True, help="requested window start (ISO8601)")
    parser.add_argument("--cutoff", required=True, help="requested window cutoff (ISO8601)")
    parser.add_argument("--rationale", default="", help="optional descriptive provenance")
    parser.add_argument("--policy", default="", help="optional named window policy")
    parser.add_argument(
        "--existing-bundle",
        type=Path,
        default=None,
        help="a previously saved run directory to compare the requested window against",
    )
    parser.add_argument(
        "--canonical-out",
        type=Path,
        default=None,
        help="write shell assignments of the canonical UTC bounds to this path",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        window = parse_evaluation_window(
            network=args.network,
            address=args.address,
            start=args.start,
            cutoff=args.cutoff,
            rationale=args.rationale,
            policy=args.policy,
        )
    except EvaluationWindowError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    print(window.render())

    if args.existing_bundle is not None:
        resolved = _resolve_bundle(args.existing_bundle)
        existing = read_requested_window(resolved) if resolved is not None else None
        if resolved is None or existing is None:
            print(
                f"existing bundle: {args.existing_bundle} (no readable saved "
                "capture found; nothing to compare)"
            )
        else:
            print(f"existing bundle: {resolved}")
            existing_start, existing_cutoff = existing
            relation = classify_window_relation(
                existing_start=existing_start,
                existing_cutoff=existing_cutoff,
                new_start=window.start,
                new_cutoff=window.cutoff,
            )
            print(
                f"existing bundle requested window: "
                f"start={existing_start.isoformat()} cutoff={existing_cutoff.isoformat()}"
            )
            print(f"relation to new request: {relation} (reported, not enforced)")

    if args.canonical_out is not None:
        args.canonical_out.parent.mkdir(parents=True, exist_ok=True)
        args.canonical_out.write_text(window.canonical_env())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
