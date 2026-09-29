"""Bounded chronological forward tracing.

The model is a walk over *states*, not over addresses (D010). A state is
"this asset, at this address, having arrived by this event, at this position in
the chain, along this branch". That distinction is the whole point:

- A global visited-address set would discard a later receipt at an address the
  walk has already seen. Funds really do return to an address. Day-one test 2.
- A lifetime shortest path would let a receipt explain an outgoing transfer that
  happened before it. Later receipts cannot explain earlier sends. Day-one test 1.

Nothing here invents an edge. An asset change, a bridge, a privacy mechanism or
an opaque contract simply produces no further observed transfers of the traced
asset, and the branch ends with a recorded reason. Day-one test 9.
"""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass, field

from app.adapters.base import (
    AssetRef,
    ChainAdapter,
    Direction,
    NormalizedTransfer,
    ProviderError,
    ProviderErrorClass,
)
from app.core.settings import Settings
from app.engine.result import (
    BranchEnding,
    BudgetUse,
    EndpointClass,
    Limitation,
    ObservedTransfer,
    TraceResult,
)
from app.models.enums import (
    AttributionStatus,
    BoundaryReason,
    CaseFlowLinkage,
    ConfirmationState,
    CoverageStatus,
    EventKind,
    ExecutionStatus,
)
from app.services.labels import LabelRegistry

#: Sorts before every real chain_sequence, so a seed with no known position
#: does not accidentally exclude the transfers that follow it.
BEFORE_EVERYTHING = ""


@dataclass(frozen=True)
class Position:
    """A point in chain order: block time first, then intra-block sequence.

    ``sequence`` is empty when the source could not supply ordering. Comparisons
    involving an empty sequence within the same block are treated as unresolved
    by the caller rather than silently decided here.
    """

    block_time: dt.datetime | None
    sequence: str

    def strictly_after(self, other: Position) -> bool:
        if self.block_time is not None and other.block_time is not None:
            if self.block_time > other.block_time:
                return True
            if self.block_time < other.block_time:
                return False
        return self.sequence > other.sequence

    def same_moment_as(self, other: Position) -> bool:
        return self.block_time == other.block_time


@dataclass
class TraceState:
    """One position in the walk (D010)."""

    address: str
    asset: AssetRef
    arrival: Position
    arrival_event_reference: str | None
    hop_depth: int
    #: Event references from the seed to here. Makes branches distinguishable and
    #: bounds cycles per branch rather than globally.
    branch_path: tuple[str, ...] = ()
    observed_amount_base_units: int | None = None

    @property
    def consumed(self) -> frozenset[str]:
        return frozenset(self.branch_path)


@dataclass
class Budgets:
    max_hops: int
    max_events: int
    max_provider_requests: int
    wall_clock_seconds: int

    @classmethod
    def from_settings(cls, settings: Settings) -> Budgets:
        return cls(
            max_hops=settings.budget_max_hops,
            max_events=settings.budget_max_events,
            max_provider_requests=settings.budget_max_provider_requests,
            wall_clock_seconds=settings.budget_wall_clock_seconds,
        )


@dataclass
class _RunCounters:
    events_examined: int = 0
    provider_requests: int = 0
    max_hop_reached: int = 0
    started_monotonic: float = field(default_factory=time.monotonic)
    #: Events already recorded as observed edges. One chain event is one edge,
    #: however many branches pass through it.
    recorded_events: set[str] = field(default_factory=set)
    #: Events already expanded into a state. Two branches that reconverge and
    #: then follow the same transfer are one path from that transfer onward;
    #: walking it once per branch would duplicate value across branches.
    expanded_arrivals: set[str] = field(default_factory=set)

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started_monotonic


