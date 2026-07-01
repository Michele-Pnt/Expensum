"""Aggiunge tabella data_breaches: registro violazioni dati personali (Art. 33(5) GDPR).

Revision ID: l3m4n5o6p7q8
Revises: k2l3m4n5o6p7
Create Date: 2026-07-01 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "l3m4n5o6p7q8"
down_revision: Union[str, Sequence[str], None] = "k2l3m4n5o6p7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "data_breaches",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("breach_ref", sa.String(32), nullable=False, unique=True),
        sa.Column("detected_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("discovered_by", sa.String(100), nullable=True),
        sa.Column("nature", sa.Text, nullable=True),
        sa.Column("affected_data_categories", sa.JSON, nullable=True),
        sa.Column("affected_users_count", sa.Integer, nullable=True),
        sa.Column("risk_level", sa.String(10), nullable=True),
        sa.Column("garante_notified", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("garante_notified_at", sa.DateTime, nullable=True),
        sa.Column("garante_receipt_ref", sa.String(100), nullable=True),
        sa.Column("users_notified", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("users_notified_at", sa.DateTime, nullable=True),
        sa.Column("art34_exempt_reason", sa.Text, nullable=True),
        sa.Column("containment_measures", sa.Text, nullable=True),
        sa.Column("root_cause", sa.Text, nullable=True),
        sa.Column("status", sa.String(12), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_data_breaches_detected_at", "data_breaches", ["detected_at"])


def downgrade() -> None:
    op.drop_index("ix_data_breaches_detected_at", table_name="data_breaches")
    op.drop_table("data_breaches")
