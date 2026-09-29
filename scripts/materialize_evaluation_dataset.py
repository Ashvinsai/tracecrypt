"""Stage 3B: materialize wallet-window feature rows from ACCEPTED
evaluation_wallets.csv records plus SAVED behavioral-evidence run bundles.

    uv run python ../scripts/materialize_evaluation_dataset.py \\
        --registry ../data/evaluation_wallets.csv \\
        --evidence-root ../var/collect-behavioral-evidence/by-wallet \\
        --out ../var/evaluation-dataset

Offline and deterministic: reads only already-saved files, makes no
network call. A wallet with no saved evidence bundle at
<evidence-root>/<network>/<address>/{manifest.json,evidence.json} is
skipped with reason "missing_evidence" -- never fetched live.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "api"))

from app.services.evaluation_dataset import materialize_evaluation_dataset  # noqa: E402
from app.services.feature_dataset import build_feature_table  # noqa: E402

DEFAULT_REGISTRY = REPO_ROOT / "data" / "evaluation_wallets.csv"
DEFAULT_EVIDENCE_ROOT = REPO_ROOT / "var" / "collect-behavioral-evidence" / "by-wallet"
DEFAULT_OUT = REPO_ROOT / "var" / "evaluation-dataset"


def _json_default(value: object) -> str:
    """Serialize provenance dates without weakening JSON type checking."""
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE_ROOT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--write", action="store_true", help="write output files (default: print only)"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    result = materialize_evaluation_dataset(
        registry_path=args.registry,
        behavioral_evidence_root=args.evidence_root,
    )

    print(f"registry: {args.registry}")
    print(f"feature_definition_version: {result.feature_definition_version}")
    print(f"snapshot_hash: {result.snapshot_hash}")
    print(f"materialized rows: {len(result.rows)}")
    print(f"skipped: {len(result.skipped)}")
    for skip in result.skipped:
        print(f"  skipped {skip.network}/{skip.address}: {skip.reason}")

    if not args.write:
        print("\nDry run only -- pass --write to save output.")
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    header, table = build_feature_table(result.rows)
    (args.out / "wallet_window_rows.json").write_text(
        json.dumps(
            {"header": header, "rows": table},
            default=_json_default,
            indent=2,
            sort_keys=True,
        )
    )
    (args.out / "manifest.json").write_text(
        json.dumps(
            {
                "registry": str(args.registry),
                "feature_definition_version": result.feature_definition_version,
                "snapshot_hash": result.snapshot_hash,
                "row_count": len(result.rows),
                "skipped": [
                    {"network": s.network, "address": s.address, "reason": s.reason}
                    for s in result.skipped
                ],
            },
            default=_json_default,
            indent=2,
            sort_keys=True,
        )
    )
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
