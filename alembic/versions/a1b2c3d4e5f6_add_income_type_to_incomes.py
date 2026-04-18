"""add_income_type_to_incomes

Revision ID: a1b2c3d4e5f6
Revises: f7b2c56cec79
Create Date: 2026-04-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f7b2c56cec79'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Aggiunge la colonna income_type alla tabella incomes.
    # nullable=True per compatibilità con righe esistenti senza tipo.
    op.add_column(
        'incomes',
        sa.Column('income_type', sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('incomes', 'income_type')
