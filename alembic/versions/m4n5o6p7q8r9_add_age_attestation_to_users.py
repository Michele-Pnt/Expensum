"""add age_attestation_at to users

Revision ID: m4n5o6p7q8r9
Revises: l3m4n5o6p7q8
Create Date: 2026-07-01

Aggiunge users.age_attestation_at per registrare quando l'utente ha attestato
di avere 18+ anni (D.Lgs. 101/2018 + capacità contrattuale tier Pro).
Il timestamp viene scritto anche in audit_log con action='age_attestation'.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "m4n5o6p7q8r9"
down_revision: Union[str, Sequence[str], None] = "l3m4n5o6p7q8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("age_attestation_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "age_attestation_at")
