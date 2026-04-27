from datetime import datetime

from sqlalchemy import Column, String, Float, Integer, Date, DateTime, ForeignKey, UniqueConstraint, Index

from src.user_store import Base


class Expense(Base):
    """Tabella delle spese per utenti con backend PostgreSQL."""
    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    expense_date = Column(Date, nullable=False)
    amount = Column(Float, nullable=False)
    name = Column(String, nullable=False)
    category_name = Column(String, nullable=False)
    account_id = Column(String, nullable=False)
    monthly_balance_id = Column(Integer, ForeignKey("monthly_balances.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Income(Base):
    """Tabella delle entrate per utenti con backend PostgreSQL."""
    __tablename__ = "incomes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    income_date = Column(Date, nullable=False)
    amount = Column(Float, nullable=False)
    name = Column(String, nullable=False)
    account_id = Column(String, nullable=False)
    income_type = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Account(Base):
    """Tabella dei conti bancari per utenti con backend PostgreSQL."""
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    name = Column(String, nullable=False)
    balance = Column(Float, default=0.0)
    currency = Column(String, default="EUR")
    account_type = Column(String, nullable=True)


class SystemCategory(Base):
    """Categorie predefinite condivise fra tutti gli utenti. Immutabile a runtime."""
    __tablename__ = "system_categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)


class UserCategory(Base):
    """Categorie effettive per utente.

    Per utenti Notion: mirror del DB Categories Notion, con notion_page_id e average
    aggiornati sui tre trigger (post-setup, pre-report, job notturno).
    Per utenti Postgres: categorie locali, average calcolato da expenses sugli stessi trigger.
    """
    __tablename__ = "user_categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    name = Column(String, nullable=False)
    average = Column(Float, nullable=False, default=0.0)
    monthly_budget = Column(Float, nullable=True)
    notion_page_id = Column(String, nullable=True)   # None per utenti Postgres
    synced_at = Column(DateTime, nullable=True)       # None per utenti Postgres

    __table_args__ = (
        UniqueConstraint('user_id', 'name', name='uq_user_categories_user_name'),
        Index('ix_user_categories_user_id', 'user_id'),
    )


class Subscription(Base):
    """Tabella degli abbonamenti per utenti con backend PostgreSQL."""
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    name = Column(String, nullable=False)
    amount = Column(Float, nullable=True)
    last_billed = Column(Date, nullable=True)
    sub_type = Column(String, nullable=True)
    account_id = Column(Integer, nullable=True)
    category_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class MonthlyBalance(Base):
    """Tabella dei bilanci mensili per utenti con backend PostgreSQL."""
    __tablename__ = "monthly_balances"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    month = Column(Date, nullable=False)
    income_total = Column(Float, default=0.0)
    expense_total = Column(Float, default=0.0)
    net_savings = Column(Float, default=0.0)
