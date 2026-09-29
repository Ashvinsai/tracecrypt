"""Stage 4 resume check: decide whether an evaluation-wallet record can skip
the wizard's registration and review steps because it is already accepted.

This is a read-only orchestration helper. It never writes any file, never
changes a control_category, reviewer, or review_state, and never opens
verified_anchors.csv, deposit_candidates.csv, review_log.csv, or
evaluation_review_log.csv. Direct ingestion keeps its own duplicate-refusal
semantics (scripts/ingest_evaluation_wallet.py): this CLI exists so the wizard
can branch on an already-existing record, *not* so ingestion can silently
accept duplicates.

Exit codes are a stable, documented interface -- the wizard branches on them
explicitly rather than letting ``set -e`` turn an expected status into an
abort:

    0   accepted and resumable: skip registration AND review
    10  no record for this network/address: a fresh wallet; run the full path
    11  record exists and is 'unreviewed': skip registration only (a duplicate
        cannot be appended), but still require human review
    12  record exists with a DIFFERENT control_category than requested: stop
    13  record is 'accepted' but not resumable (blank source_reference, or a
        blank/automation-like reviewer): stop
    14  record exists and is terminal but NOT accepted ('rejected' or
        'quarantined'): stop -- this tool never auto-promotes it
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "api"))

from app.services.evaluation_review import is_invalid_reviewer  # noqa: E402
from app.services.evaluation_wallets import load_evaluation_wallets  # noqa: E402

DEFAULT_REGISTRY = REPO_ROOT / "data" / "evaluation_wallets.csv"

EXIT_ACCEPTED = 0
EXIT_NOT_FOUND = 10
EXIT_UNREVIEWED = 11
EXIT_CATEGORY_MISMATCH = 12
EXIT_ACCEPTED_INVALID = 13
EXIT_TERMINAL_NOT_ACCEPTED = 14


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--network", required=True)
    parser.add_argument("--address", required=True)
    parser.add_argument("--category", required=True, dest="control_category")
    parser.add_argument(
        "--registry", type=Path, default=DEFAULT_REGISTRY,
        help="evaluation_wallets.csv to inspect (read-only)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    registry: Path = args.registry

    wallets = load_evaluation_wallets(registry)
    same_address = [
        w for w in wallets if w.network == args.network and w.address == args.address
    ]

    if not same_address:
        print(
            f"resume-check: no record for {args.network}/{args.address} in {registry} "
            "-- fresh wallet, run the full register+review path"
        )
        return EXIT_NOT_FOUND

    exact = [w for w in same_address if w.control_category == args.control_category]
    if not exact:
        existing = sorted({w.control_category for w in same_address})
        print(
            f"resume-check: REFUSED -- {args.network}/{args.address} exists with "
            f"control_category {existing}, not the requested "
            f"{args.control_category!r}; refusing to guess which category you meant",
            file=sys.stderr,
        )
        return EXIT_CATEGORY_MISMATCH

    wallet = exact[0]
    if wallet.review_state == "accepted":
        if not wallet.source_reference.strip():
            print(
                "resume-check: REFUSED -- record is accepted but its source_reference "
                "is blank; fix the registry row before resuming",
                file=sys.stderr,
            )
            return EXIT_ACCEPTED_INVALID
        if is_invalid_reviewer(wallet.reviewer):
            print(
                "resume-check: REFUSED -- record is accepted but its reviewer is blank "
                "or automation-like; a named human reviewer must be on record",
                file=sys.stderr,
            )
            return EXIT_ACCEPTED_INVALID
        print(
            "resume-check: existing registry record found for "
            f"{args.network}/{args.address} [{args.control_category}]"
        )
        print(f"  review_state: {wallet.review_state}")
        print(f"  reviewer:     {wallet.reviewer}")
        print(f"  data_mode:    {wallet.data_mode}")
        print("  verdict: accepted -- registration and review can be skipped")
        return EXIT_ACCEPTED

    if wallet.review_state == "unreviewed":
        print(
            f"resume-check: record exists for {args.network}/{args.address} "
            f"[{args.control_category}] but review_state=unreviewed; registration "
            "would duplicate it, so only review remains (human decision required)"
        )
        return EXIT_UNREVIEWED

    print(
        f"resume-check: REFUSED -- record for {args.network}/{args.address} "
        f"[{args.control_category}] is review_state={wallet.review_state!r}; this "
        "terminal state is not auto-promoted and a duplicate cannot be appended",
        file=sys.stderr,
    )
    return EXIT_TERMINAL_NOT_ACCEPTED


if __name__ == "__main__":
    raise SystemExit(main())
