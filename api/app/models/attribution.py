"""Attribution: entities, evidence, and label assertions.

Ownership, role, allegation, sanctions tag, and completeness are separate
concepts and stay separate columns. Conflicting assertions coexist; resolving a
conflict never deletes the losing record.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import ForeignKey, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.settings import DataMode
from app.db.base import Base, UtcDateTime, new_uuid
from app.models.chain import Address, _enum, data_mode_col
from app.models.enums import (
    AddressRole,
    AssertionType,
    AttributionStatus,
    EntityType,
    ReviewState,
)


class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(200))
    entity_type: Mapped[EntityType] = mapped_column(_enum(EntityType, "entity_type"))
    jurisdiction: Mapped[str | None] = mapped_column(String(80), nullable=True)
    parent_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("entities.id", ondelete="SET NULL"), nullable=True
    )
    data_mode: Mapped[DataMode] = mapped_column(data_mode_col)
    created_at: Mapped[dt.datetime] = mapped_column(
        UtcDateTime, server_default=func.now()
    )


class AttributionEvidence(Base):
    """Why we believe a label. Required for every assertion; no evidence, no label."""

    __tablename__ = "attribution_evidence"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=new_uuid)
    source_type: Mapped[str] = mapped_column(String(80))
    source_reference: Mapped[str] = mapped_column(Text)
    retrieval_date: Mapped[dt.datetime] = mapped_column(UtcDateTime)
    document_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    methodology: Mapped[str] = mapped_column(Text)
    reviewer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reuse_terms: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        UtcDateTime, server_default=func.now()
    )


class LabelAssertion(Base):
    """One claim about one address, with provenance and a validity interval.

    Only ``assertion_type='service_control'`` with ``review_state='accepted'``
    and a validity interval covering the observation time may terminate a trace
    branch. A ``deposit_candidate`` never can.
    """

    __tablename__ = "label_assertions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=new_uuid)
    address_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("addresses.id", ondelete="CASCADE"))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("entities.id", ondelete="SET NULL"), nullable=True
    )
    assertion_type: Mapped[AssertionType] = mapped_column(_enum(AssertionType, "assertion_type"))
    address_role: Mapped[AddressRole] = mapped_column(_enum(AddressRole, "address_role"))
    evidence_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("attribution_evidence.id", ondelete="RESTRICT")
    )
    review_state: Mapped[ReviewState] = mapped_column(_enum(ReviewState, "review_state"))
    attribution_status: Mapped[AttributionStatus] = mapped_column(
        _enum(AttributionStatus, "attribution_status")
    )
    valid_from: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    valid_to: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_verified_at: Mapped[dt.datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )
    label_set_version: Mapped[str] = mapped_column(String(40))
    data_mode: Mapped[DataMode] = mapped_column(data_mode_col)
    created_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        UtcDateTime, server_default=func.now()
    )

    address: Mapped[Address] = relationship()
    entity: Mapped[Entity | None] = relationship()
    evidence: Mapped[AttributionEvidence] = relationship()

    def covers(self, moment: dt.datetime) -> bool:
        """Is this assertion valid at ``moment``? Open bounds mean unbounded."""
        if self.valid_from is not None and moment < self.valid_from:
            return False
        return not (self.valid_to is not None and moment > self.valid_to)

    def can_terminate_trace(self, moment: dt.datetime) -> bool:
        return (
            self.assertion_type is AssertionType.service_control
            and self.review_state is ReviewState.accepted
            and self.covers(moment)
        )
