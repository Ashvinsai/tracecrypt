"""Checkpointed new-event monitoring for supported TRC-20 transfers (Stage 4, D029).

One poll is one bounded pass over a window of a provider's indexed transfer
history, through the same ``ChainAdapter.fetch_transfers`` every other path
uses. It is polling of indexed history, never a mempool or pending-transaction
feed, and nothing here claims otherwise.

Correctness rests on four rules:

* **Idempotency is enforced by the database.** An alert's ``dedupe_key`` is
  ``<rule>:<event_reference>`` under ``UNIQUE(watch_id, dedupe_key)``. The
  event reference is the adapter's chain-specific identity (D005), never a
  transaction hash, so two transfers in one transaction stay two alerts and a
  re-read event is never alerted twice -- across overlap, pagination repeats,
  retries, and process restarts alike.
* **The checkpoint only moves on a complete poll.** A provider failure, a
  truncated window, or a crash leaves it where it was. The next poll re-reads
  from ``checkpoint - overlap`` and the unique key absorbs the repeats.
* **Alerts and the checkpoint commit together.** Everything a poll changes is
  one transaction; only the "poll started" audit row is committed first.
* **A provider error is a failed poll**, recorded as such, never "0 new events".
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters.base import (
    AcquisitionRecord,
    AssetRef,
    ChainAdapter,
    Direction,
    NormalizedTransfer,
    ProviderError,
    ProviderErrorClass,
)
from app.adapters.tron import TronGridAdapter
from app.core.amounts import serialize, to_display
from app.core.settings import DataMode
from app.models.casework import Alert, Case, Watch, WatchPollRun
from app.models.chain import Address, Asset, Network
from app.models.enums import (
    AlertState,
    AssetKind,
    ConfirmationState,
    CoverageStatus,
    EventKind,
    ExecutionStatus,
    WatchPollStatus,
)
from app.services.addresses import AddressValidationError, canonicalize

MONITOR_VERSION = "monitor-0.1.0"
RULE_KEY = "new_supported_token_transfer"
RULE_VERSION = "1"
RULE_REASON = (
    "A transfer of the watched verified asset involving the watched address was "
    "first observed by this monitor."
)

#: Stated on every poll and alert. These are properties of the design, not caveats
#: to be tuned away.
LIMITATIONS = (
    "Polling of an indexed provider history endpoint. This is not a mempool or "
    "pending-transaction feed; nothing is seen before the provider indexes it.",
    "The checkpoint is a block-time frontier. A poll re-reads overlap_seconds behind "
    "it; an event the provider indexes later than that after its block time would "
    "not be observed. The provider's indexing lag has not been measured.",
    "The TronGrid history endpoint serves confirmed rows only and exposes no "
    "removed-event signal, so reorg retraction is only exercised where a source "
    "reports confirmation_state=removed. An event missing from a later poll is not "
    "treated as removed.",
    "An alert records an observed transfer. It is not a fraud finding, an ownership "
    "claim, or a request to act.",
)

_MAX_LISTED_EXCLUSIONS = 200
_IN_CHUNK = 500


class MonitoringError(ValueError):
    """A caller error: unsupported asset, mode mismatch, inactive watch."""


@dataclass
class PollOutcome:
    poll_run_id: uuid.UUID
    watch_id: uuid.UUID
    status: WatchPollStatus
    coverage_status: CoverageStatus
    data_mode: DataMode
    window_start: dt.datetime
    window_end: dt.datetime
    checkpoint_before: dt.datetime | None
    checkpoint_after: dt.datetime | None
    pages_fetched: int = 0
    events_observed: int = 0
    new_alert_references: list[str] = field(default_factory=list)
    duplicate_events: int = 0
    retracted_references: list[str] = field(default_factory=list)
    excluded: dict[str, int] = field(default_factory=dict)
    error_class: str | None = None
    error_message: str | None = None

    @property
    def new_alerts(self) -> int:
        return len(self.new_alert_references)

    def to_json(self) -> dict[str, Any]:
        return {
            "poll_run_id": str(self.poll_run_id),
            "watch_id": str(self.watch_id),
            "status": self.status.value,
            "coverage_status": self.coverage_status.value,
            "data_mode": self.data_mode.value,
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "checkpoint_before": _iso(self.checkpoint_before),
            "checkpoint_after": _iso(self.checkpoint_after),
            "checkpoint_advanced": self.checkpoint_after != self.checkpoint_before,
            "pages_fetched": self.pages_fetched,
            "events_observed": self.events_observed,
            "new_alerts": self.new_alerts,
            "new_alert_references": self.new_alert_references,
            "duplicate_events": self.duplicate_events,
            "retracted_references": self.retracted_references,
            "excluded": self.excluded,
            "error_class": self.error_class,
            "error_message": self.error_message,
        }


def _iso(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value else None


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def redact(text: str, secrets: Iterable[str | None]) -> str:
    """Replace any configured secret value in ``text``. Provider messages are untrusted."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return text


