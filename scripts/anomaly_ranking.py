"""Stage 3C Isolation Forest CLI -- SYNTHETIC pipeline demonstration.

    uv run python scripts/anomaly_ranking.py --seed 7

Trains the `app.services.anomaly_ranking` ranker on a deterministic SYNTHETIC
wallet-window set, scores a held-out slice, and evaluates that ranking against
a predeclared demonstration rubric (review-worthy precision@k vs a
random-ranking baseline, plus the ranks of known operational confounders),
printing JSON. It exists to show the fit/score/evaluate path runs end-to-end
offline.

There are no accepted-and-materialized REAL evaluation windows on file yet
(see docs/PROGRESS.md Stage 3C and docs/DECISIONS.md 2026-09-21), so this
script deliberately uses ONLY synthetic rows and labels its own output
"pipeline_demonstration". It reports no accuracy/precision/recall/AUC metric --
there is no held-out evaluation yet and no real corpus to evaluate against.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "api"))

from app.reports.anomaly_evaluation import render_anomaly_evaluation_html  # noqa: E402
from app.services.anomaly_ranking import (  # noqa: E402
    SYNTHETIC_DEMONSTRATION_RUBRIC,
    assert_no_training_overlap,
    evaluate_anomaly,
    score_anomaly,
    synthetic_demonstration_rows,
    train_anomaly,
)
from app.services.evaluation_experiment import ExperimentKind  # noqa: E402
from app.services.feature_dataset import split_by_wallet  # noqa: E402

EVALUATION_KIND = "pipeline_demonstration"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--n-estimators", type=int, default=128)
    parser.add_argument("--eval-fraction", type=float, default=0.25)
    parser.add_argument("--k", type=int, default=5, help="top-k for precision@k")
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="optional path to also write the JSON report",
    )
    parser.add_argument(
        "--html-out",
        type=Path,
        default=None,
        help="optional path to also write the rendered HTML evaluation report",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    rows = synthetic_demonstration_rows()
    train_rows, holdout_rows = split_by_wallet(
        rows, eval_fraction=args.eval_fraction, seed=args.seed
    )

    model = train_anomaly(
        train_rows, seed=args.seed, n_estimators=args.n_estimators
    )
    assert_no_training_overlap(model, holdout_rows)
    scores = score_anomaly(model, holdout_rows, allow_training_rows=False)

    evaluation = evaluate_anomaly(
        model,
        holdout_rows,
        rubric=SYNTHETIC_DEMONSTRATION_RUBRIC,
        k=args.k,
        split_description=(
            f"split_by_wallet(eval_fraction={args.eval_fraction}, seed={args.seed})"
        ),
        experiment_kind=ExperimentKind.synthetic_pipeline_demonstration,
    )

    report = {
        "evaluation_kind": EVALUATION_KIND,
        "experiment_kind": ExperimentKind.synthetic_pipeline_demonstration.value,
        "data_mode": "SYNTHETIC",
        "real_data_used": False,
        "caveat": (
            "Synthetic pipeline demonstration only. No real evaluation corpus "
            "exists, no accuracy/precision/recall/AUC was computed, and these "
            "ranks are not fraud, ownership, or service claims."
        ),
        "split": {
            "method": "split_by_wallet",
            "eval_fraction": args.eval_fraction,
            "seed": args.seed,
            "train_rows": len(train_rows),
            "holdout_rows": len(holdout_rows),
        },
        "model": model.metadata(),
        "evaluation": evaluation.to_dict(),
        "scores": [score.to_dict() for score in scores],
    }

    payload = json.dumps(report, indent=2, sort_keys=True)
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(payload)
    if args.html_out is not None:
        args.html_out.parent.mkdir(parents=True, exist_ok=True)
        args.html_out.write_text(render_anomaly_evaluation_html(evaluation))
    sys.stdout.write(payload + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
