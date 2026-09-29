from __future__ import annotations

import datetime as dt

from app.models.enums import AssertionType, ReviewState
from app.services.labels import Anchor
from app.services.vasp_neighborhood import (
    NeighborhoodCoverage,
    NeighborhoodObservation,
    generate_neighborhood,
)

SNAPSHOT = dt.datetime(2026, 8, 10, 15, 59, 54, tzinfo=dt.UTC)
ANCHOR = "TYfxtkCooUX7rzjRqBGLan9XkCxqkrCRir"
CUSTOMER = "TCustomerExampleAddress"
TOKEN = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"


def _anchor() -> Anchor:
    return Anchor(
        network_key="tron",
        address=ANCHOR,
        entity_name="OKX",
        entity_type="exchange",
        assertion_type=AssertionType.service_control,
        address_role="unknown",
        review_state=ReviewState.accepted,
        source_reference="okx:por-snapshot",
        retrieval_date=SNAPSHOT,
        methodology="Accepted snapshot-scoped service-control evidence.",
        reviewer="prepared-for-review",
        valid_from=SNAPSHOT,
        valid_to=SNAPSHOT,
        last_verified_at=SNAPSHOT,
        label_set_version="anchor-set-test",
        source_hash="anchor-hash",
    )


def _observation(
    *,
    event_reference: str,
    source: str,
    target: str,
    time: dt.datetime = SNAPSHOT,
    amount: int = 100_000_000,
    token: str = TOKEN,
    status: str = "success",
    role: str = "outgoing",
) -> NeighborhoodObservation:
    return NeighborhoodObservation(
        network="tron",
        token_contract=token,
        event_reference=event_reference,
        tx_hash=event_reference.split(":")[1],
        event_index=0,
        source_address=source,
        target_address=target,
        amount_base_units=amount,
        block_time=time,
        execution_status=status,
        confirmation_state="confirmed",
        ordering_ambiguous=False,
        direction=role,
    )


def test_one_off_customer_interaction_is_weak_deposit_candidate_not_service_control() -> None:
    observation = _observation(
        event_reference="tron:one-off:0",
        source=CUSTOMER,
        target=ANCHOR,
    )

    result = generate_neighborhood(
        anchor=_anchor(),
        network="tron",
        token_contract=TOKEN,
        observations=[observation],
        coverage=NeighborhoodCoverage(complete=True, window_start=SNAPSHOT, window_end=SNAPSHOT),
    )

    (candidate,) = result.candidates
    assert candidate.relationship_type == "deposit_candidate"
    assert candidate.matched_rules == ()
    assert candidate.review_status == "unreviewed"
    assert candidate.evidence_references == ("tron:one-off:0",)


def test_events_outside_anchor_snapshot_cannot_match_anchor_relationship_rule() -> None:
    before = SNAPSHOT - dt.timedelta(seconds=1)
    after = SNAPSHOT + dt.timedelta(seconds=1)
    observations = [
        _observation(
            event_reference="tron:before:0",
            source=CUSTOMER,
            target=ANCHOR,
            time=before,
        ),
        _observation(
            event_reference="tron:inside:0",
            source=CUSTOMER,
            target=ANCHOR,
            time=SNAPSHOT,
        ),
        _observation(
            event_reference="tron:after:0",
            source=CUSTOMER,
            target=ANCHOR,
            time=after,
        ),
    ]

    result = generate_neighborhood(
        anchor=_anchor(),
        network="tron",
        token_contract=TOKEN,
        observations=observations,
        coverage=NeighborhoodCoverage(complete=True, window_start=before, window_end=after),
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].relationship_type == "deposit_candidate"
    assert result.candidates[0].evidence_references == ("tron:inside:0",)
    assert result.excluded_observation_count == 0
    assert {row["event_reference"] for row in result.address_only_context} == {
        "tron:before:0",
        "tron:after:0",
    }
    assert "only as address-level context" in " ".join(result.limitations)


