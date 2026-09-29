"""Readiness evaluation-unit accounting.

Regression guard: a corpus of N materialized windows from M wallets must
report N windows AND M distinct wallets, never conflate the two, and repeated
windows from one wallet must not inflate the independent-source count.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from app.reports.evaluation_readiness import build_readiness_report
from app.services.evaluation_dataset import materialize_evaluation_dataset
from app.services.evaluation_wallets import EvaluationWallet, append_evaluation_wallet
from app.services.feature_dataset import wallet_id

NETWORK = "tron"
JAN = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
DAY = dt.timedelta(days=1)


def _wallet(
    address: str,
    *,
    category: str = "other_operational_confounder",
    upstream_source_id: str = "src-1",
    review_state: str = "accepted",
    data_mode: str = "RECORDED_PUBLIC",
) -> EvaluationWallet:
    return EvaluationWallet(
        network=NETWORK,
        address=address,
        control_category=category,
        source_reference=f"https://example.invalid/{address}",
        evidence_type="SYNTHETIC fixture",
        valid_from="2026-01-01",
        valid_to="",
        review_state=review_state,
        notes="fixture",
        upstream_source_id=upstream_source_id,
        reviewer="Test Reviewer",
        data_mode=data_mode,
    )


def _bundle(root: Path, address: str, run_id: str, *, start: dt.datetime) -> None:
    run_dir = root / NETWORK / address / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": run_id,
        "query": {
            "candidate_address": address,
            "analysis_start": start.isoformat(),
            "analysis_cutoff": (start + DAY).isoformat(),
        },
        "truncated_by_page_limit": {"incoming": False, "outgoing": False},
        "truncated_by_event_limit": {"incoming": False, "outgoing": False},
        "truncated_by_request_budget": False,
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest))
    (run_dir / "evidence.json").write_text(json.dumps({"rows": []}))


def _empty_result(tmp_path: Path):
    return materialize_evaluation_dataset(
        registry_path=tmp_path / "no-registry.csv",
        behavioral_evidence_root=tmp_path / "no-evidence",
    )


def _report(tmp_path: Path, wallets: list[EvaluationWallet], *, group_of=None):
    registry = tmp_path / "evaluation_wallets.csv"
    for wallet in wallets:
        append_evaluation_wallet(registry, wallet)
    evidence_root = tmp_path / "evidence"
    real_result = materialize_evaluation_dataset(
        registry_path=registry, behavioral_evidence_root=evidence_root
    )
    return build_readiness_report(
        registry_path=registry,
        real_wallets=wallets,
        synthetic_wallets=[],
        real_result=real_result,
        synthetic_result=_empty_result(tmp_path),
        group_of=group_of,
    )


# --- A: 10 windows, 1 wallet ---------------------------------------------------


def test_one_wallet_ten_windows_reports_ten_windows_one_wallet(tmp_path: Path) -> None:
    address = "TWALLETONE"
    wallets = [_wallet(address)]
    evidence = tmp_path / "evidence"
    for i in range(10):
        _bundle(evidence, address, f"run-{i:02d}", start=JAN + i * DAY)

    report = _report(tmp_path, wallets)

    assert report.materialized_window_count_real == 10
    assert report.materialized_distinct_wallet_count_real == 1
    assert report.materialized_windows_per_wallet == {wallet_id(NETWORK, address): 10}
    assert report.wallets_with_multiple_materialized_windows == 1
    assert report.maximum_windows_from_one_wallet == 10
    assert report.most_represented_wallet_window_fraction == 1.0
    assert report.wallets_with_exactly_one_window == 0
    assert report.real_registry_record_count == 1


# --- B: two wallets x 5 windows ------------------------------------------------


def test_two_wallets_five_windows_each(tmp_path: Path) -> None:
    a, b = "TWALLETA", "TWALLETB"
    evidence = tmp_path / "evidence"
    for address in (a, b):
        for i in range(5):
            _bundle(evidence, address, f"run-{i:02d}", start=JAN + i * DAY)

    report = _report(tmp_path, [_wallet(a), _wallet(b, category="self_custody")])

    assert report.materialized_window_count_real == 10
    assert report.materialized_distinct_wallet_count_real == 2
    assert report.maximum_windows_from_one_wallet == 5
    assert report.most_represented_wallet_window_fraction == 0.5
    assert report.wallets_with_multiple_materialized_windows == 2


def test_wallets_with_exactly_one_window_is_counted(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _bundle(evidence, "TSOLO", "run-0", start=JAN)
    _bundle(evidence, "TMULTI", "run-0", start=JAN)
    _bundle(evidence, "TMULTI", "run-1", start=JAN + DAY)

    report = _report(tmp_path, [_wallet("TSOLO"), _wallet("TMULTI")])

    assert report.wallets_with_exactly_one_window == 1
    assert report.wallets_with_multiple_materialized_windows == 1


# --- C: repeated windows never inflate independent sources ---------------------


def test_repeated_windows_do_not_inflate_independent_source_count(tmp_path: Path) -> None:
    address = "TSAMESOURCE"
    evidence = tmp_path / "evidence"
    for i in range(5):
        _bundle(evidence, address, f"run-{i:02d}", start=JAN + i * DAY)

    report = _report(tmp_path, [_wallet(address, upstream_source_id="one-disclosure")])

    assert report.materialized_window_count_real == 5
    assert report.independent_source_count_real == 1
    assert report.accepted_independent_source_count == 1


# --- D: category coverage at wallet and window level ---------------------------


def test_category_coverage_distinguishes_wallets_from_windows(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    for i in range(5):
        _bundle(evidence, "TCONF", f"run-{i:02d}", start=JAN + i * DAY)
    for i in range(2):
        _bundle(evidence, "TSELF", f"run-{i:02d}", start=JAN + i * DAY)

    report = _report(
        tmp_path,
        [
            _wallet("TCONF", upstream_source_id="s1"),
            _wallet("TSELF", category="self_custody", upstream_source_id="s2"),
        ],
    )

    assert report.materialized_category_window_counts == {
        "other_operational_confounder": 5,
        "self_custody": 2,
    }
    assert report.materialized_category_wallet_counts == {
        "other_operational_confounder": 1,
        "self_custody": 1,
    }


# --- M + privacy: existing fields keep their meaning; no raw addresses ---------


def test_existing_fields_retain_meaning_and_no_raw_address_leaks(tmp_path: Path) -> None:
    address = "TPRIVACYWALLET"
    evidence = tmp_path / "evidence"
    _bundle(evidence, address, "run-0", start=JAN)
    _bundle(evidence, address, "run-1", start=JAN + DAY)

    report = _report(tmp_path, [_wallet(address)])

    assert report.real_wallet_count == 1
    assert report.accepted_real_registry_record_count == 1
    assert report.materialized_window_count_real == 2
    assert report.accepted_materialized_distinct_wallet_count == 1
    assert address not in json.dumps(report.to_dict())


# --- grouping supplied vs absent -----------------------------------------------


def test_absent_grouping_is_reported_as_a_limitation(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _bundle(evidence, "TG1", "run-0", start=JAN)

    report = _report(tmp_path, [_wallet("TG1")])

    assert report.related_wallet_grouping_supplied is False
    assert report.materialized_distinct_group_count_real is None
    assert report.group_held_out_split_feasible is False
    assert any("grouping" in b for b in report.unresolved_blockers)


def test_explicit_grouping_enables_group_split_reporting(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    for address in ("TGA1", "TGA2", "TGB1"):
        _bundle(evidence, address, "run-0", start=JAN)
    wallets = [_wallet("TGA1"), _wallet("TGA2"), _wallet("TGB1")]
    group_of = {
        wallet_id(NETWORK, "TGA1"): "group-a",
        wallet_id(NETWORK, "TGA2"): "group-a",
        wallet_id(NETWORK, "TGB1"): "group-b",
    }

    report = _report(tmp_path, wallets, group_of=group_of)

    assert report.related_wallet_grouping_supplied is True
    assert report.materialized_distinct_group_count_real == 2
    assert report.group_held_out_split_feasible is True
    assert report.unresolved_blockers == []
