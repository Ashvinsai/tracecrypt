"""Durable, tenant-scoped intake, work queue, event index and analyst signals.

These are investigation records, never labels asserting guilt or ownership.
"""
from __future__ import annotations
import datetime as dt
import uuid
from typing import Any
from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, JSONColumn, UtcDateTime, new_uuid


class IntakeCredential(Base):
    __tablename__ = "intake_credentials"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(40))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, server_default=func.now())
    expires_at: Mapped[dt.datetime] = mapped_column(UtcDateTime)


class ComplaintIntake(Base):
    __tablename__ = "complaint_intakes"
    __table_args__ = (UniqueConstraint("organization_id", "source", "external_reference", name="uq_intake_source_reference"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    credential_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("intake_credentials.id", ondelete="SET NULL"))
    source: Mapped[str] = mapped_column(String(40))
    external_reference: Mapped[str] = mapped_column(String(120))
    data_mode: Mapped[str] = mapped_column(String(32))
    allegation_type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONColumn)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, server_default=func.now())


class InvestigationJob(Base):
    __tablename__ = "investigation_jobs"
    __table_args__ = (Index("ix_job_ready", "data_mode", "status", "available_at"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    intake_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("complaint_intakes.id", ondelete="SET NULL"), index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(30), default="trace")
    status: Mapped[str] = mapped_column(String(30), default="queued")
    data_mode: Mapped[str] = mapped_column(String(32))
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSONColumn)
    input_sha256: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    available_at: Mapped[dt.datetime] = mapped_column(UtcDateTime)
    lease_token: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, server_default=func.now())
    started_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    finished_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("investigation_snapshots.id", ondelete="SET NULL"))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(1000))
    outcome: Mapped[dict[str, Any]] = mapped_column(JSONColumn, default=dict)


class IndexedInvestigationEvent(Base):
    """Versioned observed events per saved run; not an entire-chain index.

    Repeated observations across runs are retained rather than overwriting
    history. Event identity is network-scoped. Raw exact amounts stay strings.
    """
    __tablename__ = "indexed_investigation_events"
    __table_args__ = (
        UniqueConstraint("run_id", "event_reference", name="uq_index_run_event"),
        Index("ix_event_from", "organization_id", "network_key", "data_mode", "from_address"),
        Index("ix_event_to", "organization_id", "network_key", "data_mode", "to_address"),
        Index("ix_event_asset_time", "organization_id", "network_key", "token_contract", "block_time"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("investigation_snapshots.id", ondelete="CASCADE"), index=True)
    network_key: Mapped[str] = mapped_column(String(40))
    data_mode: Mapped[str] = mapped_column(String(32))
    event_reference: Mapped[str] = mapped_column(String(256))
    from_address: Mapped[str] = mapped_column(String(128))
    to_address: Mapped[str] = mapped_column(String(128))
    token_contract: Mapped[str] = mapped_column(String(128))
    block_time: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)
    observed: Mapped[dict[str, Any]] = mapped_column(JSONColumn)
    observed_sha256: Mapped[str] = mapped_column(String(64))


class OperationSignal(Base):
    __tablename__ = "operation_signals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("investigation_jobs.id", ondelete="SET NULL"))
    data_mode: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(60))
    priority: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONColumn)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, server_default=func.now())
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    acknowledged_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime)


class CrossChainReview(Base):
    """Immutable, tenant-scoped protocol checks, separate from address tracing."""
    __tablename__ = "cross_chain_reviews"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=new_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, server_default=func.now())
    data_mode: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(64))
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSONColumn)
    evidence_bundle: Mapped[dict[str, Any]] = mapped_column(JSONColumn)
    bundle_sha256: Mapped[str] = mapped_column(String(64))
    continuation_job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("investigation_jobs.id", ondelete="SET NULL"))
