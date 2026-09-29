"""Stage 3B.2: human review workflow for data/evaluation_wallets.csv.

Letters A-N below correspond to the acceptance items in
docs/ACCEPTANCE_CATALOG.md's Stage 3B.2 entry.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.reports.evaluation_readiness import build_readiness_report
from app.services.evaluation_dataset import materialize_evaluation_dataset
from app.services.evaluation_review import (
    ACCEPTED_BUT_NO_MATERIALIZABLE_WINDOW,
    EVALUATION_REVIEW_LOG,
    ReviewAction,
    ReviewRequest,
    build_review_packet,
    domain_eligibility_for_wallet,
    is_invalid_reviewer,
    review_evaluation_wallet,
)
from app.services.evaluation_wallets import EvaluationWallet, append_evaluation_wallet

TRON_INC_ROW = {
    "network": "tron",
    "address": "TEySEZLJf6rs2mCujGpDEsgoMVWKLAk9mT",
    "control_category": "self_custody",
    "source_reference": "https://www.sec.gov/Archives/edgar/data/1956744/000149315226006323/ex99-1.htm",
    "evidence_type": "first-party disclosure",
    "valid_from": "2026-02-12",
    "valid_to": "",
    "review_state": "unreviewed",
    "notes": "designated on-chain TRX treasury wallet",
    "upstream_source_id": "tron-inc-2026-02-12-8k-ex99-1-trx-treasury-disclosure",
    "reviewer": "",
    "data_mode": "RECORDED_PUBLIC",
}


def _write_registry(data_dir: Path, rows: list[dict[str, str]]) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    import csv

    from app.services.evaluation_wallets import EVALUATION_WALLET_COLUMNS

    path = data_dir / "evaluation_wallets.csv"
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=EVALUATION_WALLET_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


# --- A: dry-run by default, writes nothing -----------------------------------


def test_dry_run_is_default_and_writes_nothing(tmp_path: Path) -> None:
    _write_registry(tmp_path, [TRON_INC_ROW])
    before = _hash(tmp_path / "evaluation_wallets.csv")

    request = ReviewRequest(
        network="tron",
        address=TRON_INC_ROW["address"],
        control_category="self_custody",
        action=ReviewAction.accept,
        reviewer="a.reviewer",
        rationale="looks fine",
        evidence_inspected=TRON_INC_ROW["upstream_source_id"],
    )
    outcome = review_evaluation_wallet(tmp_path, request, write=False)
    assert outcome.ok
    assert not outcome.written

    after = _hash(tmp_path / "evaluation_wallets.csv")
    assert before == after
    assert not (tmp_path / EVALUATION_REVIEW_LOG).exists()


# --- B: reviewer identity validation ------------------------------------------


@pytest.mark.parametrize("bad_name", ["", "  ", "agent", "Claude", "the assistant", "AI", "system"])
def test_invalid_reviewer_identities_are_refused(bad_name: str) -> None:
    assert is_invalid_reviewer(bad_name) is True


@pytest.mark.parametrize("good_name", ["ash", "a.reviewer", "Priya Sharma", "Aiyana Cole"])
def test_valid_reviewer_identities_are_accepted(good_name: str) -> None:
    assert is_invalid_reviewer(good_name) is False


def test_review_refuses_blank_reviewer_and_blank_rationale(tmp_path: Path) -> None:
    _write_registry(tmp_path, [TRON_INC_ROW])
    req = ReviewRequest(
        network="tron",
        address=TRON_INC_ROW["address"],
        control_category="self_custody",
        action=ReviewAction.accept,
        reviewer="agent",
        rationale="fine",
        evidence_inspected=TRON_INC_ROW["upstream_source_id"],
    )
    outcome = review_evaluation_wallet(tmp_path, req, write=False)
    assert outcome.refusal is not None
    assert outcome.refusal.code == "reviewer_required"

    req2 = ReviewRequest(
        network="tron",
        address=TRON_INC_ROW["address"],
        control_category="self_custody",
        action=ReviewAction.accept,
        reviewer="ash",
        rationale="   ",
        evidence_inspected=TRON_INC_ROW["upstream_source_id"],
    )
    outcome2 = review_evaluation_wallet(tmp_path, req2, write=False)
    assert outcome2.refusal is not None
    assert outcome2.refusal.code == "rationale_required"


# --- C: evidence_inspected must identify the record's own source -------------


def test_arbitrary_evidence_inspected_text_is_refused(tmp_path: Path) -> None:
    _write_registry(tmp_path, [TRON_INC_ROW])
    req = ReviewRequest(
        network="tron",
        address=TRON_INC_ROW["address"],
        control_category="self_custody",
        action=ReviewAction.accept,
        reviewer="ash",
        rationale="fine",
        evidence_inspected="totally unrelated text",
    )
    outcome = review_evaluation_wallet(tmp_path, req, write=False)
    assert outcome.refusal is not None
    assert outcome.refusal.code == "evidence_not_identified"


def test_evidence_inspected_matching_source_reference_is_accepted(tmp_path: Path) -> None:
    _write_registry(tmp_path, [TRON_INC_ROW])
    req = ReviewRequest(
        network="tron",
        address=TRON_INC_ROW["address"],
        control_category="self_custody",
        action=ReviewAction.quarantine,
        reviewer="ash",
        rationale="category mismatch needs escalation",
        evidence_inspected=TRON_INC_ROW["source_reference"],
    )
    outcome = review_evaluation_wallet(tmp_path, req, write=False)
    assert outcome.ok


# --- D: one call changes exactly one row and appends exactly one log record --


def test_one_review_call_changes_one_row_and_appends_one_log_record(tmp_path: Path) -> None:
    other_row = dict(TRON_INC_ROW)
    other_row["address"] = "TOTHERADDRESS"
    other_row["control_category"] = "payment_service"
    other_row["source_reference"] = "https://example.invalid/other"
    other_row["upstream_source_id"] = "other-upstream"
    _write_registry(tmp_path, [TRON_INC_ROW, other_row])

    req = ReviewRequest(
        network="tron",
        address=TRON_INC_ROW["address"],
        control_category="self_custody",
        action=ReviewAction.quarantine,
        reviewer="ash",
        rationale="category mismatch needs escalation",
        evidence_inspected=TRON_INC_ROW["source_reference"],
    )
    outcome = review_evaluation_wallet(tmp_path, req, write=True)
    assert outcome.ok

    import csv

    with (tmp_path / "evaluation_wallets.csv").open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["review_state"] == "quarantined"
    assert rows[1]["review_state"] == "unreviewed"  # untouched

    with (tmp_path / EVALUATION_REVIEW_LOG).open(newline="") as fh:
        log_rows = list(csv.DictReader(fh))
    assert len(log_rows) == 1
    assert log_rows[0]["network"] == "tron"
    assert log_rows[0]["new_review_state"] == "quarantined"


# --- E: terminal-state re-review, one allowed transition ---------------------


def test_rereviewing_terminal_state_is_refused_except_accepted_to_quarantined(
    tmp_path: Path,
) -> None:
    accepted_row = dict(TRON_INC_ROW)
    accepted_row["review_state"] = "accepted"
    _write_registry(tmp_path, [accepted_row])

    # accepted -> quarantined: allowed.
    ok_req = ReviewRequest(
        network="tron",
        address=TRON_INC_ROW["address"],
        control_category="self_custody",
        action=ReviewAction.quarantine,
        reviewer="ash",
        rationale="problem discovered after acceptance",
        evidence_inspected=TRON_INC_ROW["source_reference"],
    )
    assert review_evaluation_wallet(tmp_path, ok_req, write=False).ok

    # accepted -> rejected: refused.
    bad_req = ReviewRequest(
        network="tron",
        address=TRON_INC_ROW["address"],
        control_category="self_custody",
        action=ReviewAction.reject,
        reviewer="ash",
        rationale="changed my mind",
        evidence_inspected=TRON_INC_ROW["source_reference"],
    )
    outcome = review_evaluation_wallet(tmp_path, bad_req, write=False)
    assert outcome.refusal is not None
    assert outcome.refusal.code == "already_terminal"

    rejected_row = dict(TRON_INC_ROW)
    rejected_row["review_state"] = "rejected"
    _write_registry(tmp_path, [rejected_row])
    outcome2 = review_evaluation_wallet(tmp_path, ok_req, write=False)
    assert outcome2.refusal is not None
    assert outcome2.refusal.code == "already_terminal"


# --- F: cannot touch other protected files (hash-based) -----------------------


def test_review_workflow_never_touches_protected_files(tmp_path: Path) -> None:
    protected = {
        "verified_anchors.csv": "a,b\n1,2\n",
        "deposit_candidates.csv": "a,b\n1,2\n",
        "review_log.csv": "a,b\n1,2\n",
        "independent_review.csv": "a,b\n1,2\n",
    }
    for name, content in protected.items():
        (tmp_path / name).write_text(content)
    before_hashes = {name: _hash(tmp_path / name) for name in protected}

    _write_registry(tmp_path, [TRON_INC_ROW])
    req = ReviewRequest(
        network="tron",
        address=TRON_INC_ROW["address"],
        control_category="self_custody",
        action=ReviewAction.accept,
        reviewer="ash",
        rationale="fine",
        evidence_inspected=TRON_INC_ROW["source_reference"],
    )
    review_evaluation_wallet(tmp_path, req, write=True)

    after_hashes = {name: _hash(tmp_path / name) for name in protected}
    assert before_hashes == after_hashes


# --- G: no code path self-promotes without explicit reviewer+rationale+action -


def test_no_action_supplied_means_nothing_decided_nothing_written(tmp_path: Path) -> None:
    _write_registry(tmp_path, [TRON_INC_ROW])
    before = _hash(tmp_path / "evaluation_wallets.csv")

    req = ReviewRequest(
        network="tron",
        address=TRON_INC_ROW["address"],
        control_category="self_custody",
        action=None,
    )
    outcome = review_evaluation_wallet(tmp_path, req, write=True)
    assert outcome.applied is None
    assert outcome.refusal is None
    assert _hash(tmp_path / "evaluation_wallets.csv") == before


# --- H: corporate-treasury source is never rewritten into self_custody --------


def test_treasury_source_is_not_auto_rewritten_and_mismatch_is_surfaced(tmp_path: Path) -> None:
    _write_registry(tmp_path, [TRON_INC_ROW])
    packet = build_review_packet(tmp_path, "tron", TRON_INC_ROW["address"], "self_custody")
    assert packet is not None
    assert "self_custody" in packet.category_semantics_note
    assert "not literally 'self_custody'" in packet.category_semantics_note
    assert "does not resolve that mismatch" in packet.category_semantics_note

    # No accept call anywhere silently changes control_category; the column
    # in evaluation_wallets.csv is not writable via review_evaluation_wallet.
    req = ReviewRequest(
        network="tron",
        address=TRON_INC_ROW["address"],
        control_category="self_custody",
        action=ReviewAction.accept,
        reviewer="ash",
        rationale="fine",
        evidence_inspected=TRON_INC_ROW["source_reference"],
    )
    review_evaluation_wallet(tmp_path, req, write=True)
    import csv

    with (tmp_path / "evaluation_wallets.csv").open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["control_category"] == "self_custody"  # unchanged, never rewritten


# --- I: accepted registry record with no saved feature bundle ----------------


def test_accepted_record_with_no_saved_bundle_stays_accepted_but_materializes_nothing(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    wallet = EvaluationWallet(
        network="tron",
        address="TSYNTHETICACCEPTEDNOBUNDLE",
        control_category="self_custody",
        source_reference="SYNTHETIC-source",
        evidence_type="SYNTHETIC fixture",
        valid_from="2026-01-01",
        valid_to="",
        review_state="accepted",
        notes="SYNTHETIC fixture, no saved evidence bundle",
        upstream_source_id="",
        reviewer="SYNTHETIC-reviewer",
        data_mode="SYNTHETIC",
    )
    append_evaluation_wallet(data_dir / "evaluation_wallets.csv", wallet)

    evidence_root = tmp_path / "no-evidence-here"
    eligibility = domain_eligibility_for_wallet(
        data_dir, evidence_root, "tron", "TSYNTHETICACCEPTEDNOBUNDLE"
    )
    assert eligibility == ACCEPTED_BUT_NO_MATERIALIZABLE_WINDOW

    result = materialize_evaluation_dataset(
        registry_path=data_dir / "evaluation_wallets.csv",
        behavioral_evidence_root=evidence_root,
    )
    assert len(result.rows) == 0
    assert any(s.reason == "missing_evidence" for s in result.skipped)

    # Registry record itself is untouched -- still accepted.
    from app.services.evaluation_wallets import load_evaluation_wallets

    reloaded = load_evaluation_wallets(data_dir / "evaluation_wallets.csv")
    assert reloaded[0].review_state == "accepted"


# --- J/K/L: readiness split-feasibility semantics -----------------------------


def _bundle(root: Path, address: str) -> None:
    run_dir = root / "tron" / address / f"SYNTHETIC-{address}"
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": f"SYNTHETIC-{address}",
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


def _empty_result(tmp_path: Path):
    return materialize_evaluation_dataset(
        registry_path=tmp_path / "no-registry.csv",
        behavioral_evidence_root=tmp_path / "no-evidence",
    )


def test_two_unreviewed_registry_wallets_zero_materialized_is_not_split_feasible(
    tmp_path: Path,
) -> None:
    real_wallets = [
        EvaluationWallet(
            network="tron",
            address="TEySEZLJf6rs2mCujGpDEsgoMVWKLAk9mT",
            control_category="self_custody",
            source_reference="ref-1",
            evidence_type="first-party disclosure",
            valid_from="2026-02-12",
            valid_to="",
            review_state="unreviewed",
            notes="n",
            upstream_source_id="up-1",
            reviewer="",
            data_mode="RECORDED_PUBLIC",
        ),
        EvaluationWallet(
            network="tron",
            address="TGcwj4sP1iiSwMrMEPmDw43J1V3CehK7rM",
            control_category="other_operational_confounder",
            source_reference="ref-2",
            evidence_type="first-party disclosure",
            valid_from="2026-06-18",
            valid_to="",
            review_state="unreviewed",
            notes="n",
            upstream_source_id="up-2",
            reviewer="",
            data_mode="RECORDED_PUBLIC",
        ),
    ]
    empty_result = _empty_result(tmp_path)

    report = build_readiness_report(
        registry_path=tmp_path / "evaluation_wallets.csv",
        real_wallets=real_wallets,
        synthetic_wallets=[],
        real_result=empty_result,
        synthetic_result=empty_result,
    )
    assert report.model_dataset_split_feasible is False
    assert report.split_feasible is False
    assert report.registry_wallet_split_structurally_possible is True
    assert report.unreviewed_real_registry_record_count == 2
    assert report.accepted_real_registry_record_count == 0
    assert report.materialized_window_count_real == 0


def test_two_materialized_rows_same_wallet_is_not_split_feasible(tmp_path: Path) -> None:
    wallet = _synthetic_wallet("TSAMEWALLET")
    registry = tmp_path / "reg.csv"
    append_evaluation_wallet(registry, wallet)
    evidence_root = tmp_path / "evidence"
    _bundle(evidence_root, "TSAMEWALLET")

    result = materialize_evaluation_dataset(
        registry_path=registry, behavioral_evidence_root=evidence_root
    )
    # Duplicate the same wallet's single row to simulate "two rows, one wallet".
    doubled_rows = result.rows + result.rows
    from dataclasses import replace

    doubled_result = replace(result, rows=doubled_rows)

    report = build_readiness_report(
        registry_path=registry,
        real_wallets=[wallet],
        synthetic_wallets=[],
        real_result=doubled_result,
        synthetic_result=_empty_result(tmp_path),
    )
    assert report.model_dataset_split_feasible is False


def test_two_distinct_materialized_wallets_is_split_feasible_with_no_metric_claim(
    tmp_path: Path,
) -> None:
    wallet_a = _synthetic_wallet("TWALLETA")
    wallet_b = _synthetic_wallet("TWALLETB")
    registry = tmp_path / "reg.csv"
    append_evaluation_wallet(registry, wallet_a)
    append_evaluation_wallet(registry, wallet_b)
    evidence_root = tmp_path / "evidence"
    _bundle(evidence_root, "TWALLETA")
    _bundle(evidence_root, "TWALLETB")

    result = materialize_evaluation_dataset(
        registry_path=registry, behavioral_evidence_root=evidence_root
    )
    assert len({row.wallet_id for row in result.rows}) == 2

    report = build_readiness_report(
        registry_path=registry,
        real_wallets=[wallet_a, wallet_b],
        synthetic_wallets=[],
        real_result=result,
        synthetic_result=_empty_result(tmp_path),
    )
    assert report.model_dataset_split_feasible is True
    assert report.split_feasible is True

    as_text = report.to_json().lower()
    for fragment in ("accuracy", "precision", "recall", "auc", "adequate", "sufficient sample"):
        assert fragment not in as_text


# --- M: JSON and HTML outputs agree --------------------------------------------


def test_json_and_html_outputs_agree_on_corrected_fields(tmp_path: Path) -> None:
    from app.reports.evaluation_readiness import render_readiness_html

    empty_result = _empty_result(tmp_path)
    report = build_readiness_report(
        registry_path=tmp_path / "evaluation_wallets.csv",
        real_wallets=[],
        synthetic_wallets=[],
        real_result=empty_result,
        synthetic_result=empty_result,
    )
    html_out = render_readiness_html(report)
    as_dict = report.to_dict()
    assert str(as_dict["model_dataset_split_feasible"]) in html_out
    assert as_dict["status"] in html_out
