"""Vincola quick_expense_shortcuts.name a 60 caratteri anche a schema.

Prima esisteva solo la validazione applicativa in
`api_chat_quick_expenses_custom_create` — un cap solo lato API può cambiare o
sparire in un refactor futuro senza che nessuno se ne accorga; qui diventa
un vincolo del database, verificato indipendentemente dal codice che scrive.

Revision ID: f8e7e7a858b3
Revises: 8f7ca225f00d
Create Date: 2026-09-03
"""
from alembic import op
import sqlalchemy as sa

revision = "f8e7e7a858b3"
down_revision = "8f7ca225f00d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "quick_expense_shortcuts", "name",
        existing_type=sa.String(), type_=sa.String(length=60), existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "quick_expense_shortcuts", "name",
        existing_type=sa.String(length=60), type_=sa.String(), existing_nullable=False,
    )
