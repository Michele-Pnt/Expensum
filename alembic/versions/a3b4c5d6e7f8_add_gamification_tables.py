"""Crea le tabelle della gamification: contatori, achievement, XP, eventi report.

Tabelle di sistema, nello stesso dominio di `tx_events` e `user_streaks`: NESSUNA
policy RLS. L'isolamento fra utenti è applicativo (filtro su chat_id dietro
l'autenticazione). La contropartita è la disciplina sul contenuto: qui dentro solo
codici achievement, contatori interi e timestamp — mai importi, nomi categoria,
merchant o testo libero dell'utente.

Nota su `report_events`: è separata da `saved_reports` (dominio storage, con RLS e
inesistente su backend Notion) perché il tracking di generazione/apertura deve
funzionare su entrambi i backend senza toccare la pipeline dei report.

Questa migration crea solo lo schema. Il backfill retroattivo per gli utenti beta
— che ha bisogno dello storage finanziario per-utente e può durare minuti — vive in
`scripts/backfill_gamification.py`, fuori dalla transazione Alembic.

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-08-02 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, Sequence[str], None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_metric_counters",
        sa.Column("chat_id", sa.String(), nullable=False),
        sa.Column("metric", sa.String(length=48), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("value_date", sa.Date(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["chat_id"], ["users.chat_id"]),
        sa.PrimaryKeyConstraint("chat_id", "metric"),
    )
    op.create_index("ix_user_metric_counters_metric", "user_metric_counters", ["metric"])

    op.create_table(
        "user_achievements",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.String(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("dedup_key", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("xp_awarded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_value", sa.Integer(), nullable=True),
        sa.Column("unlocked_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("source", sa.String(length=12), nullable=False, server_default="live"),
        sa.Column("notified_telegram", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("seen_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["chat_id"], ["users.chat_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chat_id", "code", "dedup_key",
                            name="uq_user_achievements_chat_code_key"),
    )
    op.create_index("ix_user_achievements_chat_id", "user_achievements", ["chat_id"])
    op.create_index("ix_user_achievements_chat_unlocked", "user_achievements",
                    ["chat_id", "unlocked_at"])

    op.create_table(
        "user_gamification_profiles",
        sa.Column("chat_id", sa.String(), nullable=False),
        sa.Column("total_xp", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_level_up_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["chat_id"], ["users.chat_id"]),
        sa.PrimaryKeyConstraint("chat_id"),
    )

    op.create_table(
        "report_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.String(), nullable=False),
        sa.Column("share_token", sa.String(length=36), nullable=True),
        sa.Column("report_type", sa.String(length=20), nullable=False),
        sa.Column("event_type", sa.String(length=12), nullable=False),
        sa.Column("source", sa.String(length=12), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["chat_id"], ["users.chat_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chat_id", "share_token", "event_type",
                            name="uq_report_events_token_type"),
    )
    op.create_index("ix_report_events_chat_id", "report_events", ["chat_id"])
    op.create_index("ix_report_events_chat_type", "report_events", ["chat_id", "event_type"])


def downgrade() -> None:
    op.drop_index("ix_report_events_chat_type", table_name="report_events")
    op.drop_index("ix_report_events_chat_id", table_name="report_events")
    op.drop_table("report_events")

    op.drop_table("user_gamification_profiles")

    op.drop_index("ix_user_achievements_chat_unlocked", table_name="user_achievements")
    op.drop_index("ix_user_achievements_chat_id", table_name="user_achievements")
    op.drop_table("user_achievements")

    op.drop_index("ix_user_metric_counters_metric", table_name="user_metric_counters")
    op.drop_table("user_metric_counters")
