"""Case work: cases, seeds, trace runs, states, findings, watches, exports, audit."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.settings import DataMode
from app.db.base import Base, BaseUnits, JSONColumn, UtcDateTime, new_uuid
from app.models.chain import _enum, data_mode_col
from app.models.enums import (
    AlertState,
    AttributionStatus,
    BoundaryReason,
    CaseAmountBasis,
    CaseFlowLinkage,
    ConfirmationState,
    CoverageStatus,
    ExecutionStatus,
    SeedMode,
    TraceRunStatus,
    WatchPollStatus,
)


class Case(Base):
    __tablename__ = "cases"
    __table_args__ = (
        UniqueConstraint("organization_id", "case_reference", name="uq_case_reference"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    case_reference: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(40), default="open")
    data_mode: Mapped[DataMode] = mapped_column(data_mode_col)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        UtcDateTime, server_default=func.now()
    )

    seeds: Mapped[list[CaseSeed]] = relationship(back_populates="case")


class CaseSeed(Base):
    """The starting point of a trace.

    ``incident`` mode requires an asset and asserts the seed carries case funds.
    ``address_discovery`` mode asserts nothing about victim funds (PRD section 2).
    """

    __tablename__ = "case_seeds"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=new_uuid)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    mode: Mapped[SeedMode] = mapped_column(_enum(SeedMode, "seed_mode"))
    network_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("networks.id", ondelete="RESTRICT"))
    address_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("addresses.id", ondelete="RESTRICT"))
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True
    )
    transfer_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transfer_events.id", ondelete="SET NULL"), nullable=True
    )
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assets.id", ondelete="RESTRICT"), nullable=True
    )
    amount_base_units: Mapped[int | None] = mapped_column(BaseUnits, nullable=True)
    incident_time: Mapped[dt.datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )
    window_start: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    window_end: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        UtcDateTime, server_default=func.now()
    )

    case: Mapped[Case] = relationship(back_populates="seeds")


class TraceRun(Base):
    __tablename__ = "trace_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=new_uuid)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    case_seed_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("case_seeds.id", ondelete="CASCADE"))
    status: Mapped[TraceRunStatus] = mapped_column(_enum(TraceRunStatus, "trace_run_status"))
    engine_version: Mapped[str] = mapped_column(String(40))
    label_set_version: Mapped[str] = mapped_column(String(40))
    analysis_cutoff: Mapped[dt.datetime] = mapped_column(UtcDateTime)
    budgets: Mapped[dict[str, Any]] = mapped_column(JSONColumn, default=dict)
    input_hash: Mapped[str] = mapped_column(String(80))
    coverage_status: Mapped[CoverageStatus] = mapped_column(
        _enum(CoverageStatus, "coverage_status")
    )
    data_mode: Mapped[DataMode] = mapped_column(data_mode_col)
    started_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    cancelled_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class TraceState(Base):
    """A position in the walk: address + asset + arrival event + branch (D010)."""

    __tablename__ = "trace_states"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=new_uuid)
    trace_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trace_runs.id", ondelete="CASCADE"))
    parent_state_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("trace_states.id", ondelete="CASCADE"), nullable=True
    )
    network_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("networks.id", ondelete="RESTRICT"))
    address_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("addresses.id", ondelete="RESTRICT"))
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"))
    arrival_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transfer_events.id", ondelete="SET NULL"), nullable=True
    )
    hop_depth: Mapped[int] = mapped_column(Integer, default=0)
    #: Ordered event references from the seed to here. Makes branches distinguishable.
    branch_path: Mapped[list[str]] = mapped_column(JSONColumn, default=list)
    status: Mapped[str] = mapped_column(String(40), default="pending")
    boundary_reason: Mapped[BoundaryReason | None] = mapped_column(
        _enum(BoundaryReason, "boundary_reason"), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        UtcDateTime, server_default=func.now()
    )


class Finding(Base):
    """A reportable conclusion. The four status axes are stored independently (D006)."""

    __tablename__ = "findings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=new_uuid)
    trace_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trace_runs.id", ondelete="CASCADE"))
    trace_state_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("trace_states.id", ondelete="SET NULL"), nullable=True
    )
    finding_type: Mapped[str] = mapped_column(String(60))
    attribution_status: Mapped[AttributionStatus] = mapped_column(
        _enum(AttributionStatus, "attribution_status")
    )
    coverage_status: Mapped[CoverageStatus] = mapped_column(
        _enum(CoverageStatus, "coverage_status")
    )
    case_flow_linkage: Mapped[CaseFlowLinkage] = mapped_column(
        _enum(CaseFlowLinkage, "case_flow_linkage")
    )
    boundary_reason: Mapped[BoundaryReason | None] = mapped_column(
        _enum(BoundaryReason, "boundary_reason"), nullable=True
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("entities.id", ondelete="SET NULL"), nullable=True
    )
    address_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("addresses.id", ondelete="SET NULL"), nullable=True
    )
    #: What the chain shows. Always populated for a transfer finding.
    observed_amount_base_units: Mapped[int | None] = mapped_column(BaseUnits, nullable=True)
    #: How any case-associated amount was derived. Defaults to honest ignorance.
    case_amount_basis: Mapped[CaseAmountBasis] = mapped_column(
        _enum(CaseAmountBasis, "case_amount_basis"),
        default=CaseAmountBasis.allocation_unknown,
    )
    case_amount_lower_base_units: Mapped[int | None] = mapped_column(BaseUnits, nullable=True)
    case_amount_upper_base_units: Mapped[int | None] = mapped_column(BaseUnits, nullable=True)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONColumn, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(
        UtcDateTime, server_default=func.now()
    )


class Watch(Base):
    """A polled observation of one (network, address, verified asset), scoped to a case.

    The checkpoint is an observation frontier (D029): every qualifying event
    with ``block_time <= checkpoint_time`` was acquired by a complete, untruncated,
    error-free poll. It only moves forward on such a poll. ``cursor`` is unused:
    a TronGrid fingerprint is tied to one exact parameter set, so it is not a
    durable resume point.
    """

    __tablename__ = "watches"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=new_uuid)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    network_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("networks.id", ondelete="RESTRICT"))
    address_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("addresses.id", ondelete="RESTRICT"))
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assets.id", ondelete="RESTRICT"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    cursor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    data_mode: Mapped[DataMode] = mapped_column(data_mode_col)
    #: Events before this instant are out of scope. Defaults to the watch's creation.
    analysis_start: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: How far behind the checkpoint each poll deliberately re-reads.
    overlap_seconds: Mapped[int] = mapped_column(Integer, default=600)
    checkpoint_time: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    checkpoint_updated_at: Mapped[dt.datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        UtcDateTime, server_default=func.now()
    )


class WatchPollRun(Base):
    """Audit record of one bounded poll, written whether it succeeded or not (T3)."""

    __tablename__ = "watch_poll_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=new_uuid)
    watch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("watches.id", ondelete="CASCADE"))
    status: Mapped[WatchPollStatus] = mapped_column(_enum(WatchPollStatus, "watch_poll_status"))
    coverage_status: Mapped[CoverageStatus] = mapped_column(
        _enum(CoverageStatus, "coverage_status")
    )
    data_mode: Mapped[DataMode] = mapped_column(data_mode_col)
    provider: Mapped[str] = mapped_column(String(120))
    started_at: Mapped[dt.datetime] = mapped_column(UtcDateTime)
    completed_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    window_start: Mapped[dt.datetime] = mapped_column(UtcDateTime)
    window_end: Mapped[dt.datetime] = mapped_column(UtcDateTime)
    checkpoint_before: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    checkpoint_after: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    pages_fetched: Mapped[int] = mapped_column(Integer, default=0)
    provider_requests: Mapped[int | None] = mapped_column(Integer, nullable=True)
    events_observed: Mapped[int] = mapped_column(Integer, default=0)
    new_alerts: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_events: Mapped[int] = mapped_column(Integer, default=0)
    error_class: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Excluded-event counts by reason, acquisition records, limitations.
    summary: Mapped[dict[str, Any]] = mapped_column(JSONColumn, default=dict)


class Alert(Base):
    """One alert per (watch, rule, event_reference); the unique key is the idempotency guard."""

    __tablename__ = "alerts"
    __table_args__ = (UniqueConstraint("watch_id", "dedupe_key", name="uq_alert_dedupe"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=new_uuid)
    watch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("watches.id", ondelete="CASCADE"))
    rule_key: Mapped[str] = mapped_column(String(80))
    rule_version: Mapped[str] = mapped_column(String(40))
    dedupe_key: Mapped[str] = mapped_column(String(200))
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONColumn, default=dict)
    acknowledged_at: Mapped[dt.datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        UtcDateTime, server_default=func.now()
    )
    event_reference: Mapped[str] = mapped_column(String(200))
    data_mode: Mapped[DataMode] = mapped_column(data_mode_col)
    state: Mapped[AlertState] = mapped_column(
        _enum(AlertState, "alert_state"), default=AlertState.active
    )
    execution_status: Mapped[ExecutionStatus] = mapped_column(
        _enum(ExecutionStatus, "execution_status")
    )
    confirmation_state: Mapped[ConfirmationState] = mapped_column(
        _enum(ConfirmationState, "confirmation_state")
    )
    block_time: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    first_observed_at: Mapped[dt.datetime] = mapped_column(UtcDateTime)
    first_poll_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("watch_poll_runs.id", ondelete="SET NULL"), nullable=True
    )


class Export(Base):
    """Phase 10."""

    __tablename__ = "exports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=new_uuid)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    bundle_version: Mapped[str] = mapped_column(String(40))
    manifest_hash: Mapped[str] = mapped_column(String(128))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        UtcDateTime, server_default=func.now()
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(80))
    object_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    object_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    request_id: Mapped[str] = mapped_column(String(80))
    occurred_at: Mapped[dt.datetime] = mapped_column(
        UtcDateTime, server_default=func.now()
    )
    audit_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONColumn, default=dict)
