"""Aggiunge il sistema di referral: codice su tally_leads e tabella reward.

Ogni lead Tally riceve un referral_code opaco al submit (usabile come link
d'invito); referred_by_code traccia da chi è stato invitato. lifetime_founder_*
segnano lo sblocco (via 3 referral andati a buon fine) dell'accesso garantito
alla futura offerta Lifetime Founder — oggi solo marketing, nessuna logica di
acquisto esiste ancora nel backend, il flag va solo persistito per honorarlo
in futuro.

referral_rewards traccia i reward Pro (60gg) da applicare: uno per ogni
'referred', uno soltanto (tetto fisso, non additivo) per il 'referrer'.

Revision ID: z6a7b8c9d0e1
Revises: y5z6a7b8c9d0
Create Date: 2026-07-20 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "z6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "y5z6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tally_leads", sa.Column("referral_code", sa.String(), nullable=True))
    op.add_column("tally_leads", sa.Column("referred_by_code", sa.String(), nullable=True))
    op.add_column(
        "tally_leads",
        sa.Column("lifetime_founder_guaranteed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("tally_leads", sa.Column("lifetime_founder_guaranteed_at", sa.DateTime(), nullable=True))
    op.create_unique_constraint("uq_tally_leads_referral_code", "tally_leads", ["referral_code"])
    op.create_index("ix_tally_leads_referral_code", "tally_leads", ["referral_code"])
    op.create_index("ix_tally_leads_referred_by_code", "tally_leads", ["referred_by_code"])

    op.create_table(
        "referral_rewards",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("beneficiary_email", sa.String(), nullable=False),
        sa.Column("beneficiary_chat_id", sa.String(), nullable=True),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("days_granted", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("source_tally_lead_id", sa.Integer(), sa.ForeignKey("tally_leads.id"), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_referral_rewards_beneficiary_email", "referral_rewards", ["beneficiary_email"])


def downgrade() -> None:
    op.drop_index("ix_referral_rewards_beneficiary_email", table_name="referral_rewards")
    op.drop_table("referral_rewards")
    op.drop_index("ix_tally_leads_referred_by_code", table_name="tally_leads")
    op.drop_index("ix_tally_leads_referral_code", table_name="tally_leads")
    op.drop_constraint("uq_tally_leads_referral_code", "tally_leads", type_="unique")
    op.drop_column("tally_leads", "lifetime_founder_guaranteed_at")
    op.drop_column("tally_leads", "lifetime_founder_guaranteed")
    op.drop_column("tally_leads", "referred_by_code")
    op.drop_column("tally_leads", "referral_code")
