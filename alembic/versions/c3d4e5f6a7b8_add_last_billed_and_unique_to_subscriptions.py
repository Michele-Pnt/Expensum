"""add_last_billed_to_subscriptions

Revision ID: c3d4e5f6a7b8
Revises: 1135fb2161e3
Create Date: 2026-04-20 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('subscriptions', sa.Column('last_billed', sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column('subscriptions', 'last_billed')
