"""Run one live validation against an EVM network, or replay a saved one offline.

    # live (needs CFA_DATA_MODE=LIVE and the network's own RPC setting:
    # CFA_ETHEREUM_RPC_URL for --network ethereum, CFA_BSC_RPC_URL for --network bsc)
    uv run python ../scripts/validate_evm_live.py \
        --network ethereum \
        --address 0x... --contract 0xdAC17F958D2ee523a2206206994597C13D831ec7 \
        --decimals 6 --symbol USDT \
        --start 2026-09-19T23:59:00Z --cutoff 2026-09-20T00:00:00Z \
        --max-requests 40

    # replay, offline, through the same parser and tracer. The network comes
    # from the saved manifest; an explicit, conflicting --network is refused.
    CFA_DATA_MODE=RECORDED_PUBLIC uv run python ../scripts/validate_evm_live.py \
        --replay ../var/live-validation/<run-id>

An explicitly requested live run fails when the mode or the RPC endpoint is
missing. It never silently substitutes a public RPC endpoint, and it never
reports a skipped or fixture run as a live one.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "api"))

from app.adapters.evm import (  # noqa: E402
    BLOCK_RESOLUTION_CURRENT,
    BLOCK_RESOLUTION_LEGACY,
    EVM_NETWORKS,
)
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
    parser.add_argument("--contract", help="the verified ERC-20 token contract")
    parser.add_argument(
        "--seed-event", default=None, help="eip155:<chain_id>:<tx_hash>:<log_index>"
    )
    parser.add_argument(
        "--network",
        choices=sorted(EVM_NETWORKS),
        default=None,
        help="live: the EVM network (default ethereum); replay: read from the manifest",
    )
    parser.add_argument(
        "--decimals",
        type=int,
        default=None,
        help="token decimals; checked against the contract's own decimals() (default 6)",
    )
    parser.add_argument("--symbol", default=None, help="display symbol only (default USDT)")
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
        help="cap on genuine RPC requests across the whole run; unset is unbounded",
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
    network = args.network
    decimals = args.decimals
    symbol = args.symbol
    max_requests = args.max_requests
    verify_token = True
    block_resolution_policy = BLOCK_RESOLUTION_CURRENT

    if args.replay is not None:
        if not args.replay.is_dir():
            print(f"no bundle at {args.replay}", file=sys.stderr)
            return 2
        replay_from = args.replay / "raw" if (args.replay / "raw").is_dir() else args.replay
        manifest_path = args.replay / "manifest.json"
        if not manifest_path.is_file():
            # The network is evidence, not a CLI default: without the manifest
            # there is nothing to say which chain these exchanges came from.
            print(f"no manifest.json in {args.replay}; cannot tell its network", file=sys.stderr)
            return 2
        manifest = json.loads(manifest_path.read_text())
        query = manifest["query"]
        recorded_network = query.get("network")
        if recorded_network not in EVM_NETWORKS:
            print(f"bundle network {recorded_network!r} is not an EVM network", file=sys.stderr)
            return 2
        if network is not None and network != recorded_network:
            print(
                f"--network {network!r} conflicts with the saved bundle's network "
                f"{recorded_network!r}; refusing to reinterpret recorded evidence",
                file=sys.stderr,
            )
            return 2
        network = recorded_network
        address = address or query["address"]
        contract = contract or query["token_contract"]
        seed_event = seed_event or query["seed_event_reference"]
        if start is None and query.get("analysis_start"):
            start = parse_time(query["analysis_start"])
        if cutoff is None and query.get("analysis_cutoff"):
            cutoff = parse_time(query["analysis_cutoff"])
        token = _read_json(args.replay / "token-verification.json")
        # Replay only the checks the LIVE run actually recorded.
        verify_token = token is not None
        if decimals is None and token is not None:
            decimals = token.get("requested_decimals")
        if symbol is None and token is not None:
            symbol = token.get("requested_display_symbol")
        configuration = manifest.get("configuration") or {}
        if max_requests is None:
            max_requests = configuration.get("acquisition_max_requests")
        # Reissue exactly the requests the bundle holds: a bundle recorded
        # before the policy was written down used the legacy start bound.
        block_resolution_policy = configuration.get(
            "evm_block_resolution_policy", BLOCK_RESOLUTION_LEGACY
        )

    network = network or "ethereum"
    decimals = 6 if decimals is None else decimals
    symbol = symbol or "USDT"

    if not address or not contract:
        print("--address and --contract are required for a live run", file=sys.stderr)
        return 2

    if replay_from is None and not settings.evm_rpc_url(network):
        # Constraint: never silently choose a public RPC endpoint, and never
        # another network's. Only the variable's name is printed, never a value.
        label = {"ethereum": "Ethereum", "bsc": "BSC"}.get(network, network)
        print(
            f"{label} LIVE validation blocked: RPC not configured "
            f"(set {EVM_NETWORKS[network].rpc_env_var})",
            file=sys.stderr,
        )
        return 2

    request = ValidationRequest(
        address=address,
        token_contract=contract,
        seed_event_reference=seed_event,
        network_key=network,
        asset_decimals=decimals,
        asset_symbol=symbol,
        analysis_cutoff=cutoff,
        analysis_start=start,
        max_requests=max_requests,
        run_id=args.run_id,
        verify_token=verify_token,
        block_resolution_policy=block_resolution_policy,
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
        print(f"  {ending['endpoint_class']:<18} {ending['address']:<42} {name}")
    print("\ncompare the bundle against a public explorer before relying on it")
    native = EVM_NETWORKS[network].native_symbol
    print(f"native {native} transfers are not traced -- token Transfer-log tracking only")
    return 0


def _read_json(path: Path) -> dict[str, object] | None:
    return json.loads(path.read_text()) if path.is_file() else None


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(main_async(build_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
