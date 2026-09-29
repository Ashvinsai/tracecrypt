"""Stage 2C: find candidate deposit-address leads for one accepted anchor.

    uv run python ../scripts/collect_candidates.py \
        --anchor TXXXX --contract TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t \
        --start 2026-08-01T00:00:00Z --cutoff 2026-08-02T00:00:00Z \
        --candidate-limit 50 --max-requests 20

Prints what each candidate row would become and writes nothing to
data/deposit_candidates.csv until --write. A candidate is never promoted to
verified_anchors -- that is a separate human review decision made through
review_candidates.py, not something this command can do.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "api"))

from app.core.settings import get_settings  # noqa: E402
from app.services.collect_candidates import (  # noqa: E402
    CandidateCollectionError,
    CollectionRequest,
    collect_candidates,
)

DEFAULT_OUT = REPO_ROOT / "var" / "collect-candidates"
DEFAULT_DATA = REPO_ROOT / "data"


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--anchor", required=True, help="an already-accepted anchor address")
    parser.add_argument("--contract", required=True, help="the verified token contract")
    parser.add_argument("--network", default="tron")
    parser.add_argument("--decimals", type=int, default=6)
    parser.add_argument("--symbol", default="USDT")
    parser.add_argument("--start", type=parse_time, default=None, help="lower bound (UTC)")
    parser.add_argument("--cutoff", type=parse_time, default=None, help="upper bound (UTC)")
    parser.add_argument(
        "--candidate-limit",
        type=int,
        default=50,
        help="stop once this many distinct senders are found",
    )
    parser.add_argument(
        "--max-requests",
        type=int,
        default=None,
        help="cap on genuine network requests this collection may make; unset is unbounded",
    )
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument(
        "--write", action="store_true", help="without this, deposit_candidates.csv is unchanged"
    )
    return parser


async def main_async(args: argparse.Namespace) -> int:
    settings = get_settings()
    request = CollectionRequest(
        anchor_address=args.anchor,
        token_contract=args.contract,
        network_key=args.network,
        asset_decimals=args.decimals,
        asset_symbol=args.symbol,
        analysis_start=args.start,
        analysis_cutoff=args.cutoff,
        candidate_limit=args.candidate_limit,
        max_requests=args.max_requests,
        run_id=args.run_id,
    )

    try:
        run = await collect_candidates(
            settings, request, out_root=args.out_dir, data_dir=args.data_dir, write=args.write
        )
    except CandidateCollectionError as exc:
        print(f"refused or failed: {exc}", file=sys.stderr)
        return 2

    print(f"run                    {run.run_id}")
    print(f"bundle                 {run.directory}")
    print(f"anchor                 {run.anchor_address}  ({run.anchor_entity_name})")
    print(f"requests used          {run.requests_used}")
    print(f"candidates found       {len(run.candidates)}")
    print(f"truncated (limit)      {run.truncated_by_candidate_limit}")
    print(f"truncated (budget)     {run.truncated_by_request_budget}")
    if run.import_report is not None:
        print(f"import result          {run.import_report.summary()}")
        for rejection in run.import_report.rejections:
            print(f"  x  line {rejection.line}: {rejection.code}: {rejection.message}")
    if not args.write:
        print("\nnothing written to deposit_candidates.csv (pass --write)")
    else:
        print(
            "\nwrote candidate leads into deposit_candidates.csv, all unreviewed; "
            "review_candidates.py can inspect them, but promotion to a verified "
            "anchor is not offered from this set"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(main_async(build_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
