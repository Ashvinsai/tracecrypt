"""Stage 2 behavioral/sweep evidence for one candidate and one verified
token contract.

    uv run python ../scripts/collect_behavioral_evidence.py \\
        --candidate TXXXX --token-contract TYYYY \\
        --start 2026-08-10T13:00:00Z --cutoff 2026-08-10T17:00:00Z \\
        --page-limit 5 --event-limit 100 --max-requests 20

Prints what each behavioral evidence row would become and writes nothing to
data/behavioral_evidence.csv until --write. Never writes verified_anchors.csv
or deposit_candidates.csv's review fields, or review_log.csv -- repeated
forwarding or high outgoing concentration is behavioral evidence only; it
never promotes or labels this command's own candidate.

Two subject-kind modes (--subject-kind, default candidate_or_anchor):

    candidate_or_anchor (default, unchanged): --candidate must already be a
    known record in deposit_candidates.csv/verified_anchors.csv. --write is
    allowed and appends data/behavioral_evidence.csv.

    evaluation_wallet: --candidate must instead be an ACCEPTED record in
    --evaluation-registry (default data/evaluation_wallets.csv). Always
    bundle-only: never writes deposit_candidates.csv, verified_anchors.csv,
    review_log.csv, evaluation_review_log.csv, or behavioral_evidence.csv,
    and --write is refused outright.

        uv run python ../scripts/collect_behavioral_evidence.py \\
            --candidate TXXXX --token-contract TYYYY \\
            --start 2026-08-10T13:00:00Z --cutoff 2026-08-10T17:00:00Z \\
            --subject-kind evaluation_wallet \\
            --evaluation-registry ../data/evaluation_wallets.csv
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
from app.services.collect_behavioral_evidence import (  # noqa: E402
    BehavioralEvidenceError,
    BehavioralEvidenceRequest,
    collect_behavioral_evidence,
    collect_behavioral_evidence_for_evaluation_wallet,
)

DEFAULT_OUT = REPO_ROOT / "var" / "collect-behavioral-evidence"
#: For --subject-kind evaluation_wallet, --out-dir names the by-wallet evidence
#: root; the canonical bundle path is
#: <evidence_root>/<network>/<address>/<run_id>/. This default mirrors
#: materialize_evaluation_dataset.py/evaluation_readiness_report.py's own
#: DEFAULT_EVIDENCE_ROOT.
DEFAULT_EVIDENCE_ROOT = DEFAULT_OUT / "by-wallet"
DEFAULT_DATA = REPO_ROOT / "data"
#: Matches materialize_evaluation_dataset.py/evaluation_readiness_report.py's
#: own DEFAULT_REGISTRY convention.
DEFAULT_EVALUATION_REGISTRY = REPO_ROOT / "data" / "evaluation_wallets.csv"


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--candidate", required=True, help="a known candidate or anchor address")
    parser.add_argument("--token-contract", required=True, help="the verified token contract")
    parser.add_argument("--network", default="tron")
    parser.add_argument("--token-decimals", type=int, default=6)
    parser.add_argument("--token-symbol", default="USDT")
    parser.add_argument(
        "--start", type=parse_time, required=True, help="lower bound for the scan (UTC)"
    )
    parser.add_argument(
        "--cutoff", type=parse_time, required=True, help="upper bound for the scan (UTC)"
    )
    parser.add_argument(
        "--page-limit", type=int, default=10, help="cap on paginated requests walked per direction"
    )
    parser.add_argument(
        "--event-limit", type=int, default=500, help="cap on transfer rows kept per direction"
    )
    parser.add_argument(
        "--max-requests",
        type=int,
        default=None,
        help="cap on genuine network requests this collection may make; unset is unbounded",
    )
    parser.add_argument(
        "--verify-execution",
        action="store_true",
        help="spend one extra receipt request per distinct tx to confirm execution status "
        "(off by default -- see module docstring)",
    )
    parser.add_argument(
        "--enrich-events",
        action="store_true",
        help="spend one extra events request per distinct tx to resolve a real event_index "
        "(off by default; ambiguous rows still get a distinct content-derived reference)",
    )
    parser.add_argument("--run-id", default=None)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help=(
            "output root. candidate_or_anchor: the run directory is <out-dir>/<run-id> "
            f"(default {DEFAULT_OUT}). evaluation_wallet: this names the by-wallet "
            "evidence root, and the canonical bundle path is "
            f"<out-dir>/<network>/<address>/<run-id>/ (default {DEFAULT_EVIDENCE_ROOT})"
        ),
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument(
        "--write", action="store_true", help="without this, behavioral_evidence.csv is unchanged"
    )
    parser.add_argument(
        "--subject-kind",
        choices=["candidate_or_anchor", "evaluation_wallet"],
        default="candidate_or_anchor",
        help=(
            "'candidate_or_anchor' (default, unchanged behavior): --candidate must already be "
            "on record in deposit_candidates.csv/verified_anchors.csv, and --write is allowed "
            "to append data/behavioral_evidence.csv. 'evaluation_wallet': --candidate must "
            "instead be an ACCEPTED record in --evaluation-registry (evaluation_wallets.csv); "
            "this mode is always bundle-only -- it never touches deposit_candidates.csv, "
            "verified_anchors.csv, review_log.csv, evaluation_review_log.csv, or "
            "behavioral_evidence.csv, and --write is refused."
        ),
    )
    parser.add_argument(
        "--allow-overwrite-existing-run",
        action="store_true",
        help=(
            "only meaningful with --subject-kind evaluation_wallet: by default, a capture "
            "is refused if manifest.json already exists at <out-dir>/<run-id>, so a saved "
            "preferred run is never silently overwritten by a later recapture. Pass this "
            "flag to explicitly replace it."
        ),
    )
    parser.add_argument(
        "--evaluation-registry",
        type=Path,
        default=DEFAULT_EVALUATION_REGISTRY,
        help=(
            "only meaningful with --subject-kind evaluation_wallet: path to "
            "evaluation_wallets.csv (default: data/evaluation_wallets.csv, matching "
            "materialize_evaluation_dataset.py/evaluation_readiness_report.py's own default)"
        ),
    )
    parser.add_argument(
        "--evaluation-window-rationale",
        default="",
        help=(
            "optional, descriptive provenance recorded in the run manifest's window_selection "
            "block; never affects which events are fetched"
        ),
    )
    parser.add_argument(
        "--evaluation-window-policy",
        default="",
        help="optional named window policy, recorded alongside the rationale",
    )
    return parser


async def main_async(args: argparse.Namespace) -> int:
    settings = get_settings()

    if args.subject_kind == "evaluation_wallet" and args.write:
        print(
            "refused: --subject-kind evaluation_wallet is bundle-only; --write is not "
            "allowed for this mode (an evaluation wallet is never a source of a "
            "behavioral_evidence.csv row)",
            file=sys.stderr,
        )
        return 2

    request = BehavioralEvidenceRequest(
        candidate_address=args.candidate,
        token_contract=args.token_contract,
        analysis_start=args.start,
        analysis_cutoff=args.cutoff,
        network_key=args.network,
        token_decimals=args.token_decimals,
        token_symbol=args.token_symbol,
        page_limit=args.page_limit,
        event_limit=args.event_limit,
        max_requests=args.max_requests,
        verify_execution=args.verify_execution,
        enrich_events=args.enrich_events,
        run_id=args.run_id,
        subject_kind=args.subject_kind,
        allow_overwrite_existing_run=args.allow_overwrite_existing_run,
        evaluation_window_rationale=args.evaluation_window_rationale,
        evaluation_window_policy=args.evaluation_window_policy,
    )

    if args.out_dir is not None:
        out_dir = args.out_dir
    elif args.subject_kind == "evaluation_wallet":
        out_dir = DEFAULT_EVIDENCE_ROOT
    else:
        out_dir = DEFAULT_OUT

    try:
        if args.subject_kind == "evaluation_wallet":
            # --evaluation-registry names evaluation_wallets.csv itself; the
            # service looks up "<data_dir>/evaluation_wallets.csv", so its
            # parent directory is passed as the data_dir for this call only.
            # This never touches --data-dir's deposit_candidates.csv/
            # verified_anchors.csv/review_log.csv. out_dir is the by-wallet
            # evidence root; the service appends <network>/<address>/<run_id>.
            run = await collect_behavioral_evidence_for_evaluation_wallet(
                settings,
                request,
                out_root=out_dir,
                data_dir=args.evaluation_registry.parent,
            )
        else:
            run = await collect_behavioral_evidence(
                settings, request, out_root=out_dir, data_dir=args.data_dir, write=args.write
            )
    except BehavioralEvidenceError as exc:
        print(f"refused or failed: {exc}", file=sys.stderr)
        return 2

    direction_counts: dict[str, int] = {}
    for row in run.rows:
        direction_counts[row.direction] = direction_counts.get(row.direction, 0) + 1

    print(f"run                       {run.run_id}")
    print(f"bundle                    {run.directory}")
    # Stable, machine-readable line so the caller never has to reconstruct the
    # path: the wizard reads exactly this to learn where the bundle was saved.
    print(f"bundle_path={run.directory}")
    print(f"candidate                 {run.candidate_address}")
    print(f"requests used             {run.requests_used}")
    print(f"rows found                {len(run.rows)}  (by direction: {direction_counts})")
    print(f"excluded (non-transfer)   {run.excluded_non_transfer_count}")
    print(f"excluded (failed/revert)  {run.excluded_failed_or_reverted_count}")
    print(f"truncated (page limit)    {run.truncated_by_page_limit}")
    print(f"truncated (event limit)   {run.truncated_by_event_limit}")
    print(f"truncated (budget)        {run.truncated_by_request_budget}")
    for direction, err in run.direction_errors.items():
        print(f"  {direction} error: {err}")
    if not args.write:
        print("\nnothing written to behavioral_evidence.csv (pass --write)")
    else:
        print(
            "\nwrote behavioral evidence into behavioral_evidence.csv; repeated forwarding "
            "or high concentration recorded here is behavioral evidence only -- it never "
            "promotes or labels this candidate"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(main_async(build_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
