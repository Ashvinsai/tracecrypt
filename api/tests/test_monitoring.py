"""Checkpointed new-event monitoring (Stage 4, D029): M01-M16.

No network access. ``ScriptedAdapter`` is a real ``ChainAdapter`` (like the
fixture adapter, D007) whose visible history a test changes between polls to
model late indexing; the TronGrid path is exercised offline through ``respx``
with the documented response shapes already used in ``test_tron_adapter.py``.
Restart tests use a file-backed SQLite database and a fresh engine, so what
survives is what was actually committed.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.base import (
    AcquisitionRecord,
    AssetRef,
    ChainAdapter,
    Direction,
    NormalizedTransfer,
    ProviderError,
    ProviderErrorClass,
    TransferPage,
)
from app.adapters.fixture import FixtureAdapter
from app.adapters.tron import SOLIDIFIED_RECEIPT_PATH, TronGridAdapter
from app.core.settings import DataMode
from app.db.base import Base, make_engine
from app.models.casework import Alert, Case, Watch, WatchPollRun
from app.models.chain import Asset, Network
from app.models.enums import (
    AcquisitionStatus,
    AlertState,
    AssetKind,
    ConfirmationState,
    CoverageStatus,
    EventKind,
    ExecutionStatus,
    NetworkFamily,
    WatchPollStatus,
)
from app.models.identity import Organization
from app.services import monitoring
from app.services.addresses import CanonicalAddress, canonicalize
from app.services.monitoring import MonitoringError, create_watch, dedupe_key, poll_watch
from tests.conftest import login

WATCHED = "TMrjWHAq1BPg9iG9ZaBTsG1AoxWERR29Mz"
PEER = "TRTqwgSLfUVziqWCyN6ZMThBkMgRvSaYtE"
OTHER = "THLEvxEkNUHb5bx3YsFDfePYjfYQEtAhJf"
SYN_CONTRACT = "TQghWzGAMfcTPWzsDGWREVqKbbFMzegaGY"
SPOOF_CONTRACT = "TUJmRrUmPrJZgqhRGjGKwbAzqZx3EHpoW2"
REAL_USDT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
T0 = dt.datetime(2026, 8, 1, 10, 0, tzinfo=dt.UTC)
SYN_ASSET = AssetRef("tron", SYN_CONTRACT, 6, "USDT-SYN")


def at(minutes: float) -> dt.datetime:
    return T0 + dt.timedelta(minutes=minutes)


def ev(
    tx: str,
    index: int | None = 0,
    *,
    minutes: float = 5,
    frm: str = PEER,
    to: str = WATCHED,
    amount: int = 1_000_000,
    kind: EventKind = EventKind.transfer,
    execution: ExecutionStatus = ExecutionStatus.success,
    confirmation: ConfirmationState = ConfirmationState.confirmed,
    contract: str = SYN_CONTRACT,
    block_height: int | None = 71_000_000,
) -> NormalizedTransfer:
    ambiguous = index is None
    return NormalizedTransfer(
        event_reference=f"tron:{tx}:unindexed:{amount:x}" if ambiguous else f"tron:{tx}:{index}",
        tx_hash=tx,
        event_kind=kind,
        asset=AssetRef("tron", contract, 6, "USDT-SYN"),
        from_address=frm,
        to_address=to,
        amount_base_units=amount,
        execution_status=execution,
        confirmation_state=confirmation,
        block_height=block_height,
        block_time=at(minutes),
        index_in_block=None if ambiguous else 3,
        event_index=index,
        ordering_ambiguous=ambiguous,
    )


class ScriptedAdapter(ChainAdapter):
    """A real adapter over an in-memory history that a test can grow between polls."""

    network_key = "tron"
    supported_data_modes = frozenset({DataMode.SYNTHETIC, DataMode.RECORDED_PUBLIC})

    def __init__(
        self,
        events: list[NormalizedTransfer] | None = None,
        *,
        page_size: int = 50,
        fail_on_page: int | None = None,
        fail_message: str = "provider quota exceeded",
    ) -> None:
        self.events = list(events or [])
        self.page_size = page_size
        self.fail_on_page = fail_on_page
        self.fail_message = fail_message
        self.calls: list[tuple[dt.datetime | None, dt.datetime, str | None]] = []

    def validate_address(self, value: str) -> CanonicalAddress:
        return canonicalize(self.network_key, value)

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
        self.calls.append((analysis_start, analysis_cutoff, cursor))
        page = int(cursor or 0)
        if self.fail_on_page is not None and page == self.fail_on_page:
            raise ProviderError(ProviderErrorClass.quota, self.fail_message)
        visible = [
            e
            for e in self.events
            if e.block_time is not None
            and e.block_time <= analysis_cutoff
            and (analysis_start is None or e.block_time >= analysis_start)
        ]
        size = min(limit, self.page_size)
        window = visible[page * size : (page + 1) * size]
        next_cursor = str(page + 1) if (page + 1) * size < len(visible) else None
        return TransferPage(
            events=window,
            next_cursor=next_cursor,
            acquisition=AcquisitionRecord(
                provider="scripted",
                endpoint="scripted://tron/transfers",
                requested_at=analysis_cutoff,
                status=AcquisitionStatus.succeeded,
                coverage_status=CoverageStatus.complete_within_scope,
                data_mode=DataMode.SYNTHETIC,
                analysis_cutoff=analysis_cutoff,
                parser_version="scripted-0",
            ),
        )


def _case(db: Session, org: Organization, mode: DataMode = DataMode.SYNTHETIC) -> Case:
    case = Case(
        organization_id=org.id,
        case_reference=f"MON-{uuid.uuid4().hex[:8]}",
        title="monitoring test",
        data_mode=mode,
    )
    db.add(case)
    db.flush()
    return case


def _watch(db: Session, case: Case, **kwargs) -> Watch:
    params = {
        "network_key": "tron",
        "address": WATCHED,
        "token_contract": SYN_CONTRACT,
        "data_mode": case.data_mode,
        "analysis_start": T0,
        "overlap_seconds": 600,
        "now": T0,
    }
    params.update(kwargs)
    return create_watch(db, case=case, **params)


async def _poll(db: Session, watch: Watch, adapter: ChainAdapter, minutes: float, **kwargs):
    kwargs.setdefault("observation_mode", DataMode.SYNTHETIC)
    return await poll_watch(db, watch, adapter, now=at(minutes), **kwargs)


def _alerts(db: Session, watch: Watch) -> list[Alert]:
    return list(
        db.execute(select(Alert).where(Alert.watch_id == watch.id).order_by(Alert.event_reference))
        .scalars()
        .all()
    )


@pytest.fixture
def watch(db: Session, tron, synthetic_usdt, org_a) -> Watch:
    return _watch(db, _case(db, org_a))


# -- M01-M03 -----------------------------------------------------------------


async def test_m01_one_new_event_creates_exactly_one_alert(db: Session, watch: Watch) -> None:
    big = 2**70 + 12345  # beyond float precision and int64
    adapter = ScriptedAdapter([ev("tx_one", 0, minutes=5, amount=big)])

    outcome = await _poll(db, watch, adapter, 10)

    assert outcome.status is WatchPollStatus.succeeded
    assert outcome.coverage_status is CoverageStatus.complete_within_scope
    assert outcome.new_alert_references == ["tron:tx_one:0"]
    alerts = _alerts(db, watch)
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.event_reference == "tron:tx_one:0"
    assert alert.dedupe_key == dedupe_key("tron:tx_one:0")
    assert alert.rule_key == "new_supported_token_transfer"
    assert alert.state is AlertState.active
    assert alert.data_mode is DataMode.SYNTHETIC
    event = alert.evidence["event"]
    assert event["amount_base_units"] == str(big)
    assert isinstance(event["amount_base_units"], str)
    assert event["asset"]["token_contract"] == SYN_CONTRACT
    assert event["tx_hash"] == "tx_one"
    assert event["from_address"] == PEER and event["to_address"] == WATCHED
    assert event["direction_relative_to_watch"] == "incoming"
    assert alert.evidence["execution_status"] == "success"
    assert alert.evidence["confirmation_state"] == "confirmed"
    assert any("not a mempool" in line for line in alert.evidence["limitations"])
    assert watch.checkpoint_time == at(10)
    assert outcome.checkpoint_after == at(10)


async def test_m02_polling_the_same_data_twice_does_not_duplicate(
    db: Session, watch: Watch
) -> None:
    adapter = ScriptedAdapter([ev("tx_one", 0, minutes=5)])

    first = await _poll(db, watch, adapter, 10)
    second = await _poll(db, watch, adapter, 10)

    assert first.new_alerts == 1
    assert second.status is WatchPollStatus.succeeded
    assert second.new_alerts == 0
    assert second.duplicate_events == 1
    assert len(_alerts(db, watch)) == 1


async def test_m03_replay_overlap_is_safe(db: Session, watch: Watch) -> None:
    e1, e2, e3 = ev("tx_1", minutes=5), ev("tx_2", minutes=15), ev("tx_3", minutes=25)
    adapter = ScriptedAdapter([e1, e2])

    first = await _poll(db, watch, adapter, 20)
    adapter.events.append(e3)
    second = await _poll(db, watch, adapter, 30)

    # The second poll deliberately re-reads 10 minutes behind the checkpoint.
    assert second.window_start == at(20) - dt.timedelta(seconds=600)
    assert adapter.calls[-1][0] == at(10)
    assert first.new_alert_references == ["tron:tx_1:0", "tron:tx_2:0"]
    assert second.new_alert_references == ["tron:tx_3:0"]
    assert second.duplicate_events == 1  # E2, re-read in the overlap
    assert [a.event_reference for a in _alerts(db, watch)] == [
        "tron:tx_1:0",
        "tron:tx_2:0",
        "tron:tx_3:0",
    ]


# -- M04 / M13: restart against a durable database ----------------------------


def _file_db(tmp_path: Path):
    engine = make_engine(f"sqlite+pysqlite:///{tmp_path / 'monitor.db'}")
    Base.metadata.create_all(engine)
    return engine


def _seed_file_db(engine) -> uuid.UUID:
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        network = Network(
            key="tron",
            display_name="TRON",
            family=NetworkFamily.account,
            native_asset_symbol="TRX",
            is_supported=True,
        )
        db.add(network)
        db.flush()
        db.add(
            Asset(
                network_id=network.id,
                kind=AssetKind.token,
                token_contract=SYN_CONTRACT,
                decimals=6,
                display_symbol="USDT-SYN",
                is_supported=True,
                data_mode=DataMode.SYNTHETIC,
            )
        )
        org = Organization(name="Cell", slug=f"cell-{uuid.uuid4().hex[:6]}")
        db.add(org)
        db.flush()
        watch = _watch(db, _case(db, org))
        db.commit()
        return watch.id


async def test_m04_restart_recovery_does_not_realert(tmp_path: Path) -> None:
    engine = _file_db(tmp_path)
    watch_id = _seed_file_db(engine)
    e1, e2 = ev("tx_1", minutes=5), ev("tx_2", minutes=15)

    with sessionmaker(bind=engine, expire_on_commit=False)() as db:
        watch = db.get(Watch, watch_id)
        assert watch is not None
        assert (await _poll(db, watch, ScriptedAdapter([e1]), 10)).new_alerts == 1
    engine.dispose()

    # A new process: new engine, new session, new adapter, same file.
    engine = make_engine(f"sqlite+pysqlite:///{tmp_path / 'monitor.db'}")
    with sessionmaker(bind=engine, expire_on_commit=False)() as db:
        watch = db.get(Watch, watch_id)
        assert watch is not None
        assert watch.checkpoint_time == at(10)
        outcome = await _poll(db, watch, ScriptedAdapter([e1, e2]), 20)
        assert outcome.new_alert_references == ["tron:tx_2:0"]
        assert outcome.duplicate_events == 1
        assert len(_alerts(db, watch)) == 2
    engine.dispose()


async def test_m13_alert_persisted_but_checkpoint_not_advanced_does_not_duplicate(
    tmp_path: Path,
) -> None:
    engine = _file_db(tmp_path)
    watch_id = _seed_file_db(engine)
    e1 = ev("tx_1", minutes=5)

    with sessionmaker(bind=engine, expire_on_commit=False)() as db:
        watch = db.get(Watch, watch_id)
        assert watch is not None
        await _poll(db, watch, ScriptedAdapter([e1]), 10)
        # Simulate the crash window: the alert is durable, the checkpoint is not.
        watch.checkpoint_time = None
        watch.checkpoint_updated_at = None
        db.commit()
    engine.dispose()

    engine = make_engine(f"sqlite+pysqlite:///{tmp_path / 'monitor.db'}")
    with sessionmaker(bind=engine, expire_on_commit=False)() as db:
        watch = db.get(Watch, watch_id)
        assert watch is not None and watch.checkpoint_time is None
        outcome = await _poll(db, watch, ScriptedAdapter([e1]), 10)
        assert outcome.status is WatchPollStatus.succeeded
        assert outcome.new_alerts == 0
        assert outcome.duplicate_events == 1
        assert len(_alerts(db, watch)) == 1
    engine.dispose()


async def test_m13_the_database_rejects_a_duplicate_alert(db: Session, watch: Watch) -> None:
    await _poll(db, watch, ScriptedAdapter([ev("tx_1")]), 10)
    duplicate = Alert(
        watch_id=watch.id,
        rule_key="new_supported_token_transfer",
        rule_version="1",
        dedupe_key=dedupe_key("tron:tx_1:0"),
        evidence={},
        event_reference="tron:tx_1:0",
        data_mode=DataMode.SYNTHETIC,
        execution_status=ExecutionStatus.success,
        confirmation_state=ConfirmationState.confirmed,
        first_observed_at=at(10),
    )
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(duplicate)
        db.flush()


async def test_m13_a_racing_insert_is_absorbed_by_the_unique_key(
    db: Session, watch: Watch, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = ScriptedAdapter([ev("tx_1")])
    await _poll(db, watch, adapter, 10)
    # Hide the existing alert from the application-level pre-check, as a
    # concurrent writer would; only the database constraint remains.
    monkeypatch.setattr(monitoring, "_existing_alerts", lambda *_a, **_k: {})

    outcome = await _poll(db, watch, adapter, 10)

    assert outcome.new_alerts == 0
    assert outcome.duplicate_events == 1
    assert len(_alerts(db, watch)) == 1


# -- M05-M08, M10: event identity and qualification ---------------------------


async def test_m05_two_transfers_in_one_transaction_are_two_alerts(
    db: Session, watch: Watch
) -> None:
    adapter = ScriptedAdapter(
        [ev("tx_multi", 0, amount=5_000_000), ev("tx_multi", 1, amount=5_000_000)]
    )

    outcome = await _poll(db, watch, adapter, 10)

    alerts = _alerts(db, watch)
    assert outcome.new_alerts == 2
    assert [a.event_reference for a in alerts] == ["tron:tx_multi:0", "tron:tx_multi:1"]
    assert {a.evidence["event"]["tx_hash"] for a in alerts} == {"tx_multi"}


async def test_m06_failed_and_reverted_transfers_do_not_alert(db: Session, watch: Watch) -> None:
    adapter = ScriptedAdapter(
        [
            ev("tx_failed", execution=ExecutionStatus.failed),
            ev("tx_reverted", execution=ExecutionStatus.reverted),
        ]
    )

    outcome = await _poll(db, watch, adapter, 10)

    assert _alerts(db, watch) == []
    assert outcome.excluded == {"failed_execution": 1, "reverted_execution": 1}
    run = db.get(WatchPollRun, outcome.poll_run_id)
    assert run is not None
    assert {e["reason"] for e in run.summary["excluded_events"]} == {
        "failed_execution",
        "reverted_execution",
    }


async def test_m07_an_approval_never_becomes_a_transfer_alert(db: Session, watch: Watch) -> None:
    outcome = await _poll(
        db, watch, ScriptedAdapter([ev("tx_approve", kind=EventKind.approval)]), 10
    )

    assert _alerts(db, watch) == []
    assert outcome.excluded == {"approval": 1}


async def test_m08_same_symbol_wrong_contract_does_not_alert(db: Session, watch: Watch) -> None:
    spoof = ev("tx_spoof", contract=SPOOF_CONTRACT)
    assert spoof.asset.display_symbol == SYN_ASSET.display_symbol

    outcome = await _poll(db, watch, ScriptedAdapter([spoof]), 10)

    assert _alerts(db, watch) == []
    assert outcome.excluded == {"unsupported_asset_contract": 1}


@pytest.mark.parametrize(
    ("event", "reason"),
    [
        (ev("tx_zero", amount=0), "zero_value"),
        (ev("tx_elsewhere", frm=PEER, to=OTHER), "does_not_involve_watched_address"),
        (ev("tx_old", minutes=-30), "before_watch_scope"),
    ],
)
async def test_other_non_qualifying_events_are_excluded_with_a_reason(
    db: Session, watch: Watch, event: NormalizedTransfer, reason: str
) -> None:
    adapter = ScriptedAdapter([event])

    outcome = await poll_watch(
        db,
        watch,
        _widen(adapter),
        observation_mode=DataMode.SYNTHETIC,
        now=at(10),
    )

    assert _alerts(db, watch) == []
    assert outcome.excluded == {reason: 1}


def _widen(adapter: ScriptedAdapter) -> ScriptedAdapter:
    """Serve the whole history regardless of the requested lower bound, as a
    provider that ignores ``min_timestamp`` would; the monitor must still hold
    its own scope start."""
    original = adapter.fetch_transfers

    async def fetch(**kwargs):
        kwargs["analysis_start"] = None
        return await original(**kwargs)

    adapter.fetch_transfers = fetch  # type: ignore[method-assign]
    return adapter


async def test_outgoing_transfer_is_recorded_as_outgoing(db: Session, watch: Watch) -> None:
    await _poll(db, watch, ScriptedAdapter([ev("tx_out", frm=WATCHED, to=OTHER)]), 10)

    [alert] = _alerts(db, watch)
    assert alert.evidence["event"]["direction_relative_to_watch"] == "outgoing"


async def test_m10_pagination_repeats_collapse_but_same_tx_events_stay_distinct(
    db: Session, watch: Watch
) -> None:
    e1 = ev("tx_a", 0, minutes=1)
    e2 = ev("tx_b", 0, minutes=2)
    e3 = ev("tx_b", 1, minutes=2)
    # Page boundaries shift and the provider returns E2 on both pages.
    adapter = ScriptedAdapter([e1, e2, e2, e3], page_size=2)

    outcome = await _poll(db, watch, adapter, 10)

    assert outcome.pages_fetched == 2
    assert outcome.events_observed == 3
    assert outcome.duplicate_events == 1
    assert [a.event_reference for a in _alerts(db, watch)] == [
        "tron:tx_a:0",
        "tron:tx_b:0",
        "tron:tx_b:1",
    ]


async def test_a_reused_reference_with_different_content_is_reported(
    db: Session, watch: Watch
) -> None:
    original = ev("tx_c", 0, amount=1_000_000)
    altered = ev("tx_c", 0, amount=2_000_000)

    outcome = await _poll(db, watch, ScriptedAdapter([original, altered]), 10)

    run = db.get(WatchPollRun, outcome.poll_run_id)
    assert run is not None
    assert run.summary["conflicting_references"] == ["tron:tx_c:0"]
    assert len(_alerts(db, watch)) == 1


# -- M09, M14, truncation: failure is never "no activity" ---------------------


async def test_m09_provider_failure_is_not_an_empty_successful_poll(
    db: Session, watch: Watch
) -> None:
    adapter = ScriptedAdapter([ev("tx_1")], fail_on_page=0)

    outcome = await _poll(db, watch, adapter, 10)

    assert outcome.status is WatchPollStatus.provider_failure
    assert outcome.coverage_status is CoverageStatus.failed
    assert outcome.error_class == "quota"
    assert outcome.checkpoint_after is None and watch.checkpoint_time is None
    run = db.get(WatchPollRun, outcome.poll_run_id)
    assert run is not None
    assert run.status is WatchPollStatus.provider_failure
    assert run.coverage_status is CoverageStatus.failed
    assert run.new_alerts == 0
    assert outcome.to_json()["checkpoint_advanced"] is False


async def test_m14_checkpoint_does_not_skip_after_a_mid_window_failure(
    db: Session, watch: Watch
) -> None:
    events = [ev("tx_1", minutes=1), ev("tx_2", minutes=2), ev("tx_3", minutes=3)]
    adapter = ScriptedAdapter(events, page_size=1, fail_on_page=1)

    partial = await _poll(db, watch, adapter, 10)

    assert partial.status is WatchPollStatus.partial
    assert partial.coverage_status is CoverageStatus.partial
    assert partial.new_alert_references == ["tron:tx_1:0"]
    assert watch.checkpoint_time is None

    adapter.fail_on_page = None
    recovered = await _poll(db, watch, adapter, 11)

    assert recovered.window_start == T0  # nothing was skipped
    assert recovered.status is WatchPollStatus.succeeded
    assert recovered.new_alert_references == ["tron:tx_2:0", "tron:tx_3:0"]
    assert recovered.duplicate_events == 1
    assert watch.checkpoint_time == at(11)


async def test_a_truncated_window_does_not_advance_the_checkpoint(
    db: Session, watch: Watch
) -> None:
    adapter = ScriptedAdapter([ev("tx_1", minutes=1), ev("tx_2", minutes=2)], page_size=1)

    truncated = await _poll(db, watch, adapter, 10, max_pages=1)
    assert truncated.status is WatchPollStatus.truncated
    assert truncated.coverage_status is CoverageStatus.partial
    assert watch.checkpoint_time is None

    finished = await _poll(db, watch, adapter, 10, max_pages=5)
    assert finished.status is WatchPollStatus.succeeded
    assert finished.new_alert_references == ["tron:tx_2:0"]


async def test_a_provider_error_message_never_carries_the_api_key(
    db: Session, watch: Watch
) -> None:
    secret = "sk-live-0123456789abcdef"  # noqa: S105 - a test value, not a credential
    adapter = ScriptedAdapter(fail_on_page=0, fail_message=f"denied for key {secret}")

    outcome = await _poll(db, watch, adapter, 10, secrets=[secret])

    run = db.get(WatchPollRun, outcome.poll_run_id)
    assert run is not None
    assert secret not in (outcome.error_message or "")
    assert secret not in json.dumps(run.summary) + (run.error_message or "")
    assert "[redacted]" in (run.error_message or "")


# -- M11: ordering around the checkpoint ---------------------------------------


async def test_m11_same_timestamp_events_at_the_checkpoint_are_not_dropped(
    db: Session, tron, synthetic_usdt, org_a
) -> None:
    watch = _watch(db, _case(db, org_a), overlap_seconds=0)
    first = ev("tx_edge", 0, minutes=10)
    adapter = ScriptedAdapter([first])

    await _poll(db, watch, adapter, 10)
    assert watch.checkpoint_time == at(10)

    # Indexed after the first poll, at exactly the checkpoint instant and in the
    # same block: one with a known index, one whose position is unknown.
    same_block = ev("tx_edge", 1, minutes=10)
    ambiguous = ev("tx_edge_amb", None, minutes=10)
    adapter.events += [same_block, ambiguous]
    outcome = await _poll(db, watch, adapter, 20)

    assert outcome.window_start == at(10)  # inclusive, even with zero overlap
    assert sorted(outcome.new_alert_references) == sorted(
        [same_block.event_reference, ambiguous.event_reference]
    )
    assert outcome.duplicate_events == 1
    by_ref = {a.event_reference: a for a in _alerts(db, watch)}
    assert by_ref[ambiguous.event_reference].evidence["event"]["ordering_ambiguous"] is True
    assert by_ref[ambiguous.event_reference].evidence["event"]["chain_sequence"] is None


# -- Reorg / confirmation state --------------------------------------------------


async def test_a_removed_event_retracts_its_alert_without_deleting_it(
    db: Session, watch: Watch
) -> None:
    provisional = ev("tx_reorg", confirmation=ConfirmationState.provisional)
    adapter = ScriptedAdapter([provisional])
    await _poll(db, watch, adapter, 10)
    [alert] = _alerts(db, watch)
    assert alert.confirmation_state is ConfirmationState.provisional

    adapter.events = [ev("tx_reorg", confirmation=ConfirmationState.removed)]
    outcome = await _poll(db, watch, adapter, 15)

    [alert] = _alerts(db, watch)
    assert outcome.retracted_references == ["tron:tx_reorg:0"]
    assert alert.state is AlertState.retracted
    assert alert.confirmation_state is ConfirmationState.removed
    history = alert.evidence["state_history"]
    assert [h["confirmation_state"] for h in history] == ["provisional", "removed"]
    assert "retracted" in history[-1]["reason"]


async def test_a_provisional_alert_is_upgraded_when_confirmed(db: Session, watch: Watch) -> None:
    adapter = ScriptedAdapter([ev("tx_p", confirmation=ConfirmationState.provisional)])
    await _poll(db, watch, adapter, 10)
    adapter.events = [ev("tx_p", confirmation=ConfirmationState.confirmed)]

    outcome = await _poll(db, watch, adapter, 12)

    [alert] = _alerts(db, watch)
    assert outcome.new_alerts == 0
    assert alert.state is AlertState.active
    assert alert.confirmation_state is ConfirmationState.confirmed
    assert len(alert.evidence["state_history"]) == 2


async def test_a_removed_event_never_seen_before_creates_no_alert(
    db: Session, watch: Watch
) -> None:
    outcome = await _poll(
        db, watch, ScriptedAdapter([ev("tx_gone", confirmation=ConfirmationState.removed)]), 10
    )

    assert _alerts(db, watch) == []
    assert outcome.excluded == {"removed": 1}


# -- M12: data modes -------------------------------------------------------------


@pytest.fixture
def live_usdt(db: Session, tron) -> Asset:
    asset = Asset(
        network_id=tron.id,
        kind=AssetKind.token,
        token_contract=REAL_USDT,
        decimals=6,
        display_symbol="USDT",
        is_supported=True,
        data_mode=DataMode.LIVE,
    )
    db.add(asset)
    db.flush()
    return asset


async def test_m12_a_synthetic_source_cannot_serve_a_live_watch(
    db: Session, org_a, live_usdt
) -> None:
    watch = _watch(
        db, _case(db, org_a, DataMode.LIVE), token_contract=REAL_USDT, data_mode=DataMode.LIVE
    )
    adapter = ScriptedAdapter([ev("tx_1", contract=REAL_USDT)])

    outcome = await poll_watch(db, watch, adapter, observation_mode=DataMode.LIVE)

    assert outcome.status is WatchPollStatus.refused
    assert adapter.calls == []
    assert _alerts(db, watch) == []
    assert watch.checkpoint_time is None


async def test_m12_a_poll_mode_must_match_the_watch_mode(db: Session, watch: Watch) -> None:
    adapter = ScriptedAdapter([ev("tx_1")])

    outcome = await _poll(db, watch, adapter, 10, observation_mode=DataMode.RECORDED_PUBLIC)

    assert outcome.status is WatchPollStatus.refused
    assert "never mixed" in (outcome.error_message or "")
    assert adapter.calls == []


def _fixture_file(tmp_path: Path, mode: DataMode) -> Path:
    doc = {
        "data_mode": mode.value,
        "events": [
            {
                "event_reference": "tron:tx_rec:0",
                "tx_hash": "tx_rec",
                "asset": {"token_contract": SYN_CONTRACT, "decimals": 6, "display_symbol": "X"},
                "from_address": PEER,
                "to_address": WATCHED,
                "amount_base_units": "4200000",
                "block_height": 71000001,
                "index_in_block": 1,
                "event_index": 0,
                "block_time": at(5).isoformat(),
            }
        ],
    }
    if mode is DataMode.RECORDED_PUBLIC:
        doc["capture_time"] = at(8).isoformat()
    path = tmp_path / f"{mode.value.lower()}.json"
    path.write_text(json.dumps(doc))
    return path


async def test_m12_recorded_replay_is_labelled_recorded_public(
    db: Session, tron, synthetic_usdt, org_a, tmp_path: Path
) -> None:
    watch = _watch(
        db, _case(db, org_a, DataMode.RECORDED_PUBLIC), data_mode=DataMode.RECORDED_PUBLIC
    )
    adapter = FixtureAdapter(_fixture_file(tmp_path, DataMode.RECORDED_PUBLIC))

    outcome = await _poll(db, watch, adapter, 10, observation_mode=DataMode.RECORDED_PUBLIC)

    [alert] = _alerts(db, watch)
    assert outcome.data_mode is DataMode.RECORDED_PUBLIC
    assert alert.data_mode is DataMode.RECORDED_PUBLIC
    assert alert.evidence["data_mode"] == "RECORDED_PUBLIC"
    assert alert.evidence["acquisition"]["capture_time"] == at(8).isoformat()
    assert alert.evidence["observation_lag"]["seconds"] is None
    assert alert.evidence["observation_lag"]["basis"] == "unavailable_recorded_replay"


async def test_m12_a_synthetic_fixture_cannot_pose_as_a_recorded_replay(
    db: Session, tron, synthetic_usdt, org_a, tmp_path: Path
) -> None:
    watch = _watch(
        db, _case(db, org_a, DataMode.RECORDED_PUBLIC), data_mode=DataMode.RECORDED_PUBLIC
    )
    adapter = FixtureAdapter(_fixture_file(tmp_path, DataMode.SYNTHETIC))

    outcome = await _poll(db, watch, adapter, 10, observation_mode=DataMode.RECORDED_PUBLIC)

    assert outcome.status is WatchPollStatus.refused
    assert "declares SYNTHETIC" in (outcome.error_message or "")
    assert _alerts(db, watch) == []


async def test_m12_the_live_adapter_refuses_a_synthetic_watch(db: Session, watch: Watch) -> None:
    def forbidden(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("a refused poll must not reach the provider")

    adapter = TronGridAdapter(
        "https://api.trongrid.io",
        api_key="k",
        client=httpx.AsyncClient(transport=httpx.MockTransport(forbidden)),
    )

    outcome = await _poll(db, watch, adapter, 10)

    assert outcome.status is WatchPollStatus.refused
    assert "SYNTHETIC" in (outcome.error_message or "")
    assert adapter.request_count == 0


async def test_m12_a_live_watch_rejects_a_synthetic_fixture_asset(
    db: Session, tron, synthetic_usdt, org_a
) -> None:
    with pytest.raises(MonitoringError, match="SYNTHETIC fixture asset"):
        _watch(db, _case(db, org_a, DataMode.LIVE), data_mode=DataMode.LIVE)


async def test_a_watch_needs_the_exact_supported_contract_not_a_symbol(
    db: Session, tron, synthetic_usdt, org_a
) -> None:
    with pytest.raises(MonitoringError, match="not a supported asset"):
        _watch(db, _case(db, org_a), token_contract="USDT-SYN")
    with pytest.raises(MonitoringError, match="not a supported asset"):
        _watch(db, _case(db, org_a), token_contract=SPOOF_CONTRACT)


# -- M15: observation lag ----------------------------------------------------------


async def test_m15_synthetic_lag_is_deterministic_and_labelled_simulated(
    db: Session, watch: Watch
) -> None:
    await _poll(db, watch, ScriptedAdapter([ev("tx_1", minutes=5)]), 10)

    [alert] = _alerts(db, watch)
    lag = alert.evidence["observation_lag"]
    assert lag["seconds"] == 300
    assert lag["basis"] == "simulated_clock"
    assert "not a latency measurement" in lag["note"]


async def test_m15_a_live_poll_cannot_use_an_injected_clock(db: Session, org_a, live_usdt) -> None:
    watch = _watch(
        db, _case(db, org_a, DataMode.LIVE), token_contract=REAL_USDT, data_mode=DataMode.LIVE
    )
    adapter = TronGridAdapter("https://api.trongrid.io", api_key="k")

    with pytest.raises(MonitoringError, match="injected clock"):
        await poll_watch(db, watch, adapter, observation_mode=DataMode.LIVE, now=at(10))


BASE = "https://api.trongrid.io"
TX_OK = "aa" * 32
TX_REVERT = "bb" * 32


def _history_row(tx: str, block_ms: int) -> dict:
    return {
        "transaction_id": tx,
        "block_timestamp": block_ms,
        "from": PEER,
        "to": WATCHED,
        "type": "Transfer",
        "value": "25000000",
        "token_info": {"symbol": "USDT", "address": REAL_USDT, "decimals": 6, "name": "Tether USD"},
    }


def _events_body(tx: str, block_ms: int) -> dict:
    return {
        "data": [
            {
                "block_number": 71000010,
                "block_timestamp": block_ms,
                "contract_address": REAL_USDT,
                "event_index": 0,
                "event_name": "Transfer",
                "transaction_id": tx,
                "result": {"from": PEER, "to": WATCHED, "value": "25000000"},
            }
        ]
    }


def _receipt(tx: str, result: str, block_ms: int) -> dict:
    return {
        "id": tx,
        "fee": 0,
        "blockNumber": 71000010,
        "blockTimeStamp": block_ms,
        "receipt": {"result": result},
    }


@respx.mock
async def test_m15_live_path_verifies_execution_and_measures_wall_clock_lag(
    db: Session, org_a, live_usdt
) -> None:
    """The TronGrid adapter end to end, offline: history, event index, receipt."""
    real_now = dt.datetime.now(dt.UTC)
    block_ms = int((real_now - dt.timedelta(minutes=5)).timestamp() * 1000)
    watch = _watch(
        db,
        _case(db, org_a, DataMode.LIVE),
        token_contract=REAL_USDT,
        data_mode=DataMode.LIVE,
        analysis_start=real_now - dt.timedelta(hours=1),
        now=real_now - dt.timedelta(hours=1),
    )
    respx.get(f"{BASE}/v1/accounts/{WATCHED}/transactions/trc20").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [_history_row(TX_OK, block_ms), _history_row(TX_REVERT, block_ms)],
                "meta": {},
            },
        )
    )
    respx.get(f"{BASE}/v1/transactions/{TX_OK}/events").mock(
        return_value=httpx.Response(200, json=_events_body(TX_OK, block_ms))
    )
    respx.get(f"{BASE}/v1/transactions/{TX_REVERT}/events").mock(
        return_value=httpx.Response(200, json=_events_body(TX_REVERT, block_ms))
    )

    def receipt(request: httpx.Request) -> httpx.Response:
        tx = json.loads(request.content)["value"]
        return httpx.Response(
            200, json=_receipt(tx, "SUCCESS" if tx == TX_OK else "REVERT", block_ms)
        )

    respx.post(f"{BASE}{SOLIDIFIED_RECEIPT_PATH}").mock(side_effect=receipt)
    adapter = TronGridAdapter(BASE, api_key="test-key")

    outcome = await poll_watch(db, watch, adapter, observation_mode=DataMode.LIVE)

    assert outcome.status is WatchPollStatus.succeeded
    assert outcome.new_alert_references == [f"tron:{TX_OK}:0"]
    assert outcome.excluded == {"reverted_execution": 1}
    [alert] = _alerts(db, watch)
    assert alert.data_mode is DataMode.LIVE
    assert alert.execution_status is ExecutionStatus.success
    assert alert.evidence["execution_verification"] == {"verified": True}
    lag = alert.evidence["observation_lag"]
    assert lag["basis"] == "live_wall_clock"
    assert 290 <= lag["seconds"] <= 600
    assert "not mempool" in lag["note"]
    run = db.get(WatchPollRun, outcome.poll_run_id)
    assert run is not None and run.provider_requests is not None and run.provider_requests >= 4
    assert "test-key" not in json.dumps(run.summary) + json.dumps(alert.evidence)


@respx.mock
async def test_live_http_error_is_a_provider_failure(db: Session, org_a, live_usdt) -> None:
    real_now = dt.datetime.now(dt.UTC)
    watch = _watch(
        db,
        _case(db, org_a, DataMode.LIVE),
        token_contract=REAL_USDT,
        data_mode=DataMode.LIVE,
        analysis_start=real_now - dt.timedelta(hours=1),
        now=real_now - dt.timedelta(hours=1),
    )
    respx.get(f"{BASE}/v1/accounts/{WATCHED}/transactions/trc20").mock(
        return_value=httpx.Response(429, json={"Error": "rate limited"})
    )

    outcome = await poll_watch(
        db, watch, TronGridAdapter(BASE, api_key="test-key"), observation_mode=DataMode.LIVE
    )

    assert outcome.status is WatchPollStatus.provider_failure
    assert outcome.error_class == "rate_limit"
    assert watch.checkpoint_time is None


# -- M16: authorization -------------------------------------------------------------


def _create_case_and_watch(client) -> tuple[str, str]:
    case = client.post(
        "/api/v1/cases", json={"case_reference": f"W-{uuid.uuid4().hex[:6]}", "title": "t"}
    )
    assert case.status_code == 201, case.text
    case_id = case.json()["data"]["id"]
    watch = client.post(
        f"/api/v1/cases/{case_id}/watches",
        json={
            "network_key": "tron",
            "address": WATCHED,
            "token_contract": SYN_CONTRACT,
            "analysis_start": T0.isoformat(),
        },
    )
    assert watch.status_code == 201, watch.text
    return case_id, watch.json()["data"]["id"]


def test_m16_routes_require_authentication(client, tron, synthetic_usdt) -> None:
    case_id = uuid.uuid4()
    assert client.get(f"/api/v1/cases/{case_id}/watches").status_code == 401
    assert (
        client.post(
            f"/api/v1/cases/{case_id}/watches",
            json={"network_key": "tron", "address": WATCHED, "token_contract": SYN_CONTRACT},
        ).status_code
        == 401
    )
    assert client.get(f"/api/v1/cases/{case_id}/watches/{uuid.uuid4()}/alerts").status_code == 401


async def test_m16_owner_sees_watch_and_alerts(
    client, db: Session, tron, synthetic_usdt, user_a
) -> None:
    assert login(client, user_a).status_code == 200
    case_id, watch_id = _create_case_and_watch(client)

    listed = client.get(f"/api/v1/cases/{case_id}/watches").json()["data"]
    assert [w["id"] for w in listed] == [watch_id]
    assert listed[0]["data_mode"] == "SYNTHETIC"
    assert listed[0]["checkpoint_time"] is None
    assert "not a mempool feed" in listed[0]["observation_method"]

    watch = db.get(Watch, uuid.UUID(watch_id))
    assert watch is not None
    await _poll(db, watch, ScriptedAdapter([ev("tx_api", amount=2**65)]), 10)

    alerts = client.get(f"/api/v1/cases/{case_id}/watches/{watch_id}/alerts")
    assert alerts.status_code == 200
    [alert] = alerts.json()["data"]
    assert alert["event_reference"] == "tron:tx_api:0"
    assert alert["evidence"]["event"]["amount_base_units"] == str(2**65)
    polls = client.get(f"/api/v1/cases/{case_id}/watches/{watch_id}/polls").json()["data"]
    assert polls[0]["status"] == "succeeded"


def test_m16_a_foreign_organization_gets_404_for_watch_and_alerts(
    client, tron, synthetic_usdt, user_a, user_b
) -> None:
    assert login(client, user_a).status_code == 200
    case_id, watch_id = _create_case_and_watch(client)
    client.post("/api/v1/auth/logout")

    assert login(client, user_b).status_code == 200
    assert client.get(f"/api/v1/cases/{case_id}/watches").status_code == 404
    assert client.get(f"/api/v1/cases/{case_id}/watches/{watch_id}").status_code == 404
    assert client.get(f"/api/v1/cases/{case_id}/watches/{watch_id}/alerts").status_code == 404
    assert (
        client.post(
            f"/api/v1/cases/{case_id}/watches",
            json={"network_key": "tron", "address": WATCHED, "token_contract": SYN_CONTRACT},
        ).status_code
        == 404
    )
    # Naming the foreign watch under one's own case does not reach it either.
    own = client.post("/api/v1/cases", json={"case_reference": "B-1", "title": "b"})
    own_case = own.json()["data"]["id"]
    assert client.get(f"/api/v1/cases/{own_case}/watches/{watch_id}/alerts").status_code == 404
    assert client.get(f"/api/v1/cases/{own_case}/watches/{watch_id}/polls").status_code == 404


def test_m16_a_symbol_is_not_accepted_as_the_watched_asset(
    client, tron, synthetic_usdt, user_a
) -> None:
    assert login(client, user_a).status_code == 200
    case = client.post("/api/v1/cases", json={"case_reference": "S-1", "title": "s"})
    case_id = case.json()["data"]["id"]

    response = client.post(
        f"/api/v1/cases/{case_id}/watches",
        json={"network_key": "tron", "address": WATCHED, "token_contract": "USDT"},
    )

    assert response.status_code == 422


def test_capability_row_is_partial_and_never_claims_a_verified_live_feed() -> None:
    from app.services.operational_status import build_capabilities

    for key_configured, mode in [(False, "SYNTHETIC"), (True, "LIVE")]:
        row = {
            c["key"]: c
            for c in build_capabilities(
                readiness=None,
                saved_run_count=0,
                live_key_configured=key_configured,
                configured_data_mode=mode,
            )
        }["monitoring"]
        assert row["status"] == "partial"
        assert "not a mempool feed" in row["detail"]
    assert "has not been verified" in row["detail"]
