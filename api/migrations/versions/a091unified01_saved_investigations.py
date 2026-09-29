"""Combined workspace: immutable case-scoped investigation snapshots.

Revision ID: a091unified01
Revises: 4c0696953d8d
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import app.db.base

revision = "a091unified01"
down_revision = "4c0696953d8d"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "investigation_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", app.db.base.UtcDateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("data_mode", sa.String(32), nullable=False),
        sa.Column("input_payload", app.db.base.JSONColumn, nullable=False),
        sa.Column("trace", app.db.base.JSONColumn, nullable=False),
        sa.Column("intelligence", app.db.base.JSONColumn, nullable=False),
        sa.Column("trace_sha256", sa.String(64), nullable=False),
        sa.Column("intelligence_sha256", sa.String(64), nullable=False),
        sa.Column("request_id", sa.String(80), nullable=False),
    )
    op.create_index("ix_investigation_snapshots_case_id", "investigation_snapshots", ["case_id"])


def downgrade():
    op.drop_index("ix_investigation_snapshots_case_id", table_name="investigation_snapshots")
    op.drop_table("investigation_snapshots")
