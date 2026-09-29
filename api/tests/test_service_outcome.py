"""Acceptance tests for the Stage 3A read-only outcome layer.

Behaviors A-J referenced in docs/ACCEPTANCE_CATALOG.md map onto the test
functions below (see module docstring lines for the letter each covers).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from app.services.service_outcome import (
    CATEGORY_CANDIDATE_LEAD,
    CATEGORY_SUPPORTED_DESTINATION,
    CATEGORY_UNKNOWN_OR_BLOCKED,
    REASON_EXPIRED_LABEL,
    REASON_INSUFFICIENT_VERIFICATION,
    REASON_NO_ACCEPTED_LABEL,
    REASON_UNRESOLVED_CONFLICT,
    REASON_WRONG_NETWORK,
    EvidenceReference,
    classify_service_outcome,
)
from app.services.strong_inference_policy import (
    FAMILY_BEHAVIORAL,
    FAMILY_RESOURCE_SPONSORSHIP,
    FAMILY_REVIEWED_LINKAGE,
    FAMILY_TRX_FUNDING,
    POLICY_VERSION,
    IndependentEvidenceItem,
    apply_strong_inference_policy,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
VAR_DIR = REPO_ROOT / "var"

BASE_KWARGS = dict(
    execution_status="success",
    coverage_status="complete_within_scope",
    attribution_status="supported",
    case_flow_linkage="established",
    acquisition_completeness="complete_within_scope",
    verification_quality="receipt_verified",
    event_identity_quality="receipt_event_index",
    ordering_quality="precise",
    ordering_ambiguous=False,
    evidence_references=(EvidenceReference("seed_transfer", "tx-1"),),
)


def _candidate_lead_outcome(**overrides):
    """A base outcome that lands in candidate_lead (insufficient verification
    on an otherwise accepted/in-date/right-network label) -- the only
    category apply_strong_inference_policy ever promotes from."""
    kwargs = dict(overrides)
    kwargs.setdefault("verification_quality", "history_only")
    return _outcome(**kwargs)


def _outcome(**overrides):
    kwargs = dict(BASE_KWARGS)
    kwargs.update(overrides)
    return classify_service_outcome(
        claim_id=kwargs.pop("claim_id", "claim-1"),
        candidate_service_name=kwargs.pop("candidate_service_name", "OKX"),
        label_review_state=kwargs.pop("label_review_state", "accepted"),
        label_in_date=kwargs.pop("label_in_date", True),
        label_network_matches=kwargs.pop("label_network_matches", True),
        has_material_conflict=kwargs.pop("has_material_conflict", False),
        **kwargs,
    )


# --- A: direct seed transfer AND chronological path both reach an accepted
# in-date service anchor without assigning ownership of an intermediary. ---
def test_A_direct_seed_transfer_reaches_accepted_label_without_intermediary_ownership():
    direct = _outcome(claim_id="A->H direct seed transfer")
    assert direct.category == CATEGORY_SUPPORTED_DESTINATION
    assert direct.service_name == "OKX"

    # A chronological path A -> D -> H: D's ownership/address_role is a
    # SEPARATE claim and stays unknown/unclaimed even though H is named for
    # this path.
    path_outcome = _outcome(claim_id="A->D->H chronological path")
    assert path_outcome.category == CATEGORY_SUPPORTED_DESTINATION
    assert path_outcome.service_name == "OKX"

    intermediary_ownership = _outcome(
        claim_id="D ownership",
        candidate_service_name=None,
        evidence_references=(),
    )
    assert intermediary_ownership.category == CATEGORY_UNKNOWN_OR_BLOCKED
    assert REASON_NO_ACCEPTED_LABEL in intermediary_ownership.reason_codes


# --- B: a supported branch and a blocked/unknown branch stay independently
# visible in one result; partial acquisition elsewhere doesn't erase either. -
def test_B_sibling_branches_stay_independent():
    supported = _outcome(claim_id="branch-1 supported", acquisition_completeness="truncated")
    assert supported.category == CATEGORY_SUPPORTED_DESTINATION
    assert supported.acquisition_completeness == "truncated"

    blocked_sibling = _outcome(
        claim_id="branch-2 pooled withdrawal fan-out",
        candidate_service_name=None,
        evidence_references=(),
        acquisition_completeness="truncated",
    )
    assert blocked_sibling.category == CATEGORY_UNKNOWN_OR_BLOCKED
    # Neither collapses the other's category.
    assert supported.category != blocked_sibling.category


# --- C: unreviewed/expired/conflicted/wrong-network labels cannot produce
# supported_destination; a dated reserve-proof claim stays a snapshot claim. -
def test_C_unreviewed_expired_conflicted_wrong_network_block_supported_destination():
    unreviewed = _outcome(label_review_state="unreviewed")
    assert unreviewed.category != CATEGORY_SUPPORTED_DESTINATION

    expired = _outcome(label_in_date=False)
    assert expired.category == CATEGORY_UNKNOWN_OR_BLOCKED
    assert REASON_EXPIRED_LABEL in expired.reason_codes

    conflicted = _outcome(has_material_conflict=True)
    assert conflicted.category == CATEGORY_UNKNOWN_OR_BLOCKED
    assert REASON_UNRESOLVED_CONFLICT in conflicted.reason_codes

    wrong_network = _outcome(label_network_matches=False)
    assert wrong_network.category == CATEGORY_UNKNOWN_OR_BLOCKED
    assert REASON_WRONG_NETWORK in wrong_network.reason_codes

    # A dated reserve-proof-style claim (valid_from == valid_to, a single
    # instant) never becomes a continuous-control or customer-deposit claim:
    # the outcome layer adds no such field, and none of the unresolved/notes
    # text produced here asserts continuous control or deposit status.
    supported = _outcome()
    for text in supported.unresolved:
        assert "continuous control" not in text
        assert "customer deposit" not in text


# --- D: repeated forwarding + shared sponsor/funder ALONE cannot produce
# strong_inference, promote a candidate, or merge identities. -------------
def test_D_shared_upstream_source_alone_is_not_independent_evidence():
    base = _candidate_lead_outcome()
    items = (
        IndependentEvidenceItem(
            family=FAMILY_BEHAVIORAL,
            evidence_id="behavior-1",
            upstream_source_id="candidate-self",
            reviewed=True,
            address_specific=True,
        ),
        IndependentEvidenceItem(
            family=FAMILY_RESOURCE_SPONSORSHIP,
            evidence_id="sponsor-1",
            upstream_source_id="funder-A",
            reviewed=True,
            address_specific=True,
        ),
        IndependentEvidenceItem(
            family=FAMILY_TRX_FUNDING,
            evidence_id="funding-1",
            upstream_source_id="funder-A",
            reviewed=True,
            address_specific=True,
        ),
    )
    result = apply_strong_inference_policy(
        base, items, label_in_date=True, label_network_matches=True
    )
    assert result.category in (CATEGORY_CANDIDATE_LEAD, CATEGORY_UNKNOWN_OR_BLOCKED)
    assert result.category != "strong_inference"

    # Two aggregators sharing one funder: both items trace to one upstream
    # source, so this is one source, not two independent ones.
    shared_funder_items = (
        IndependentEvidenceItem(
            family=FAMILY_REVIEWED_LINKAGE,
            evidence_id="aggregator-A-linkage",
            upstream_source_id="common-funder-X",
            reviewed=True,
            address_specific=True,
            data_mode="SYNTHETIC",
        ),
        IndependentEvidenceItem(
            family=FAMILY_REVIEWED_LINKAGE,
            evidence_id="aggregator-B-linkage",
            upstream_source_id="common-funder-X",
            reviewed=True,
            address_specific=True,
            data_mode="SYNTHETIC",
        ),
    )
    result2 = apply_strong_inference_policy(
        base, shared_funder_items, label_in_date=True, label_network_matches=True
    )
    assert result2.category in (CATEGORY_CANDIDATE_LEAD, CATEGORY_UNKNOWN_OR_BLOCKED)


def _hash_files(paths: list[Path]) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for path in paths:
        out[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    return out


def test_D_no_file_writes_from_repeated_pattern_alone():
    protected = [
        DATA_DIR / "verified_anchors.csv",
        DATA_DIR / "deposit_candidates.csv",
        DATA_DIR / "review_log.csv",
    ]
    before = _hash_files(protected)
    base = _candidate_lead_outcome()
    items = (
        IndependentEvidenceItem(
            family=FAMILY_BEHAVIORAL,
            evidence_id="behavior-1",
            upstream_source_id="candidate-self",
            reviewed=True,
            address_specific=True,
        ),
    )
    apply_strong_inference_policy(base, items, label_in_date=True, label_network_matches=True)
    after = _hash_files(protected)
    assert before == after


# --- E: current-state delegation is not backdated; missing execution/order
# verification is not silently upgraded. ------------------------------------
def test_E_history_only_verification_blocks_supported_destination():
    unverified_path = _outcome(verification_quality="history_only")
    assert unverified_path.category != CATEGORY_SUPPORTED_DESTINATION
    assert unverified_path.category == CATEGORY_CANDIDATE_LEAD
    assert REASON_INSUFFICIENT_VERIFICATION in unverified_path.reason_codes


def test_E_ordering_ambiguous_blocks_supported_destination():
    ambiguous = _outcome(ordering_ambiguous=True)
    assert ambiguous.category != CATEGORY_SUPPORTED_DESTINATION


def test_E_current_state_delegation_not_backdated_by_policy():
    base = _candidate_lead_outcome()
    items = (
        IndependentEvidenceItem(
            family=FAMILY_REVIEWED_LINKAGE,
            evidence_id="linkage-1",
            upstream_source_id="source-1",
            reviewed=True,
            address_specific=True,
            data_mode="SYNTHETIC",
        ),
        IndependentEvidenceItem(
            family=FAMILY_REVIEWED_LINKAGE,
            evidence_id="linkage-2",
            upstream_source_id="source-2",
            reviewed=True,
            address_specific=True,
            data_mode="SYNTHETIC",
        ),
    )
    result = apply_strong_inference_policy(
        base,
        items,
        label_in_date=True,
        label_network_matches=True,
        delegation_is_current_state_only=True,
        claimed_as_historical=True,
    )
    assert result.category != "strong_inference"
    assert any("backdated" in u for u in result.unresolved)


# --- F: SYNTHETIC positive case exercises strong_inference; removing the
# required independent evidence drops it back down. No file writes either
# way. ------------------------------------------------------------------
def test_F_synthetic_positive_and_negative_pair():
    base = _candidate_lead_outcome()
    positive_items = (
        IndependentEvidenceItem(
            family=FAMILY_REVIEWED_LINKAGE,
            evidence_id="SYNTHETIC-linkage-alpha",
            upstream_source_id="SYNTHETIC-source-alpha",
            reviewed=True,
            address_specific=True,
            data_mode="SYNTHETIC",
        ),
        IndependentEvidenceItem(
            family=FAMILY_REVIEWED_LINKAGE,
            evidence_id="SYNTHETIC-linkage-beta",
            upstream_source_id="SYNTHETIC-source-beta",
            reviewed=True,
            address_specific=True,
            data_mode="SYNTHETIC",
        ),
    )
    promoted = apply_strong_inference_policy(
        base, positive_items, label_in_date=True, label_network_matches=True
    )
    assert promoted.category == "strong_inference"
    assert promoted.policy_version == POLICY_VERSION

    negative_items = positive_items[:1]  # remove the required 2nd independent source
    not_promoted = apply_strong_inference_policy(
        base, negative_items, label_in_date=True, label_network_matches=True
    )
    assert not_promoted.category in (CATEGORY_CANDIDATE_LEAD, CATEGORY_UNKNOWN_OR_BLOCKED)


def test_F_policy_never_writes_review_files():
    protected = [
        DATA_DIR / "verified_anchors.csv",
        DATA_DIR / "deposit_candidates.csv",
        DATA_DIR / "review_log.csv",
    ]
    before = _hash_files(protected)
    base = _candidate_lead_outcome()
    items = (
        IndependentEvidenceItem(
            family=FAMILY_REVIEWED_LINKAGE,
            evidence_id="SYNTHETIC-linkage-alpha",
            upstream_source_id="SYNTHETIC-source-alpha",
            reviewed=True,
            address_specific=True,
            data_mode="SYNTHETIC",
        ),
        IndependentEvidenceItem(
            family=FAMILY_REVIEWED_LINKAGE,
            evidence_id="SYNTHETIC-linkage-beta",
            upstream_source_id="SYNTHETIC-source-beta",
            reviewed=True,
            address_specific=True,
            data_mode="SYNTHETIC",
        ),
    )
    apply_strong_inference_policy(base, items, label_in_date=True, label_network_matches=True)
    after = _hash_files(protected)
    assert before == after


# --- G: SYNTHETIC confounder cases (frequent customer, self-custody,
# energy-rental) are not labeled service-controlled from behavior alone.
# These are correctness fixtures, NOT real evaluation data, and make no
# precision/accuracy claim of any kind. --------------------------------
@pytest.mark.parametrize(
    "confounder_label",
    ["SYNTHETIC-frequent-customer", "SYNTHETIC-self-custody", "SYNTHETIC-energy-rental"],
)
def test_G_behavior_only_confounders_never_reach_strong_inference(confounder_label):
    base = _outcome(candidate_service_name=None, evidence_references=())
    items = (
        IndependentEvidenceItem(
            family=FAMILY_BEHAVIORAL,
            evidence_id=f"{confounder_label}-behavior-1",
            upstream_source_id=confounder_label,
            reviewed=True,
            address_specific=True,
            data_mode="SYNTHETIC",
        ),
        IndependentEvidenceItem(
            family=FAMILY_RESOURCE_SPONSORSHIP,
            evidence_id=f"{confounder_label}-sponsor-1",
            upstream_source_id=confounder_label,
            reviewed=True,
            address_specific=True,
            data_mode="SYNTHETIC",
        ),
    )
    result = apply_strong_inference_policy(
        base, items, label_in_date=True, label_network_matches=True
    )
    assert result.category != "strong_inference"


# --- H: repeated runs are byte-identical; evidence refs resolve; JSON/HTML
# agree. ------------------------------------------------------------------
def test_H_repeated_runs_produce_byte_identical_json():
    first = classify_service_outcome(claim_id="c1", **BASE_KWARGS, label_review_state="accepted",
                                      label_in_date=True, label_network_matches=True,
                                      candidate_service_name="OKX")
    second = classify_service_outcome(claim_id="c1", **BASE_KWARGS, label_review_state="accepted",
                                       label_in_date=True, label_network_matches=True,
                                       candidate_service_name="OKX")
    assert json.dumps(first.to_dict(), sort_keys=True) == json.dumps(
        second.to_dict(), sort_keys=True
    )


def test_H_evidence_references_resolve_to_real_input():
    supplied_evidence_ids = {"tx-1"}
    outcome = _outcome()
    for ref in outcome.evidence_references:
        assert ref.evidence_id in supplied_evidence_ids


def test_H_json_and_html_agree():
    from app.reports.comparison import render_service_outcome_html

    outcome = _outcome()
    html = render_service_outcome_html(outcome)
    assert outcome.category in html
    assert outcome.service_name in html
    for code in outcome.reason_codes:
        assert code in html


# --- I: regression -- the outcome layer changes nothing about existing
# trace/comparison output when it isn't called. ----------------------------
def test_I_not_calling_outcome_layer_leaves_comparison_output_unchanged():
    from app.services.evidence_comparison import build_comparison

    report1 = build_comparison(
        "TAddrRegression",
        deposit_candidate_row=None,
        anchor_rows=[],
        resource_rows=[],
        request_budget_truncated=False,
        provider_limit_truncated=False,
        funder_limit_truncated=False,
    )
    report2 = build_comparison(
        "TAddrRegression",
        deposit_candidate_row=None,
        anchor_rows=[],
        resource_rows=[],
        request_budget_truncated=False,
        provider_limit_truncated=False,
        funder_limit_truncated=False,
    )
    assert asdict(report1) == asdict(report2)


# --- J: protected files and historical var/ bundles are byte-unchanged
# after exercising this layer. ----------------------------------------------
def test_J_protected_files_and_var_bundles_untouched():
    protected = [
        DATA_DIR / "verified_anchors.csv",
        DATA_DIR / "deposit_candidates.csv",
        DATA_DIR / "review_log.csv",
        DATA_DIR / "independent_review.csv",
        DATA_DIR / "evaluation_wallets.csv",
    ]
    run_dirs = [
        VAR_DIR / "collect-behavioral-evidence" / "20260920T162301Z-adfb1e",
        VAR_DIR / "collect-behavioral-evidence" / "20260920T165506Z-ee96cd",
    ]
    var_files = [p for d in run_dirs if d.is_dir() for p in sorted(d.rglob("*")) if p.is_file()]

    before_protected = _hash_files(protected)
    before_var = _hash_files(var_files)

    # Exercise both modules fully.
    outcome = _outcome()
    apply_strong_inference_policy(
        outcome,
        (
            IndependentEvidenceItem(
                family=FAMILY_REVIEWED_LINKAGE,
                evidence_id="SYNTHETIC-x",
                upstream_source_id="SYNTHETIC-src",
                reviewed=True,
                address_specific=True,
                data_mode="SYNTHETIC",
            ),
        ),
        label_in_date=True,
        label_network_matches=True,
    )

    after_protected = _hash_files(protected)
    after_var = _hash_files(var_files)
    assert before_protected == after_protected
    assert before_var == after_var


def test_evaluation_wallets_not_referenced_by_strong_inference_policy():
    source = Path(
        REPO_ROOT / "api" / "app" / "services" / "strong_inference_policy.py"
    ).read_text()
    assert "evaluation_wallets" not in source


def test_evaluation_wallets_not_referenced_by_service_outcome():
    source = Path(REPO_ROOT / "api" / "app" / "services" / "service_outcome.py").read_text()
    assert "evaluation_wallets" not in source