# -- watches ----------------------------------------------------------------


def create_watch(
    db: Session,
    *,
    case: Case,
    network_key: str,
    address: str,
    token_contract: str,
    data_mode: DataMode,
    analysis_start: dt.datetime | None = None,
    overlap_seconds: int = 600,
    created_by: uuid.UUID | None = None,
    now: dt.datetime | None = None,
) -> Watch:
    """Register a watch on one supported (network, token contract) and address.

    The network is named, never inferred from the address (D002); the asset is
    the exact verified contract, never a symbol (D003). Flushes, does not commit.
    """
    if data_mode is not case.data_mode:
        raise MonitoringError(
            f"case is {case.data_mode.value}; a {data_mode.value} watch cannot be added to it"
        )
    if overlap_seconds < 0:
        raise MonitoringError("overlap_seconds must be non-negative")
    if analysis_start is not None and analysis_start.tzinfo is None:
        raise MonitoringError("analysis_start must be timezone-aware")

    network = db.execute(select(Network).where(Network.key == network_key)).scalar_one_or_none()
    if network is None or not network.is_supported:
        raise MonitoringError("unsupported network")
    try:
        canonical = canonicalize(network.key, address)
    except AddressValidationError as exc:
        raise MonitoringError(str(exc)) from exc

    asset = db.execute(
        select(Asset).where(
            Asset.network_id == network.id,
            Asset.kind == AssetKind.token,
            Asset.token_contract == token_contract,
            Asset.is_supported.is_(True),
        )
    ).scalar_one_or_none()
    if asset is None:
        raise MonitoringError("token contract is not a supported asset on this network")
    if data_mode is DataMode.LIVE and asset.data_mode is DataMode.SYNTHETIC:
        raise MonitoringError("a LIVE watch cannot use a SYNTHETIC fixture asset (T13)")

    address_row = db.execute(
        select(Address).where(
            Address.network_id == network.id,
            Address.canonical_address == canonical.canonical,
        )
    ).scalar_one_or_none()
    if address_row is None:
        address_row = Address(
            network_id=network.id,
            canonical_address=canonical.canonical,
            original_input=canonical.original,
            address_format=canonical.address_format,
            data_mode=data_mode,
        )
        db.add(address_row)
        db.flush()

    watch = Watch(
        case_id=case.id,
        network_id=network.id,
        address_id=address_row.id,
        asset_id=asset.id,
        is_active=True,
        data_mode=data_mode,
        analysis_start=analysis_start,
        overlap_seconds=overlap_seconds,
        created_by=created_by,
        created_at=now or _utc_now(),
    )
    db.add(watch)
    db.flush()
    return watch


@dataclass(frozen=True)
class WatchTarget:
    network_key: str
    address: str
    asset: AssetRef


