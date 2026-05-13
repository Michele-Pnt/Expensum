"""add_user_onboarding_preferences

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Aggiunge campi preferenze utente e stato onboarding alla tabella users."""
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(sa.Column('preferred_language', sa.String(), nullable=False, server_default='it'))
        batch_op.add_column(sa.Column('currency', sa.String(), nullable=False, server_default='EUR'))
        batch_op.add_column(sa.Column('timezone', sa.String(), nullable=False, server_default='Europe/Rome'))
        batch_op.add_column(sa.Column('lifestyle_json', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('monthly_budget', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('notification_time', sa.String(), nullable=True, server_default='08:00'))
        batch_op.add_column(sa.Column('notifications_enabled', sa.Boolean(), nullable=True, server_default='1'))
        batch_op.add_column(sa.Column('onboarding_step', sa.String(), nullable=True, server_default='pending'))
        batch_op.add_column(sa.Column('onboarding_completed_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Rimuove i campi preferenze utente e stato onboarding."""
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('onboarding_completed_at')
        batch_op.drop_column('onboarding_step')
        batch_op.drop_column('notifications_enabled')
        batch_op.drop_column('notification_time')
        batch_op.drop_column('monthly_budget')
        batch_op.drop_column('lifestyle_json')
        batch_op.drop_column('timezone')
        batch_op.drop_column('currency')
        batch_op.drop_column('preferred_language')
