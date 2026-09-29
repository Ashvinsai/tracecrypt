"""Stage 4 monitoring: watch checkpoint, alert identity/state, poll-run audit (D029).

``watches`` and ``alerts`` were reserved empty by the initial schema. The new
NOT NULL columns (a watch's ``data_mode``, an alert's ``event_reference``) have
no honest default for a pre-existing row, so this migration refuses to run if
either table already holds rows rather than guess a data mode or event identity.

Revision ID: 4c0696953d8d
Revises: 9902ff974344
Create Date: 2026-09-23 20:50:50.458647

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import Text  # noqa: F401 - used by rendered JSONB variants
import app.db.base  # noqa: F401 - custom column types render as app.db.base.*
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '4c0696953d8d'
down_revision: Union[str, Sequence[str], None] = '9902ff974344'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DATA_MODE = ('LIVE', 'RECORDED_PUBLIC', 'SYNTHETIC')
COVERAGE_STATUS = ('complete_within_scope', 'partial', 'unknown', 'failed')
EXECUTION_STATUS = ('success', 'failed', 'reverted', 'unknown')
CONFIRMATION_STATE = ('provisional', 'confirmed', 'removed', 'unknown')
WATCH_POLL_STATUS = (
    'running', 'succeeded', 'partial', 'provider_failure', 'truncated', 'refused'
)
ALERT_STATE = ('active', 'retracted')
NEW_ENUMS = {'watch_poll_status': WATCH_POLL_STATUS, 'alert_state': ALERT_STATE}


def _enum(values: tuple[str, ...], name: str) -> sa.types.TypeEngine:
    """A native enum on PostgreSQL that reuses the named type rather than recreating it."""
    return sa.Enum(*values, name=name).with_variant(
        postgresql.ENUM(*values, name=name, create_type=False), 'postgresql'
    )


def _refuse_if_populated(table: str) -> None:
    count = op.get_bind().execute(sa.text(f'SELECT COUNT(*) FROM {table}')).scalar_one()
    if count:
        raise RuntimeError(
            f'{table} holds {count} row(s) written before monitoring existed; this '
            'migration will not invent a data mode or event identity for them'
        )


def upgrade() -> None:
    """Upgrade schema."""
    _refuse_if_populated('alerts')
    _refuse_if_populated('watches')

    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        for name, values in NEW_ENUMS.items():
            postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)

    with op.batch_alter_table('watches') as batch:
        batch.add_column(sa.Column('data_mode', _enum(DATA_MODE, 'data_mode'), nullable=False))
        batch.add_column(sa.Column('analysis_start', app.db.base.UtcDateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('overlap_seconds', sa.Integer(), nullable=False))
        batch.add_column(sa.Column('checkpoint_time', app.db.base.UtcDateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('checkpoint_updated_at', app.db.base.UtcDateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('created_by', sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            'fk_watches_created_by', 'users', ['created_by'], ['id'], ondelete='SET NULL'
        )

    op.create_table('watch_poll_runs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('watch_id', sa.Uuid(), nullable=False),
    sa.Column('status', _enum(WATCH_POLL_STATUS, 'watch_poll_status'), nullable=False),
    sa.Column('coverage_status', _enum(COVERAGE_STATUS, 'coverage_status'), nullable=False),
    sa.Column('data_mode', _enum(DATA_MODE, 'data_mode'), nullable=False),
    sa.Column('provider', sa.String(length=120), nullable=False),
    sa.Column('started_at', app.db.base.UtcDateTime(timezone=True), nullable=False),
    sa.Column('completed_at', app.db.base.UtcDateTime(timezone=True), nullable=True),
    sa.Column('window_start', app.db.base.UtcDateTime(timezone=True), nullable=False),
    sa.Column('window_end', app.db.base.UtcDateTime(timezone=True), nullable=False),
    sa.Column('checkpoint_before', app.db.base.UtcDateTime(timezone=True), nullable=True),
    sa.Column('checkpoint_after', app.db.base.UtcDateTime(timezone=True), nullable=True),
    sa.Column('pages_fetched', sa.Integer(), nullable=False),
    sa.Column('provider_requests', sa.Integer(), nullable=True),
    sa.Column('events_observed', sa.Integer(), nullable=False),
    sa.Column('new_alerts', sa.Integer(), nullable=False),
    sa.Column('duplicate_events', sa.Integer(), nullable=False),
    sa.Column('error_class', sa.String(length=40), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('summary', sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql'), nullable=False),
    sa.ForeignKeyConstraint(['watch_id'], ['watches.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )

    with op.batch_alter_table('alerts') as batch:
        batch.add_column(sa.Column('event_reference', sa.String(length=200), nullable=False))
        batch.add_column(sa.Column('data_mode', _enum(DATA_MODE, 'data_mode'), nullable=False))
        batch.add_column(sa.Column('state', _enum(ALERT_STATE, 'alert_state'), nullable=False))
        batch.add_column(sa.Column('execution_status', _enum(EXECUTION_STATUS, 'execution_status'), nullable=False))
        batch.add_column(sa.Column('confirmation_state', _enum(CONFIRMATION_STATE, 'confirmation_state'), nullable=False))
        batch.add_column(sa.Column('block_time', app.db.base.UtcDateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('first_observed_at', app.db.base.UtcDateTime(timezone=True), nullable=False))
        batch.add_column(sa.Column('first_poll_run_id', sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            'fk_alerts_first_poll_run_id',
            'watch_poll_runs',
            ['first_poll_run_id'],
            ['id'],
            ondelete='SET NULL',
        )


def downgrade() -> None:
    """Downgrade schema. Discards monitoring state; the reserved tables remain."""
    with op.batch_alter_table('alerts') as batch:
        batch.drop_constraint('fk_alerts_first_poll_run_id', type_='foreignkey')
        for column in (
            'first_poll_run_id', 'first_observed_at', 'block_time', 'confirmation_state',
            'execution_status', 'state', 'data_mode', 'event_reference',
        ):
            batch.drop_column(column)
    op.drop_table('watch_poll_runs')
    with op.batch_alter_table('watches') as batch:
        batch.drop_constraint('fk_watches_created_by', type_='foreignkey')
        for column in (
            'created_by', 'checkpoint_updated_at', 'checkpoint_time', 'overlap_seconds',
            'analysis_start', 'data_mode',
        ):
            batch.drop_column(column)

    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        for name in NEW_ENUMS:
            postgresql.ENUM(name=name).drop(bind, checkfirst=True)
