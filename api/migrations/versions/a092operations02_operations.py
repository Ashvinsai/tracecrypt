"""Durable complaint intake, job leases, indexed observations and signals.

Revision ID: a092operations02
Revises: a091unified01
"""
from alembic import op
import sqlalchemy as sa
from app.db.base import JSONColumn, UtcDateTime
revision = "a092operations02"
down_revision = "a091unified01"
branch_labels = None
depends_on = None


def upgrade():
    # The models are an exact declarative representation of this first revision
    # of the operations tables. Later changes require new migrations.
    from app.models.operations import (IntakeCredential, ComplaintIntake, InvestigationJob,
                                      IndexedInvestigationEvent, OperationSignal)
    bind = op.get_bind()
    for model in (IntakeCredential, ComplaintIntake, InvestigationJob, IndexedInvestigationEvent, OperationSignal):
        model.__table__.create(bind, checkfirst=False)


def downgrade():
    for name in ("operation_signals", "indexed_investigation_events", "investigation_jobs", "complaint_intakes", "intake_credentials"):
        op.drop_table(name)