class ChronologicalTracer:
    """Forward exploration bounded by hops, events, provider calls, and time."""

    def __init__(
        self,
        adapter: ChainAdapter,
        labels: LabelRegistry,
        settings: Settings,
        *,
        budgets: Budgets | None = None,
        page_limit: int = 200,
    ) -> None:
        self.adapter = adapter
        self.labels = labels
        self.settings = settings
        self.budgets = budgets or Budgets.from_settings(settings)
        self.page_limit = page_limit

    async def trace(
        self,
        *,
        seed_address: str,
        asset: AssetRef,
        analysis_cutoff: dt.datetime,
        analysis_start: dt.datetime | None = None,
        seed_event: NormalizedTransfer | None = None,
        case_flow_linkage: CaseFlowLinkage = CaseFlowLinkage.established,
    ) -> TraceResult:
        self.adapter.assert_mode_allowed(self.settings.data_mode)
        if analysis_cutoff.tzinfo is None or (analysis_start is not None and analysis_start.tzinfo is None):
            raise ValueError("analysis window must be timezone-aware")
        if analysis_start is not None and analysis_start > analysis_cutoff:
            raise ValueError("analysis_start must not exceed cutoff")

        started_at = dt.datetime.now(dt.UTC)
        counters = _RunCounters()
        result = TraceResult(
            seed_address=self.adapter.validate_address(seed_address).canonical,
            seed_event_reference=seed_event.event_reference if seed_event else None,
            network_key=self.adapter.network_key,
            asset_contract=asset.token_contract,
            asset_symbol=asset.display_symbol,
            asset_decimals=asset.decimals,
            data_mode=self.settings.data_mode,
            analysis_cutoff=analysis_cutoff,
            analysis_start=analysis_start,
            started_at=started_at,
            finished_at=None,
            engine_version=self.settings.engine_version,
            label_set_version=self.settings.label_set_version,
            coverage_status=CoverageStatus.complete_within_scope,
            case_flow_linkage=case_flow_linkage,
            label_snapshot=self.labels.snapshot(),
        )

        if seed_event is not None and not self._is_spendable(seed_event):
            # A rejected seed must not silently become an address-discovery
            # trace from its alleged recipient.
            result.case_flow_linkage = CaseFlowLinkage.not_established
            result.coverage_status = CoverageStatus.partial
            result.limitations.append(Limitation(
                code="seed_not_verified",
                message=("The selected seed is not a successful, confirmed, non-zero "
                         "transfer. No fund-flow continuation was attempted."),
                address=result.seed_address,
                event_reference=seed_event.event_reference,
            ))
            result.finished_at = dt.datetime.now(dt.UTC)
            return result

        if seed_event is not None and self._is_spendable(seed_event):
            # Record the case-link transfer itself. The forward walk starts at
            # its recipient (hop 0), so without this a direct transfer to a
            # boundary would appear as a path with no transfer in it at all.
            result.seed_transfer = ObservedTransfer(
                event_reference=seed_event.event_reference,
                tx_hash=seed_event.tx_hash,
                from_address=seed_event.from_address,
                to_address=seed_event.to_address,
                amount_base_units=seed_event.amount_base_units,
                asset_contract=seed_event.asset.token_contract,
                asset_decimals=seed_event.asset.decimals,
                asset_symbol=seed_event.asset.display_symbol,
                block_time=seed_event.block_time,
                chain_sequence=seed_event.chain_sequence,
                ordering_ambiguous=seed_event.ordering_ambiguous,
                execution_status=seed_event.execution_status.value,
                confirmation_state=seed_event.confirmation_state.value,
                hop_depth=0,
            )

        start_position = (
            Position(seed_event.block_time, seed_event.chain_sequence or BEFORE_EVERYTHING)
            if seed_event
            else Position(analysis_start, BEFORE_EVERYTHING)
        )
        start_address = (
            seed_event.to_address or result.seed_address if seed_event else result.seed_address
        )

        frontier: list[TraceState] = [
            TraceState(
                address=self.adapter.validate_address(start_address).canonical,
                asset=asset,
                arrival=start_position,
                arrival_event_reference=(
                    seed_event.event_reference if seed_event else None
                ),
                branch_path=(seed_event.event_reference,) if seed_event else (),
                hop_depth=0,
                observed_amount_base_units=(
                    seed_event.amount_base_units if seed_event else None
                ),
            )
        ]

        while frontier:
            state = frontier.pop(0)
            counters.max_hop_reached = max(counters.max_hop_reached, state.hop_depth)

            exhausted = self._budget_exhausted(state, counters)
            if exhausted is not None:
                self._end_branch(result, state, EndpointClass.boundary, exhausted, analysis_cutoff)
                result.coverage_status = CoverageStatus.partial
                continue

            if self._stop_at_label(result, state, analysis_cutoff):
                continue

            try:
                outgoing = await self._collect_outgoing(state, analysis_cutoff, counters)
            except ProviderError as exc:
                # A provider failure is not an absence of activity (T3).
                result.limitations.append(
                    Limitation(
                        code=f"provider_{exc.error_class.value}",
                        message=str(exc),
                        address=state.address,
                    )
                )
                result.coverage_status = CoverageStatus.failed
                self._end_branch(
                    result,
                    state,
                    EndpointClass.boundary,
                    BoundaryReason.provider_failure,
                    analysis_cutoff,
                )
                continue

            successors, merged_into = self._successors(result, state, outgoing, counters)
            if not successors and merged_into:
                # This branch did not run out of activity; it converged onto a
                # path another branch is already walking. Saying "no outgoing
                # activity" here would be a false statement about the chain.
                self._end_branch(
                    result,
                    state,
                    EndpointClass.unresolved,
                    None,
                    analysis_cutoff,
                    note=(
                        "Branch reconverged onto an already-explored path at "
                        f"{merged_into}. The onward transfers are recorded once, on that path."
                    ),
                )
                continue
            if not successors:
                self._end_branch(
                    result,
                    state,
                    EndpointClass.unresolved,
                    BoundaryReason.no_outgoing_activity,
                    analysis_cutoff,
                    note=(
                        "No further observed transfer of this asset from this address within "
                        "the analysed scope. An asset change, bridge, privacy mechanism, or "
                        "opaque contract would also look like this; no continuation is assumed."
                    ),
                )
                continue
            frontier.extend(successors)

        result.finished_at = dt.datetime.now(dt.UTC)
        result.budget_use = BudgetUse(
            hops_used=counters.max_hop_reached,
            events_examined=counters.events_examined,
            traversal_requests=counters.provider_requests,
            elapsed_seconds=round(counters.elapsed, 3),
            hop_limit=self.budgets.max_hops,
            event_limit=self.budgets.max_events,
            traversal_request_limit=self.budgets.max_provider_requests,
            wall_clock_limit_seconds=self.budgets.wall_clock_seconds,
        )
        return result

    # -- internals --------------------------------------------------------

    def _budget_exhausted(self, state: TraceState, counters: _RunCounters) -> BoundaryReason | None:
        if state.hop_depth >= self.budgets.max_hops:
            return BoundaryReason.hop_limit
        if counters.events_examined >= self.budgets.max_events:
            return BoundaryReason.event_limit
        if counters.provider_requests >= self.budgets.max_provider_requests:
            return BoundaryReason.api_budget
        if counters.elapsed >= self.budgets.wall_clock_seconds:
            return BoundaryReason.time_limit
        return None

    def _stop_at_label(
        self, result: TraceResult, state: TraceState, moment: dt.datetime
    ) -> bool:
        """End the branch only on a reviewed, in-date service-control assertion."""
        at = state.arrival.block_time or moment
        if self.labels.has_active_conflict(self.adapter.network_key, state.address, at):
            result.limitations.append(Limitation(code="conflicting_service_labels",
                message="Active reviewed labels disagree on service identity or address role. No custody attribution was selected; tracing continues.",
                address=state.address))
        anchor = self.labels.terminating_anchor(self.adapter.network_key, state.address, at)
        if anchor is not None:
            self._end_branch(
                result,
                state,
                EndpointClass.known_service,
                BoundaryReason.service_boundary,
                moment,
                label=anchor.to_evidence(),
                attribution_status=AttributionStatus.supported,
            )
            return True

        candidate = self.labels.candidate_anchor(self.adapter.network_key, state.address, at)
        if candidate is not None:
            # Shown, but the walk continues: a candidate is not a verified
            # custody boundary and must not silently end a branch.
            result.branch_endings.append(
                BranchEnding(
                    address=state.address,
                    endpoint_class=EndpointClass.deposit_candidate,
                    attribution_status=AttributionStatus.candidate,
                    boundary_reason=None,
                    hop_depth=state.hop_depth,
                    branch_path=list(state.branch_path),
                    arrival_event_reference=state.arrival_event_reference,
                    observed_amount_base_units=state.observed_amount_base_units,
                    asset_decimals=state.asset.decimals,
                    label=candidate.to_evidence(),
                    note="Candidate only. Tracing continues; this is not a verified boundary.",
                )
            )
        return False

    async def _collect_outgoing(
        self, state: TraceState, analysis_cutoff: dt.datetime, counters: _RunCounters
    ) -> list[NormalizedTransfer]:
        events: list[NormalizedTransfer] = []
        cursor: str | None = None
        seen_references: set[str] = set()
        seen_cursors: set[str] = set()

        while True:
            if counters.provider_requests >= self.budgets.max_provider_requests:
                raise ProviderError(ProviderErrorClass.budget_exhausted,
                    "Pagination remained incomplete when the traversal request budget ended.")
            page = await self.adapter.fetch_transfers(
                address=state.address,
                asset=state.asset,
                direction=Direction.outgoing,
                analysis_cutoff=analysis_cutoff,
                analysis_start=state.arrival.block_time,
                cursor=cursor,
                limit=self.page_limit,
            )
            counters.provider_requests += 1
            for event in page.events:
                # Day-one test 7: a repeated page must not duplicate an event,
                # and two distinct events must not be merged.
                if event.event_reference in seen_references:
                    continue
                seen_references.add(event.event_reference)
                events.append(event)
            cursor = page.next_cursor
            if not cursor:
                break
            if cursor in seen_cursors:
                raise ProviderError(ProviderErrorClass.parse_error,
                    "Provider repeated a pagination cursor; remaining history is unresolved.")
            seen_cursors.add(cursor)
        return events

    def _successors(
        self,
        result: TraceResult,
        state: TraceState,
        outgoing: list[NormalizedTransfer],
        counters: _RunCounters,
    ) -> tuple[list[TraceState], str | None]:
        successors: list[TraceState] = []
        merged_into: str | None = None
        for event in sorted(outgoing, key=lambda e: (e.block_time or dt.datetime.min.replace(
            tzinfo=dt.UTC
        ), e.chain_sequence or "")):
            counters.events_examined += 1

            if not self._is_spendable(event):
                if (event.event_kind is EventKind.transfer and not event.is_zero_value
                    and event.execution_status not in (ExecutionStatus.failed, ExecutionStatus.reverted)
                    and event.confirmation_state is not ConfirmationState.removed):
                    result.limitations.append(Limitation(
                        code="execution_or_finality_unverified",
                        message="Observed event was not followed: successful execution and confirmed finality are both required.",
                        address=state.address,
                        event_reference=event.event_reference,
                    ))
                    if result.coverage_status is CoverageStatus.complete_within_scope:
                        result.coverage_status = CoverageStatus.partial
                continue

            position = Position(event.block_time, event.chain_sequence or BEFORE_EVERYTHING)

            if not position.strictly_after(state.arrival):
                if position.same_moment_as(state.arrival) and (
                    event.ordering_ambiguous or not event.chain_sequence
                ):
                    # Same block, no usable ordering. Not dropped, not followed:
                    # recorded as unresolved (day-one test 1's boundary case).
                    result.limitations.append(
                        Limitation(
                            code="ambiguous_ordering",
                            message=(
                                "Outgoing transfer shares a block with the arrival and the "
                                "source supplied no ordering; it cannot be established that "
                                "it followed the receipt."
                            ),
                            address=state.address,
                            event_reference=event.event_reference,
                        )
                    )
                    result.coverage_status = CoverageStatus.partial
                # Otherwise the event is genuinely earlier than the arrival and
                # cannot have carried these funds. Day-one test 1.
                continue

            if event.event_reference in state.consumed:
                # This branch has already walked this event; following it again
                # would be a cycle. Other branches are unaffected.
                continue

            if event.event_reference not in counters.recorded_events:
                counters.recorded_events.add(event.event_reference)
                result.observed_transfers.append(
                    ObservedTransfer(
                        event_reference=event.event_reference,
                        tx_hash=event.tx_hash,
                        from_address=event.from_address,
                        to_address=event.to_address,
                        amount_base_units=event.amount_base_units,
                        asset_contract=event.asset.token_contract,
                        asset_decimals=event.asset.decimals,
                        asset_symbol=event.asset.display_symbol,
                        block_time=event.block_time,
                        chain_sequence=event.chain_sequence,
                        ordering_ambiguous=event.ordering_ambiguous,
                        execution_status=event.execution_status.value,
                        confirmation_state=event.confirmation_state.value,
                        hop_depth=state.hop_depth + 1,
                    )
                )

            if event.to_address is None:
                continue
            if event.event_reference in counters.expanded_arrivals:
                # Another branch already walks onward from this exact transfer.
                # The upstream branches stay distinct in the record; the shared
                # suffix is explored once.
                merged_into = merged_into or event.event_reference
                continue
            counters.expanded_arrivals.add(event.event_reference)
            successors.append(
                TraceState(
                    address=event.to_address,
                    asset=state.asset,
                    arrival=position,
                    arrival_event_reference=event.event_reference,
                    hop_depth=state.hop_depth + 1,
                    branch_path=(*state.branch_path, event.event_reference),
                    observed_amount_base_units=event.amount_base_units,
                )
            )
        return successors, merged_into

    @staticmethod
    def _is_spendable(event: NormalizedTransfer) -> bool:
        """Only a successful, confirmed, non-zero transfer continues a path.

        Approvals move nothing. Failed and reverted executions move nothing.
        Removed events were undone by a reorg. A zero-value transfer carries no
        value forward. All of them are still evidence and stay in the record;
        they simply do not extend a fund-flow path. Day-one test 6.
        """
        if event.event_kind is not EventKind.transfer:
            return False
        if event.execution_status is not ExecutionStatus.success:
            return False
        if event.confirmation_state is not ConfirmationState.confirmed:
            return False
        return event.amount_base_units > 0

    def _end_branch(
        self,
        result: TraceResult,
        state: TraceState,
        endpoint_class: EndpointClass,
        boundary_reason: BoundaryReason | None,
        moment: dt.datetime,
        *,
        label: object | None = None,
        attribution_status: AttributionStatus = AttributionStatus.unresolved,
        note: str | None = None,
    ) -> None:
        result.branch_endings.append(
            BranchEnding(
                address=state.address,
                endpoint_class=endpoint_class,
                attribution_status=attribution_status,
                boundary_reason=boundary_reason,
                hop_depth=state.hop_depth,
                branch_path=list(state.branch_path),
                arrival_event_reference=state.arrival_event_reference,
                observed_amount_base_units=state.observed_amount_base_units,
                asset_decimals=state.asset.decimals,
                label=label,  # type: ignore[arg-type]
                note=note,
            )
        )


__all__ = ["Budgets", "ChronologicalTracer", "Position", "TraceState"]
