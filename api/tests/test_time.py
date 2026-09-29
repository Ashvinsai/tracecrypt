"""Timestamps are timezone-aware UTC on every dialect.

The tracer is chronological. A naive datetime coming back from storage would
either compare wrongly or raise, and on SQLite that is the default behaviour.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import Session

from app.core.settings import DataMode
from app.models.chain import Block
from tests.helpers import make_block


def test_block_time_returns_aware_utc(db: Session, tron) -> None:
    block = make_block(db, tron, 71_000_500)
    db.expire(block)
    stored = db.get(Block, block.id)
    assert stored is not None
    assert stored.block_time.tzinfo is not None
    assert stored.block_time.utcoffset() == dt.timedelta(0)


def test_non_utc_input_is_normalized(db: Session, tron) -> None:
    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    moment = dt.datetime(2026, 8, 1, 15, 30, tzinfo=ist)
    block = Block(
        network_id=tron.id,
        height=71_000_501,
        block_hash="blk-ist",
        block_time=moment,
        data_mode=DataMode.SYNTHETIC,
    )
    db.add(block)
    db.flush()
    db.expire(block)
    stored = db.get(Block, block.id)
    assert stored is not None
    assert stored.block_time == moment
    assert stored.block_time.hour == 10  # same instant, expressed in UTC


def test_naive_datetime_is_rejected(db: Session, tron) -> None:
    """A naive timestamp is ambiguous, and ambiguity in ordering is a wrong answer."""
    block = Block(
        network_id=tron.id,
        height=71_000_502,
        block_hash="blk-naive",
        block_time=dt.datetime(2026, 8, 1, 10, 0),  # noqa: DTZ001 - deliberately naive
        data_mode=DataMode.SYNTHETIC,
    )
    db.add(block)
    with pytest.raises(StatementError) as caught:
        db.flush()
    assert isinstance(caught.value.orig, ValueError)
    assert "naive datetime" in str(caught.value.orig)


def test_chronological_comparison_survives_storage(db: Session, tron) -> None:
    earlier = make_block(db, tron, 71_000_010)
    later = make_block(db, tron, 71_000_020)
    db.expire_all()
    a = db.get(Block, earlier.id)
    b = db.get(Block, later.id)
    assert a is not None and b is not None
    assert a.block_time < b.block_time
    assert a.block_time < dt.datetime.now(dt.UTC)
