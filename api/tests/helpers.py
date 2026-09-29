"""Shared builders for observation rows."""

from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from app.core.settings import DataMode
from app.models.chain import Block, Transaction, TransferEvent
from app.models.enums import ConfirmationState, EventKind, ExecutionStatus

T0 = dt.datetime(2026, 8, 1, 10, 0, tzinfo=dt.UTC)


def make_block(db: Session, network, height: int, *, canonical: bool = True) -> Block:
    block = Block(
        network_id=network.id,
        height=height,
        block_hash=f"blk{height}" if canonical else f"blk{height}-orphan",
        parent_hash=f"blk{height - 1}",
        block_time=T0 + dt.timedelta(minutes=height % 1000),
        is_canonical=canonical,
        data_mode=DataMode.SYNTHETIC,
    )
    db.add(block)
    db.flush()
    return block


def make_transaction(
    db: Session,
    network,
    tx_hash: str,
    *,
    execution_status: ExecutionStatus = ExecutionStatus.success,
) -> Transaction:
    tx = Transaction(
        network_id=network.id,
        tx_hash=tx_hash,
        execution_status=execution_status,
        data_mode=DataMode.SYNTHETIC,
    )
    db.add(tx)
    db.flush()
    return tx


def make_event(
    db: Session,
    network,
    asset,
    tx: Transaction,
    *,
    event_reference: str,
    amount: int,
    event_kind: EventKind = EventKind.transfer,
    execution_status: ExecutionStatus = ExecutionStatus.success,
    confirmation_state: ConfirmationState = ConfirmationState.confirmed,
    chain_sequence: str | None = "000071000010:000003:000000",
    ordering_ambiguous: bool = False,
    from_address_id=None,
    to_address_id=None,
) -> TransferEvent:
    event = TransferEvent(
        network_id=network.id,
        transaction_id=tx.id,
        asset_id=asset.id,
        event_reference=event_reference,
        event_kind=event_kind,
        from_address_id=from_address_id,
        to_address_id=to_address_id,
        amount_base_units=amount,
        execution_status=execution_status,
        confirmation_state=confirmation_state,
        chain_sequence=chain_sequence,
        ordering_ambiguous=ordering_ambiguous,
        is_zero_value=(amount == 0),
        parser_version="test-0.1.0",
        data_mode=DataMode.SYNTHETIC,
    )
    db.add(event)
    db.flush()
    return event
