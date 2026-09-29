"""A12, A13, A18: failed, approval, and zero-value events are evidence, not transfers."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chain import TransferEvent
from app.models.enums import ConfirmationState, EventKind, ExecutionStatus
from tests.helpers import make_event, make_transaction


def confirmed_transfers(db: Session, network):
    """The one query the tracing engine is allowed to walk.

    Exclusion is by predicate. Nothing is deleted, because a failed attempt is
    itself evidence of intent.
    """
    return (
        db.execute(
            select(TransferEvent).where(
                TransferEvent.network_id == network.id,
                TransferEvent.event_kind == EventKind.transfer,
                TransferEvent.execution_status == ExecutionStatus.success,
                TransferEvent.confirmation_state == ConfirmationState.confirmed,
            )
        )
        .scalars()
        .all()
    )


def test_failed_excluded_from_confirmed(db: Session, tron, synthetic_usdt) -> None:
    """A12: a failed transaction's event is stored but never traced as a transfer."""
    good_tx = make_transaction(db, tron, "tx_good")
    make_event(db, tron, synthetic_usdt, good_tx, event_reference="tron:tx_good:0", amount=100)

    bad_tx = make_transaction(db, tron, "tx_failed", execution_status=ExecutionStatus.failed)
    failed = make_event(
        db,
        tron,
        synthetic_usdt,
        bad_tx,
        event_reference="tron:tx_failed:0",
        amount=100,
        execution_status=ExecutionStatus.failed,
    )

    assert db.get(TransferEvent, failed.id) is not None, "failed events must be preserved"
    refs = {e.event_reference for e in confirmed_transfers(db, tron)}
    assert "tron:tx_good:0" in refs
    assert "tron:tx_failed:0" not in refs


def test_approval_excluded_from_confirmed(db: Session, tron, synthetic_usdt) -> None:
    """A13: an approval moves no value and never appears on a transfer path."""
    tx = make_transaction(db, tron, "tx_approval")
    approval = make_event(
        db,
        tron,
        synthetic_usdt,
        tx,
        event_reference="tron:tx_approval:0",
        amount=0,
        event_kind=EventKind.approval,
    )
    assert db.get(TransferEvent, approval.id) is not None
    assert "tron:tx_approval:0" not in {e.event_reference for e in confirmed_transfers(db, tron)}


def test_zero_value_flagged(db: Session, tron, synthetic_usdt) -> None:
    """A18: a zero-value transfer is stored, flagged, and carries no case value."""
    tx = make_transaction(db, tron, "tx_zero")
    event = make_event(db, tron, synthetic_usdt, tx, event_reference="tron:tx_zero:0", amount=0)
    db.expire(event)
    stored = db.get(TransferEvent, event.id)
    assert stored is not None
    assert stored.is_zero_value is True
    assert stored.amount_base_units == 0
    # It is a confirmed transfer by execution, and still worth nothing to a case.
    assert stored in confirmed_transfers(db, tron)


def test_removed_event_is_not_settled(db: Session, tron, synthetic_usdt) -> None:
    """A reorg-removed event must not be reported as a settled transfer (T7)."""
    tx = make_transaction(db, tron, "tx_reorged")
    make_event(
        db,
        tron,
        synthetic_usdt,
        tx,
        event_reference="tron:tx_reorged:0",
        amount=12,
        confirmation_state=ConfirmationState.removed,
    )
    assert "tron:tx_reorged:0" not in {e.event_reference for e in confirmed_transfers(db, tron)}