def test_invalid_asset_network_execution_and_order_rows_do_not_support_candidates() -> None:
    observations = [
        _observation(event_reference="tron:valid-1:0", source=CUSTOMER, target=ANCHOR),
        _observation(event_reference="tron:valid-2:0", source=CUSTOMER, target=ANCHOR),
        _observation(event_reference="tron:other-network:0", source=CUSTOMER, target=ANCHOR),
        _observation(
            event_reference="tron:other-asset:0", source=CUSTOMER, target=ANCHOR, token="TOTHER"
        ),
        _observation(
            event_reference="tron:failed:0", source=CUSTOMER, target=ANCHOR, status="failed"
        ),
        _observation(
            event_reference="tron:zero:0", source=CUSTOMER, target=ANCHOR, amount=0
        ),
        _observation(
            event_reference="tron:ambiguous:0",
            source=CUSTOMER,
            target=ANCHOR,
        ),
        _observation(
            event_reference="tron:removed:0", source=CUSTOMER, target=ANCHOR
        ),
    ]
    observations[2] = NeighborhoodObservation(
        **{**observations[2].__dict__, "network": "ethereum"}
    )
    observations[6] = NeighborhoodObservation(
        **{**observations[6].__dict__, "ordering_ambiguous": True}
    )
    observations[7] = NeighborhoodObservation(
        **{**observations[7].__dict__, "confirmation_state": "removed"}
    )
    observations.append(
        NeighborhoodObservation(
            **{
                **observations[0].__dict__,
                "event_reference": "tron:unindexed:0",
                "event_index": None,
            }
        )
    )

    result = generate_neighborhood(
        anchor=_anchor(),
        network="tron",
        token_contract=TOKEN,
        observations=observations,
        coverage=NeighborhoodCoverage(complete=True, window_start=SNAPSHOT, window_end=SNAPSHOT),
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].relationship_type == "service_neighbor_candidate"
    assert result.candidates[0].evidence_references == ("tron:valid-1:0", "tron:valid-2:0")
    assert result.excluded_observation_count == 7
    assert all(candidate.address != ANCHOR for candidate in result.candidates)


def test_anchor_must_be_accepted_service_control(tmp_path) -> None:
    import pytest

    invalid = Anchor(
        **{
            **_anchor().__dict__,
            "assertion_type": AssertionType.deposit_candidate,
        }
    )
    with pytest.raises(ValueError, match="accepted service_control"):
        generate_neighborhood(
            anchor=invalid,
            network="tron",
            token_contract=TOKEN,
            observations=[],
            coverage=NeighborhoodCoverage(
                complete=True, window_start=SNAPSHOT, window_end=SNAPSHOT
            ),
        )


def test_duplicate_observation_of_same_event_does_not_inflate_repeated_count() -> None:
    transfer = _observation(
        event_reference="tron:single-deposit:0", source=CUSTOMER, target=ANCHOR
    )
    result = generate_neighborhood(
        anchor=_anchor(),
        network="tron",
        token_contract=TOKEN,
        observations=[transfer, transfer],
        coverage=NeighborhoodCoverage(
            complete=True, window_start=SNAPSHOT, window_end=SNAPSHOT
        ),
    )

    (candidate,) = result.candidates
    assert candidate.relationship_type == "deposit_candidate"
    assert candidate.features["repeated_transfer_count"] == 1
    assert candidate.evidence_references == ("tron:single-deposit:0",)


def test_incomplete_coverage_downgrades_collection_rule_to_unresolved() -> None:
    observations = [
        _observation(
            event_reference=f"tron:incomplete-in-{index}:0",
            source=f"TUpstream{index}",
            target=CUSTOMER,
            time=SNAPSHOT - dt.timedelta(minutes=10 - index),
            role="incoming",
        )
        for index in range(3)
    ] + [
        _observation(
            event_reference=f"tron:incomplete-out-{index}:0",
            source=CUSTOMER,
            target=ANCHOR,
            role="outgoing",
        )
        for index in range(2)
    ]

    result = generate_neighborhood(
        anchor=_anchor(),
        network="tron",
        token_contract=TOKEN,
        observations=observations,
        coverage=NeighborhoodCoverage(
            complete=False,
            window_start=SNAPSHOT - dt.timedelta(minutes=10),
            window_end=SNAPSHOT,
            limitations=("request budget exhausted",),
        ),
    )

    (candidate,) = result.candidates
    assert candidate.relationship_type == "unresolved_candidate_relationship"
    assert candidate.matched_rules == ()
    assert candidate.coverage_complete is False
    assert "request budget exhausted" in candidate.limitations
    assert "incomplete" in " ".join(result.limitations).lower()


