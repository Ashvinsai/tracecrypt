"""A01-A03, A15: one transaction can carry many transfers (D005)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.chain import TransferEvent
from tests.helpers import make_event, make_transaction


def test_multiple_events_one_transaction(db: Session, tron, synthetic_usdt) -> None:
    """A01: both transfers in one transaction persist and are both retrievable."""
    tx = make_transaction(db, tron, "tx_seed_multi")
    make_event(db, tron, synthetic_usdt, tx, event_reference="tron:tx_seed_multi:0", amount=100)
    make_event(db, tron, synthetic_usdt, tx, event_reference="tron:tx_seed_multi:1", amount=7)

    rows = (
        db.execute(select(TransferEvent).where(TransferEvent.transaction_id == tx.id))
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert sorted(r.amount_base_units for r in rows) == [7, 100]
    assert {r.event_reference for r in rows} == {
        "tron:tx_seed_multi:0",
        "tron:tx_seed_multi:1",
    }


def test_event_reference_unique(db: Session, tron, synthetic_usdt) -> None:
    """A02: the same (network, event_reference) cannot be stored twice."""
    tx = make_transaction(db, tron, "tx_dup")
    make_event(db, tron, synthetic_usdt, tx, event_reference="tron:tx_dup:0", amount=1)
    with pytest.raises(IntegrityError):
        make_event(db, tron, synthetic_usdt, tx, event_reference="tron:tx_dup:0", amount=1)


def test_tx_hash_is_not_event_identity(db: Session, tron, synthetic_usdt) -> None:
    """A03: no constraint exists that would let a tx hash collapse distinct events."""
    unique_columns = {
        tuple(sorted(c.name for c in constraint.columns))
        for constraint in TransferEvent.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("event_reference", "network_id") in unique_columns
    for cols in unique_columns:
        assert "transaction_id" not in cols, (
            "a unique constraint involving transaction_id would deduplicate real transfers"
        )


def test_no_invented_event_index(db: Session, tron, synthetic_usdt) -> None:
    """A15: no source index means ambiguity is recorded, not a guessed position."""
    tx = make_transaction(db, tron, "tx_ambiguous")
    event = make_event(
        db,
        tron,
        synthetic_usdt,
        tx,
        event_reference="tron:tx_ambiguous:unknown-index",
        amount=3,
        chain_sequence=None,
        ordering_ambiguous=True,
    )
    db.expire(event)
    stored = db.get(TransferEvent, event.id)
    assert stored is not None
    assert stored.chain_sequence is None
    assert stored.ordering_ambiguous is True
