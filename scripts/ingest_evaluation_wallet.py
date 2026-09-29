"""Stage 3B: safe local ingestion of ONE independently sourced evaluation
(control/confounder) wallet record into data/evaluation_wallets.csv.

    uv run python ../scripts/ingest_evaluation_wallet.py \\
        --network tron --address TXXXX \\
        --category self_custody \\
        --source-reference "https://example.invalid/independent-attestation" \\
        --evidence-type "self-attested and independently corroborated wallet" \\
        --reviewer "a.reviewer" \\
        --data-mode RECORDED_PUBLIC \\
        [--write]

Dry-run by default: prints what would be appended and exits without
touching any file. Requires the explicit --write flag to actually append.

This CLI never asks for or accepts credentials, seed phrases, private keys,
screenshots containing secrets, complaint text, or victim/PII information --
no such fields exist in this schema, by design; adding one would be a
regression against this project's threat model.

This CLI has no code path that touches verified_anchors.csv,
deposit_candidates.csv, independent_review.csv, or review_log.csv, and
cannot change service attribution or candidate review state. It only ever
opens and appends to data/evaluation_wallets.csv.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "api"))

from app.services.evaluation_wallets import (  # noqa: E402
    EVALUATION_WALLET_COLUMNS,
    EvaluationWallet,
    EvaluationWalletError,
    append_evaluation_wallet,
    load_evaluation_wallets,
    validate_evaluation_wallet,
)

DEFAULT_PATH = REPO_ROOT / "data" / "evaluation_wallets.csv"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--network", required=True)
    parser.add_argument("--address", required=True)
    parser.add_argument("--category", required=True, dest="control_category")
    parser.add_argument("--source-reference", required=True)
    parser.add_argument("--evidence-type", required=True)
    parser.add_argument("--valid-from", default="")
    parser.add_argument("--valid-to", default="")
    parser.add_argument("--review-state", default="unreviewed")
    parser.add_argument("--notes", default="")
    parser.add_argument("--upstream-source-id", default="")
    parser.add_argument("--reviewer", default="")
    parser.add_argument("--data-mode", default="RECORDED_PUBLIC")
    parser.add_argument(
        "--path", type=Path, default=DEFAULT_PATH, help="evaluation_wallets.csv to write to"
    )
    parser.add_argument(
        "--write", action="store_true", help="actually append (default: dry-run only)"
    )
    return parser


def _hash_existing_lines(path: Path) -> str:
    if not path.is_file():
        return hashlib.sha256(b"").hexdigest()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _duplicate_exists(path: Path, wallet: EvaluationWallet) -> bool:
    for existing in load_evaluation_wallets(path):
        if (
            existing.network == wallet.network
            and existing.address == wallet.address
            and existing.control_category == wallet.control_category
        ):
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    wallet = EvaluationWallet(
        network=args.network,
        address=args.address,
        control_category=args.control_category,
        source_reference=args.source_reference,
        evidence_type=args.evidence_type,
        valid_from=args.valid_from,
        valid_to=args.valid_to,
        review_state=args.review_state,
        notes=args.notes,
        upstream_source_id=args.upstream_source_id,
        reviewer=args.reviewer,
        data_mode=args.data_mode,
    )

    try:
        validate_evaluation_wallet(wallet)
    except EvaluationWalletError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    if _duplicate_exists(args.path, wallet):
        print(
            "REFUSED: a record for this exact (network, address, category) already "
            f"exists in {args.path}; this CLI never silently double-appends. Edit the "
            "existing row by hand if it needs a correction.",
            file=sys.stderr,
        )
        return 3

    print("Validation summary:")
    print(f"  network={wallet.network} address={wallet.address}")
    print(f"  category={wallet.control_category}")
    print(f"  source_reference={wallet.source_reference}")
    print(f"  evidence_type={wallet.evidence_type}")
    valid_from = wallet.valid_from or "unbounded"
    valid_to = wallet.valid_to or "unbounded"
    print(f"  validity_window=[{valid_from}, {valid_to}]")
    print(f"  review_state={wallet.review_state} reviewer={wallet.reviewer or '(none yet)'}")
    upstream = wallet.upstream_source_id or "(none stated)"
    print(f"  data_mode={wallet.data_mode} upstream_source_id={upstream}")
    print(
        "  SCOPE: this category is documented for this address within its stated "
        "validity window and evidence_type only; it is not a universal or "
        "permanent claim, and it is never a fraud/innocence label."
    )

    if not args.write:
        print("\nDry run only -- nothing written. Pass --write to append.")
        return 0

    before_hash = _hash_existing_lines(args.path)
    before_lines = args.path.read_text().splitlines() if args.path.is_file() else []

    append_evaluation_wallet(args.path, wallet)

    after_lines = args.path.read_text().splitlines()
    # Preserve pre-existing DATA rows byte-for-byte. The one line allowed to
    # change is the header, and only as a schema upgrade (a stale
    # pre-Stage-3B header gaining the upstream_source_id/reviewer/data_mode
    # columns via _migrate_header_if_stale) -- never a change to any row's
    # actual content.
    if before_lines:
        assert after_lines[0] == before_lines[0] or after_lines[0] == ",".join(
            EVALUATION_WALLET_COLUMNS
        ), "the header changed to something other than the documented schema upgrade"
        assert after_lines[1 : len(before_lines)] == before_lines[1:], (
            "existing data rows were not preserved byte-for-byte -- refusing to trust this write"
        )
    print(f"\nWrote 1 row to {args.path} (pre-existing content hash: {before_hash}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
