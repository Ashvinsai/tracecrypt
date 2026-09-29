"""Case-scoped checked protocol reviews.

Revision ID: a093crosschain03
Revises: a092operations02
"""
from alembic import op
import sqlalchemy as sa
from app.db.base import JSONColumn, UtcDateTime
revision='a093crosschain03'
down_revision='a092operations02'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('cross_chain_reviews',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('organization_id',sa.Uuid(),sa.ForeignKey('organizations.id',ondelete='CASCADE'),nullable=False),
        sa.Column('case_id',sa.Uuid(),sa.ForeignKey('cases.id',ondelete='CASCADE'),nullable=False),
        sa.Column('created_by',sa.Uuid(),sa.ForeignKey('users.id',ondelete='SET NULL'),nullable=True),
        sa.Column('created_at',UtcDateTime(),server_default=sa.func.now(),nullable=False),
        sa.Column('data_mode',sa.String(32),nullable=False),sa.Column('status',sa.String(64),nullable=False),
        sa.Column('input_payload',JSONColumn,nullable=False),sa.Column('evidence_bundle',JSONColumn,nullable=False),
        sa.Column('bundle_sha256',sa.String(64),nullable=False),
        sa.Column('continuation_job_id',sa.Uuid(),sa.ForeignKey('investigation_jobs.id',ondelete='SET NULL'),nullable=True))
    op.create_index('ix_cross_chain_reviews_organization_id','cross_chain_reviews',['organization_id'])
    op.create_index('ix_cross_chain_reviews_case_id','cross_chain_reviews',['case_id'])


def downgrade():op.drop_table('cross_chain_reviews')
