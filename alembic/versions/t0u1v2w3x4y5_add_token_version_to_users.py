"""Aggiunge token_version alla tabella users per la revoca delle sessioni.

Abilita la funzionalità "ricordami" con sessioni persistenti revocabili: la
`token_version` viene salvata nel cookie di sessione al login e confrontata ad
ogni richiesta. Incrementandola (cambio password, "esci da tutti i dispositivi")
tutte le sessioni attive dell'utente diventano invalide senza dover ruotare la
FLASK_SECRET_KEY (che sloggherebbe invece tutti gli utenti).

Il default 0 vale sia per le righe esistenti (backfill) sia per i nuovi utenti.

Revision ID: t0u1v2w3x4y5
Revises: s0t1u2v3w4x5
Create Date: 2026-07-11 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "t0u1v2w3x4y5"
down_revision: Union[str, Sequence[str], None] = "s0t1u2v3w4x5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
