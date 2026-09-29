"""Stage 3B materialization: offline, deterministic, no live evidence
fetch, no duplicate rows from re-materializing the same saved run."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.evaluation_dataset import materialize_evaluation_dataset
from app.services.evaluation_wallets import EvaluationWallet, append_evaluation_wallet

NETWORK = "tron"


def _write_run_bundle(
    root: Path, network: str, address: str, run_id: str = "SYNTHETIC-run-1"
) -> None:
    run_dir = root / network / address / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": run_id,
        "query": {
            "candidate_address": address,
            "analysis_start": "2026-01-01T00:00:00+00:00",
            "analysis_cutoff": "2026-01-02T00:00:00+00:00",
        },
        "truncated_by_page_limit": {"incoming": False, "outgoing": False},
        "truncated_by_event_limit": {"incoming": False, "outgoing": False},
        "truncated_by_request_budget": False,
    }
    evidence = {"rows": []}
    (run_dir / "manifest.json").write_text(json.dumps(manifest))
    (run_dir / "evidence.json").write_text(json.dumps(evidence))


def _accepted_wallet(address: str, **overrides: str) -> EvaluationWallet:
    kwargs = dict(
        network=NETWORK,
        address=address,
        control_category="self_custody",
        source_reference="SYNTHETIC-source",
        evidence_type="SYNTHETIC fixture",
        valid_from="2026-01-01T00:00:00Z",
        valid_to="",
        review_state="accepted",
        notes="SYNTHETIC fixture -- not a real evaluation record",
        upstream_source_id="",
        reviewer="SYNTHETIC-reviewer",
        data_mode="SYNTHETIC",
    )
    kwargs.update(overrides)
    return EvaluationWallet(**kwargs)


def test_missing_evidence_is_skipped_not_fetched_live(tmp_path: Path) -> None:
    registry = tmp_path / "evaluation_wallets.csv"
    append_evaluation_wallet(registry, _accepted_wallet("TNOBUNDLE"))
    evidence_root = tmp_path / "evidence"  # no bundle written

    result = materialize_evaluation_dataset(
        registry_path=registry, behavioral_evidence_root=evidence_root
    )

    assert result.rows == []
    assert len(result.skipped) == 1
    assert result.skipped[0].reason == "missing_evidence"


def test_accepted_wallet_with_saved_bundle_materializes_one_row(tmp_path: Path) -> None:
    registry = tmp_path / "evaluation_wallets.csv"
    append_evaluation_wallet(registry, _accepted_wallet("TSYNTHETIC1"))
    evidence_root = tmp_path / "evidence"
    _write_run_bundle(evidence_root, NETWORK, "TSYNTHETIC1")

    result = materialize_evaluation_dataset(
        registry_path=registry, behavioral_evidence_root=evidence_root
    )

    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.data_mode == "SYNTHETIC"
    assert row.control_category == "self_custody"
    assert row.evaluation_source_reference == "SYNTHETIC-source"


def test_re_materializing_the_same_saved_run_does_not_duplicate_rows(tmp_path: Path) -> None:
    registry = tmp_path / "evaluation_wallets.csv"
    append_evaluation_wallet(registry, _accepted_wallet("TSYNTHETIC1"))
    evidence_root = tmp_path / "evidence"
    _write_run_bundle(evidence_root, NETWORK, "TSYNTHETIC1")

    first = materialize_evaluation_dataset(
        registry_path=registry, behavioral_evidence_root=evidence_root
    )
    second = materialize_evaluation_dataset(
        registry_path=registry, behavioral_evidence_root=evidence_root
    )

    assert len(first.rows) == 1
    assert len(second.rows) == 1
    assert first.snapshot_hash == second.snapshot_hash


def test_snapshot_hash_changes_with_feature_definition_version(tmp_path: Path) -> None:
    registry = tmp_path / "evaluation_wallets.csv"
    append_evaluation_wallet(registry, _accepted_wallet("TSYNTHETIC1"))
    evidence_root = tmp_path / "evidence"
    _write_run_bundle(evidence_root, NETWORK, "TSYNTHETIC1")

    v1 = materialize_evaluation_dataset(
        registry_path=registry,
        behavioral_evidence_root=evidence_root,
        feature_definition_version="v1",
    )
    v2 = materialize_evaluation_dataset(
        registry_path=registry,
        behavioral_evidence_root=evidence_root,
        feature_definition_version="v2",
    )

    assert v1.snapshot_hash != v2.snapshot_hash


def test_unreviewed_wallet_is_never_materialized(tmp_path: Path) -> None:
    registry = tmp_path / "evaluation_wallets.csv"
    append_evaluation_wallet(registry, _accepted_wallet("TUNREVIEWED", review_state="unreviewed"))
    evidence_root = tmp_path / "evidence"
    _write_run_bundle(evidence_root, NETWORK, "TUNREVIEWED")

    result = materialize_evaluation_dataset(
        registry_path=registry, behavioral_evidence_root=evidence_root
    )

    assert result.rows == []


def test_no_raw_address_appears_in_materialized_rows(tmp_path: Path) -> None:
    registry = tmp_path / "evaluation_wallets.csv"
    append_evaluation_wallet(registry, _accepted_wallet("TSYNTHETICADDRESSVALUE"))
    evidence_root = tmp_path / "evidence"
    _write_run_bundle(evidence_root, NETWORK, "TSYNTHETICADDRESSVALUE")

    result = materialize_evaluation_dataset(
        registry_path=registry, behavioral_evidence_root=evidence_root
    )

    for row in result.rows:
        flat = row.to_flat_dict()
        for value in flat.values():
            assert "TSYNTHETICADDRESSVALUE" not in str(value)
