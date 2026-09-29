"""Stage 2C2: resource-delegation and TRX-funding evidence for one candidate.

    uv run python ../scripts/collect_resource_evidence.py \
        --candidate TXXXX \
        --start 2026-08-10T15:00:00Z --cutoff 2026-08-11T00:00:00Z \
        --provider-limit 10 --funder-limit 10 --max-requests 20

Prints what each evidence row would become and writes nothing to
data/resource_evidence.csv until --write. Never writes verified_anchors.csv,
deposit_candidates.csv's review fields, or review_log.csv -- a resource
provider or a TRX funder is never promoted to an owner or a service label by
this command.
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
from app.services.collect_resource_evidence import (  # noqa: E402
    KnownTokenTransfer,
    ResourceEvidenceError,
    ResourceEvidenceRequest,
    collect_resource_evidence,
)
from app.services.resource_evidence_report import summarize  # noqa: E402

DEFAULT_OUT = REPO_ROOT / "var" / "collect-resource-evidence"
DEFAULT_DATA = REPO_ROOT / "data"


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--candidate", required=True, help="a known candidate or anchor address")
    parser.add_argument("--network", default="tron")
    parser.add_argument(
        "--start", type=parse_time, default=None, help="lower bound for the historical scan (UTC)"
    )
    parser.add_argument(
        "--cutoff", type=parse_time, default=None, help="upper bound for the historical scan (UTC)"
    )
    parser.add_argument(
        "--provider-limit",
        type=int,
        default=10,
        help="cap on resource_delegation rows kept, current-state and historical alike",
    )
    parser.add_argument(
        "--funder-limit", type=int, default=10, help="cap on trx_funding rows kept"
    )
    parser.add_argument(
        "--max-requests",
        type=int,
        default=None,
        help="cap on genuine network requests this collection may make; unset is unbounded",
    )
    parser.add_argument(
        "--known-transfer-counterparty", default=None, help="the accepted anchor H, if recording it"
    )
    parser.add_argument("--known-transfer-tx", default=None, help="tx hash of D -> H")
    parser.add_argument("--known-transfer-event", default=None, help="tron:<txid>:<event_index>")
    parser.add_argument("--known-transfer-amount", type=int, default=None, help="base units")
    parser.add_argument("--known-transfer-block-time", type=parse_time, default=None)
    parser.add_argument("--known-transfer-symbol", default="USDT")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument(
        "--write", action="store_true", help="without this, resource_evidence.csv is unchanged"
    )
    return parser


def _known_transfer(args: argparse.Namespace) -> KnownTokenTransfer | None:
    fields = (
        args.known_transfer_counterparty,
        args.known_transfer_tx,
        args.known_transfer_event,
        args.known_transfer_amount,
        args.known_transfer_block_time,
    )
    if all(f is None for f in fields):
        return None
    if any(f is None for f in fields):
        print(
            "--known-transfer-* flags must all be given together, or none of them",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return KnownTokenTransfer(
        counterparty_address=args.known_transfer_counterparty,
        tx_hash=args.known_transfer_tx,
        event_reference=args.known_transfer_event,
        amount_base_units=args.known_transfer_amount,
        block_time=args.known_transfer_block_time,
        asset_symbol=args.known_transfer_symbol,
    )


async def main_async(args: argparse.Namespace) -> int:
    settings = get_settings()
    request = ResourceEvidenceRequest(
        candidate_address=args.candidate,
        network_key=args.network,
        analysis_start=args.start,
        analysis_cutoff=args.cutoff,
        provider_limit=args.provider_limit,
        funder_limit=args.funder_limit,
        max_requests=args.max_requests,
        known_token_transfer=_known_transfer(args),
        run_id=args.run_id,
    )

    try:
        run = await collect_resource_evidence(
            settings, request, out_root=args.out_dir, data_dir=args.data_dir, write=args.write
        )
    except ResourceEvidenceError as exc:
        print(f"refused or failed: {exc}", file=sys.stderr)
        return 2

    counts = summarize([row.to_csv_row() for row in run.rows])
    if not counts.reconciles():
        raise AssertionError(
            f"category counts {counts.by_category} do not sum to "
            f"{counts.total_rows} rows -- refusing to print an inconsistent report"
        )

    print(f"run                    {run.run_id}")
    print(f"bundle                 {run.directory}")
    print(f"candidate              {run.candidate_address}")
    print(f"requests used          {run.requests_used}")
    print(f"rows found             {counts.total_rows}  (by category: {counts.by_category})")
    print(f"  historical token_transfer        {counts.historical_token_transfer}")
    print(f"  historical resource_delegation   {counts.historical_delegation_operations}")
    print(f"    delegate                       {counts.historical_delegate_operations}")
    print(f"    undelegate                     {counts.historical_undelegate_operations}")
    print(f"  current-state resource_delegation {counts.current_state_resource_relationships}")
    print(f"  incoming trx_funding              {counts.incoming_trx_funding}")
    print(f"truncated (provider)   {run.truncated_by_provider_limit}")
    print(f"truncated (funder)     {run.truncated_by_funder_limit}")
    print(f"truncated (budget)     {run.truncated_by_request_budget}")
    if run.delegation_index_error:
        print(f"delegation index error {run.delegation_index_error}")
    for err in run.delegated_resource_errors:
        print(f"  delegated-resource error: {err}")
    if run.history_scan_error:
        print(f"history scan error     {run.history_scan_error}")
    if not args.write:
        print("\nnothing written to resource_evidence.csv (pass --write)")
    else:
        print(
            "\nwrote resource evidence into resource_evidence.csv; no provider or "
            "funder is promoted to an owner or a service label by this command"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(main_async(build_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
