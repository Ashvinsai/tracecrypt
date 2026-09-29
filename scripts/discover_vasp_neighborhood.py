"""Bounded, report-only TRON/TRC-20 candidate neighborhood discovery.

A live run requires CFA_DATA_MODE=LIVE, CFA_LABEL_SOURCE=reviewed_sets, a
TronGrid key, explicit time bounds, and finite request/page/event/address caps.
Replay runs under RECORDED_PUBLIC using a prior run directory.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "api"))

from app.core.settings import DataMode, LabelSource, get_settings  # noqa: E402
from app.services.vasp_neighborhood import NeighborhoodRequest  # noqa: E402
from app.services.vasp_neighborhood_runner import (  # noqa: E402
    NeighborhoodDiscoveryError,
    run_discovery,
)

DEFAULT_OUT = REPO_ROOT / "var" / "vasp-neighborhood"
DEFAULT_DATA = REPO_ROOT / "data"
USDT_TRC20 = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anchor", required=True, help="accepted service_control anchor")
    parser.add_argument("--contract", required=True, help="verified TRC-20 token contract")
    parser.add_argument("--network", choices=("tron",), default="tron")
    parser.add_argument(
        "--start", type=parse_time, required=True, help="inclusive UTC window start"
    )
    parser.add_argument(
        "--cutoff", type=parse_time, required=True, help="inclusive UTC window cutoff"
    )
    parser.add_argument("--max-requests", type=int, required=True)
    parser.add_argument("--page-limit", type=int, required=True, help="pages for anchor history")
    parser.add_argument("--pages-per-address", type=int, required=True)
    parser.add_argument(
        "--event-limit",
        type=int,
        required=True,
        help="events retained per direction/address",
    )
    parser.add_argument(
        "--address-limit", type=int, required=True, help="candidate addresses inspected"
    )
    parser.add_argument("--no-verify-execution", action="store_true")
    parser.add_argument("--no-enrich-events", action="store_true")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--replay", type=Path, default=None)
    return parser


async def main_async(args: argparse.Namespace) -> int:
    settings = get_settings()
    if args.replay is None:
        if settings.data_mode is not DataMode.LIVE:
            print("live discovery requires CFA_DATA_MODE=LIVE", file=sys.stderr)
            return 2
        if settings.effective_label_source is not LabelSource.reviewed_sets:
            print("live discovery requires CFA_LABEL_SOURCE=reviewed_sets", file=sys.stderr)
            return 2
    elif settings.data_mode is not DataMode.RECORDED_PUBLIC:
        print("replay requires CFA_DATA_MODE=RECORDED_PUBLIC", file=sys.stderr)
        return 2

    try:
        request = NeighborhoodRequest(
            anchor_address=args.anchor,
            token_contract=args.contract,
            network=args.network,
            window_start=args.start,
            window_end=args.cutoff,
            max_requests=args.max_requests,
            page_limit=args.page_limit,
            pages_per_address=args.pages_per_address,
            event_limit=args.event_limit,
            address_limit=args.address_limit,
            verify_execution=not args.no_verify_execution,
            enrich_events=not args.no_enrich_events,
        )
        run = await run_discovery(
            settings,
            request,
            out_root=args.out_dir,
            data_dir=args.data_dir,
            replay_from=args.replay,
        )
    except (NeighborhoodDiscoveryError, ValueError) as exc:
        print(f"neighborhood discovery failed: {exc}", file=sys.stderr)
        return 2

    print(f"run                    {run.run_id} ({'replay' if run.replayed else 'live'})")
    print(f"bundle                 {run.directory}")
    print(f"provider requests      {run.requests_used}")
    print(f"recorded exchanges     {run.raw_exchange_count}")
    print(f"coverage complete      {str(run.result.coverage.complete).lower()}")
    print(f"addresses examined    {run.result.coverage.addresses_examined}")
    print(f"candidate relationships {len(run.result.candidates)}")
    for candidate in run.result.candidates:
        print(f"  {candidate.relationship_type:<34} {candidate.address}")
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(main_async(build_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
