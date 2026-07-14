"""Aggiunge la tabella job_runs per il monitoraggio degli scheduled job.

Registra l'esito di ogni esecuzione dei job APScheduler (via listener) e dei job
di sistema (es. backup pg_dump). Consente alla dashboard admin di verificare che
i job di oggi siano girati, con che stato/return code, e di rilevare i no-show.

Tabella operativa senza dati personali: nessuna RLS (deve essere leggibile dalla
dashboard admin, che non fa binding tenant).

Revision ID: v2w3x4y5z6a7
Revises: u1v2w3x4y5z6
Create Date: 2026-07-14 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "v2w3x4y5z6a7"
down_revision: Union[str, Sequence[str], None] = "u1v2w3x4y5z6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("trigger_type", sa.String(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("return_code", sa.Integer(), nullable=True),
        sa.Column("error_text", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_runs_job_id", "job_runs", ["job_id"])
    op.create_index("ix_job_runs_finished_at", "job_runs", ["finished_at"])
    op.create_index("ix_job_runs_job_finished", "job_runs", ["job_id", "finished_at"])


def downgrade() -> None:
    op.drop_index("ix_job_runs_job_finished", "job_runs")
    op.drop_index("ix_job_runs_finished_at", "job_runs")
    op.drop_index("ix_job_runs_job_id", "job_runs")
    op.drop_table("job_runs")
