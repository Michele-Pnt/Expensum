from datetime import datetime
import uuid

from sqlalchemy import (
    Column,
    String,
    Float,
    Integer,
    Date,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    Index,
    Text,
    JSON,
)

from src.user_store import Base


class Expense(Base):
    """Tabella delle spese per utenti con backend PostgreSQL/SQLite.

    `category_name` è una colonna legacy mantenuta nullable durante la migrazione
    3NF. Il campo authoritative è `category_id`; `category_name` non deve essere
    usato nel codice applicativo — esiste solo per il backfill in `_ensure_sqlite_schema`.
    """

    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    expense_date = Column(Date, nullable=False)
    amount = Column(Float, nullable=False)
    name = Column(String, nullable=False)
    # Legacy bridge — sarà NULL dopo il backfill; NON usare nel codice applicativo.
    category_name = Column(String, nullable=True)
    category_id = Column(Integer, ForeignKey("user_categories.id"), nullable=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Income(Base):
    """Tabella delle entrate per utenti con backend PostgreSQL/SQLite."""

    __tablename__ = "incomes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    income_date = Column(Date, nullable=False)
    amount = Column(Float, nullable=False)
    name = Column(String, nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    income_type = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Account(Base):
    """Tabella dei conti per utente.

    `opening_balance` e' il fatto persistito; il saldo corrente si calcola on-read.
    """

    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    name = Column(String, nullable=False)
    opening_balance = Column(Float, default=0.0)
    currency = Column(String, default="EUR")
    account_type = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_accounts_user_name"),
    )


class SystemCategory(Base):
    """Categorie predefinite condivise fra tutti gli utenti. Immutabile a runtime."""

    __tablename__ = "system_categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)


class UserCategory(Base):
    """Categorie base dell'utente.

    I metadati specifici di Notion vengono salvati nella tabella separata
    `user_category_notion_links`.
    """

    __tablename__ = "user_categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    name = Column(String, nullable=False)
    monthly_budget = Column(Float, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_user_categories_user_name"),
        Index("ix_user_categories_user_id", "user_id"),
    )


class UserCategoryNotionLink(Base):
    """Metadati Notion associati a una categoria locale.

    `average` resta una cache del valore Notion per preservare le UX esistenti.
    """

    __tablename__ = "user_category_notion_links"

    category_id = Column(Integer, ForeignKey("user_categories.id"), primary_key=True)
    notion_page_id = Column(String, nullable=True, unique=True)
    synced_at = Column(DateTime, nullable=True)
    average = Column(Float, nullable=True)


class Subscription(Base):
    """Tabella degli abbonamenti per utenti con backend PostgreSQL/SQLite."""

    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    name = Column(String, nullable=False)
    amount = Column(Float, nullable=True)
    last_billed = Column(Date, nullable=True)
    sub_type = Column(String, nullable=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    category_id = Column(Integer, ForeignKey("user_categories.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SavedReport(Base):
    """Report generati (settimanali e mensili) salvati per lo storico web."""

    __tablename__ = "saved_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.chat_id"), nullable=False, index=True)
    report_type = Column(String(20), nullable=False)   # "weekly" | "monthly"
    report_date = Column(Date, nullable=False)
    share_token = Column(String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    text_content = Column(Text, nullable=False)
    report_data = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