def test_distinct_sender_aggregation_is_collection_candidate_not_service_control() -> None:
    observations = [
        _observation(
            event_reference=f"tron:in-{index}:0",
            source=f"TUpstream{index}",
            target=CUSTOMER,
            time=SNAPSHOT - dt.timedelta(minutes=10 - index),
            role="incoming",
        )
        for index in range(3)
    ] + [
        _observation(
            event_reference=f"tron:out-{index}:0",
            source=CUSTOMER,
            target=ANCHOR,
            time=SNAPSHOT,
            role="outgoing",
        )
        for index in range(2)
    ]

    result = generate_neighborhood(
        anchor=_anchor(),
        network="tron",
        token_contract=TOKEN,
        observations=observations,
        coverage=NeighborhoodCoverage(
            complete=True,
            window_start=SNAPSHOT - dt.timedelta(minutes=10),
            window_end=SNAPSHOT,
        ),
    )

    (candidate,) = result.candidates
    assert candidate.relationship_type == "collection_candidate"
    assert candidate.features["distinct_incoming_senders"] == 3
    assert candidate.features["repeated_transfer_count"] == 2
    assert set(candidate.evidence_references) == {
        "tron:in-0:0",
        "tron:in-1:0",
        "tron:in-2:0",
        "tron:out-0:0",
        "tron:out-1:0",
    }
    assert "does not establish service ownership" in candidate.not_service_control_reason


def test_out_of_scope_repeated_interactions_never_form_vasp_candidate() -> None:
    before = SNAPSHOT - dt.timedelta(days=1)
    window_end = SNAPSHOT + dt.timedelta(days=1)
    observations = [
        _observation(
            event_reference=f"tron:outside-{index}:0",
            source=CUSTOMER,
            target=ANCHOR,
            time=before + dt.timedelta(minutes=index),
        )
        for index in range(3)
    ]

    result = generate_neighborhood(
        anchor=_anchor(),
        network="tron",
        token_contract=TOKEN,
        observations=observations,
        coverage=NeighborhoodCoverage(
            complete=True, window_start=before, window_end=window_end
        ),
    )

    assert result.candidates == ()
    assert len(result.address_only_context) == 3
    assert all(
        row["reason"] == "outside the reviewed service-control claim's validity interval"
        for row in result.address_only_context
    )


def test_candidate_report_contains_no_service_control_claim_or_anchor_promotion() -> None:
    observation = _observation(
        event_reference="tron:single-event:0", source=CUSTOMER, target=ANCHOR
    )
    result = generate_neighborhood(
        anchor=_anchor(),
        network="tron",
        token_contract=TOKEN,
        observations=[observation],
        coverage=NeighborhoodCoverage(
            complete=True, window_start=SNAPSHOT, window_end=SNAPSHOT
        ),
    )
    payload = result.to_json()

    assert payload["anchor"]["assertion_type"] == "service_control"
    assert payload["anchor"]["review_state"] == "accepted"
    assert payload["candidates"][0]["relationship_type"] == "deposit_candidate"
    assert payload["candidates"][0]["review_status"] == "unreviewed"
    assert "service_control" not in {
        candidate["relationship_type"] for candidate in payload["candidates"]
    }


def test_empty_candidate_report_is_explicit_and_deterministic() -> None:
    coverage = NeighborhoodCoverage(
        complete=True,
        window_start=SNAPSHOT,
        window_end=SNAPSHOT,
        requests_used=1,
        max_requests=10,
        page_limit=2,
        pages_used=1,
        address_limit=20,
        addresses_examined=3,
    )
    kwargs = {
        "anchor": _anchor(),
        "network": "tron",
        "token_contract": TOKEN,
        "observations": [],
        "coverage": coverage,
    }

    first = generate_neighborhood(**kwargs).to_json()
    second = generate_neighborhood(**kwargs).to_json()

    assert first == second
    assert first["candidate_count"] == 0
    assert first["candidates"] == []
    assert first["coverage"]["requests_used"] == 1
    assert first["anchor"]["valid_to"] == SNAPSHOT.isoformat()


def test_repeated_customer_deposits_are_only_unreviewed_neighbor_candidates() -> None:
    observations = [
        _observation(
            event_reference=f"tron:customer-{index}:0",
            source=CUSTOMER,
            target=ANCHOR,
            time=SNAPSHOT,
        )
        for index in range(3)
    ]

    result = generate_neighborhood(
        anchor=_anchor(),
        network="tron",
        token_contract=TOKEN,
        observations=observations,
        coverage=NeighborhoodCoverage(complete=True, window_start=SNAPSHOT, window_end=SNAPSHOT),
    )

    (candidate,) = result.candidates
    assert candidate.address == CUSTOMER
    assert candidate.relationship_type == "service_neighbor_candidate"
    assert candidate.review_status == "unreviewed"
    assert candidate.human_reviewed is False
    assert candidate.evidence_references == tuple(
        f"tron:customer-{index}:0" for index in range(3)
    )
    assert candidate.matched_rules == ("repeated_outgoing_to_anchor",)
    assert candidate.features["repeated_transfer_count"] == 3
    assert "does not establish service ownership" in candidate.not_service_control_reason
    assert all(candidate.relationship_type != "service_control" for candidate in result.candidates)
