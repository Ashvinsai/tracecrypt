"""Load a synthetic/recorded fixture into the database.

Deliberately fictional addresses and service names must never reach a production
label database or a live provider (T13). The loader enforces that by refusing to
write anything under a LIVE data mode.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings import DataMode
from app.models.chain import (
    Address,
    Asset,
    Block,
    Network,
    Transaction,
    TransactionInclusion,
    TransferEvent,
)
from app.models.enums import (
    AssetKind,
    ConfirmationState,
    EventKind,
    ExecutionStatus,
)


class FixtureLoadError(RuntimeError):
    pass


@dataclass
class LoadResult:
    assets_loaded: int = 0
    addresses_loaded: int = 0
    blocks_loaded: int = 0
    transactions_loaded: int = 0
    events_loaded: int = 0


def _parse_time(value: str | None) -> dt.datetime | None:
    if value is None:
        return None
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def load_fixture_into_db(
    db: Session,
    fixture_path: Path | str,
    *,
    network: Network,
    data_mode: DataMode = DataMode.SYNTHETIC,
    parser_version: str = "fixture-0.1.0",
) -> LoadResult:
    if data_mode is DataMode.LIVE:
        raise FixtureLoadError(
            "refusing to load fixture rows under data_mode=LIVE; "
            "synthetic identifiers must never enter live data"
        )

    doc: dict[str, Any] = json.loads(Path(fixture_path).read_text())
    declared = DataMode(doc.get("data_mode", DataMode.SYNTHETIC.value))
    if declared is DataMode.LIVE:
        raise FixtureLoadError(f"fixture {fixture_path} declares data_mode=LIVE")

    result = LoadResult()
    assets: dict[str | None, Asset] = {}
    addresses: dict[str, Address] = {}
    blocks: dict[str, Block] = {}
    transactions: dict[str, Transaction] = {}

    def get_asset(spec: dict[str, Any]) -> Asset:
        contract = spec.get("token_contract")
        if contract in assets:
            return assets[contract]
        existing = db.execute(
            select(Asset).where(
                Asset.network_id == network.id,
                Asset.kind == AssetKind.token,
                Asset.token_contract == contract,
            )
        ).scalar_one_or_none()
        if existing is None:
            existing = Asset(
                network_id=network.id,
                kind=AssetKind.token,
                token_contract=contract,
                decimals=spec["decimals"],
                display_symbol=spec["display_symbol"],
                issuer_reference=None,
                is_supported=contract == doc["assets"]["supported"]["token_contract"],
                data_mode=data_mode,
            )
            db.add(existing)
            db.flush()
            result.assets_loaded += 1
        assets[contract] = existing
        return existing

    def get_address(value: str | None) -> Address | None:
        if value is None:
            return None
        if value in addresses:
            return addresses[value]
        existing = db.execute(
            select(Address).where(
                Address.network_id == network.id,
                Address.canonical_address == value,
            )
        ).scalar_one_or_none()
        if existing is None:
            existing = Address(
                network_id=network.id,
                canonical_address=value,
                original_input=value,
                address_format="base58check",
                data_mode=data_mode,
            )
            db.add(existing)
            db.flush()
            result.addresses_loaded += 1
        addresses[value] = existing
        return existing

    def get_block(raw: dict[str, Any]) -> Block | None:
        block_hash = raw.get("block_hash")
        if block_hash is None:
            return None
        if block_hash in blocks:
            return blocks[block_hash]
        existing = db.execute(
            select(Block).where(Block.network_id == network.id, Block.block_hash == block_hash)
        ).scalar_one_or_none()
        if existing is None:
            existing = Block(
                network_id=network.id,
                height=raw["block_height"],
                block_hash=block_hash,
                parent_hash=raw.get("parent_block_hash"),
                block_time=_parse_time(raw.get("block_time")) or dt.datetime.now(dt.UTC),
                is_canonical=True,
                data_mode=data_mode,
            )
            db.add(existing)
            db.flush()
            result.blocks_loaded += 1
        blocks[block_hash] = existing
        return existing

    def get_transaction(raw: dict[str, Any], block: Block | None) -> Transaction:
        tx_hash = raw["tx_hash"]
        if tx_hash in transactions:
            return transactions[tx_hash]
        existing = db.execute(
            select(Transaction).where(
                Transaction.network_id == network.id, Transaction.tx_hash == tx_hash
            )
        ).scalar_one_or_none()
        if existing is None:
            existing = Transaction(
                network_id=network.id,
                tx_hash=tx_hash,
                execution_status=ExecutionStatus(raw.get("execution_status", "success")),
                data_mode=data_mode,
            )
            db.add(existing)
            db.flush()
            result.transactions_loaded += 1
            if block is not None:
                db.add(
                    TransactionInclusion(
                        transaction_id=existing.id,
                        block_id=block.id,
                        index_in_block=raw.get("index_in_block"),
                        is_canonical=True,
                    )
                )
                db.flush()
        transactions[tx_hash] = existing
        return existing

    for raw in doc.get("events", []):
        asset = get_asset(raw["asset"])
        block = get_block(raw)
        tx = get_transaction(raw, block)
        ordering_ambiguous = bool(raw.get("ordering_ambiguous", False))
        event_index = raw.get("event_index")
        if event_index is None:
            ordering_ambiguous = True
        chain_sequence = (
            None
            if ordering_ambiguous or raw.get("block_height") is None
            else f"{raw['block_height']:012d}:{raw.get('index_in_block', 0):06d}:{event_index:06d}"
        )
        amount = int(raw["amount_base_units"])
        db.add(
            TransferEvent(
                network_id=network.id,
                transaction_id=tx.id,
                asset_id=asset.id,
                event_reference=raw["event_reference"],
                event_kind=EventKind(raw.get("event_kind", "transfer")),
                from_address_id=getattr(get_address(raw.get("from_address")), "id", None),
                to_address_id=getattr(get_address(raw.get("to_address")), "id", None),
                amount_base_units=amount,
                execution_status=ExecutionStatus(raw.get("execution_status", "success")),
                confirmation_state=ConfirmationState(raw.get("confirmation_state", "confirmed")),
                block_id=block.id if block else None,
                block_time=_parse_time(raw.get("block_time")),
                chain_sequence=chain_sequence,
                ordering_ambiguous=ordering_ambiguous,
                is_zero_value=amount == 0,
                parser_version=parser_version,
                data_mode=data_mode,
            )
        )
        result.events_loaded += 1

    db.flush()
    return result
