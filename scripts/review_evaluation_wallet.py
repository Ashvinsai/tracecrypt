"""Stage 3B.2: human review of ONE data/evaluation_wallets.csv record.

    # Show the review packet, decide nothing (valid, expected mode: no
    # --action/--reviewer supplied):
    uv run python ../scripts/review_evaluation_wallet.py \\
        --network tron --address TXXXX --category self_custody

    # Apply a decision (still dry-run without --write):
    uv run python ../scripts/review_evaluation_wallet.py \\
        --network tron --address TXXXX --category self_custody \\
        --action accept --reviewer "a.reviewer" \\
        --rationale "..." --evidence-inspected "<source_reference or upstream_source_id>" \\
        [--write]

This CLI never decides which action to apply -- it only validates and
applies the action explicitly supplied on the command line. It never
fetches a URL itself; the packet only shows what is already on file. It
never touches verified_anchors.csv, deposit_candidates.csv, review_log.csv,
independent_review.csv, or any behavioral-evidence/attribution output --
only data/evaluation_wallets.csv and data/evaluation_review_log.csv.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "api"))

from app.services.evaluation_review import (  # noqa: E402
    ReviewAction,
    ReviewRequest,
    build_review_packet,
    domain_eligibility_for_wallet,
    review_evaluation_wallet,
)

DEFAULT_DATA_DIR = REPO_ROOT / "data"
DEFAULT_EVIDENCE_ROOT = REPO_ROOT / "var" / "collect-behavioral-evidence" / "by-wallet"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--network", required=True)
    parser.add_argument("--address", required=True)
    parser.add_argument("--category", required=True, dest="control_category")
    parser.add_argument(
        "--action", choices=[a.value for a in ReviewAction], default=None,
        help="accept/reject/quarantine; omit to only print the review packet",
    )
    parser.add_argument("--reviewer", default=None, help="named human reviewer identity")
    parser.add_argument("--rationale", default=None)
    parser.add_argument("--evidence-inspected", default=None)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE_ROOT)
    parser.add_argument(
        "--write", action="store_true", help="actually apply the decision (default: dry-run)"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    packet = build_review_packet(args.data_dir, args.network, args.address, args.control_category)
    if packet is None:
        print(
            f"REFUSED: no evaluation_wallets.csv record for {args.network}/{args.address} "
            f"with control_category={args.control_category!r}",
            file=sys.stderr,
        )
        return 2

    print("=== Evaluation-wallet review packet ===")
    print(packet.render())
    eligibility = domain_eligibility_for_wallet(
        args.data_dir, args.evidence_root, args.network, args.address
    )
    print("\nfeature-domain eligibility (concept D, saved-evidence check only):")
    print(f"  {eligibility}")

    action = ReviewAction(args.action) if args.action else None
    request = ReviewRequest(
        network=args.network,
        address=args.address,
        control_category=args.control_category,
        action=action,
        reviewer=args.reviewer,
        rationale=args.rationale,
        evidence_inspected=args.evidence_inspected,
    )

    if action is None:
        print("\nNo --action supplied: packet displayed, nothing decided, nothing written.")
        return 0

    outcome = review_evaluation_wallet(args.data_dir, request, write=args.write)
    if outcome.refusal is not None:
        print(f"\nREFUSED [{outcome.refusal.code}]: {outcome.refusal.message}", file=sys.stderr)
        return 3

    applied = outcome.applied
    assert applied is not None
    print(
        f"\n{'WROTE' if args.write else 'DRY-RUN (not written)'}: "
        f"{applied.network}/{applied.address} [{applied.control_category}] "
        f"{applied.from_state} -> {applied.to_state} by {applied.reviewer} "
        f"at {applied.decided_at.isoformat()}"
    )
    if not args.write:
        print("Pass --write to actually apply this decision.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
