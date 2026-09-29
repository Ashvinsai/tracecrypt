"""Stage 4: legal-process request drafts.

Pure-function tests -- no client, no database, no chain. Uses the same
hand-built result-dict contract as test_evidence_export.py.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.services.legal_requests import (
    KIND_ASSET_RESTRICTION,
    KIND_INFORMATION,
    KIND_PRESERVATION,
    RequestDraftError,
    build_request_draft,
)

GENERATED_AT = dt.datetime(2026, 9, 22, 12, 0, 0, tzinfo=dt.UTC)

VICTIM = "TVictim000000000000000000000000000"
SERVICE_HOT_WALLET = "TServiceHot0000000000000000000000"
SERVICE_DEPOSIT = "TServiceDeposit000000000000000000"
SERVICE_UNKNOWN_ROLE = "TServiceUnknown0000000000000000000"
CANDIDATE_UNREVIEWED = "TCandidate00000000000000000000000"
UNREACHED = "TNeverReached00000000000000000000"

_REQUIRED = {
    "requesting_agency": "State Cyber Cell, Testland",
    "requesting_officer": "Inspector A. Sharma",
    "case_reference": "FIR-2026-00042",
    "alleged_incident_summary": "Victim reports a fraudulent investment scheme.",
}


def _branch(
    address: str,
    *,
    endpoint_class: str,
    attribution_status: str = "supported",
    label: dict | None = None,
) -> dict:
    return {
        "address": address,
        "endpoint_class": endpoint_class,
        "attribution_status": attribution_status,
        "boundary_reason": None,
        "hop_depth": 1,
        "branch_path": [VICTIM, address],
        "arrival_event_reference": "tron:tx_hop1:0",
        "observed_amount_base_units": "745297300000",
        "observed_amount_display": "745297.300000",
        "case_amount_basis": "allocation_unknown",
        "label": label,
        "note": None,
    }


def _label(entity_name: str, address_role: str, review_state: str = "accepted") -> dict:
    return {
        "entity_name": entity_name,
        "entity_type": "exchange",
        "assertion_type": "service_control",
        "address_role": address_role,
        "review_state": review_state,
        "source_reference": "https://example.test/disclosure",
        "retrieval_date": "2026-09-01",
        "methodology": "Accepted scope",
        "reviewer": "analyst-1",
        "valid_from": "2026-08-01T00:00:00+00:00",
        "valid_to": None,
        "last_verified_at": "2026-09-01T00:00:00+00:00",
        "label_set_version": "3",
        "source_hash": "abc123",
        "source_file": "verified_anchors.csv",
        "reviewed_by": "analyst-1",
        "reviewed_at": "2026-09-01T00:00:00+00:00",
        "label_source": None,
        "original_reference": None,
        "original_hash": None,
        "original_member": None,
        "original_row_locator": None,
        "review_reference": "abc123456789012@2026-09-01T00:00:00+00:00",
    }


def _result(**overrides) -> dict:
    result = {
        "seed": {
            "address": VICTIM,
            "event_reference": "tron:tx_seed:0",
            "network_key": "tron",
            "asset": {
                "token_contract": "TQghWzGAMfcTPWzsDGWREVqKbbFMzegaGY",
                "display_symbol": "USDT-SYN",
                "decimals": 6,
            },
        },
        "scope": {
            "data_mode": "SYNTHETIC",
            "analysis_cutoff": "2026-09-22T00:00:00+00:00",
            "started_at": "2026-09-22T00:00:00+00:00",
            "finished_at": "2026-09-22T00:00:01+00:00",
            "engine_version": "0.1.0",
            "label_set_version": "3",
            "coverage_status": "complete_within_scope",
            "case_flow_linkage": "established",
            "label_snapshot": {},
        },
        "seed_transfer": {
            "event_reference": "tron:tx_seed:0",
            "tx_hash": "tx_seed",
            "from_address": VICTIM,
            "to_address": "TMule0000000000000000000000000000",
            "amount_base_units": "750000000000",
            "amount_display": "750000.000000",
            "asset": {
                "token_contract": "TQghWzGAMfcTPWzsDGWREVqKbbFMzegaGY",
                "decimals": 6,
                "display_symbol": "USDT-SYN",
            },
            "block_time": "2026-09-22T00:00:00+00:00",
            "chain_sequence": "0",
            "ordering_ambiguous": False,
            "execution_status": "success",
            "confirmation_state": "solidified",
            "hop_depth": 0,
            "acquisition_id": None,
        },
        "observed_transfers": [
            {
                "event_reference": "tron:tx_hop1:0",
                "tx_hash": "tx_hop1",
                "from_address": "TMule0000000000000000000000000000",
                "to_address": SERVICE_HOT_WALLET,
                "amount_base_units": "745297300000",
                "amount_display": "745297.300000",
                "asset": {
                    "token_contract": "TQghWzGAMfcTPWzsDGWREVqKbbFMzegaGY",
                    "decimals": 6,
                    "display_symbol": "USDT-SYN",
                },
                "block_time": "2026-09-22T01:00:00+00:00",
                "chain_sequence": "1",
                "ordering_ambiguous": False,
                "execution_status": "success",
                "confirmation_state": "solidified",
                "hop_depth": 1,
                "acquisition_id": None,
            }
        ],
        "branch_endings": [
            _branch(
                SERVICE_HOT_WALLET,
                endpoint_class="known_service",
                label=_label("Northwind Exchange (FICTIONAL)", "hot_wallet"),
            ),
            _branch(
                SERVICE_DEPOSIT,
                endpoint_class="known_service",
                label=_label("Northwind Exchange (FICTIONAL)", "deposit"),
            ),
            _branch(
                SERVICE_UNKNOWN_ROLE,
                endpoint_class="known_service",
                label=_label("Northwind Exchange (FICTIONAL)", "unknown"),
            ),
            _branch(
                CANDIDATE_UNREVIEWED,
                endpoint_class="deposit_candidate",
                attribution_status="candidate",
                label=None,
            ),
        ],
        "limitations": [],
        "budget_use": {
            "hops_used": 1,
            "hop_limit": 8,
            "events_examined": 2,
            "event_limit": 5000,
            "traversal_requests": 1,
            "traversal_request_limit": 400,
            "elapsed_seconds": 0.02,
        },
        "acquisitions": [],
        "disclaimer": "not a legal instrument",
    }
    result.update(overrides)
    return result


def test_information_request_against_a_hot_wallet_is_not_refused() -> None:
    """The pooled-wallet refusal only applies to asset_restriction; an
    information request naming the exchange's own hot wallet is fine."""
    draft = build_request_draft(
        _result(),
        request_kind=KIND_INFORMATION,
        target_address=SERVICE_HOT_WALLET,
        generated_at=GENERATED_AT,
        **_REQUIRED,
    )
    assert draft.status == "drafted"
    assert draft.refusal_reason is None


