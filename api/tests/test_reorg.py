"""A11: block inclusion history survives a reorganization."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chain import TransactionInclusion
from tests.helpers import make_block, make_transaction


def test_inclusion_history_preserved(db: Session, tron) -> None:
    """A11: the orphaned inclusion is marked non-canonical, never deleted."""
    orphan = make_block(db, tron, 71_000_090, canonical=False)
    winner = make_block(db, tron, 71_000_090)
    tx = make_transaction(db, tron, "tx_reorg_subject")

    db.add(TransactionInclusion(transaction_id=tx.id, block_id=orphan.id, index_in_block=4))
    db.flush()

    # The reorg arrives: the first inclusion loses, a new one is recorded.
    first = db.execute(
        select(TransactionInclusion).where(TransactionInclusion.block_id == orphan.id)
    ).scalar_one()
    first.is_canonical = False
    db.add(TransactionInclusion(transaction_id=tx.id, block_id=winner.id, index_in_block=2))
    db.flush()

    rows = (
        db.execute(
            select(TransactionInclusion).where(TransactionInclusion.transaction_id == tx.id)
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2, "the losing inclusion is evidence and must survive"
    assert sum(1 for r in rows if r.is_canonical) == 1
    assert {r.index_in_block for r in rows} == {2, 4}
