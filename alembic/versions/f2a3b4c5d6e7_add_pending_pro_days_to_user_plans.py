"""Aggiunge pending_pro_days a user_plans.

`extend_trial_days` impostava sempre `is_trial=True` con una scadenza calcolata.
Per un utente già Pro senza scadenza (beta permanente o abbonato pagante) questo
era un declassamento mascherato: un reward da referral lo portava da Pro illimitato
a un trial di 60 giorni. Adesso in quel caso il piano non viene toccato e i giorni
maturano qui, per essere applicati quando il Pro finisce davvero.

Default 0 e NOT NULL: le righe esistenti non hanno crediti pregressi.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-08-02 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_plans",
        sa.Column("pending_pro_days", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("user_plans", "pending_pro_days")
