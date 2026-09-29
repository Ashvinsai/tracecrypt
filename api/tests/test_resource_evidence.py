"""TRON resource delegation as evidence, and the two claims it cannot support.

Day-one tests 10 and 12 (`docs/FIVE_STAGE_PLAN.md`). Both are ways a shared
energy sponsor turns into a confident wrong answer: one merges strangers, the
other reads a current-state response as a history.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.engine.resources import (
    INDEPENDENT_EVIDENCE_KINDS,
    DelegationCoverage,
    DelegationObservation,
    active_at,
    delegation_timing,
    may_promote,
    parse_account_index,
    parse_delegated_resource_v2,
    sponsor_leads,
)
from app.models.enums import (
    AssertionType,
    AttributionStatus,
    CoverageStatus,
    DelegationBasis,
    ResourceType,
    ReviewState,
)
from app.services.labels import Anchor, LabelRegistry

T0 = dt.datetime(2026, 8, 1, 10, 0, tzinfo=dt.UTC)
NOW = dt.datetime(2026, 9, 20, 12, 0, tzinfo=dt.UTC)

SPONSOR = "TSponsorEnergyRentalXXXXXXXXXXXXXXX"
D1 = "TReceiverOneXXXXXXXXXXXXXXXXXXXXXXX"
D2 = "TReceiverTwoXXXXXXXXXXXXXXXXXXXXXXX"

INDEX_ENDPOINT = "POST /wallet/getdelegatedresourceaccountindexv2"
STATE_ENDPOINT = "POST /walletsolidity/getdelegatedresourcev2"


def current_state(receiver: str, sponsor: str = SPONSOR) -> DelegationObservation:
    return DelegationObservation(
        network_key="tron",
        sponsor_address=sponsor,
        receiver_address=receiver,
        resource=ResourceType.energy,
        basis=DelegationBasis.current_state,
        observed_at=NOW,
        source_reference=STATE_ENDPOINT,
    )


# --- Day-one 10: a shared sponsor merges nothing and names nobody ------------


def test_shared_sponsor_does_not_merge_unrelated_wallets() -> None:
    leads = sponsor_leads([current_state(D1), current_state(D2)])

    assert len(leads) == 2
    by_receiver = {lead.receiver_address: lead for lead in leads}
    assert set(by_receiver) == {D1, D2}

    # A lead is about one receiver and its sponsor. There is no group, and
    # neither receiver appears anywhere in the other's evidence.
    assert D2 not in by_receiver[D1].addresses_mentioned()
    assert D1 not in by_receiver[D2].addresses_mentioned()
    for lead in leads:
        assert lead.attribution_status is AttributionStatus.candidate
        assert lead.entity_name is None


def test_sponsor_label_does_not_transfer_to_the_receiver() -> None:
    registry = LabelRegistry(
        [
            Anchor(
                network_key="tron",
                address=SPONSOR,
                entity_name="Northwind Exchange (FICTIONAL)",
                entity_type="exchange",
                assertion_type=AssertionType.service_control,
                address_role="hot_wallet",
                review_state=ReviewState.accepted,
                source_reference="fixtures/tron_synthetic_case_alpha.json",
                retrieval_date=T0,
                methodology="synthetic fixture",
                reviewer="synthetic fixture",
                valid_from=None,
                valid_to=None,
                last_verified_at=T0,
                label_set_version="synthetic-0",
            )
        ]
    )

    (lead,) = sponsor_leads([current_state(D1)], registry=registry, moment=NOW)

    # The sponsor's own provenance is shown, never inherited.
    assert lead.sponsor_label is not None
    assert lead.sponsor_label.entity_name == "Northwind Exchange (FICTIONAL)"
    assert lead.entity_name is None
    assert lead.attribution_status is AttributionStatus.candidate
    assert may_promote(lead, corroboration=()).allowed is False


def test_shared_sponsor_alone_cannot_promote_a_candidate() -> None:
    (lead,) = sponsor_leads([current_state(D1)])

    assert may_promote(lead, corroboration=()).allowed is False
    # Resource delegation plus TRX funding is still one kind of overlap.
    assert may_promote(lead, corroboration=("trx_funding",)).allowed is False
    assert may_promote(lead, corroboration=("repeated_sweeps",)).allowed is False

    decision = may_promote(lead, corroboration=("sourced_disclosure",))
    assert decision.allowed is True
    # Promotion reaches inference, never a supported ownership claim.
    assert decision.resulting_status is AttributionStatus.inferred
    assert "sourced_disclosure" in INDEPENDENT_EVIDENCE_KINDS


def test_high_fanout_sponsor_is_flagged_as_a_shared_service() -> None:
    receivers = [f"TReceiver{i:031d}" for i in range(25)]
    leads = sponsor_leads([current_state(r) for r in receivers], shared_service_fanout_threshold=10)

    assert all(lead.sponsor_looks_like_shared_service for lead in leads)
    for lead in leads:
        assert not may_promote(lead, corroboration=("sourced_disclosure",)).allowed


# --- Day-one 12: current state is not a history -----------------------------


def test_current_state_does_not_establish_when_a_delegation_began() -> None:
    timing = delegation_timing(current_state(D1))

    assert timing.established_at is None
    assert timing.status == "unknown"
    assert timing.basis is DelegationBasis.current_state


def test_lock_expiry_is_not_a_delegation_start() -> None:
    observation = DelegationObservation(
        network_key="tron",
        sponsor_address=SPONSOR,
        receiver_address=D1,
        resource=ResourceType.energy,
        basis=DelegationBasis.current_state,
        observed_at=NOW,
        source_reference=STATE_ENDPOINT,
        frozen_balance_base_units=1_000_000_000,
        lock_expires_at=NOW + dt.timedelta(days=3),
    )

    assert delegation_timing(observation).established_at is None
    # Present now says nothing about a moment before we looked.
    assert active_at(observation, T0) is None
    assert active_at(observation, NOW) is True


def test_current_state_observation_refuses_to_carry_an_operation_time() -> None:
    with pytest.raises(ValueError, match="current state"):
        DelegationObservation(
            network_key="tron",
            sponsor_address=SPONSOR,
            receiver_address=D1,
            resource=ResourceType.energy,
            basis=DelegationBasis.current_state,
            observed_at=NOW,
            source_reference=STATE_ENDPOINT,
            operation_time=T0,
            operation_tx_hash="tx-invented",
        )


def test_historical_operation_requires_a_transaction_and_a_block_time() -> None:
    with pytest.raises(ValueError, match="historical"):
        DelegationObservation(
            network_key="tron",
            sponsor_address=SPONSOR,
            receiver_address=D1,
            resource=ResourceType.energy,
            basis=DelegationBasis.historical_operation,
            observed_at=NOW,
            source_reference="tx history",
        )


def test_historical_operation_establishes_a_dated_claim() -> None:
    observation = DelegationObservation(
        network_key="tron",
        sponsor_address=SPONSOR,
        receiver_address=D1,
        resource=ResourceType.energy,
        basis=DelegationBasis.historical_operation,
        observed_at=NOW,
        source_reference="tx history",
        operation_tx_hash="tx-delegate-1",
        operation_time=T0,
        operation_kind="DelegateResourceContract",
    )

    timing = delegation_timing(observation)
    assert timing.established_at == T0
    assert timing.status == "dated"
    assert timing.evidence_reference == "tx-delegate-1"


def test_empty_current_state_is_not_an_absence_of_history() -> None:
    coverage = DelegationCoverage(
        queried_at=NOW,
        endpoint=INDEX_ENDPOINT,
        observations_found=0,
        has_historical_source=False,
    )

    assert coverage.status is CoverageStatus.unknown
    codes = {limitation.code for limitation in coverage.limitations()}
    assert "delegation_history_not_queried" in codes
    assert not coverage.establishes_absence


def test_naive_timestamps_are_rejected() -> None:
    with pytest.raises(ValueError, match="timezone"):
        DelegationObservation(
            network_key="tron",
            sponsor_address=SPONSOR,
            receiver_address=D1,
            resource=ResourceType.energy,
            basis=DelegationBasis.current_state,
            observed_at=dt.datetime(2026, 9, 20, 12, 0),  # noqa: DTZ001 - the point of the test
            source_reference=STATE_ENDPOINT,
        )


# --- Parsers, against the documented response shapes ------------------------


def test_account_index_yields_addresses_and_nothing_else() -> None:
    """The documented response is `account`, `fromAccounts`, `toAccounts`."""
    payload = {"account": D1, "fromAccounts": [SPONSOR], "toAccounts": []}

    observations = parse_account_index(payload, network_key="tron", observed_at=NOW)

    (observation,) = observations
    assert observation.sponsor_address == SPONSOR
    assert observation.receiver_address == D1
    assert observation.basis is DelegationBasis.current_state
    # The endpoint names no resource, no amount and no time. None is invented.
    assert observation.resource is None
    assert observation.frozen_balance_base_units is None
    assert observation.lock_expires_at is None
    assert delegation_timing(observation).status == "unknown"


def test_delegated_resource_v2_splits_the_two_resources() -> None:
    payload = {
        "delegatedResource": [
            {
                "from": SPONSOR,
                "to": D1,
                "frozen_balance_for_energy": 5_000_000_000,
                "expire_time_for_energy": 1_790_000_000_000,
                "frozen_balance_for_bandwidth": 1_000_000,
                "expire_time_for_bandwidth": 0,
            }
        ]
    }

    observations = parse_delegated_resource_v2(payload, network_key="tron", observed_at=NOW)

    by_resource = {o.resource: o for o in observations}
    assert set(by_resource) == {ResourceType.energy, ResourceType.bandwidth}
    energy = by_resource[ResourceType.energy]
    assert energy.frozen_balance_base_units == 5_000_000_000
    assert energy.lock_expires_at == dt.datetime.fromtimestamp(1_790_000_000, tz=dt.UTC)
    # expire_time 0 documents no lock, not an epoch-zero delegation.
    assert by_resource[ResourceType.bandwidth].lock_expires_at is None
    assert all(delegation_timing(o).established_at is None for o in observations)


def test_zero_balance_rows_do_not_become_delegations() -> None:
    payload = {
        "delegatedResource": [
            {
                "from": SPONSOR,
                "to": D1,
                "frozen_balance_for_energy": 0,
                "frozen_balance_for_bandwidth": 0,
            }
        ]
    }

    assert parse_delegated_resource_v2(payload, network_key="tron", observed_at=NOW) == []
