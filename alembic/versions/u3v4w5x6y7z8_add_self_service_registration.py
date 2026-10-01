"""Add self-service registration, consent and recurring-income storage.

Revision ID: u3v4w5x6y7z8
Revises: t2u3v4w5x6y7
Create Date: 2026-10-01 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "u3v4w5x6y7z8"
down_revision: Union[str, Sequence[str], None] = "t2u3v4w5x6y7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_user_columns() -> None:
    """Add registration state and referral ownership columns."""
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "registration_status",
            sa.String(length=32),
            nullable=False,
            server_default="active",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "registration_source",
            sa.String(length=32),
            nullable=False,
            server_default="telegram",
        ),
    )
    op.add_column(
        "users", sa.Column("beta_slot_reserved_until", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column("onboarding_profile_completed_at", sa.DateTime(), nullable=True),
    )
    op.add_column("users", sa.Column("referral_code", sa.String(), nullable=True))
    op.add_column("users", sa.Column("referred_by_code", sa.String(), nullable=True))


def _create_tables() -> None:
    """Create the account-flow and quality-data tables."""
    op.create_table(
        "registration_capacity",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("max_accounts", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "auth_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.chat_id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_digest", sa.String(length=128), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("token_digest", name="uq_auth_tokens_digest"),
    )
    op.create_index(
        "ix_auth_tokens_user_purpose", "auth_tokens", ["user_id", "purpose"]
    )
    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.chat_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("household_type", sa.String(length=32), nullable=True),
        sa.Column("has_job", sa.Boolean(), nullable=True),
        sa.Column("financial_experience", sa.String(length=32), nullable=True),
        sa.Column("report_detail_preference", sa.String(length=32), nullable=True),
        sa.Column("acquisition_source", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "user_profile_goals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.chat_id", ondelete="CASCADE"), nullable=False),
        sa.Column("goal_code", sa.String(length=64), nullable=False),
        sa.Column("priority_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "goal_code", name="uq_user_profile_goal_code"),
        sa.UniqueConstraint("user_id", "priority_order", name="uq_user_profile_goal_order"),
    )
    op.create_index("ix_user_profile_goals_user_id", "user_profile_goals", ["user_id"])
    op.create_table(
        "consent_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.chat_id", ondelete="CASCADE"), nullable=False),
        sa.Column("consent_type", sa.String(length=64), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_consent_events_user_type_created",
        "consent_events",
        ["user_id", "consent_type", "created_at"],
    )
    op.create_table(
        "marketing_sync_tasks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.chat_id", ondelete="CASCADE"), nullable=False),
        sa.Column("consent_event_id", sa.Integer(), sa.ForeignKey("consent_events.id"), nullable=False),
        sa.Column("desired_state", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime(), nullable=False),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_marketing_sync_tasks_pending",
        "marketing_sync_tasks",
        ["status", "next_retry_at"],
    )
    op.create_table(
        "recurring_income_rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.chat_id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("cadence", sa.String(length=16), nullable=False),
        sa.Column("payday_day", sa.Integer(), nullable=False),
        sa.Column("next_due_date", sa.Date(), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("income_category_id", sa.Integer(), sa.ForeignKey("user_income_categories.id"), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_recurring_income_rules_user_active",
        "recurring_income_rules",
        ["user_id", "active"],
    )
    op.create_table(
        "ai_improvement_samples",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.chat_id", ondelete="CASCADE"), nullable=False),
        sa.Column("input_method", sa.String(length=16), nullable=False),
        sa.Column("proposed_fields_json", sa.JSON(), nullable=False),
        sa.Column("final_fields_json", sa.JSON(), nullable=False),
        sa.Column("changed_fields_json", sa.JSON(), nullable=False),
        sa.Column("model_provider", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("consent_event_id", sa.Integer(), sa.ForeignKey("consent_events.id"), nullable=False),
        sa.Column("ocr_text_encrypted", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_ai_improvement_samples_user_created",
        "ai_improvement_samples",
        ["user_id", "created_at"],
    )


def _add_income_occurrence_columns() -> None:
    """Add the idempotency key used by recurring-income materialization."""
    source_rule_column = sa.Column(
        "source_rule_id",
        sa.Integer(),
        sa.ForeignKey("recurring_income_rules.id", name="fk_incomes_source_rule_id"),
        nullable=True,
    )
    scheduled_for_column = sa.Column("scheduled_for", sa.Date(), nullable=True)
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("incomes", recreate="always") as batch_op:
            batch_op.add_column(source_rule_column)
            batch_op.add_column(scheduled_for_column)
    else:
        op.add_column("incomes", source_rule_column)
        op.add_column("incomes", scheduled_for_column)
    condition = sa.text("source_rule_id IS NOT NULL AND scheduled_for IS NOT NULL")
    op.create_index(
        "uq_incomes_source_rule_scheduled",
        "incomes",
        ["source_rule_id", "scheduled_for"],
        unique=True,
        sqlite_where=condition,
        postgresql_where=condition,
    )


def _backfill_users_and_referrals() -> None:
    """Mark legacy accounts verified and move unambiguous referral ownership."""
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE users SET email_verified_at = COALESCE(created_at, CURRENT_TIMESTAMP), "
            "registration_status = 'active', "
            "registration_source = CASE WHEN chat_id LIKE 'web_%' "
            "THEN 'legacy_beta' ELSE 'telegram' END"
        )
    )

    duplicate_email = connection.execute(
        sa.text(
            "SELECT lower(trim(email)) FROM tally_leads "
            "WHERE email IS NOT NULL AND trim(email) <> '' "
            "GROUP BY lower(trim(email)) HAVING count(*) > 1"
        )
    ).first()
    if duplicate_email:
        raise RuntimeError("Duplicate Tally referral rows require manual migration review")

    duplicate_code = connection.execute(
        sa.text(
            "SELECT referral_code FROM tally_leads "
            "WHERE referral_code IS NOT NULL GROUP BY referral_code HAVING count(*) > 1"
        )
    ).first()
    if duplicate_code:
        raise RuntimeError("Duplicate Tally referral codes require manual migration review")

    connection.execute(
        sa.text(
            "UPDATE users SET referral_code = ("
            "SELECT t.referral_code FROM tally_leads t "
            "WHERE lower(trim(t.email)) = lower(trim(users.email))"
            "), referred_by_code = ("
            "SELECT t.referred_by_code FROM tally_leads t "
            "WHERE lower(trim(t.email)) = lower(trim(users.email))"
            ") WHERE email IS NOT NULL"
        )
    )


def _seed_capacity_row() -> None:
    """Seed the singleton beta-capacity row without overwriting an operator value."""
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT count(*) FROM registration_capacity")).scalar_one() == 0:
        connection.execute(
            sa.text(
                "INSERT INTO registration_capacity "
                "(id, max_accounts, created_at, updated_at) "
                "VALUES (1, 50, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )


def _enable_rls() -> None:
    """Enable tenant RLS for recurring rules and quality samples on PostgreSQL."""
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        return
    for table in ("recurring_income_rules", "ai_improvement_samples"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
                USING (user_id = current_setting('app.user_id', true))
                WITH CHECK (user_id = current_setting('app.user_id', true))
            """
        )