def resolve_target(db: Session, watch: Watch) -> WatchTarget:
    network = db.get(Network, watch.network_id)
    address = db.get(Address, watch.address_id)
    asset = db.get(Asset, watch.asset_id) if watch.asset_id else None
    if network is None or address is None or asset is None or asset.token_contract is None:
        raise MonitoringError("watch does not name a network, address, and token asset")
    if not asset.is_supported:
        raise MonitoringError("the watched asset is no longer supported")
    return WatchTarget(
        network_key=network.key,
        address=address.canonical_address,
        asset=AssetRef(
            network_key=network.key,
            token_contract=asset.token_contract,
            decimals=asset.decimals,
            display_symbol=asset.display_symbol,
        ),
    )


# -- event qualification ----------------------------------------------------


def exclusion_reason(
    event: NormalizedTransfer,
    *,
    target: WatchTarget,
    baseline: dt.datetime,
    canonical: Callable[[str | None], str | None],
) -> str | None:
    """Why an event does not qualify for the rule, or ``None`` if it does.

    Mirrors the tracer's ``_is_spendable`` (approvals, failed/reverted executions,
    removed and zero-value events move no value), plus the checks a watch adds:
    exact asset contract, involvement of the watched address, and scope start.
    """
    if (
        event.asset.network_key != target.asset.network_key
        or event.asset.token_contract != target.asset.token_contract
    ):
        return "unsupported_asset_contract"
    if event.event_kind is EventKind.approval:
        return "approval"
    if event.event_kind is not EventKind.transfer:
        return "not_a_transfer"
    if event.execution_status is ExecutionStatus.failed:
        return "failed_execution"
    if event.execution_status is ExecutionStatus.reverted:
        return "reverted_execution"
    if event.confirmation_state is ConfirmationState.removed:
        return "removed"
    if event.is_zero_value:
        return "zero_value"
    if target.address not in (canonical(event.from_address), canonical(event.to_address)):
        return "does_not_involve_watched_address"
    if event.block_time is not None and event.block_time < baseline:
        return "before_watch_scope"
    return None


#: Reasons that, seen on an event that already has an active alert, retract it.
RETRACTING_REASONS = frozenset({"failed_execution", "reverted_execution", "removed"})


def _order_key(event: NormalizedTransfer) -> tuple[dt.datetime, str, str]:
    # Strongest ordering the evidence supports: block time, then the chain
    # sequence when known. Ties fall back to the reference only so processing is
    # deterministic; that is not a claim about chain order (ordering_ambiguous
    # stays on the alert).
    return (
        event.block_time or dt.datetime.max.replace(tzinfo=dt.UTC),
        event.chain_sequence or "",
        event.event_reference,
    )


def _lag(
    event: NormalizedTransfer, observed_at: dt.datetime, mode: DataMode, simulated: bool
) -> dict[str, Any]:
    if event.block_time is None:
        return {"seconds": None, "basis": "unavailable", "note": "event has no block time"}
    if mode is DataMode.RECORDED_PUBLIC:
        return {
            "seconds": None,
            "basis": "unavailable_recorded_replay",
            "note": "a replay's observation time says nothing about live observation lag",
        }
    seconds = int((observed_at - event.block_time).total_seconds())
    if mode is DataMode.SYNTHETIC:
        return {
            "seconds": seconds,
            "basis": "simulated_clock" if simulated else "synthetic_fixture_times",
            "note": "computed from synthetic data; not a latency measurement",
        }
    return {
        "seconds": seconds,
        "basis": "live_wall_clock",
        "note": (
            "time between the event's block time and this monitor first observing it; "
            "not mempool, propagation, or exchange notification latency"
        ),
    }


def _acquisition_json(record: AcquisitionRecord | None) -> dict[str, Any] | None:
    if record is None:
        return None
    return {
        "provider": record.provider,
        "endpoint": record.endpoint,
        "requested_at": _iso(record.requested_at),
        "observed_at": _iso(record.observed_at),
        "request_params_hash": record.request_params_hash,
        "response_hash": record.response_hash,
        "parser_version": record.parser_version,
        "capture_time": _iso(record.capture_time),
    }


