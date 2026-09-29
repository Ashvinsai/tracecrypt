"""Stage 3B model-readiness report CLI.

    uv run python ../scripts/evaluation_readiness_report.py \\
        --registry ../data/evaluation_wallets.csv \\
        --evidence-root ../var/collect-behavioral-evidence/by-wallet

Offline and deterministic: reads only already-saved evaluation_wallets.csv
records and already-saved behavioral-evidence run bundles on disk. Makes no
network call, trains no model, and reports no accuracy/precision/recall/AUC
metric -- there is no model yet (see app.reports.evaluation_readiness).

Real (data_mode != SYNTHETIC) and SYNTHETIC records are split before being
handed to build_readiness_report so a synthetic pipeline-smoke-test wallet
can never inflate the real-corpus counts.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "api"))

from app.reports.evaluation_readiness import (  # noqa: E402
    build_readiness_report,
    render_readiness_html,
)
from app.services.evaluation_dataset import materialize_evaluation_dataset  # noqa: E402
from app.services.evaluation_wallets import (  # noqa: E402
    EVALUATION_WALLET_COLUMNS,
    EvaluationWallet,
    load_evaluation_wallets,
)

DEFAULT_REGISTRY = REPO_ROOT / "data" / "evaluation_wallets.csv"
DEFAULT_EVIDENCE_ROOT = REPO_ROOT / "var" / "collect-behavioral-evidence" / "by-wallet"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE_ROOT)
    parser.add_argument(
        "--html-out",
        type=Path,
        default=None,
        help="optional path to also write the rendered HTML report",
    )
    parser.add_argument(
        "--grouping",
        type=Path,
        default=None,
        help=(
            "optional JSON object mapping pseudonymous wallet_id -> related-wallet "
            "group id. This is EXTERNAL operator input; when absent, only a "
            "wallet-level split is reported and no grouping is inferred."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    all_wallets = load_evaluation_wallets(args.registry)
    real_wallets = [w for w in all_wallets if w.data_mode != "SYNTHETIC"]
    synthetic_wallets = [w for w in all_wallets if w.data_mode == "SYNTHETIC"]

    group_of: dict[str, str] | None = None
    if args.grouping is not None:
        raw = json.loads(args.grouping.read_text())
        if not isinstance(raw, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in raw.items()
        ):
            raise SystemExit(
                "REFUSED: --grouping must be a JSON object of {wallet_id: group_id} strings"
            )
        group_of = raw

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        real_registry_path = _write_registry_subset(tmp_path / "real.csv", real_wallets)
        synthetic_registry_path = _write_registry_subset(
            tmp_path / "synthetic.csv", synthetic_wallets
        )

        real_result = materialize_evaluation_dataset(
            registry_path=real_registry_path, behavioral_evidence_root=args.evidence_root
        )
        synthetic_result = materialize_evaluation_dataset(
            registry_path=synthetic_registry_path, behavioral_evidence_root=args.evidence_root
        )

        report = build_readiness_report(
            registry_path=args.registry,
            real_wallets=real_wallets,
            synthetic_wallets=synthetic_wallets,
            real_result=real_result,
            synthetic_result=synthetic_result,
            group_of=group_of,
        )

    print(report.to_json())

    if args.html_out is not None:
        args.html_out.parent.mkdir(parents=True, exist_ok=True)
        args.html_out.write_text(render_readiness_html(report))
        print(f"\nWrote HTML report to {args.html_out}")

    return 0


def _write_registry_subset(path: Path, wallets: list[EvaluationWallet]) -> Path:
    """Write a temporary registry file containing only ``wallets``, so
    materialize_evaluation_dataset can be run once per real/synthetic
    partition -- each partition gets its own correct snapshot_hash rather
    than sharing the combined registry's hash."""
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=EVALUATION_WALLET_COLUMNS)
        writer.writeheader()
        for wallet in wallets:
            writer.writerow(wallet.to_csv_row())
    return path


if __name__ == "__main__":
    raise SystemExit(main())
