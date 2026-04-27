"""add_entity_fields

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-23 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('accounts', sa.Column('account_type', sa.String(), nullable=True))
    op.add_column('user_categories', sa.Column('monthly_budget', sa.Float(), nullable=True))
    op.add_column('subscriptions', sa.Column('sub_type', sa.String(), nullable=True))
    op.add_column('subscriptions', sa.Column('account_id', sa.Integer(), nullable=True))
    op.add_column('subscriptions', sa.Column('category_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('subscriptions', 'category_id')
    op.drop_column('subscriptions', 'account_id')
    op.drop_column('subscriptions', 'sub_type')
    op.drop_column('user_categories', 'monthly_budget')
    op.drop_column('accounts', 'account_type')