def _event_json(event: NormalizedTransfer, target: WatchTarget, direction: str) -> dict[str, Any]:
    return {
        "network": target.network_key,
        "asset": {
            "network_key": event.asset.network_key,
            "token_contract": event.asset.token_contract,
            "decimals": event.asset.decimals,
            "display_symbol": event.asset.display_symbol,
            "display_symbol_is_metadata_only": True,
        },
        "event_reference": event.event_reference,
        "tx_hash": event.tx_hash,
        "event_kind": event.event_kind.value,
        "direction_relative_to_watch": direction,
        "from_address": event.from_address,
        "to_address": event.to_address,
        "amount_base_units": serialize(event.amount_base_units),
        "amount_display": to_display(event.amount_base_units, event.asset.decimals),
        "block_time": _iso(event.block_time),
        "block_height": event.block_height,
        "chain_sequence": event.chain_sequence,
        "ordering_ambiguous": event.ordering_ambiguous,
    }


# -- polling ----------------------------------------------------------------


def _check_mode(adapter: ChainAdapter, watch: Watch, mode: DataMode) -> str | None:
    if watch.data_mode is not mode:
        return (
            f"watch is {watch.data_mode.value} but the poll is {mode.value}; modes are never mixed"
        )
    try:
        adapter.assert_mode_allowed(mode)
    except ProviderError as exc:
        return str(exc)
    declared = getattr(adapter, "data_mode", None)
    if declared is not None and declared is not mode:
        return f"the source declares {declared.value}, not {mode.value}"
    return None


