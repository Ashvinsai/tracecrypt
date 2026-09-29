"""Chronological tracer.

These are the day-one correctness tests the plan puts first, plus the D-series
from the acceptance catalog. Every one of them is a way the trace can be
confidently wrong, which is worse than being unresolved.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.adapters.base import (
    AssetRef,
    ChainAdapter,
    Direction,
    NormalizedTransfer,
    ProviderError,
    ProviderErrorClass,
    TransferPage,
)
from app.core.settings import AppEnv, DataMode, Settings
from app.engine.result import EndpointClass
from app.engine.tracer import Budgets, ChronologicalTracer
from app.models.enums import (
    AssertionType,
    AttributionStatus,
    BoundaryReason,
    ConfirmationState,
    EventKind,
    ExecutionStatus,
    ReviewState,
)
from app.services.addresses import CanonicalAddress
from app.services.labels import Anchor, LabelRegistry

T0 = dt.datetime(2026, 8, 1, 10, 0, tzinfo=dt.UTC)
CUTOFF = dt.datetime(2027, 1, 1, tzinfo=dt.UTC)
ASSET = AssetRef("tron", "TQghWzGAMfcTPWzsDGWREVqKbbFMzegaGY", 6, "USDT-SYN")

A, B, C, D, E = "addr-A", "addr-B", "addr-C", "addr-D", "addr-E"
SERVICE = "addr-SERVICE"
CANDIDATE = "addr-CANDIDATE"


def transfer(
    ref: str,
    frm: str,
    to: str,
    amount: int,
    minute: int,
    *,
    index: int = 0,
    height: int | None = None,
    kind: EventKind = EventKind.transfer,
    execution: ExecutionStatus = ExecutionStatus.success,
    confirmation: ConfirmationState = ConfirmationState.confirmed,
    ambiguous: bool = False,
) -> NormalizedTransfer:
    block = height if height is not None else 71_000_000 + minute
    return NormalizedTransfer(
        event_reference=ref,
        tx_hash=ref.split(":")[0],
        event_kind=kind,
        asset=ASSET,
        from_address=frm,
        to_address=to,
        amount_base_units=amount,
        execution_status=execution,
        confirmation_state=confirmation,
        block_height=block,
        block_time=T0 + dt.timedelta(minutes=minute),
        index_in_block=0,
        event_index=None if ambiguous else index,
        ordering_ambiguous=ambiguous,
    )


class ScriptedAdapter(ChainAdapter):
    """A ChainAdapter driven by a list of events, so the engine is really exercised."""

    network_key = "tron"
    supported_data_modes = frozenset({DataMode.SYNTHETIC})

    def __init__(self, events: list[NormalizedTransfer], *, page_size: int = 50) -> None:
        self.events = events
        self.page_size = page_size
        self.calls: list[str] = []
        self.analysis_starts: list[dt.datetime | None] = []
        self.failing: set[str] = set()

    def validate_address(self, value: str) -> CanonicalAddress:
        return CanonicalAddress(value, value, "scripted")

    async def fetch_transfers(
        self,
        *,
        address: str,
        asset: AssetRef,
        direction: Direction,
        analysis_cutoff: dt.datetime,
        analysis_start: dt.datetime | None = None,
        cursor: str | None = None,
        limit: int = 200,
        enrich: bool | None = None,
    ) -> TransferPage:
        self.calls.append(address)
        self.analysis_starts.append(analysis_start)
        if address in self.failing:
            raise ProviderError(ProviderErrorClass.rate_limit, f"scripted failure for {address}")
        matching = [
            e
            for e in self.events
            if e.from_address == address
            and e.asset.token_contract == asset.token_contract
            and (e.block_time is None or e.block_time <= analysis_cutoff)
            and (
                analysis_start is None
                or e.block_time is None
                or e.block_time >= analysis_start
            )
        ]
        start = int(cursor) if cursor else 0
        window = matching[start : start + self.page_size]
        has_more = start + self.page_size < len(matching)
        next_cursor = str(start + self.page_size) if has_more else None
        return TransferPage(events=window, next_cursor=next_cursor)


def settings() -> Settings:
    return Settings(
        app_env=AppEnv.test,
        data_mode=DataMode.SYNTHETIC,
        secret_key="test-secret-key-that-is-long-enough-for-the-validator",
        _env_file=None,
    )


def registry(*anchors: Anchor) -> LabelRegistry:
    return LabelRegistry(list(anchors))


def anchor(
    address: str,
    *,
    assertion_type: AssertionType = AssertionType.service_control,
    review_state: ReviewState = ReviewState.accepted,
    valid_from: dt.datetime | None = None,
    valid_to: dt.datetime | None = None,
) -> Anchor:
    return Anchor(
        network_key="tron",
        address=address,
        entity_name="Northwind Exchange (FICTIONAL)",
        entity_type="exchange",
        assertion_type=assertion_type,
        address_role="deposit",
        review_state=review_state,
        source_reference="fixtures/tron_synthetic_case_alpha.json",
        retrieval_date=T0,
        methodology="Invented for tests.",
        reviewer="test",
        valid_from=valid_from,
        valid_to=valid_to,
        last_verified_at=T0,
        label_set_version="test",
    )


def tracer(adapter: ScriptedAdapter, labels: LabelRegistry, **budget_kwargs) -> ChronologicalTracer:
    defaults = dict(
        max_hops=8, max_events=5000, max_provider_requests=400, wall_clock_seconds=300
    )
    defaults.update(budget_kwargs)
    return ChronologicalTracer(adapter, labels, settings(), budgets=Budgets(**defaults))


# -- day-one test 1 ---------------------------------------------------------


async def test_earlier_outgoing_transfer_cannot_continue_the_path() -> None:
    """An outgoing transfer that happened *before* the receipt cannot carry it."""
    arrival = transfer("tx_in:0", A, B, 100, minute=20)
    events = [
        arrival,
        transfer("tx_early:0", B, C, 100, minute=10),  # before the receipt
        transfer("tx_late:0", B, D, 100, minute=30),  # after the receipt
    ]
    adapter = ScriptedAdapter(events)
    result = await tracer(adapter, registry()).trace(
        seed_address=A, asset=ASSET, analysis_cutoff=CUTOFF, seed_event=arrival
    )
    followed = {t.event_reference for t in result.observed_transfers}
    assert "tx_late:0" in followed
    assert "tx_early:0" not in followed
    assert adapter.analysis_starts == [arrival.block_time, (T0 + dt.timedelta(minutes=30))]
    assert D in {b.address for b in result.branch_endings}
    assert C not in {b.address for b in result.branch_endings}


async def test_arrival_timestamp_is_inclusive_query_bound_and_same_time_stays_ambiguous() -> None:
    arrival = transfer("tx_in:0", A, B, 100, minute=20)
    same_time = transfer("tx_same_time:0", B, C, 100, minute=20, ambiguous=True)
    later = transfer("tx_later:0", B, D, 100, minute=30)
    adapter = ScriptedAdapter([arrival, same_time, later])

    result = await tracer(adapter, registry()).trace(
        seed_address=A, asset=ASSET, analysis_cutoff=CUTOFF, seed_event=arrival
    )

    assert adapter.analysis_starts[0] == arrival.block_time
    assert "tx_same_time:0" in {
        limitation.event_reference for limitation in result.limitations
    }
    assert "tx_later:0" in {event.event_reference for event in result.observed_transfers}
    assert C not in {ending.address for ending in result.branch_endings}
    assert D in {ending.address for ending in result.branch_endings}


# -- day-one test 2 ---------------------------------------------------------


async def test_later_receipt_at_a_seen_address_is_not_discarded() -> None:
    """Funds return to an address. A global visited set would lose the second visit."""
    arrival = transfer("tx_seed:0", A, B, 100, minute=10)
    events = [
        arrival,
        transfer("tx_b_to_c:0", B, C, 100, minute=20),
        transfer("tx_c_back_to_b:0", C, B, 100, minute=30),  # returns to B
        transfer("tx_b_out_again:0", B, D, 100, minute=40),  # only valid after the return
    ]
    result = await tracer(ScriptedAdapter(events), registry()).trace(
        seed_address=A, asset=ASSET, analysis_cutoff=CUTOFF, seed_event=arrival
    )
    followed = {t.event_reference for t in result.observed_transfers}
    assert "tx_c_back_to_b:0" in followed
    assert "tx_b_out_again:0" in followed, "the second visit to B must still be explored"
    assert D in {b.address for b in result.branch_endings}


async def test_a_cycle_terminates_without_repeating_an_event() -> None:
    """D04: a loop must end, and it must end by exhausting events, not by luck."""
    arrival = transfer("tx_seed:0", A, B, 50, minute=1)
    events = [
        arrival,
        transfer("tx_b_c:0", B, C, 50, minute=2),
        transfer("tx_c_b:0", C, B, 50, minute=3),
    ]
    result = await tracer(ScriptedAdapter(events), registry()).trace(
        seed_address=A, asset=ASSET, analysis_cutoff=CUTOFF, seed_event=arrival
    )
    refs = [t.event_reference for t in result.observed_transfers]
    assert len(refs) == len(set(refs)), "no event may be walked twice on one branch"
    assert result.finished_at is not None


# -- day-one tests 6, 8, 9 --------------------------------------------------


async def test_approvals_failures_removals_and_zero_value_do_not_extend_a_path() -> None:
    """Day-one test 6: none of these moved value, so none of them continues a path."""
    arrival = transfer("tx_seed:0", A, B, 100, minute=10)
    events = [
        arrival,
        transfer("tx_approval:0", B, C, 0, minute=20, kind=EventKind.approval),
        transfer("tx_failed:0", B, C, 100, minute=21, execution=ExecutionStatus.failed),
        transfer("tx_reverted:0", B, C, 100, minute=22, execution=ExecutionStatus.reverted),
        transfer(
            "tx_removed:0", B, C, 100, minute=23, confirmation=ConfirmationState.removed
        ),
        transfer("tx_zero:0", B, C, 0, minute=24),
    ]
    result = await tracer(ScriptedAdapter(events), registry()).trace(
        seed_address=A, asset=ASSET, analysis_cutoff=CUTOFF, seed_event=arrival
    )
    assert result.observed_transfers == []
    endings = result.branch_endings
    assert len(endings) == 1
    assert endings[0].boundary_reason is BoundaryReason.no_outgoing_activity


async def test_mixed_balance_does_not_become_victim_value() -> None:
    """Day-one test 8: 900 pre-existing + 100 victim in, 500 out, is ambiguous."""
    arrival = transfer("tx_victim_in:0", A, B, 100_000_000, minute=15)
    events = [
        transfer("tx_prefund:0", E, B, 900_000_000, minute=5),
        arrival,
        transfer("tx_mixed_out:0", B, SERVICE, 500_000_000, minute=25),
    ]
    result = await tracer(
        ScriptedAdapter(events), registry(anchor(SERVICE))
    ).trace(seed_address=A, asset=ASSET, analysis_cutoff=CUTOFF, seed_event=arrival)

    out = next(t for t in result.observed_transfers if t.event_reference == "tx_mixed_out:0")
    assert out.amount_base_units == 500_000_000

    payload = result.to_json()
    ending = next(
        b for b in payload["branch_endings"] if b["endpoint_class"] == "known_service"
    )
    # The observed transfer is 500. The case-associated amount is not.
    assert ending["observed_amount_base_units"] == "500000000"
    assert ending["case_amount_basis"] == "allocation_unknown"
    assert all(b["case_amount_basis"] == "allocation_unknown" for b in payload["branch_endings"])


async def test_reconverging_branches_are_both_preserved_and_not_summed() -> None:
    """D03: fan-out into one address keeps both branches and duplicates no value."""
    arrival = transfer("tx_seed:0", A, B, 100, minute=5)
    events = [
        arrival,
        transfer("tx_fan_a:0", B, C, 60, minute=10),
        transfer("tx_fan_b:0", B, D, 40, minute=11),
        transfer("tx_recon_a:0", C, SERVICE, 60, minute=20),
        transfer("tx_recon_b:0", D, SERVICE, 40, minute=21),
    ]
    result = await tracer(
        ScriptedAdapter(events), registry(anchor(SERVICE))
    ).trace(seed_address=A, asset=ASSET, analysis_cutoff=CUTOFF, seed_event=arrival)

    at_service = [b for b in result.branch_endings if b.address == SERVICE]
    assert len(at_service) == 2, "both arriving branches must be preserved separately"
    assert {tuple(b.branch_path) for b in at_service} == {
        ("tx_seed:0", "tx_fan_a:0", "tx_recon_a:0"),
        ("tx_seed:0", "tx_fan_b:0", "tx_recon_b:0"),
    }
    assert sorted(b.observed_amount_base_units or 0 for b in at_service) == [40, 60]
    assert all(
        b.to_json()["case_amount_basis"] == "allocation_unknown" for b in at_service
    )


async def test_unknown_onward_activity_creates_no_invented_edge() -> None:
    """Day-one test 9: a dead end is a recorded boundary, never a guessed continuation."""
    arrival = transfer("tx_seed:0", A, B, 100, minute=10)
    result = await tracer(ScriptedAdapter([arrival]), registry()).trace(
        seed_address=A, asset=ASSET, analysis_cutoff=CUTOFF, seed_event=arrival
    )
    assert result.observed_transfers == []
    ending = result.branch_endings[0]
    assert ending.endpoint_class is EndpointClass.unresolved
    assert ending.boundary_reason is BoundaryReason.no_outgoing_activity
    assert ending.label is None
    assert "no continuation is assumed" in (ending.note or "")


# -- label boundaries -------------------------------------------------------


async def test_trace_stops_at_the_first_accepted_service_boundary() -> None:
    """D05."""
    arrival = transfer("tx_seed:0", A, B, 100, minute=5)
    events = [
        arrival,
        transfer("tx_to_service:0", B, SERVICE, 100, minute=10),
        transfer("tx_service_onward:0", SERVICE, E, 100, minute=20),  # must not be followed
    ]
    adapter = ScriptedAdapter(events)
    result = await tracer(adapter, registry(anchor(SERVICE))).trace(
        seed_address=A, asset=ASSET, analysis_cutoff=CUTOFF, seed_event=arrival
    )
    assert "tx_service_onward:0" not in {t.event_reference for t in result.observed_transfers}
    assert SERVICE not in adapter.calls, "a terminated branch must not be queried onward"
    destination = result.supported_destinations[0]
    assert destination.attribution_status is AttributionStatus.supported
    assert destination.label is not None
    assert destination.label.source_reference


async def test_a_candidate_does_not_terminate_a_branch() -> None:
    """D06: a deposit candidate is shown, and the walk continues past it."""
    arrival = transfer("tx_seed:0", A, B, 100, minute=5)
    events = [
        arrival,
        transfer("tx_to_candidate:0", B, CANDIDATE, 100, minute=10),
        transfer("tx_candidate_onward:0", CANDIDATE, SERVICE, 100, minute=20),
    ]
    labels = registry(
        anchor(CANDIDATE, assertion_type=AssertionType.deposit_candidate),
        anchor(SERVICE),
    )
    result = await tracer(ScriptedAdapter(events), labels).trace(
        seed_address=A, asset=ASSET, analysis_cutoff=CUTOFF, seed_event=arrival
    )
    assert "tx_candidate_onward:0" in {t.event_reference for t in result.observed_transfers}
    candidates = result.candidate_destinations
    assert len(candidates) == 1
    assert candidates[0].attribution_status is AttributionStatus.candidate
    assert result.supported_destinations[0].address == SERVICE


async def test_an_unreviewed_label_does_not_terminate_a_branch() -> None:
    """A label without review is not a custody boundary."""
    arrival = transfer("tx_seed:0", A, B, 100, minute=5)
    events = [arrival, transfer("tx_to_service:0", B, SERVICE, 100, minute=10)]
    labels = registry(anchor(SERVICE, review_state=ReviewState.unreviewed))
    result = await tracer(ScriptedAdapter(events), labels).trace(
        seed_address=A, asset=ASSET, analysis_cutoff=CUTOFF, seed_event=arrival
    )
    assert result.supported_destinations == []
    assert result.branch_endings[-1].endpoint_class is EndpointClass.unresolved


async def test_an_expired_label_does_not_terminate_a_branch() -> None:
    """Validity intervals are enforced against the arrival time, not today."""
    arrival = transfer("tx_seed:0", A, B, 100, minute=5)
    events = [arrival, transfer("tx_to_service:0", B, SERVICE, 100, minute=10)]
    labels = registry(
        anchor(SERVICE, valid_from=T0 - dt.timedelta(days=60), valid_to=T0 - dt.timedelta(days=1))
    )
    result = await tracer(ScriptedAdapter(events), labels).trace(
        seed_address=A, asset=ASSET, analysis_cutoff=CUTOFF, seed_event=arrival
    )
    assert result.supported_destinations == []


# -- budgets and failures ---------------------------------------------------


async def test_hop_limit_emits_a_boundary_not_a_silent_stop() -> None:
    """D07."""
    arrival = transfer("tx_seed:0", A, B, 100, minute=1)
    events = [arrival]
    chain = [B, C, D, E]
    for i in range(len(chain) - 1):
        events.append(transfer(f"tx_hop{i}:0", chain[i], chain[i + 1], 100, minute=2 + i))
    result = await tracer(ScriptedAdapter(events), registry(), max_hops=2).trace(
        seed_address=A, asset=ASSET, analysis_cutoff=CUTOFF, seed_event=arrival
    )
    boundary = next(b for b in result.branch_endings if b.boundary_reason is not None)
    assert boundary.boundary_reason is BoundaryReason.hop_limit
    assert result.coverage_status.value == "partial"
    assert result.budget_use.hop_limit == 2


async def test_provider_failure_is_a_boundary_not_an_empty_result() -> None:
    """Day-one test 11, inside the engine rather than the adapter."""
    arrival = transfer("tx_seed:0", A, B, 100, minute=5)
    adapter = ScriptedAdapter([arrival])
    adapter.failing.add(B)
    result = await tracer(adapter, registry()).trace(
        seed_address=A, asset=ASSET, analysis_cutoff=CUTOFF, seed_event=arrival
    )
    assert result.coverage_status.value == "failed"
    assert result.branch_endings[0].boundary_reason is BoundaryReason.provider_failure
    assert any(x.code == "provider_rate_limit" for x in result.limitations)


async def test_same_block_without_ordering_is_recorded_as_unresolved() -> None:
    """D08: no ordering evidence means the ordering is not established."""
    arrival = transfer("tx_in:0", A, B, 100, minute=20, height=71_000_020)
    ambiguous = transfer(
        "tx_out:unindexed", B, C, 100, minute=20, height=71_000_020, ambiguous=True
    )
    result = await tracer(ScriptedAdapter([arrival, ambiguous]), registry()).trace(
        seed_address=A, asset=ASSET, analysis_cutoff=CUTOFF, seed_event=arrival
    )
    assert "tx_out:unindexed" not in {t.event_reference for t in result.observed_transfers}
    assert any(x.code == "ambiguous_ordering" for x in result.limitations)
    assert result.coverage_status.value == "partial"


async def test_pagination_is_consumed_without_duplicating_events() -> None:
    """Day-one test 7, through the engine's own page walk."""
    arrival = transfer("tx_seed:0", A, B, 100, minute=1)
    events = [arrival] + [
        transfer(f"tx_out{i}:0", B, f"sink-{i}", 10, minute=10 + i) for i in range(7)
    ]
    result = await tracer(ScriptedAdapter(events, page_size=2), registry()).trace(
        seed_address=A, asset=ASSET, analysis_cutoff=CUTOFF, seed_event=arrival
    )
    refs = [t.event_reference for t in result.observed_transfers]
    assert len(refs) == 7
    assert len(refs) == len(set(refs))