def upgrade() -> None:
    """Apply the self-service registration schema and legacy backfill."""
    _add_user_columns()
    _create_tables()
    _add_income_occurrence_columns()
    _backfill_users_and_referrals()
    op.create_index("uq_users_referral_code", "users", ["referral_code"], unique=True)
    _seed_capacity_row()
    _enable_rls()


def downgrade() -> None:
    """Remove the self-service registration schema."""
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        for table in ("recurring_income_rules", "ai_improvement_samples"):
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_index("uq_incomes_source_rule_scheduled", table_name="incomes")
    op.drop_column("incomes", "scheduled_for")
    op.drop_column("incomes", "source_rule_id")
    op.drop_index("ix_ai_improvement_samples_user_created", table_name="ai_improvement_samples")
    op.drop_table("ai_improvement_samples")
    op.drop_index("ix_recurring_income_rules_user_active", table_name="recurring_income_rules")
    op.drop_table("recurring_income_rules")
    op.drop_index("ix_marketing_sync_tasks_pending", table_name="marketing_sync_tasks")
    op.drop_table("marketing_sync_tasks")
    op.drop_index("ix_consent_events_user_type_created", table_name="consent_events")
    op.drop_table("consent_events")
    op.drop_index("ix_user_profile_goals_user_id", table_name="user_profile_goals")
    op.drop_table("user_profile_goals")
    op.drop_table("user_profiles")
    op.drop_index("ix_auth_tokens_user_purpose", table_name="auth_tokens")
    op.drop_table("auth_tokens")
    op.drop_table("registration_capacity")
    op.drop_index("uq_users_referral_code", table_name="users")
    for column in (
        "referred_by_code",
        "referral_code",
        "onboarding_profile_completed_at",
        "beta_slot_reserved_until",
        "registration_source",
        "registration_status",
        "email_verified_at",
    ):
        op.drop_column("users", column)
