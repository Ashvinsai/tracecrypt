"""Offline control/confounder wallet dataset: strictly sourced, strictly
separate from the attribution pipeline, and never a silent negative label.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.evaluation_wallets import (
    CONTROL_CATEGORIES,
    EvaluationWallet,
    EvaluationWalletError,
    append_evaluation_wallet,
    dedupe_by_upstream_source,
    find_evaluation_wallet,
    load_evaluation_wallets,
    validate_evaluation_wallet,
)

NETWORK = "tron"
ADDRESS = "TSELFCUSTODYWALLET"


def _wallet(**overrides: str) -> EvaluationWallet:
    kwargs = dict(
        network=NETWORK,
        address=ADDRESS,
        control_category="self_custody",
        source_reference="https://example.invalid/independent-attestation",
        evidence_type="self-attested and independently corroborated wallet",
        valid_from="2026-01-01T00:00:00Z",
        valid_to="",
        review_state="accepted",
        notes="fixture",
    )
    kwargs.update(overrides)
    return EvaluationWallet(**kwargs)


def test_load_returns_empty_list_when_file_missing(tmp_path: Path) -> None:
    assert load_evaluation_wallets(tmp_path / "nope.csv") == []


def test_validate_rejects_unsourced_wallet() -> None:
    with pytest.raises(EvaluationWalletError, match="source_reference"):
        validate_evaluation_wallet(_wallet(source_reference=""))


def test_validate_rejects_missing_evidence_type() -> None:
    with pytest.raises(EvaluationWalletError, match="evidence_type"):
        validate_evaluation_wallet(_wallet(evidence_type=""))


def test_validate_rejects_unsupported_category() -> None:
    with pytest.raises(EvaluationWalletError, match="control_category"):
        validate_evaluation_wallet(_wallet(control_category="definitely_fraud"))


def test_validate_rejects_unsupported_review_state() -> None:
    with pytest.raises(EvaluationWalletError, match="review_state"):
        validate_evaluation_wallet(_wallet(review_state="approved_by_gut_feeling"))


def test_all_documented_categories_validate() -> None:
    for category in CONTROL_CATEGORIES:
        validate_evaluation_wallet(_wallet(control_category=category))  # must not raise


def test_append_and_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "evaluation_wallets.csv"
    append_evaluation_wallet(path, _wallet())

    loaded = load_evaluation_wallets(path)

    assert len(loaded) == 1
    assert loaded[0].address == ADDRESS
    assert loaded[0].control_category == "self_custody"


def test_append_refuses_an_unsourced_wallet(tmp_path: Path) -> None:
    path = tmp_path / "evaluation_wallets.csv"
    with pytest.raises(EvaluationWalletError):
        append_evaluation_wallet(path, _wallet(source_reference=""))
    assert not path.exists()  # refused before any write


# --- E3: a self-custody control is not treated as an exchange negative -----


def test_self_custody_control_is_not_treated_as_an_exchange_negative(tmp_path: Path) -> None:
    path = tmp_path / "evaluation_wallets.csv"
    append_evaluation_wallet(path, _wallet(control_category="self_custody"))
    wallets = load_evaluation_wallets(path)

    found = find_evaluation_wallet(wallets, NETWORK, ADDRESS)

    assert found is not None


# --- Stage 3B.1: appending under a stale pre-Stage-3B header -----------
#
# Discovered for real while sourcing evaluation wallets: a CSV written before
# upstream_source_id/reviewer/data_mode existed (9-column header) silently
# broke on the *next* load after a new-schema row was appended under it,
# because csv.DictReader then hands the extra values back under key None.


def test_append_migrates_a_stale_pre_stage3b_header_in_place(tmp_path: Path) -> None:
    path = tmp_path / "evaluation_wallets.csv"
    path.write_text(
        "network,address,control_category,source_reference,evidence_type,"
        "valid_from,valid_to,review_state,notes\n"
    )

    append_evaluation_wallet(path, _wallet())

    lines = path.read_text().splitlines()
    assert lines[0] == (
        "network,address,control_category,source_reference,evidence_type,"
        "valid_from,valid_to,review_state,notes,upstream_source_id,reviewer,data_mode"
    )
    loaded = load_evaluation_wallets(path)
    assert len(loaded) == 1
    assert loaded[0].address == ADDRESS


def test_append_preserves_old_format_data_rows_when_migrating_header(tmp_path: Path) -> None:
    path = tmp_path / "evaluation_wallets.csv"
    old_header = (
        "network,address,control_category,source_reference,evidence_type,"
        "valid_from,valid_to,review_state,notes\n"
    )
    old_row = 'tron,TOLDROW,self_custody,https://example.invalid/old,attested,,,unreviewed,""\n'
    path.write_text(old_header + old_row)

    append_evaluation_wallet(path, _wallet(address="TNEWROW"))

    lines = path.read_text().splitlines()
    # The pre-existing data row's bytes are untouched; only the header line
    # was rewritten to the current schema.
    assert lines[1] == old_row.rstrip("\n")
    loaded = load_evaluation_wallets(path)
    addresses = {w.address for w in loaded}
    assert addresses == {"TOLDROW", "TNEWROW"}
    old = next(w for w in loaded if w.address == "TOLDROW")
    assert old.upstream_source_id == ""
    assert old.data_mode == "RECORDED_PUBLIC"


def test_absence_of_a_record_is_not_a_negative_label(tmp_path: Path) -> None:
    path = tmp_path / "evaluation_wallets.csv"
    append_evaluation_wallet(path, _wallet(address="TSOMEOTHERADDRESS"))
    wallets = load_evaluation_wallets(path)

    # ADDRESS has no record at all -- this must return None, not a
    # constructed "not a confounder" or "unknown = negative" answer.
    assert find_evaluation_wallet(wallets, NETWORK, ADDRESS) is None


def test_unreviewed_control_record_is_not_returned_as_established(tmp_path: Path) -> None:
    path = tmp_path / "evaluation_wallets.csv"
    append_evaluation_wallet(path, _wallet(review_state="unreviewed"))
    wallets = load_evaluation_wallets(path)

    assert find_evaluation_wallet(wallets, NETWORK, ADDRESS) is None


# --- Stage 3B: backward-compatible schema growth + upstream-source dedup ------


def test_load_fills_defaults_for_a_pre_stage_3b_row_missing_new_columns(tmp_path: Path) -> None:
    path = tmp_path / "evaluation_wallets.csv"
    path.write_text(
        "network,address,control_category,source_reference,evidence_type,valid_from,"
        "valid_to,review_state,notes\n"
        "tron,TOLDROW,self_custody,https://example.invalid/x,attested,,,"
        "accepted,legacy row\n"
    )

    loaded = load_evaluation_wallets(path)

    assert len(loaded) == 1
    assert loaded[0].upstream_source_id == ""
    assert loaded[0].reviewer == ""
    assert loaded[0].data_mode == "RECORDED_PUBLIC"


def test_dedupe_by_upstream_source_collapses_shared_origin() -> None:
    """J: two documents pointing to the same upstream source collapse to
    one source for evidence-counting purposes."""
    same_origin_a = _wallet(address="TA", source_reference="doc-a", upstream_source_id="origin-1")
    same_origin_b = _wallet(address="TB", source_reference="doc-b", upstream_source_id="origin-1")
    distinct = _wallet(address="TC", source_reference="doc-c", upstream_source_id="origin-2")

    count = dedupe_by_upstream_source([same_origin_a, same_origin_b, distinct])

    assert count == 2


def test_dedupe_by_upstream_source_treats_blank_ids_as_unmatched() -> None:
    unlabeled_a = _wallet(address="TA", source_reference="doc-a")
    unlabeled_b = _wallet(address="TB", source_reference="doc-b")

    count = dedupe_by_upstream_source([unlabeled_a, unlabeled_b])

    assert count == 2  # blank upstream_source_id never collapses distinct sources
