"""Aggiunge stato e conversione alle bozze mutuo.

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-08-24
"""
from alembic import op
import sqlalchemy as sa

revision = "e3f4a5b6c7d8"
down_revision = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mortgage_simulations", sa.Column("status", sa.String(length=20), nullable=False, server_default="active"))
    op.add_column("mortgage_simulations", sa.Column("converted_loan_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_mortgage_simulations_converted_loan", "mortgage_simulations", "loans", ["converted_loan_id"], ["id"])
    op.create_unique_constraint("uq_mortgage_simulations_converted_loan", "mortgage_simulations", ["converted_loan_id"])
    op.create_index("ix_mortgage_simulations_user_status", "mortgage_simulations", ["user_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_mortgage_simulations_user_status", table_name="mortgage_simulations")
    op.drop_constraint("uq_mortgage_simulations_converted_loan", "mortgage_simulations", type_="unique")
    op.drop_constraint("fk_mortgage_simulations_converted_loan", "mortgage_simulations", type_="foreignkey")
    op.drop_column("mortgage_simulations", "converted_loan_id")
    op.drop_column("mortgage_simulations", "status")