async def poll_watch(
    db: Session,
    watch: Watch,
    adapter: ChainAdapter,
    *,
    observation_mode: DataMode,
    now: dt.datetime | None = None,
    max_pages: int = 20,
    page_size: int = 200,
    verify_execution: bool = True,
    secrets: Iterable[str | None] = (),
    capture: dict[str, Any] | None = None,
) -> PollOutcome:
    """Run one bounded poll of one watch and commit its outcome.

    ``now`` injects a clock for SYNTHETIC/RECORDED_PUBLIC runs; a LIVE poll must
    use the real clock, because an injected one would fabricate observation lag.
    ``capture`` names the raw-response bundle a caller is recording, if any.
    """
    if not watch.is_active:
        raise MonitoringError("watch is not active")
    if now is not None and observation_mode is DataMode.LIVE:
        raise MonitoringError("a LIVE poll cannot use an injected clock")
    simulated = now is not None
    poll_time = now or _utc_now()
    secret_values = list(secrets)
    target = resolve_target(db, watch)

    baseline = watch.analysis_start or watch.created_at
    checkpoint_before = watch.checkpoint_time
    window_start = baseline
    if checkpoint_before is not None:
        window_start = max(
            baseline, checkpoint_before - dt.timedelta(seconds=watch.overlap_seconds)
        )
    window_end = poll_time

    run = WatchPollRun(
        watch_id=watch.id,
        status=WatchPollStatus.running,
        coverage_status=CoverageStatus.unknown,
        data_mode=observation_mode,
        provider=type(adapter).__name__,
        started_at=poll_time if simulated else _utc_now(),
        window_start=window_start,
        window_end=window_end,
        checkpoint_before=checkpoint_before,
        summary={
            "monitor_version": MONITOR_VERSION,
            "limitations": list(LIMITATIONS),
            "capture": capture,
        },
    )
    db.add(run)
    # Committed on its own so a crash mid-poll still leaves an audit row that
    # says a poll started and never completed. Nothing else is written yet.
    db.commit()

    outcome = PollOutcome(
        poll_run_id=run.id,
        watch_id=watch.id,
        status=WatchPollStatus.running,
        coverage_status=CoverageStatus.unknown,
        data_mode=observation_mode,
        window_start=window_start,
        window_end=window_end,
        checkpoint_before=checkpoint_before,
        checkpoint_after=checkpoint_before,
    )

    refusal = _check_mode(adapter, watch, observation_mode)
    if refusal is not None:
        outcome.status = WatchPollStatus.refused
        outcome.error_class = ProviderErrorClass.unsupported.value
        outcome.error_message = refusal
        _finish(db, run, outcome, poll_time, simulated, extra={})
        return outcome

    # 1. Acquire every page of the window, or stop and say why.
    requests_before = getattr(adapter, "request_count", None)
    acquired: list[tuple[NormalizedTransfer, int]] = []
    acquisitions: list[dict[str, Any] | None] = []
    error: ProviderError | None = None
    truncated = False
    cursor: str | None = None
    while True:
        try:
            page = await adapter.fetch_transfers(
                address=target.address,
                asset=target.asset,
                direction=Direction.both,
                analysis_cutoff=window_end,
                analysis_start=window_start,
                cursor=cursor,
                limit=page_size,
            )
        except ProviderError as exc:
            error = exc
            break
        acquisitions.append(_acquisition_json(page.acquisition))
        acquired.extend((event, len(acquisitions) - 1) for event in page.events)
        outcome.pages_fetched += 1
        if not page.next_cursor:
            break
        if outcome.pages_fetched >= max_pages:
            truncated = True
            break
        cursor = page.next_cursor

    # 2. Collapse repeats by event identity. Identical repeats (pagination
    # overlap) are one event; a repeated reference with different content is a
    # conflict that is reported, not silently merged.
    unique: dict[str, tuple[NormalizedTransfer, int]] = {}
    conflicts: list[str] = []
    for event, page_index in acquired:
        prior = unique.get(event.event_reference)
        if prior is None:
            unique[event.event_reference] = (event, page_index)
        elif prior[0] != event and event.event_reference not in conflicts:
            conflicts.append(event.event_reference)
    outcome.events_observed = len(unique)
    within_poll_repeats = len(acquired) - len(unique)

    def canonical(value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return adapter.validate_address(value).canonical
        except (AddressValidationError, ValueError):
            return value

    events = sorted(unique.values(), key=lambda item: _order_key(item[0]))
    existing = _existing_alerts(db, watch.id, [e.event_reference for e, _ in events])

    # 3. Establish execution for events the source left unknown, where the
    # adapter can. An unverifiable event keeps ``unknown``; it is never upgraded.
    verification_notes: dict[str, str] = {}
    if verify_execution and isinstance(adapter, TronGridAdapter):
        needs = [
            e
            for e, _ in events
            if e.execution_status is ExecutionStatus.unknown
            and exclusion_reason(e, target=target, baseline=baseline, canonical=canonical) is None
            and (
                e.event_reference not in existing
                or existing[e.event_reference].execution_status is ExecutionStatus.unknown
            )
        ]
        if needs:
            verification = await adapter.verify_execution(needs)
            by_ref = {e.event_reference: e for e in verification.events}
            for item in verification.unverified:
                verification_notes[item.event_reference] = item.reason
            events = [(by_ref.get(e.event_reference, e), i) for e, i in events]

    # 4. Decide per event: new alert, repeat (with any state change), retraction,
    # or exclusion with a reason. All in the one transaction committed below.
    excluded: Counter[str] = Counter()
    excluded_listing: list[dict[str, str]] = []
    for event, page_index in events:
        reason = exclusion_reason(event, target=target, baseline=baseline, canonical=canonical)
        alert = existing.get(event.event_reference)
        if reason is not None:
            if alert is not None and reason in RETRACTING_REASONS:
                if _retract(alert, event, reason, poll_time, run.id):
                    outcome.retracted_references.append(event.event_reference)
            excluded[reason] += 1
            if len(excluded_listing) < _MAX_LISTED_EXCLUSIONS:
                excluded_listing.append(
                    {"event_reference": event.event_reference, "reason": reason}
                )
            continue
        if alert is not None:
            outcome.duplicate_events += 1
            _refresh(alert, event, poll_time, run.id)
            continue
        direction = _direction(event, target.address, canonical)
        created = _insert_alert(
            db,
            watch=watch,
            event=event,
            target=target,
            direction=direction,
            mode=observation_mode,
            observed_at=poll_time,
            simulated=simulated,
            run_id=run.id,
            acquisition=acquisitions[page_index],
            verification_note=verification_notes.get(event.event_reference),
        )
        if created is None:
            # Another writer inserted it first; the unique key did its job.
            outcome.duplicate_events += 1
        else:
            outcome.new_alert_references.append(event.event_reference)

    outcome.excluded = dict(sorted(excluded.items()))
    outcome.duplicate_events += within_poll_repeats
    requests_after = getattr(adapter, "request_count", None)
    provider_requests = (
        requests_after - requests_before
        if isinstance(requests_before, int) and isinstance(requests_after, int)
        else None
    )

    # 5. Classify the poll. Only a complete window moves the checkpoint.
    if error is not None:
        outcome.error_class = error.error_class.value
        outcome.error_message = redact(str(error), secret_values)[:500]
        if outcome.pages_fetched == 0:
            outcome.status = WatchPollStatus.provider_failure
            outcome.coverage_status = CoverageStatus.failed
        else:
            outcome.status = WatchPollStatus.partial
            outcome.coverage_status = CoverageStatus.partial
    elif truncated:
        outcome.status = WatchPollStatus.truncated
        outcome.coverage_status = CoverageStatus.partial
        outcome.error_class = ProviderErrorClass.budget_exhausted.value
        outcome.error_message = f"page budget of {max_pages} reached before the window ended"
    else:
        outcome.status = WatchPollStatus.succeeded
        outcome.coverage_status = CoverageStatus.complete_within_scope
        new_checkpoint = max(window_end, checkpoint_before or window_end)
        watch.checkpoint_time = new_checkpoint
        watch.checkpoint_updated_at = poll_time
        outcome.checkpoint_after = new_checkpoint

    _finish(
        db,
        run,
        outcome,
        poll_time,
        simulated,
        extra={
            "acquisitions": acquisitions,
            "excluded_events": excluded_listing,
            "conflicting_references": conflicts,
            "within_poll_repeats": within_poll_repeats,
            "execution_unverified": verification_notes,
            "provider_requests": provider_requests,
            "overlap_seconds": watch.overlap_seconds,
            "scope_start": baseline.isoformat(),
        },
        provider_requests=provider_requests,
    )
    return outcome


def _finish(
    db: Session,
    run: WatchPollRun,
    outcome: PollOutcome,
    poll_time: dt.datetime,
    simulated: bool,
    *,
    extra: dict[str, Any],
    provider_requests: int | None = None,
) -> None:
    run.status = outcome.status
    run.coverage_status = outcome.coverage_status
    run.completed_at = poll_time if simulated else _utc_now()
    run.checkpoint_after = outcome.checkpoint_after
    run.pages_fetched = outcome.pages_fetched
    run.provider_requests = provider_requests
    run.events_observed = outcome.events_observed
    run.new_alerts = outcome.new_alerts
    run.duplicate_events = outcome.duplicate_events
    run.error_class = outcome.error_class
    run.error_message = outcome.error_message
    run.summary = {
        **run.summary,
        **extra,
        "excluded": outcome.excluded,
        "new_alert_references": outcome.new_alert_references,
        "retracted_references": outcome.retracted_references,
        "clock": "injected" if simulated else "wall_clock",
    }
    # Alerts, alert state changes, the checkpoint, and this row: one commit.
    db.commit()


def _existing_alerts(db: Session, watch_id: uuid.UUID, references: list[str]) -> dict[str, Alert]:
    found: dict[str, Alert] = {}
    for start in range(0, len(references), _IN_CHUNK):
        chunk = references[start : start + _IN_CHUNK]
        rows = db.execute(
            select(Alert).where(
                Alert.watch_id == watch_id,
                Alert.rule_key == RULE_KEY,
                Alert.event_reference.in_(chunk),
            )
        ).scalars()
        found.update({row.event_reference: row for row in rows})
    return found


def _direction(
    event: NormalizedTransfer, address: str, canonical: Callable[[str | None], str | None]
) -> str:
    sender, recipient = canonical(event.from_address), canonical(event.to_address)
    if sender == address and recipient == address:
        return "self"
    return "outgoing" if sender == address else "incoming"


def dedupe_key(event_reference: str) -> str:
    return f"{RULE_KEY}:{event_reference}"


def _insert_alert(
    db: Session,
    *,
    watch: Watch,
    event: NormalizedTransfer,
    target: WatchTarget,
    direction: str,
    mode: DataMode,
    observed_at: dt.datetime,
    simulated: bool,
    run_id: uuid.UUID,
    acquisition: dict[str, Any] | None,
    verification_note: str | None,
) -> Alert | None:
    evidence = {
        "rule": {"key": RULE_KEY, "version": RULE_VERSION, "reason": RULE_REASON},
        "event": _event_json(event, target, direction),
        "execution_status": event.execution_status.value,
        "execution_verification": (
            {"verified": False, "reason": verification_note}
            if verification_note is not None
            else {"verified": event.execution_status is not ExecutionStatus.unknown}
        ),
        "confirmation_state": event.confirmation_state.value,
        "first_observed_at": observed_at.isoformat(),
        "last_observed_at": observed_at.isoformat(),
        "observation_lag": _lag(event, observed_at, mode, simulated),
        "data_mode": mode.value,
        "acquisition": acquisition,
        "first_poll_run_id": str(run_id),
        "state_history": [
            {
                "at": observed_at.isoformat(),
                "state": AlertState.active.value,
                "execution_status": event.execution_status.value,
                "confirmation_state": event.confirmation_state.value,
                "reason": "first observed",
                "poll_run_id": str(run_id),
            }
        ],
        "limitations": list(LIMITATIONS),
    }
    alert = Alert(
        watch_id=watch.id,
        rule_key=RULE_KEY,
        rule_version=RULE_VERSION,
        dedupe_key=dedupe_key(event.event_reference),
        evidence=evidence,
        created_at=observed_at,
        event_reference=event.event_reference,
        data_mode=mode,
        state=AlertState.active,
        execution_status=event.execution_status,
        confirmation_state=event.confirmation_state,
        block_time=event.block_time,
        first_observed_at=observed_at,
        first_poll_run_id=run_id,
    )
    try:
        with db.begin_nested():
            db.add(alert)
            db.flush()
    except IntegrityError:
        return None
    return alert


def _record_state(alert: Alert, at: dt.datetime, run_id: uuid.UUID, reason: str) -> None:
    evidence = dict(alert.evidence)
    history = list(evidence.get("state_history", []))
    history.append(
        {
            "at": at.isoformat(),
            "state": alert.state.value,
            "execution_status": alert.execution_status.value,
            "confirmation_state": alert.confirmation_state.value,
            "reason": reason,
            "poll_run_id": str(run_id),
        }
    )
    evidence["state_history"] = history
    evidence["execution_status"] = alert.execution_status.value
    evidence["confirmation_state"] = alert.confirmation_state.value
    evidence["last_observed_at"] = at.isoformat()
    alert.evidence = evidence


def _refresh(alert: Alert, event: NormalizedTransfer, at: dt.datetime, run_id: uuid.UUID) -> None:
    """Record a genuine state change on a re-observed event; otherwise only its last sighting."""
    changes: list[str] = []
    if (
        event.confirmation_state is not ConfirmationState.unknown
        and event.confirmation_state is not alert.confirmation_state
    ):
        changes.append(
            f"confirmation {alert.confirmation_state.value} -> {event.confirmation_state.value}"
        )
        alert.confirmation_state = event.confirmation_state
    if (
        alert.execution_status is ExecutionStatus.unknown
        and event.execution_status is ExecutionStatus.success
    ):
        changes.append("execution unknown -> success")
        alert.execution_status = event.execution_status
    if changes:
        _record_state(alert, at, run_id, "; ".join(changes))
    else:
        alert.evidence = {**alert.evidence, "last_observed_at": at.isoformat()}


def _retract(
    alert: Alert, event: NormalizedTransfer, reason: str, at: dt.datetime, run_id: uuid.UUID
) -> bool:
    if alert.state is AlertState.retracted:
        return False
    alert.state = AlertState.retracted
    if event.confirmation_state is ConfirmationState.removed:
        alert.confirmation_state = ConfirmationState.removed
    if event.execution_status in (ExecutionStatus.failed, ExecutionStatus.reverted):
        alert.execution_status = event.execution_status
    _record_state(alert, at, run_id, f"retracted: later observation reports {reason}")
    return True


# -- batch and read helpers ---------------------------------------------------


async def poll_enabled_watches(
    db: Session,
    adapter: ChainAdapter,
    *,
    observation_mode: DataMode,
    watch_ids: list[uuid.UUID] | None = None,
    **kwargs: Any,
) -> list[PollOutcome]:
    """One poll of every active watch in ``observation_mode``, sequentially."""
    query = select(Watch).where(Watch.is_active.is_(True), Watch.data_mode == observation_mode)
    if watch_ids:
        query = query.where(Watch.id.in_(watch_ids))
    watches = db.execute(query.order_by(Watch.created_at, Watch.id)).scalars().all()
    return [
        await poll_watch(db, watch, adapter, observation_mode=observation_mode, **kwargs)
        for watch in watches
    ]


def alert_to_json(alert: Alert) -> dict[str, Any]:
    return {
        "id": str(alert.id),
        "watch_id": str(alert.watch_id),
        "rule_key": alert.rule_key,
        "rule_version": alert.rule_version,
        "event_reference": alert.event_reference,
        "state": alert.state.value,
        "execution_status": alert.execution_status.value,
        "confirmation_state": alert.confirmation_state.value,
        "block_time": _iso(alert.block_time),
        "first_observed_at": _iso(alert.first_observed_at),
        "data_mode": alert.data_mode.value,
        "acknowledged_at": _iso(alert.acknowledged_at),
        "evidence": alert.evidence,
    }


def watch_to_json(db: Session, watch: Watch) -> dict[str, Any]:
    target = resolve_target(db, watch)
    last_run = db.execute(
        select(WatchPollRun)
        .where(WatchPollRun.watch_id == watch.id)
        .order_by(WatchPollRun.started_at.desc(), WatchPollRun.id)
        .limit(1)
    ).scalar_one_or_none()
    last_success = db.execute(
        select(WatchPollRun.completed_at)
        .where(
            WatchPollRun.watch_id == watch.id,
            WatchPollRun.status == WatchPollStatus.succeeded,
        )
        .order_by(WatchPollRun.completed_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return {
        "id": str(watch.id),
        "case_id": str(watch.case_id),
        "network_key": target.network_key,
        "address": target.address,
        "token_contract": target.asset.token_contract,
        "display_symbol": target.asset.display_symbol,
        "data_mode": watch.data_mode.value,
        "is_active": watch.is_active,
        "analysis_start": _iso(watch.analysis_start),
        "overlap_seconds": watch.overlap_seconds,
        "checkpoint_time": _iso(watch.checkpoint_time),
        "checkpoint_updated_at": _iso(watch.checkpoint_updated_at),
        "created_at": _iso(watch.created_at),
        "last_poll": (
            {
                "status": last_run.status.value,
                "coverage_status": last_run.coverage_status.value,
                "started_at": _iso(last_run.started_at),
                "completed_at": _iso(last_run.completed_at),
                "new_alerts": last_run.new_alerts,
                "error_class": last_run.error_class,
            }
            if last_run
            else None
        ),
        "last_successful_poll_at": _iso(last_success),
        "observation_method": "polling of indexed provider history; not a mempool feed",
    }
