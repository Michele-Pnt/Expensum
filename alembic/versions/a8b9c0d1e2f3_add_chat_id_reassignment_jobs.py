"""Aggiunge chat_id_reassignment_jobs: coda per reassign_user_chat_id.

L'operazione di riassegnazione chat_id (collegamento webapp<->Telegram, cambio
account Telegram) e' cross-tenant e richiede bypass RLS (owner). Prima di questa
migration girava in-process nel bot/dashboard con MIGRATION_DATABASE_URL sempre
residente in memoria nel processo esposto a internet. Da ora l'app (ruolo
DML-only) si limita ad arruolare la richiesta in questa tabella; un worker
separato (scripts/process_reassignment_jobs.py, unico processo con le
credenziali owner, mai esposto a rete) la esegue e aggiorna lo stato in a separate worker.

Tabella operativa senza dati finanziari (solo due chat_id e uno stato): nessuna
RLS, stesso criterio di job_runs.

Revision ID: a8b9c0d1e2f3
Revises: f7g8h9i0j1k2
Create Date: 2026-07-25 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "f7g8h9i0j1k2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_id_reassignment_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("old_chat_id", sa.String(), nullable=False),
        sa.Column("new_chat_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("error_text", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_id_reassignment_jobs_status", "chat_id_reassignment_jobs", ["status"]
    )
    op.create_index(
        "ix_chat_id_reassignment_jobs_old_chat_id",
        "chat_id_reassignment_jobs",
        ["old_chat_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_chat_id_reassignment_jobs_old_chat_id", "chat_id_reassignment_jobs"
    )
    op.drop_index("ix_chat_id_reassignment_jobs_status", "chat_id_reassignment_jobs")
    op.drop_table("chat_id_reassignment_jobs")
