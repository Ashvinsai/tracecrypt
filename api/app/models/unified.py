"""Case-scoped immutable investigation snapshots for the combined workspace."""
from __future__ import annotations
import datetime as dt
import uuid
from typing import Any
from sqlalchemy import ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, JSONColumn, UtcDateTime, new_uuid


class InvestigationSnapshot(Base):
    __tablename__ = "investigation_snapshots"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=new_uuid)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, server_default=func.now())
    data_mode: Mapped[str] = mapped_column(String(32))
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSONColumn)
    trace: Mapped[dict[str, Any]] = mapped_column(JSONColumn)
    intelligence: Mapped[dict[str, Any]] = mapped_column(JSONColumn)
    trace_sha256: Mapped[str] = mapped_column(String(64))
    intelligence_sha256: Mapped[str] = mapped_column(String(64))
    request_id: Mapped[str] = mapped_column(String(80))
