"""add_plan_changes_table

Revision ID: 1a2b3c4d5e6f
Revises: f1a2b3c4d5e6
Create Date: 2026-05-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '1a2b3c4d5e6f'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Aggiunge plan_changes per tracciare lo storico dei cambi piano.

    Permette a fetch_metrics.py di calcolare conversioni Free→Pro (upgrade)
    e churn Pro mensili senza leggere snapshot storici di user_plans.
    """
    op.create_table(
        'plan_changes',
        sa.Column('change_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('chat_id', sa.String(), sa.ForeignKey('users.chat_id'), nullable=False),
        sa.Column('from_plan', sa.String(), nullable=True),
        sa.Column('to_plan', sa.String(), nullable=False),
        sa.Column('change_type', sa.String(), nullable=False),
        sa.Column('changed_at', sa.DateTime(), nullable=False),
        sa.Column('reason', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('change_id'),
    )
    op.create_index('idx_plan_changes_chat_id',    'plan_changes', ['chat_id'])
    op.create_index('idx_plan_changes_changed_at', 'plan_changes', ['changed_at'])
    op.create_index('idx_plan_changes_type',       'plan_changes', ['change_type'])


def downgrade() -> None:
    op.drop_index('idx_plan_changes_type',       table_name='plan_changes')
    op.drop_index('idx_plan_changes_changed_at', table_name='plan_changes')
    op.drop_index('idx_plan_changes_chat_id',    table_name='plan_changes')
    op.drop_table('plan_changes')
