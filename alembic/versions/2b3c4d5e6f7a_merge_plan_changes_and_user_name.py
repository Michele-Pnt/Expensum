"""merge plan_changes and user_name_fields branches

Revision ID: 2b3c4d5e6f7a
Revises: 1a2b3c4d5e6f, b3c4d5e6f7a8
Create Date: 2026-05-17 00:01:00.000000

"""
from typing import Sequence, Union

revision: str = '2b3c4d5e6f7a'
down_revision: Union[str, Sequence[str], None] = ('1a2b3c4d5e6f', 'b3c4d5e6f7a8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
