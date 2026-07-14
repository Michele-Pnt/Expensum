"""Aggiunge la tabella tx_events per lo split successi parsing per tipo x modalità.

Rispecchia in Postgres gli eventi già inviati a PostHog (expense_tracked /
expense_tracking_failed): per ogni tentativo di registrazione spesa/entrata/
trasferimento registra tipo transazione, modalità di input (testo/voce/foto/
bottone) ed esito (confirmed/cancelled/failed). Consente alla dashboard admin
di calcolare successi e success-rate per tipo x modalità senza dipendere dal
vendor esterno.

Tabella per-utente (FK su users), senza RLS: non contiene dati finanziari
(nessun importo/categoria/merchant), solo metadati del tentativo — coerente
con le regole di logging del progetto (mai contenuto libero utente).

Revision ID: w3x4y5z6a7b8
Revises: v2w3x4y5z6a7
Create Date: 2026-07-14 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "w3x4y5z6a7b8"
down_revision: Union[str, Sequence[str], None] = "v2w3x4y5z6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tx_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.String(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("tx_type", sa.String(), nullable=False),
        sa.Column("input_method", sa.String(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["chat_id"], ["users.chat_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tx_events_chat_id", "tx_events", ["chat_id"])
    op.create_index("ix_tx_events_occurred_at", "tx_events", ["occurred_at"])
    op.create_index(
        "ix_tx_events_type_method_occurred", "tx_events", ["tx_type", "input_method", "occurred_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_tx_events_type_method_occurred", "tx_events")
    op.drop_index("ix_tx_events_occurred_at", "tx_events")
    op.drop_index("ix_tx_events_chat_id", "tx_events")
    op.drop_table("tx_events")
