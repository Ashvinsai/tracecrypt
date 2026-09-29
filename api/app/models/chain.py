"""Chain observation model.

The constraints here are the ones that are expensive to get wrong later:
address identity (D002), asset identity (D003), amount precision (D004), and
event identity (D005).
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.settings import DataMode
from app.db.base import Base, BaseUnits, UtcDateTime, new_uuid
from app.models.enums import (
    AcquisitionStatus,
    AssetKind,
    ConfirmationState,
    CoverageStatus,
    EventKind,
    ExecutionStatus,
    NetworkFamily,
)


def _enum(py_enum: type, name: str) -> Enum:
    return Enum(
        py_enum,
        name=name,
        native_enum=True,
        values_callable=lambda e: [m.value for m in e],
    )


data_mode_col = _enum(DataMode, "data_mode")


class Network(Base):
    __tablename__ = "networks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=new_uuid)
    key: Mapped[str] = mapped_column(String(40), unique=True)
    display_name: Mapped[str] = mapped_column(String(100))
    family: Mapped[NetworkFamily] = mapped_column(_enum(NetworkFamily, "network_family"))
    #: NULL for TRON. Present for EVM. Never used to infer a network from an address (D002).
    chain_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    caip2: Mapped[str | None] = mapped_column(String(80), nullable=True)
    native_asset_symbol: Mapped[str] = mapped_column(String(20))
    is_supported: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Asset(Base):
    """Identity is (network, kind, token_contract). ``display_symbol`` is metadata (D003)."""

    __tablename__ = "assets"
    __table_args__ = (
        UniqueConstraint("network_id", "kind", "token_contract", name="uq_asset_identity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=new_uuid)
    network_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("networks.id", ondelete="RESTRICT"))
    kind: Mapped[AssetKind] = mapped_column(_enum(AssetKind, "asset_kind"))
    token_contract: Mapped[str | None] = mapped_column(String(128), nullable=True)
    decimals: Mapped[int] = mapped_column(Integer)
    display_symbol: Mapped[str] = mapped_column(String(40))
    #: Issuer or chain source proving this contract is the asset we claim it is.
    issuer_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    is_supported: Mapped[bool] = mapped_column(Boolean, default=False)
    data_mode: Mapped[DataMode] = mapped_column(data_mode_col)

    network: Mapped[Network] = relationship()


class Address(Base):
    """Identity is (network, canonical_address); the original input survives (D002)."""

    __tablename__ = "addresses"
    __table_args__ = (
        UniqueConstraint("network_id", "canonical_address", name="uq_address_identity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=new_uuid)
    network_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("networks.id", ondelete="RESTRICT"))
    canonical_address: Mapped[str] = mapped_column(String(128))
    original_input: Mapped[str] = mapped_column(String(128))
    address_format: Mapped[str] = mapped_column(String(40))
    first_observed_at: Mapped[dt.datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )
    data_mode: Mapped[DataMode] = mapped_column(data_mode_col)

    network: Mapped[Network] = relationship()


class Block(Base):
    __tablename__ = "blocks"
    __table_args__ = (UniqueConstraint("network_id", "block_hash", name="uq_block_identity"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=new_uuid)
    network_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("networks.id", ondelete="RESTRICT"))
    height: Mapped[int] = mapped_column(BigInteger)
    block_hash: Mapped[str] = mapped_column(String(128))
    parent_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    block_time: Mapped[dt.datetime] = mapped_column(UtcDateTime)
    is_canonical: Mapped[bool] = mapped_column(Boolean, default=True)
    observed_at: Mapped[dt.datetime] = mapped_column(
        UtcDateTime, server_default=func.now()
    )
    data_mode: Mapped[DataMode] = mapped_column(data_mode_col)


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (UniqueConstraint("network_id", "tx_hash", name="uq_transaction_identity"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=new_uuid)
    network_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("networks.id", ondelete="RESTRICT"))
    tx_hash: Mapped[str] = mapped_column(String(128))
    execution_status: Mapped[ExecutionStatus] = mapped_column(
        _enum(ExecutionStatus, "execution_status")
    )
    fee_base_units: Mapped[int | None] = mapped_column(BaseUnits, nullable=True)
    raw_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_mode: Mapped[DataMode] = mapped_column(data_mode_col)

    inclusions: Mapped[list[TransactionInclusion]] = relationship(back_populates="transaction")


class TransactionInclusion(Base):
    """Inclusion *history*, not a single FK.

    A reorg adds a row and flips ``is_canonical``. Nothing is deleted, because the
    fact that we once observed an inclusion is itself evidence (T7).
    """

    __tablename__ = "transaction_inclusions"
    __table_args__ = (UniqueConstraint("transaction_id", "block_id", name="uq_inclusion"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=new_uuid)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE")
    )
    block_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("blocks.id", ondelete="CASCADE"))
    index_in_block: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_canonical: Mapped[bool] = mapped_column(Boolean, default=True)
    observed_at: Mapped[dt.datetime] = mapped_column(
        UtcDateTime, server_default=func.now()
    )

    transaction: Mapped[Transaction] = relationship(back_populates="inclusions")
    block: Mapped[Block] = relationship()


class TransferEvent(Base):
    """One transfer. A transaction may hold many; identity is never the tx hash (D005)."""

    __tablename__ = "transfer_events"
    __table_args__ = (
        UniqueConstraint("network_id", "event_reference", name="uq_event_identity"),
        Index("ix_transfer_events_from", "from_address_id", "chain_sequence"),
        Index("ix_transfer_events_to", "to_address_id", "chain_sequence"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=new_uuid)
    network_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("networks.id", ondelete="RESTRICT"))
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE")
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"))
    #: e.g. ``tron:<tx_hash>:<event_index>`` — chain-specific, documented in D005.
    event_reference: Mapped[str] = mapped_column(String(200))
    event_kind: Mapped[EventKind] = mapped_column(_enum(EventKind, "event_kind"))
    from_address_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("addresses.id", ondelete="RESTRICT"), nullable=True
    )
    to_address_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("addresses.id", ondelete="RESTRICT"), nullable=True
    )
    amount_base_units: Mapped[int] = mapped_column(BaseUnits)
    execution_status: Mapped[ExecutionStatus] = mapped_column(
        _enum(ExecutionStatus, "execution_status")
    )
    confirmation_state: Mapped[ConfirmationState] = mapped_column(
        _enum(ConfirmationState, "confirmation_state")
    )
    block_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("blocks.id", ondelete="SET NULL"), nullable=True
    )
    block_time: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: Sortable ``<height>:<index_in_block>:<event_index>``; NULL when ordering is ambiguous.
    chain_sequence: Mapped[str | None] = mapped_column(String(80), nullable=True)
    #: True when the source could not supply ordering. We never invent an index (D005).
    ordering_ambiguous: Mapped[bool] = mapped_column(Boolean, default=False)
    is_zero_value: Mapped[bool] = mapped_column(Boolean, default=False)
    parser_version: Mapped[str] = mapped_column(String(20))
    data_mode: Mapped[DataMode] = mapped_column(data_mode_col)
    created_at: Mapped[dt.datetime] = mapped_column(
        UtcDateTime, server_default=func.now()
    )

    asset: Mapped[Asset] = relationship()
    transaction: Mapped[Transaction] = relationship()
    from_address: Mapped[Address | None] = relationship(foreign_keys=[from_address_id])
    to_address: Mapped[Address | None] = relationship(foreign_keys=[to_address_id])


class Acquisition(Base):
    """One provider interaction. A failure is a failure, never an empty history (T3)."""

    __tablename__ = "acquisitions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=new_uuid)
    source: Mapped[str] = mapped_column(String(80))
    provider: Mapped[str] = mapped_column(String(80))
    endpoint: Mapped[str] = mapped_column(Text)
    request_params_hash: Mapped[str] = mapped_column(String(80))
    requested_at: Mapped[dt.datetime] = mapped_column(UtcDateTime)
    observed_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    response_hash: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[AcquisitionStatus] = mapped_column(
        _enum(AcquisitionStatus, "acquisition_status")
    )
    coverage_status: Mapped[CoverageStatus] = mapped_column(
        _enum(CoverageStatus, "coverage_status")
    )
    error_class: Mapped[str | None] = mapped_column(String(80), nullable=True)
    analysis_cutoff: Mapped[dt.datetime] = mapped_column(UtcDateTime)
    parser_version: Mapped[str] = mapped_column(String(20))
    data_mode: Mapped[DataMode] = mapped_column(data_mode_col)
    #: Required for RECORDED_PUBLIC: when the replayed capture was actually taken.
    capture_time: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)


class AcquisitionEvent(Base):
    """Which acquisition produced which event."""

    __tablename__ = "acquisition_events"

    acquisition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("acquisitions.id", ondelete="CASCADE"), primary_key=True
    )
    transfer_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transfer_events.id", ondelete="CASCADE"), primary_key=True
    )
