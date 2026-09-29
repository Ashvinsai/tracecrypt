"""Run one live validation against TRON, or replay a saved one offline.

    # live (needs CFA_DATA_MODE=LIVE and CFA_TRON_API_KEY)
    uv run python ../scripts/validate_live.py \
        --address TXXXX --contract TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t \
        --seed-event tron:<txid>:0 \
        --start 2026-09-19T23:59:00Z --cutoff 2026-09-20T00:00:00Z \
        --max-requests 8

    # replay, offline, through the same parser and tracer
    CFA_DATA_MODE=RECORDED_PUBLIC uv run python ../scripts/validate_live.py \
        --replay ../var/live-validation/<run-id>

An explicitly requested live run fails when the mode or the key is missing. It
never reports a skipped or fixture run as a live one.
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
from app.services.live_validation import (  # noqa: E402
    LiveValidationError,
    ValidationRequest,
    run_validation,
)

DEFAULT_OUT = REPO_ROOT / "var" / "live-validation"


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--address", help="the seed address to trace from")
    parser.add_argument("--contract", help="the verified token contract")
    parser.add_argument("--seed-event", default=None, help="tron:<txid>:<event_index>")
    parser.add_argument("--network", default="tron")
    parser.add_argument("--decimals", type=int, default=6)
    parser.add_argument("--symbol", default="USDT")
    parser.add_argument(
        "--start",
        type=parse_time,
        default=None,
        help="lower bound for the seed-event search only, alongside --cutoff",
    )
    parser.add_argument("--cutoff", type=parse_time, default=None)
    parser.add_argument(
        "--max-requests",
        type=int,
        default=None,
        help="cap on genuine network requests across the whole run; unset is unbounded",
    )
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--replay",
        type=Path,
        default=None,
        help="a saved run directory; replays its raw/ through the same pipeline",
    )
    return parser


async def main_async(args: argparse.Namespace) -> int:
    settings = get_settings()
    replay_from = None
    address = args.address
    contract = args.contract
    seed_event = args.seed_event
    start = args.start
    cutoff = args.cutoff

    if args.replay is not None:
        if not args.replay.is_dir():
            print(f"no bundle at {args.replay}", file=sys.stderr)
            return 2
        replay_from = args.replay / "raw" if (args.replay / "raw").is_dir() else args.replay
        import json

        manifest_path = args.replay / "manifest.json"
        if manifest_path.is_file():
            # Replay the query the live run actually made, not a retyped one.
            query = json.loads(manifest_path.read_text())["query"]
            address = address or query["address"]
            contract = contract or query["token_contract"]
            seed_event = seed_event or query["seed_event_reference"]
            if start is None and query.get("analysis_start"):
                start = parse_time(query["analysis_start"])
            if cutoff is None and query.get("analysis_cutoff"):
                cutoff = parse_time(query["analysis_cutoff"])

    if not address or not contract:
        print("--address and --contract are required for a live run", file=sys.stderr)
        return 2

    request = ValidationRequest(
        address=address,
        token_contract=contract,
        seed_event_reference=seed_event,
        network_key=args.network,
        asset_decimals=args.decimals,
        asset_symbol=args.symbol,
        analysis_cutoff=cutoff,
        analysis_start=start,
        # A replay answers from a saved bundle, not the network -- never
        # budget-limited (the adapter itself only enforces this for a
        # genuine client; see TronGridAdapter._check_budget).
        max_requests=args.max_requests,
        run_id=args.run_id,
    )

    try:
        run = await run_validation(
            settings, request, out_root=args.out_dir, replay_from=replay_from
        )
    except LiveValidationError as exc:
        print(f"validation refused or failed: {exc}", file=sys.stderr)
        return 2

    payload = run.trace or {}
    print(f"run               {run.run_id}  ({'replay' if replay_from else 'live'})")
    print(f"bundle            {run.directory}")
    print(f"provider exchanges {run.exchanges}")
    print(f"data mode         {payload.get('scope', {}).get('data_mode')}")
    print(f"coverage          {payload.get('scope', {}).get('coverage_status')}")
    print(f"observed transfers {len(payload.get('observed_transfers', []))}")
    unverified = run.receipts.get("unverified", [])
    print(f"unverified events  {len(unverified)}")
    for ending in payload.get("branch_endings", []):
        label = ending.get("label")
        name = label["entity_name"] if label else "-"
        print(f"  {ending['endpoint_class']:<18} {ending['address']:<36} {name}")
    print("\ncompare the bundle against a public explorer before relying on it")
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(main_async(build_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
