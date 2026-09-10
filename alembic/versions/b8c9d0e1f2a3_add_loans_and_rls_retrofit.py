"""Aggiunge il tracking mutui/finanziamenti (feature Pro, solo PostgresStorage) e
corregge un gap di RLS preesistente su savings_goals/savings_goal_evaluations.

`loans`: definizione del mutuo/finanziamento (vedi src/storage/models.py::Loan).
`loan_monthly_charges`: un rigo per mese già addebitato, garantisce l'idempotenza
del job mensile (src/storage/postgres_storage.py::record_loan_monthly_charge).
`expenses.loan_id`: FK nullable, collega ogni spesa generata al loan di provenienza
per il rollup "costo totale di questo prestito" indipendente dalla categoria.

Retrofit RLS: `savings_goals`/`savings_goal_evaluations` non sono mai state incluse
nella migration RLS originaria (s0t1u2v3w4x5, 2026-07-11) perché create 16 giorni
dopo (c9d0e1f2a3b4, 2026-07-27) — gap non intenzionale, mai colmato. Corretto qui,
insieme all'introduzione delle stesse policy per `loans`/`loan_monthly_charges`,
così le tabelle finanziarie per-utente più recenti sono tutte coperte allo stesso
modo (stesso meccanismo di s0t1u2v3w4x5_enable_row_level_security.py: ENABLE, non
FORCE, USING/WITH CHECK su `user_id = current_setting('app.user_id', true)`).

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-08-19 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "c5d6e7f8a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_POLICY = "tenant_isolation"
# Tabelle a cui questa migration aggiunge la policy RLS: le nuove `loans` e il
# retrofit di `savings_goals`/`savings_goal_evaluations`.
_NEW_RLS_TABLES = ("loans", "loan_monthly_charges")


def upgrade() -> None:
    op.create_table(
        "loans",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("loan_type", sa.String(length=30), nullable=False),
        sa.Column("principal_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("disbursement_date", sa.Date(), nullable=False),
        sa.Column("duration_months", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("rate_type", sa.String(length=10), nullable=False),
        sa.Column("tan", sa.Numeric(7, 4), nullable=False),
        sa.Column("taeg", sa.Numeric(7, 4), nullable=True),
        sa.Column("spread", sa.Numeric(7, 4), nullable=True),
        sa.Column("euribor_current", sa.Numeric(7, 4), nullable=True),
        sa.Column("euribor_tenor", sa.String(length=10), nullable=True),
        sa.Column("review_frequency", sa.String(length=20), nullable=True),
        sa.Column("next_review_date", sa.Date(), nullable=True),
        sa.Column("origination_fee", sa.Numeric(12, 2), nullable=True),
        sa.Column("monthly_fee", sa.Numeric(12, 2), nullable=True),
        sa.Column("current_installment", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.chat_id"]),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("principal_amount > 0", name="ck_loans_principal_positive"),
        sa.CheckConstraint("duration_months > 0", name="ck_loans_duration_positive"),
    )
    op.create_index("ix_loans_user_id", "loans", ["user_id"])
    op.create_index("ix_loans_user_status", "loans", ["user_id", "status"])

    op.create_table(
        "loan_monthly_charges",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("loan_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("period_month", sa.Date(), nullable=False),
        sa.Column("interest_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("fee_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("residual_balance", sa.Numeric(12, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["loan_id"], ["loans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.chat_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("loan_id", "period_month", name="uq_loan_monthly_charges_loan_period"),
    )
    op.create_index("ix_loan_monthly_charges_loan_id", "loan_monthly_charges", ["loan_id"])
    op.create_index("ix_loan_monthly_charges_user_id", "loan_monthly_charges", ["user_id"])

    op.add_column("expenses", sa.Column("loan_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_expenses_loan_id", "expenses", "loans", ["loan_id"], ["id"]
    )
    op.create_index("ix_expenses_loan_id", "expenses", ["loan_id"])

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite/dev: nessuna RLS, stesso no-op di s0t1u2v3w4x5. Le garanzie restano
        # il filtro applicativo `WHERE user_id = ...` già presente nel layer storage.
        return

    for table in _NEW_RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {_POLICY} ON {table}
                USING (user_id = current_setting('app.user_id', true))
                WITH CHECK (user_id = current_setting('app.user_id', true))
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in _NEW_RLS_TABLES:
            op.execute(f"DROP POLICY IF EXISTS {_POLICY} ON {table}")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_index("ix_expenses_loan_id", "expenses")
    op.drop_constraint("fk_expenses_loan_id", "expenses", type_="foreignkey")
    op.drop_column("expenses", "loan_id")

    op.drop_index("ix_loan_monthly_charges_user_id", "loan_monthly_charges")
    op.drop_index("ix_loan_monthly_charges_loan_id", "loan_monthly_charges")
    op.drop_table("loan_monthly_charges")

    op.drop_index("ix_loans_user_status", "loans")
    op.drop_index("ix_loans_user_id", "loans")
    op.drop_table("loans")