def test_preservation_request_against_a_hot_wallet_is_not_refused() -> None:
    draft = build_request_draft(
        _result(),
        request_kind=KIND_PRESERVATION,
        target_address=SERVICE_HOT_WALLET,
        generated_at=GENERATED_AT,
        **_REQUIRED,
    )
    assert draft.status == "drafted"


def test_asset_restriction_against_a_hot_wallet_is_refused() -> None:
    draft = build_request_draft(
        _result(),
        request_kind=KIND_ASSET_RESTRICTION,
        target_address=SERVICE_HOT_WALLET,
        generated_at=GENERATED_AT,
        **_REQUIRED,
    )
    assert draft.status == "refused"
    assert "pooled" in draft.refusal_reason.lower()
    assert "hot_wallet" in draft.refusal_reason


def test_asset_restriction_against_an_unknown_role_is_refused() -> None:
    """Both of this project's real accepted OKX anchors are address_role=
    unknown today -- exactly this case -- because a reserve-disclosure
    signature does not establish whether an address is pooled or not."""
    draft = build_request_draft(
        _result(),
        request_kind=KIND_ASSET_RESTRICTION,
        target_address=SERVICE_UNKNOWN_ROLE,
        generated_at=GENERATED_AT,
        **_REQUIRED,
    )
    assert draft.status == "refused"
    assert "not established" in draft.refusal_reason


