"""Review imported claims: list what is waiting, and record a decision.

    uv run python ../scripts/review_candidates.py list
    uv run python ../scripts/review_candidates.py decide \
        --address TXXXX --action accept \
        --reviewer "investigator-1" \
        --rationale "Found the address on the dated reserve file." \
        --evidence https://www.okx.com/proof-of-reserves/download \
        --write

Accepting is the only way a claim becomes usable for tracing, so it asks for
the source you opened and re-hashes the preserved copy before believing you.
Nothing is written without ``--write``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "api"))

from app.services.candidate_review import (  # noqa: E402
    ReviewAction,
    ReviewRequest,
    load_review_queue,
    review_candidates,
)

DEFAULT_DATA = REPO_ROOT / "data"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    subparsers = parser.add_subparsers(dest="command", required=True)

    listing = subparsers.add_parser("list", help="claims awaiting a decision")
    listing.add_argument("--state", action="append", default=None)
    listing.add_argument("--network", default=None)

    decide = subparsers.add_parser("decide", help="record one decision")
    decide.add_argument("--address", required=True)
    decide.add_argument("--network", default="tron")
    decide.add_argument(
        "--action", required=True, choices=[action.value for action in ReviewAction]
    )
    decide.add_argument("--reviewer", required=True, help="the person deciding")
    decide.add_argument("--rationale", required=True, help="why, in one sentence")
    decide.add_argument(
        "--evidence",
        action="append",
        default=[],
        help="what you opened; an accept must name the row's own source",
    )
    decide.add_argument(
        "--corroboration",
        action="append",
        default=[],
        help="evidence kinds supporting a promotion",
    )
    decide.add_argument(
        "--source-reference", default=None, help="when one address has several claims"
    )
    decide.add_argument(
        "--promote", action="store_true", help="move a reviewed lead to the anchors"
    )
    decide.add_argument("--acknowledge-conflict", action="store_true")
    decide.add_argument("--write", action="store_true", help="without this, nothing is written")
    return parser


def run_list(args: argparse.Namespace) -> int:
    states = tuple(args.state) if args.state else ("unreviewed",)
    queue = load_review_queue(args.data_dir, network_key=args.network, states=states)
    if not queue:
        print(f"nothing in state {list(states)}")
        return 0
    for item in queue:
        print(f"[{item.destination.value}] {item.describe()}")
        print(f"    file {item.source_file}  sha256:{item.source_hash[:16]}")
        if item.upstream_source:
            print(f"    upstream {item.upstream_source}")
    print(f"\n{len(queue)} awaiting review")
    return 0


def run_decide(args: argparse.Namespace) -> int:
    request = ReviewRequest(
        network_key=args.network,
        address=args.address,
        action=ReviewAction(args.action),
        reviewer=args.reviewer,
        rationale=args.rationale,
        evidence_inspected=tuple(args.evidence),
        corroboration=tuple(args.corroboration),
        conflict_acknowledged=args.acknowledge_conflict,
        promote=args.promote,
        source_reference=args.source_reference,
    )
    report = review_candidates(args.data_dir, [request], write=args.write)

    for applied in report.applied:
        print(
            f"{applied.address}: {applied.from_state} -> {applied.to_state} ({applied.action.value})"
        )
        if applied.promoted_to:
            print(f"  promoted to {applied.promoted_to.value}")
        for conflict in applied.conflicts_marked:
            print(f"  competing claim marked conflicted, preserved: {conflict}")
    for refusal in report.refusals:
        print(f"refused ({refusal.code}): {refusal.message}", file=sys.stderr)

    if not args.write:
        print("\nnothing written (pass --write)")
    return 0 if not report.refusals else 2


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run_list(args) if args.command == "list" else run_decide(args)


if __name__ == "__main__":
    raise SystemExit(main())
