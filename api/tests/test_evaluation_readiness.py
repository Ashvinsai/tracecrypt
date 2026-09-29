"""Stage 3B model-readiness report: deterministic, honest about zero real
records, and never reports a model-quality metric (there is no model)."""

from __future__ import annotations

import json
from pathlib import Path

from app.reports.evaluation_readiness import (
    READINESS_NOT_READY,
    build_readiness_report,
    render_readiness_html,
)
from app.services.evaluation_dataset import materialize_evaluation_dataset
from app.services.evaluation_wallets import EvaluationWallet, append_evaluation_wallet

BANNED_METRIC_FRAGMENTS = (
    "accuracy",
    "precision",
    "recall",
    "auc",
    "anomaly_quality",
    "fraud_detection_quality",
    "attribution_quality",
)


def _synthetic_wallet(address: str) -> EvaluationWallet:
    return EvaluationWallet(
        network="tron",
        address=address,
        control_category="self_custody",
        source_reference="SYNTHETIC-source",
        evidence_type="SYNTHETIC fixture",
        valid_from="2026-01-01T00:00:00Z",
        valid_to="",
        review_state="accepted",
        notes="SYNTHETIC fixture only",
        upstream_source_id="",
        reviewer="SYNTHETIC-reviewer",
        data_mode="SYNTHETIC",
    )


def _bundle(root: Path, address: str) -> None:
    run_dir = root / "tron" / address / "SYNTHETIC-run"
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": "SYNTHETIC-run",
        "query": {
            "candidate_address": address,
            "analysis_start": "2026-01-01T00:00:00+00:00",
            "analysis_cutoff": "2026-01-02T00:00:00+00:00",
        },
        "truncated_by_page_limit": {"incoming": False, "outgoing": False},
        "truncated_by_event_limit": {"incoming": False, "outgoing": False},
        "truncated_by_request_budget": False,
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest))
    (run_dir / "evidence.json").write_text(json.dumps({"rows": []}))


def _empty_result(tmp_path: Path):
    empty_registry = tmp_path / "empty.csv"
    return materialize_evaluation_dataset(
        registry_path=empty_registry, behavioral_evidence_root=tmp_path / "no-evidence"
    )


# --- K: zero real corpus reports NOT_READY without fabricating a metric -------


def test_zero_real_wallets_reports_not_ready_without_fabricated_metric(tmp_path: Path) -> None:
    registry = tmp_path / "evaluation_wallets.csv"  # never created: 0 real records
    empty_result = _empty_result(tmp_path)

    report = build_readiness_report(
        registry_path=registry,
        real_wallets=[],
        synthetic_wallets=[],
        real_result=empty_result,
        synthetic_result=empty_result,
    )

    assert report.status == READINESS_NOT_READY
    assert report.real_wallet_count == 0
    assert any("0 real evaluation wallets" in reason for reason in report.status_reasons)

    as_json = report.to_json()
    for fragment in BANNED_METRIC_FRAGMENTS:
        assert fragment not in as_json.lower()
    assert report.to_dict()["model_metrics_reported"] is False


def test_readiness_report_is_byte_identical_for_identical_inputs(tmp_path: Path) -> None:
    registry = tmp_path / "evaluation_wallets.csv"
    empty_result = _empty_result(tmp_path)

    report_a = build_readiness_report(
        registry_path=registry,
        real_wallets=[],
        synthetic_wallets=[],
        real_result=empty_result,
        synthetic_result=empty_result,
    )
    report_b = build_readiness_report(
        registry_path=registry,
        real_wallets=[],
        synthetic_wallets=[],
        real_result=empty_result,
        synthetic_result=empty_result,
    )

    assert report_a.to_json() == report_b.to_json()


# --- L: full SYNTHETIC pipeline run, visibly tagged and excluded from real ----


def test_full_synthetic_pipeline_is_visibly_tagged_and_excluded_from_real_counts(
    tmp_path: Path,
) -> None:
    synthetic_registry = tmp_path / "synthetic_evaluation_wallets.csv"
    wallet = _synthetic_wallet("TSYNTHETICPIPELINE")
    append_evaluation_wallet(synthetic_registry, wallet)
    evidence_root = tmp_path / "evidence"
    _bundle(evidence_root, "TSYNTHETICPIPELINE")

    synthetic_result = materialize_evaluation_dataset(
        registry_path=synthetic_registry, behavioral_evidence_root=evidence_root
    )
    assert len(synthetic_result.rows) == 1
    assert synthetic_result.rows[0].data_mode == "SYNTHETIC"

    real_registry = tmp_path / "real_evaluation_wallets.csv"  # never written to: 0 real records
    real_result = _empty_result(tmp_path)

    report = build_readiness_report(
        registry_path=real_registry,
        real_wallets=[],
        synthetic_wallets=[wallet],
        real_result=real_result,
        synthetic_result=synthetic_result,
    )

    # The synthetic pipeline demonstrably works (1 materialized window)...
    assert report.materialized_window_count_synthetic == 1
    # ...but real evaluation coverage stays at zero and NOT_READY.
    assert report.materialized_window_count_real == 0
    assert report.real_wallet_count == 0
    assert report.status == READINESS_NOT_READY

    html_out = render_readiness_html(report)
    assert "NOT_READY_FOR_REAL_EVALUATION" in html_out
