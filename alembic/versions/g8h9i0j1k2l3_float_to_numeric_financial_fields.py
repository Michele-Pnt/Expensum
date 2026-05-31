"""Migra i campi monetari da Float a Numeric per precisione decimale corretta.

Revision ID: g8h9i0j1k2l3
Revises: 2b3c4d5e6f7a
Create Date: 2026-05-24 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g8h9i0j1k2l3"
down_revision: Union[str, Sequence[str], None] = "2b3c4d5e6f7a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Tabelle e colonne da migrare Float → Numeric
_FINANCIAL_COLS: list[tuple[str, str, sa.Numeric]] = [
    ("expenses",                 "amount",               sa.Numeric(12, 2)),
    ("incomes",                  "amount",               sa.Numeric(12, 2)),
    ("accounts",                 "opening_balance",      sa.Numeric(12, 2)),
    ("user_categories",          "monthly_budget",       sa.Numeric(12, 2)),
    ("user_category_notion_links", "average",            sa.Numeric(12, 2)),
    ("subscriptions",            "amount",               sa.Numeric(12, 2)),
    ("users",                    "monthly_budget",       sa.Numeric(12, 2)),
    ("llm_pricing",              "input_cost_per_1k",    sa.Numeric(12, 8)),
    ("llm_pricing",              "output_cost_per_1k",   sa.Numeric(12, 8)),
    ("llm_pricing",              "cached_input_cost_per_1k", sa.Numeric(12, 8)),
    ("llm_pricing",              "thinking_cost_per_1k", sa.Numeric(12, 8)),
    ("llm_usage_events",         "estimated_cost_amount", sa.Numeric(12, 8)),
]


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "postgresql":
        # PostgreSQL supporta ALTER COLUMN TYPE con USING per cast esplicito
        for table, col, numeric_type in _FINANCIAL_COLS:
            op.alter_column(
                table, col,
                existing_type=sa.Float(),
                type_=numeric_type,
                postgresql_using=f"{col}::numeric",
            )
    else:
        # SQLite: batch_alter_table ricrea la tabella
        processed: set[str] = set()
        for table, col, numeric_type in _FINANCIAL_COLS:
            if table not in processed:
                # Raggruppa tutte le colonne della stessa tabella in un unico batch
                pass
            processed.add(table)

        for table in {t for t, _, _ in _FINANCIAL_COLS}:
            cols_for_table = [(col, ntype) for t, col, ntype in _FINANCIAL_COLS if t == table]
            with op.batch_alter_table(table) as batch_op:
                for col, numeric_type in cols_for_table:
                    batch_op.alter_column(
                        col,
                        existing_type=sa.Float(),
                        type_=numeric_type,
                    )


def downgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "postgresql":
        for table, col, numeric_type in _FINANCIAL_COLS:
            op.alter_column(
                table, col,
                existing_type=numeric_type,
                type_=sa.Float(),
                postgresql_using=f"{col}::float",
            )
    else:
        for table in {t for t, _, _ in _FINANCIAL_COLS}:
            cols_for_table = [(col, ntype) for t, col, ntype in _FINANCIAL_COLS if t == table]
            with op.batch_alter_table(table) as batch_op:
                for col, numeric_type in cols_for_table:
                    batch_op.alter_column(
                        col,
                        existing_type=numeric_type,
                        type_=sa.Float(),
                    )