def test_asset_restriction_against_an_unlabeled_candidate_is_refused() -> None:
    draft = build_request_draft(
        _result(),
        request_kind=KIND_ASSET_RESTRICTION,
        target_address=CANDIDATE_UNREVIEWED,
        generated_at=GENERATED_AT,
        **_REQUIRED,
    )
    assert draft.status == "refused"
    assert draft.target.address_role is None


def test_asset_restriction_against_a_confirmed_deposit_address_is_drafted() -> None:
    draft = build_request_draft(
        _result(),
        request_kind=KIND_ASSET_RESTRICTION,
        target_address=SERVICE_DEPOSIT,
        generated_at=GENERATED_AT,
        **_REQUIRED,
    )
    assert draft.status == "drafted"
    assert draft.refusal_reason is None
    assert draft.target.address_role == "deposit"


def test_unreached_address_raises_a_caller_error_not_a_refused_draft() -> None:
    with pytest.raises(RequestDraftError, match="not a branch ending"):
        build_request_draft(
            _result(),
            request_kind=KIND_INFORMATION,
            target_address=UNREACHED,
            generated_at=GENERATED_AT,
            **_REQUIRED,
        )


@pytest.mark.parametrize("missing", sorted(_REQUIRED))
def test_blank_required_investigator_field_raises(missing: str) -> None:
    kwargs = dict(_REQUIRED)
    kwargs[missing] = "   "
    with pytest.raises(RequestDraftError, match=missing):
        build_request_draft(
            _result(),
            request_kind=KIND_INFORMATION,
            target_address=SERVICE_HOT_WALLET,
            generated_at=GENERATED_AT,
            **kwargs,
        )


def test_draft_marker_is_always_present_even_when_refused() -> None:
    for target in (SERVICE_HOT_WALLET, SERVICE_DEPOSIT):
        draft = build_request_draft(
            _result(),
            request_kind=KIND_ASSET_RESTRICTION,
            target_address=target,
            generated_at=GENERATED_AT,
            **_REQUIRED,
        )
        assert "DRAFT" in draft.draft_marker
        assert "not legal process" in draft.draft_marker
        assert "has not been sent" in draft.draft_marker


def test_checklist_never_fabricates_a_missing_legal_authority_reference() -> None:
    draft = build_request_draft(
        _result(),
        request_kind=KIND_INFORMATION,
        target_address=SERVICE_HOT_WALLET,
        generated_at=GENERATED_AT,
        **_REQUIRED,
    )
    authority = next(f for f in draft.checklist if f.key == "legal_authority_reference")
    assert authority.provided is False
    assert "NOT PROVIDED" in authority.value


def test_checklist_records_a_supplied_legal_authority_reference() -> None:
    draft = build_request_draft(
        _result(),
        request_kind=KIND_INFORMATION,
        target_address=SERVICE_HOT_WALLET,
        legal_authority_reference="Section 91 BNSS notice, order no. 2026/XYZ",
        generated_at=GENERATED_AT,
        **_REQUIRED,
    )
    authority = next(f for f in draft.checklist if f.key == "legal_authority_reference")
    assert authority.provided is True
    assert authority.value == "Section 91 BNSS notice, order no. 2026/XYZ"