async def test_live_adapter_refuses_to_run_under_synthetic_settings() -> None:
    """D009, enforced before a single request is made."""
    from app.adapters.tron import TronGridAdapter

    engine = ChronologicalTracer(
        TronGridAdapter("https://api.trongrid.io"), registry(), settings()
    )
    with pytest.raises(ProviderError) as caught:
        await engine.trace(seed_address="addr", asset=ASSET, analysis_cutoff=CUTOFF)
    assert caught.value.error_class is ProviderErrorClass.unsupported


# -- regression: reconvergence onto a shared suffix --------------------------


async def test_shared_suffix_after_reconvergence_is_not_walked_twice() -> None:
    """Day-one test 8, the half the first reconvergence test missed.

    Two branches meet at one address and then follow the *same* onward event.
    From that event on they are one path. Recording it once per branch would
    show 2x95 arriving at the service when the chain shows 95.
    """
    arrival = transfer("tx_seed:0", A, B, 100, minute=5)
    events = [
        arrival,
        transfer("tx_fan_a:0", B, C, 60, minute=10),
        transfer("tx_fan_b:0", B, D, 40, minute=11),
        # Both branches reconverge on E ...
        transfer("tx_recon_a:0", C, E, 60, minute=20),
        transfer("tx_recon_b:0", D, E, 40, minute=21),
        # ... and share a single onward transfer from there.
        transfer("tx_shared_out:0", E, SERVICE, 95, minute=30),
    ]
    result = await tracer(
        ScriptedAdapter(events), registry(anchor(SERVICE))
    ).trace(seed_address=A, asset=ASSET, analysis_cutoff=CUTOFF, seed_event=arrival)

    refs = [t.event_reference for t in result.observed_transfers]
    assert refs.count("tx_shared_out:0") == 1, "one chain event is one observed transfer"
    assert len(refs) == len(set(refs))

    at_service = result.supported_destinations
    assert len(at_service) == 1, "a shared suffix is one arrival, not one per upstream branch"
    assert at_service[0].observed_amount_base_units == 95

    # The reconvergence itself is still preserved: two distinct events reached E.
    arrivals_at_e = {
        t.event_reference for t in result.observed_transfers if t.to_address == E
    }
    assert arrivals_at_e == {"tx_recon_a:0", "tx_recon_b:0"}


async def test_a_merged_branch_is_not_reported_as_a_dead_end() -> None:
    """A branch that reconverges did not run out of activity, and must not say so.

    "No further observed transfer from this address" would be a false statement
    about the chain; the onward transfer exists and is recorded on the branch
    that walked it.
    """
    arrival = transfer("tx_seed:0", A, B, 100, minute=5)
    events = [
        arrival,
        transfer("tx_fan_a:0", B, C, 60, minute=10),
        transfer("tx_fan_b:0", B, D, 40, minute=11),
        transfer("tx_recon_a:0", C, E, 60, minute=20),
        transfer("tx_recon_b:0", D, E, 40, minute=21),
        transfer("tx_shared_out:0", E, SERVICE, 95, minute=30),
    ]
    result = await tracer(
        ScriptedAdapter(events), registry(anchor(SERVICE))
    ).trace(seed_address=A, asset=ASSET, analysis_cutoff=CUTOFF, seed_event=arrival)

    merged = [b for b in result.branch_endings if b.address == E]
    assert len(merged) == 1
    assert merged[0].boundary_reason is not BoundaryReason.no_outgoing_activity
    assert "reconverg" in (merged[0].note or "").lower()
