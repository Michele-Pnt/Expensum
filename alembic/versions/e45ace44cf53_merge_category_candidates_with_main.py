"""merge_category_candidates_with_main

Revision ID: e45ace44cf53
Revises: a7b8c9d0e1f2, s1t2u3v4w5x6
Create Date: 2026-07-22 11:38:15.468331

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e45ace44cf53'
down_revision: Union[str, Sequence[str], None] = ('a7b8c9d0e1f2', 's1t2u3v4w5x6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