def test_exchange_account_identifiers_provided_flag_tracks_whether_it_was_supplied() -> None:
    without = build_request_draft(
        _result(),
        request_kind=KIND_INFORMATION,
        target_address=SERVICE_HOT_WALLET,
        generated_at=GENERATED_AT,
        **_REQUIRED,
    )
    with_it = build_request_draft(
        _result(),
        request_kind=KIND_INFORMATION,
        target_address=SERVICE_HOT_WALLET,
        exchange_account_identifiers="UID 123456",
        generated_at=GENERATED_AT,
        **_REQUIRED,
    )
    without_field = next(f for f in without.checklist if f.key == "exchange_account_identifiers")
    with_field = next(f for f in with_it.checklist if f.key == "exchange_account_identifiers")
    assert without_field.provided is False
    assert with_field.provided is True
    assert with_field.value == "UID 123456"


def test_items_requested_differs_by_kind_and_asset_restriction_names_the_target_only() -> None:
    info = build_request_draft(
        _result(),
        request_kind=KIND_INFORMATION,
        target_address=SERVICE_DEPOSIT,
        generated_at=GENERATED_AT,
        **_REQUIRED,
    )
    restriction = build_request_draft(
        _result(),
        request_kind=KIND_ASSET_RESTRICTION,
        target_address=SERVICE_DEPOSIT,
        generated_at=GENERATED_AT,
        **_REQUIRED,
    )
    info_items = next(f for f in info.checklist if f.key == "items_requested").value
    restriction_items = next(f for f in restriction.checklist if f.key == "items_requested").value
    assert info_items != restriction_items
    assert "does not seek restriction of any pooled" in restriction_items


def test_identifiers_include_observed_transaction_hashes_and_point_to_the_export_bundle() -> None:
    draft = build_request_draft(
        _result(),
        request_kind=KIND_INFORMATION,
        target_address=SERVICE_HOT_WALLET,
        generated_at=GENERATED_AT,
        **_REQUIRED,
    )
    assert draft.identifiers["observed_transaction_hashes"] == ["tx_hop1", "tx_seed"]
    assert "traces/export" in draft.identifiers["note"]


def test_checklist_source_names_the_real_provider_guide() -> None:
    draft = build_request_draft(
        _result(),
        request_kind=KIND_INFORMATION,
        target_address=SERVICE_HOT_WALLET,
        generated_at=GENERATED_AT,
        **_REQUIRED,
    )
    assert draft.checklist_source["provider"] == "OKX"
    assert draft.checklist_source["source_reference"].startswith("https://www.okx.com/")


def test_investigation_findings_are_auto_filled_from_the_trace_not_free_text() -> None:
    draft = build_request_draft(
        _result(),
        request_kind=KIND_INFORMATION,
        target_address=SERVICE_DEPOSIT,
        generated_at=GENERATED_AT,
        **_REQUIRED,
    )
    findings = next(f for f in draft.checklist if f.key == "investigation_findings_to_date").value
    assert VICTIM in findings
    assert SERVICE_DEPOSIT in findings


def test_to_json_round_trips_every_top_level_field() -> None:
    draft = build_request_draft(
        _result(),
        request_kind=KIND_ASSET_RESTRICTION,
        target_address=SERVICE_HOT_WALLET,
        generated_at=GENERATED_AT,
        **_REQUIRED,
    )
    payload = draft.to_json()
    assert payload["status"] == "refused"
    assert payload["request_kind"] == "asset_restriction"
    assert payload["target"]["address"] == SERVICE_HOT_WALLET
    assert isinstance(payload["checklist"], list) and payload["checklist"]
    assert payload["generated_at"] == GENERATED_AT.isoformat()


def test_unknown_request_kind_raises() -> None:
    with pytest.raises(RequestDraftError, match="unknown request_kind"):
        build_request_draft(
            _result(),
            request_kind="freeze_everything",  # type: ignore[arg-type]
            target_address=SERVICE_HOT_WALLET,
            generated_at=GENERATED_AT,
            **_REQUIRED,
        )
