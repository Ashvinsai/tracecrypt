"""Deterministic comparison of routing validation runs (Task 08C-B3).

Loads immutable JSON artifacts from run directories and generates a unified,
provable comparison table and summary without hardcoded scenario values.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def file_sha256(path: Path) -> str:
    if not path.exists():
        return "MISSING"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_run_data(run_dir: Path) -> dict[str, Any]:
    """Load and index scenario results and metadata from an artifact directory."""
    if not run_dir.exists():
        return {"status": "NOT_PRESERVED", "path": str(run_dir)}

    sc_path = run_dir / "scenario-results.json"
    sum_path = run_dir / "summary.json"
    lat_path = run_dir / "latencies.json"

    if not sc_path.exists():
        return {"status": "NOT_PRESERVED", "path": str(run_dir)}

    scenarios = json.loads(sc_path.read_text(encoding="utf-8"))
    summary = json.loads(sum_path.read_text(encoding="utf-8")) if sum_path.exists() else {}
    latencies = json.loads(lat_path.read_text(encoding="utf-8")) if lat_path.exists() else {}

    indexed = {s["scenario_id"]: s for s in scenarios}
    return {
        "status": "LOADED",
        "path": str(run_dir),
        "source_hashes": {
            "scenario-results.json": file_sha256(sc_path),
            "summary.json": file_sha256(sum_path),
            "latencies.json": file_sha256(lat_path),
        },
        "scenarios": indexed,
        "summary": summary,
        "latencies": latencies,
        "scenario_list": scenarios,
    }


def generate_comparison(
    run_08b_dir: Path,
    run_08cb_dir: Path,
    run_08cb2_dir: Path,
    output_json: Path | None = None,
) -> dict[str, Any]:
    data_08b = load_run_data(run_08b_dir)
    data_08cb = load_run_data(run_08cb_dir)
    data_08cb2 = load_run_data(run_08cb2_dir)

    scenario_ids = [
        "01_SAME_CHAIN_CONTINUATION",
        "02_REVIEWED_VASP_REACHED",
        "03_VASP_CANDIDATE_ONLY",
        "04_PROVIDER_FAILURE_RETRYABLE",
        "05_PROVIDER_FAILURE_EXHAUSTED",
        "06_CCTP_CONTINUATION_PENDING",
        "07_CCTP_DESTINATION_ALREADY_COMPLETED",
        "08_RECEIPT_UNVERIFIED",
        "09_AMBIGUOUS_ORDERING",
        "10_REPORT_READY",
    ]

    scenario_comparisons = []
    for sc_id in scenario_ids:
        row = {"scenario_id": sc_id, "stages": {}}

        # Task 08B
        if data_08b["status"] == "LOADED" and sc_id in data_08b["scenarios"]:
            s = data_08b["scenarios"][sc_id]
            row["stages"]["08B"] = {
                "rule_choice": s["actual_selected_action"],
                "clm_choice": s["clm_choice"],
                "candidates": s["eligible_candidate_actions"],
                "probabilities": s["clm_relative_action_probabilities"],
                "shadow_agreement": s["shadow_agreement"],
                "top3": s.get("clm_top3", False),
            }
        else:
            row["stages"]["08B"] = "NOT_PRESERVED"

        # Task 08C-B
        if data_08cb["status"] == "LOADED" and sc_id in data_08cb["scenarios"]:
            s = data_08cb["scenarios"][sc_id]
            row["stages"]["08C-B"] = {
                "rule_choice": s["actual_selected_action"],
                "clm_choice": s["clm_choice"],
                "candidates": s["eligible_candidate_actions"],
                "probabilities": s["clm_relative_action_probabilities"],
                "shadow_agreement": s["shadow_agreement"],
                "top3": s.get("clm_top3", False),
            }
        else:
            row["stages"]["08C-B"] = "NOT_PRESERVED"

        # Task 08C-B2
        if data_08cb2["status"] == "LOADED" and sc_id in data_08cb2["scenarios"]:
            s = data_08cb2["scenarios"][sc_id]
            row["stages"]["08C-B2"] = {
                "service_lookup_status": s.get("service_lookup_status", "unknown"),
                "rule_choice": s["actual_selected_action"],
                "clm_choice": s["clm_choice"],
                "candidates": s["eligible_candidate_actions"],
                "probabilities": s["clm_relative_action_probabilities"],
                "shadow_agreement": s["shadow_agreement"],
                "top3": s.get("clm_top3", False),
                "clm_latency_ms": s.get("clm_latency_ms"),
                "total_routing_latency_ms": s.get("total_routing_latency_ms"),
            }
        else:
            row["stages"]["08C-B2"] = "NOT_PRESERVED"

        scenario_comparisons.append(row)

    def get_aggs(stage_data: dict[str, Any]) -> Any:
        if stage_data["status"] != "LOADED":
            return "NOT_PRESERVED"
        scs = stage_data["scenario_list"]
        agrees = sum(1 for s in scs if s["shadow_agreement"])
        top3s = sum(1 for s in scs if s.get("clm_top3", False))
        return {
            "total_scenarios": len(scs),
            "top1_agreement_count": agrees,
            "top1_agreement_rate": agrees / len(scs),
            "top3_coverage_count": top3s,
            "top3_coverage_rate": top3s / len(scs),
            "source_hashes": stage_data["source_hashes"],
        }

    comparison_report = {
        "artifact_class": "DERIVED_COMPARISON",
        "notice": "DECISION SUPPORT METADATA - NOT BLOCKCHAIN EVIDENCE",
        "authoritative_crypto_commit": "86db954bc4f855fc431c6808afee5b3cef1fd3e3",
        "stages": {
            "08B": get_aggs(data_08b),
            "08C-B": get_aggs(data_08cb),
            "08C-B2": get_aggs(data_08cb2),
        },
        "scenarios": scenario_comparisons,
    }

    if output_json:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(comparison_report, indent=2), encoding="utf-8")

    return comparison_report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reconcile routing validation runs.")
    parser.add_argument("--dir-08b", type=Path, required=True)
    parser.add_argument("--dir-08cb", type=Path, required=True)
    parser.add_argument("--dir-08cb2", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, default=None)
    args = parser.parse_args()

    res = generate_comparison(args.dir_08b, args.dir_08cb, args.dir_08cb2, args.output_json)
    print("Derived comparison generated successfully.")
