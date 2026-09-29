"""Wallet-window feature dataset construction and split safeguards --
offline, deterministic, no model behind any of it yet.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.services.feature_dataset import (
    FeatureDatasetError,
    TimeLeakageError,
    assert_no_within_wallet_time_leakage,
    build_feature_table,
    build_wallet_window_row,
    dedupe_rows,
    split_by_time,
    split_by_wallet,
    wallet_id,
)
from app.services.features import Feature

WINDOW_START = dt.datetime(2026, 8, 10, tzinfo=dt.UTC)
WINDOW_END = dt.datetime(2026, 8, 11, tzinfo=dt.UTC)


def _feature(name: str, value, completeness: str = "complete") -> Feature:
    return Feature(name, value, (), WINDOW_START, WINDOW_END, completeness, None)


# --- wallet_id: deterministic and pseudonymous --------------------------------


def test_wallet_id_is_deterministic_and_pseudonymous() -> None:
    first = wallet_id("tron", "TSOMEADDRESS")
    second = wallet_id("tron", "TSOMEADDRESS")
    different_network = wallet_id("evm", "TSOMEADDRESS")

    assert first == second
    assert first != different_network
    assert "TSOMEADDRESS" not in first


# --- disallowed feature names --------------------------------------------------


def test_disallowed_feature_names_are_rejected() -> None:
    with pytest.raises(FeatureDatasetError):
        build_wallet_window_row(
            network="tron",
            address="TCANDIDATE",
            window_start=WINDOW_START,
            window_end=WINDOW_END,
            acquisition_completeness="complete_within_scope",
            verification_quality="history_only",
            source_run_ids=("run-1",),
            behavioral_features=[_feature("counterparty_address_leak", "TX")],
        )


# --- E4: missing features stay missing rather than becoming zero --------------


def test_missing_features_stay_missing_not_zero() -> None:
    row = build_wallet_window_row(
        network="tron",
        address="TCANDIDATE",
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        acquisition_completeness="complete_within_scope",
        verification_quality="history_only",
        source_run_ids=("run-1",),
        behavioral_features=[_feature("post_outflow_residue_base_units", None, "unknown")],
    )

    assert row.features["behavioral_post_outflow_residue_base_units"] is None
    assert row.missingness["behavioral_post_outflow_residue_base_units"] is True
    flat = row.to_flat_dict()
    assert flat["feature__behavioral_post_outflow_residue_base_units"] is None
    assert flat["missing__behavioral_post_outflow_residue_base_units"] is True


# --- E8 / C: dataset generation is deterministic -------------------------------


def test_feature_dataset_generation_is_deterministic() -> None:
    kwargs = dict(
        network="tron",
        address="TCANDIDATE",
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        acquisition_completeness="complete_within_scope",
        verification_quality="history_only",
        source_run_ids=("run-1",),
        behavioral_features=[_feature("observed_outgoing_transfer_count", 235)],
        resource_features=[_feature("historical_delegation_operation_count", 10)],
        control_category=None,
    )

    first = build_wallet_window_row(**kwargs)
    second = build_wallet_window_row(**kwargs)

    assert first == second
    assert first.to_flat_dict() == second.to_flat_dict()


# --- E1: two unrelated wallets sharing one resource provider stay separate ----


def test_two_unrelated_wallets_sharing_a_resource_provider_remain_separate() -> None:
    shared_provider_feature = _feature("historical_delegation_operation_count", 10)

    row_a = build_wallet_window_row(
        network="tron",
        address="TCANDIDATE_A",
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        acquisition_completeness="complete_within_scope",
        verification_quality="history_only",
        source_run_ids=("run-a",),
        resource_features=[shared_provider_feature],
    )
    row_b = build_wallet_window_row(
        network="tron",
        address="TCANDIDATE_B",
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        acquisition_completeness="complete_within_scope",
        verification_quality="history_only",
        source_run_ids=("run-b",),
        resource_features=[shared_provider_feature],
    )

    assert row_a.wallet_id != row_b.wallet_id
    header, table = build_feature_table([row_a, row_b])
    assert len(table) == 2
    ids_in_table = {row["wallet_id"] for row in table}
    assert ids_in_table == {row_a.wallet_id, row_b.wallet_id}
    # Neither row references the other's wallet_id or address anywhere.
    for row in table:
        for key, value in row.items():
            assert (
                row_a.wallet_id not in str(value) or key == "wallet_id" and value == row_a.wallet_id
            )
            assert "TCANDIDATE_A" not in str(value)
            assert "TCANDIDATE_B" not in str(value)


# --- E2: a high-volume/fan-out control wallet is not called suspicious --------


def test_high_volume_fanout_control_wallet_is_not_flagged_suspicious() -> None:
    row = build_wallet_window_row(
        network="tron",
        address="TFANOUT",
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        acquisition_completeness="complete_within_scope",
        verification_quality="history_only",
        source_run_ids=("run-1",),
        behavioral_features=[
            _feature("observed_outgoing_transfer_count", 235),
            _feature("repeated_forwarding_count", 4),
            _feature("outgoing_concentration_max_by_amount", 0.335437),
        ],
        control_category="frequent_exchange_customer",
    )

    flat = row.to_flat_dict()
    assert flat["control_category"] == "frequent_exchange_customer"
    for key in flat:
        assert "suspicious" not in key.lower()
        assert "risk" not in key.lower()
        assert "fraud" not in key.lower()


# --- E5: history-only verification stays visibly weaker than receipt-verified -


def test_history_only_verification_remains_visibly_distinct_from_receipt_verified() -> None:
    receipt_row = build_wallet_window_row(
        network="tron",
        address="TVERIFIED",
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        acquisition_completeness="complete_within_scope",
        verification_quality="receipt_verified",
        source_run_ids=("run-1",),
    )
    history_row = build_wallet_window_row(
        network="tron",
        address="THISTORYONLY",
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        acquisition_completeness="complete_within_scope",
        verification_quality="history_only",
        source_run_ids=("run-2",),
    )

    assert receipt_row.verification_quality == "receipt_verified"
    assert history_row.verification_quality == "history_only"
    assert receipt_row.verification_quality != history_row.verification_quality
    assert receipt_row.to_flat_dict()["verification_quality"] == "receipt_verified"
    assert history_row.to_flat_dict()["verification_quality"] == "history_only"


# --- E6: acquisition-complete does not imply execution-verified --------------


def test_acquisition_complete_does_not_imply_execution_verified() -> None:
    row = build_wallet_window_row(
        network="tron",
        address="TCANDIDATE",
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        acquisition_completeness="complete_within_scope",
        verification_quality="history_only",
        source_run_ids=("run-1",),
    )

    assert row.acquisition_completeness == "complete_within_scope"
    assert row.verification_quality == "history_only"
    # They are two distinct stored fields, not one collapsed status.
    assert row.acquisition_completeness != row.verification_quality


# --- E7: evaluation labels never change service attribution ------------------


def test_evaluation_wallets_module_is_not_wired_into_attribution() -> None:
    import inspect

    import app.services.evidence_comparison as evidence_comparison_module

    source = inspect.getsource(evidence_comparison_module)
    assert "evaluation_wallets" not in source


# --- Stage 3B: evaluation-corpus / model-facing isolation grep tests ---------


def test_service_outcome_never_imports_evaluation_wallets() -> None:
    import inspect

    import app.services.service_outcome as service_outcome_module

    assert "evaluation_wallets" not in inspect.getsource(service_outcome_module)


def test_strong_inference_policy_never_imports_evaluation_wallets() -> None:
    import inspect

    import app.services.strong_inference_policy as strong_inference_policy_module

    assert "evaluation_wallets" not in inspect.getsource(strong_inference_policy_module)


def _imported_module_names(module: object) -> set[str]:
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(module))  # type: ignore[arg-type]
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_evaluation_wallets_never_imports_attribution_or_inference_modules() -> None:
    import app.services.evaluation_wallets as evaluation_wallets_module

    imported = _imported_module_names(evaluation_wallets_module)
    for forbidden in (
        "app.services.service_outcome",
        "app.services.strong_inference_policy",
        "app.services.evidence_comparison",
    ):
        assert forbidden not in imported


def test_evaluation_dataset_never_imports_service_outcome_or_strong_inference() -> None:
    """I: model-facing materialization cannot consume service_outcome /
    strong_inference_policy output as labels or features."""
    import app.services.evaluation_dataset as evaluation_dataset_module

    imported = _imported_module_names(evaluation_dataset_module)
    assert "app.services.service_outcome" not in imported
    assert "app.services.strong_inference_policy" not in imported


# --- D: split safeguards -------------------------------------------------------


def _row(address: str, window_start: dt.datetime = WINDOW_START) -> object:
    return build_wallet_window_row(
        network="tron",
        address=address,
        window_start=window_start,
        window_end=window_start + dt.timedelta(hours=1),
        acquisition_completeness="complete_within_scope",
        verification_quality="history_only",
        source_run_ids=("run-1",),
    )


def test_split_by_wallet_keeps_the_same_wallet_together() -> None:
    same_wallet_two_windows = [
        _row("TCANDIDATE", WINDOW_START),
        _row("TCANDIDATE", WINDOW_START + dt.timedelta(days=1)),
    ]
    other_wallet = [_row("TOTHER")]
    rows = same_wallet_two_windows + other_wallet

    train, evaluation = split_by_wallet(rows, eval_fraction=0.5, seed=1)

    train_wallets = {row.wallet_id for row in train}
    eval_wallets = {row.wallet_id for row in evaluation}
    assert train_wallets.isdisjoint(eval_wallets)
    # Both of TCANDIDATE's windows landed on the same side.
    candidate_id = same_wallet_two_windows[0].wallet_id
    candidate_rows = [r for r in rows if r.wallet_id == candidate_id]
    sides = [
        candidate_id in {row.wallet_id for row in train},
        candidate_id in {row.wallet_id for row in evaluation},
    ]
    assert sum(sides) == 1
    assert len(candidate_rows) == 2


def test_split_by_wallet_is_deterministic() -> None:
    rows = [_row(f"TWALLET{i}") for i in range(10)]

    first_train, first_eval = split_by_wallet(rows, eval_fraction=0.3, seed=42)
    second_train, second_eval = split_by_wallet(rows, eval_fraction=0.3, seed=42)

    assert [r.wallet_id for r in first_train] == [r.wallet_id for r in second_train]
    assert [r.wallet_id for r in first_eval] == [r.wallet_id for r in second_eval]


def test_split_by_wallet_respects_explicit_groups() -> None:
    """Two wallets a caller has declared related for split-hygiene purposes
    only (never for attribution) always land on the same side."""
    row_a = _row("TGROUPED_A")
    row_b = _row("TGROUPED_B")
    group_of = {row_a.wallet_id: "shared-group", row_b.wallet_id: "shared-group"}

    train, evaluation = split_by_wallet(
        [row_a, row_b], eval_fraction=0.5, seed=7, group_of=group_of
    )

    train_ids = {r.wallet_id for r in train}
    eval_ids = {r.wallet_id for r in evaluation}
    assert (row_a.wallet_id in train_ids) == (row_b.wallet_id in train_ids)
    assert (row_a.wallet_id in eval_ids) == (row_b.wallet_id in eval_ids)


def test_split_by_time_respects_the_cutoff() -> None:
    early = _row("TEARLY", dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
    late = _row("TLATE", dt.datetime(2026, 6, 1, tzinfo=dt.UTC))
    cutoff = dt.datetime(2026, 3, 1, tzinfo=dt.UTC)

    train, evaluation = split_by_time([early, late], cutoff=cutoff)

    assert train == [early]
    assert evaluation == [late]


# --- C: wide table construction pads missing columns across rows --------------


def test_build_feature_table_pads_missing_columns_across_rows() -> None:
    row_with_resource = build_wallet_window_row(
        network="tron",
        address="TWITHRESOURCE",
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        acquisition_completeness="complete_within_scope",
        verification_quality="history_only",
        source_run_ids=("run-1",),
        resource_features=[_feature("historical_delegation_operation_count", 10)],
    )
    row_without_resource = build_wallet_window_row(
        network="tron",
        address="TWITHOUTRESOURCE",
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        acquisition_completeness="complete_within_scope",
        verification_quality="history_only",
        source_run_ids=("run-2",),
    )

    header, table = build_feature_table([row_with_resource, row_without_resource])

    assert "feature__resource_historical_delegation_operation_count" in header
    without_row = next(r for r in table if r["wallet_id"] == row_without_resource.wallet_id)
    assert without_row["feature__resource_historical_delegation_operation_count"] == ""


# --- Stage 3B: feature_definition_version, dedupe, and stronger leakage checks -


def test_changing_feature_definition_version_changes_dedupe_key() -> None:
    kwargs = dict(
        network="tron",
        address="TCANDIDATE",
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        acquisition_completeness="complete_within_scope",
        verification_quality="history_only",
        source_run_ids=("run-1",),
    )
    row_v1 = build_wallet_window_row(**kwargs, feature_definition_version="v1")
    row_v2 = build_wallet_window_row(**kwargs, feature_definition_version="v2")

    assert row_v1.dedupe_key != row_v2.dedupe_key
    assert row_v1.feature_definition_version != row_v2.feature_definition_version


def test_dedupe_rows_drops_duplicate_materializations() -> None:
    row = _row("TCANDIDATE")
    same_again = _row("TCANDIDATE")  # same wallet/window/version -> same dedupe key

    deduped = dedupe_rows([row, same_again])

    assert len(deduped) == 1


def test_dedupe_rows_keeps_distinct_windows() -> None:
    first = _row("TCANDIDATE", WINDOW_START)
    second = _row("TCANDIDATE", WINDOW_START + dt.timedelta(days=1))

    deduped = dedupe_rows([first, second])

    assert len(deduped) == 2


def test_assert_no_within_wallet_time_leakage_passes_for_clean_split() -> None:
    train = [_row("TCANDIDATE", dt.datetime(2026, 1, 1, tzinfo=dt.UTC))]
    evaluation = [_row("TCANDIDATE", dt.datetime(2026, 6, 1, tzinfo=dt.UTC))]

    assert_no_within_wallet_time_leakage(train, evaluation)  # must not raise


def test_assert_no_within_wallet_time_leakage_catches_future_train_window() -> None:
    """F: a time split must never train on a LATER window while evaluating
    on an EARLIER window of the SAME wallet."""
    train = [_row("TCANDIDATE", dt.datetime(2026, 6, 1, tzinfo=dt.UTC))]
    evaluation = [_row("TCANDIDATE", dt.datetime(2026, 1, 1, tzinfo=dt.UTC))]

    with pytest.raises(TimeLeakageError):
        assert_no_within_wallet_time_leakage(train, evaluation)


def test_assert_no_within_wallet_time_leakage_ignores_other_wallets() -> None:
    train = [_row("TEARLY_WALLET", dt.datetime(2026, 6, 1, tzinfo=dt.UTC))]
    evaluation = [_row("TOTHER_WALLET", dt.datetime(2026, 1, 1, tzinfo=dt.UTC))]

    assert_no_within_wallet_time_leakage(train, evaluation)  # different wallets: fine


# --- G: model-facing rows never contain a raw address or a banned field name --


def test_model_facing_row_never_contains_raw_address_or_banned_fragments() -> None:
    row = build_wallet_window_row(
        network="tron",
        address="TSHOULDNOTLEAK",
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        acquisition_completeness="complete_within_scope",
        verification_quality="history_only",
        source_run_ids=("run-1",),
        control_category="self_custody",
        data_mode="RECORDED_PUBLIC",
        evaluation_source_reference="https://example.invalid/source",
    )
    flat = row.to_flat_dict()

    banned_fragments = ("case_id", "service_name", "review_state", "complaint")
    for key in flat:
        for fragment in banned_fragments:
            assert fragment not in key.lower()
    for value in flat.values():
        assert "TSHOULDNOTLEAK" not in str(value)
