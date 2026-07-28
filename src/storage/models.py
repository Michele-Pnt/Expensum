from datetime import date, datetime
import uuid

from sqlalchemy import (
    Column,
    String,
    Integer,
    Numeric,
    Date,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    CheckConstraint,
    Index,
    Text,
    JSON,
)

from src.user_store import Base


# Modelli ORM (le tabelle)

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
    amount = Column(Numeric(12, 2), nullable=False)
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
    amount = Column(Numeric(12, 2), nullable=False)
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
    opening_balance = Column(Numeric(12, 2), default=0)
    currency = Column(String, default="EUR")
    account_type = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_accounts_user_name"),
    )


class Transfer(Base):
    """Tabella dei trasferimenti tra conti per utenti con backend PostgreSQL/SQLite."""

    __tablename__ = "transfers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    from_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    to_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    transfer_date = Column(Date, nullable=False)
    name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_transfers_user_id", "user_id"),
    )


class UserCategory(Base):
    """Categorie base dell'utente.

    I metadati specifici di Notion vengono salvati nella tabella separata
    `user_category_notion_links`.
    """

    __tablename__ = "user_categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    name = Column(String, nullable=False)
    monthly_budget = Column(Numeric(12, 2), nullable=True)
    description = Column(Text, nullable=True)
    description_summary = Column(Text, nullable=True)

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
    average = Column(Numeric(12, 2), nullable=True)


class CategoryCandidate(Base):
    """Pattern di spesa ricorrenti non ancora promossi a categoria vera.

    Traccia, per utente, le occorrenze di un nome spesa normalizzato la cui
    categoria proposta dal parser non ha raggiunto la soglia di match. Una
    volta superate `occurrences` occorrenze entro la finestra temporale
    configurata, il candidate viene promosso a `UserCategory` reale tramite
    `FinancialStorage.create_category` (mai un accesso diretto a Notion/Postgres).
    """

    __tablename__ = "category_candidates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    normalized_name = Column(String, nullable=False)
    display_name = Column(String, nullable=False)
    fallback_category_id = Column(Integer, ForeignKey("user_categories.id"), nullable=True)
    occurrences = Column(Integer, nullable=False, default=1)
    first_seen_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_seen_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_score = Column(Numeric(4, 3), nullable=True)
    status = Column(String(20), nullable=False, default="pending")
    promoted_category_id = Column(Integer, ForeignKey("user_categories.id"), nullable=True)
    promoted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "normalized_name", name="uq_category_candidates_user_normalized"),
        Index("ix_category_candidates_user_id", "user_id"),
        Index("ix_category_candidates_status", "status"),
    )


class Subscription(Base):
    """Tabella degli abbonamenti per utenti con backend PostgreSQL/SQLite."""

    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    name = Column(String, nullable=False)
    amount = Column(Numeric(12, 2), nullable=True)
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


class SavingsGoal(Base):
    """Obiettivo di risparmio dell'utente (feature Pro, solo backend PostgreSQL).

    `goal_type` determina come viene calcolato il valore corrente in
    `src/savings_goals_service.py` (mai in questo modello): net_savings,
    account_balance, net_worth, savings_rate, category_spending_reduction.
    `current_snapshot` è solo una cache dell'ultimo valore calcolato dal job
    mensile — il valore "adesso" mostrato in dashboard resta ricalcolato on-read.
    """

    __tablename__ = "savings_goals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    goal_type = Column(String(30), nullable=False)
    name = Column(String, nullable=False)
    target_amount = Column(Numeric(12, 2), nullable=False)
    current_snapshot = Column(Numeric(12, 2), nullable=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    category_id = Column(Integer, ForeignKey("user_categories.id"), nullable=True)
    start_date = Column(Date, nullable=False, default=date.today)
    target_date = Column(Date, nullable=True)
    status = Column(String(20), nullable=False, default="active")  # active|completed|paused_downgrade
    last_evaluated_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("target_amount > 0", name="ck_savings_goals_target_positive"),
        Index("ix_savings_goals_user_id", "user_id"),
        Index("ix_savings_goals_user_status", "user_id", "status"),
    )


class SavingsGoalEvaluation(Base):
    """Storico mensile del voto/ETA calcolato per un obiettivo (solo storico, non stato live).

    Il valore corrente e la percentuale "adesso" restano sempre calcolati on-read
    (vedi SavingsGoal); questa tabella serve solo a mostrare l'andamento nel tempo
    del voto/ETA e a fornire dati storici al report mensile e al futuro hook RAG.
    """

    __tablename__ = "savings_goal_evaluations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    goal_id = Column(Integer, ForeignKey("savings_goals.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    period_month = Column(Date, nullable=False)  # primo giorno del mese valutato
    progress_pct = Column(Numeric(5, 2), nullable=False)
    score_label = Column(String(20), nullable=False)
    eta_date = Column(Date, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("goal_id", "period_month", name="uq_savings_goal_evaluations_goal_period"),
        Index("ix_savings_goal_evaluations_goal_id", "goal_id"),
        Index("ix_savings_goal_evaluations_user_id", "user_id"),
    )


class ChatIdReassignmentJob(Base):
    """Coda per `UserStore.reassign_user_chat_id`.

    old_chat_id/new_chat_id appartengono a due account (potenzialmente due tenant)
    diversi: operazione cross-tenant per natura, quindi nessuna RLS su questa
    tabella (stesso criterio di `JobRun` in `user_store.py`). L'app (ruolo
    DML-only) può solo arruolare/leggere; solo `scripts/process_reassignment_jobs.py`
    (ruolo owner, mai esposto a rete) esegue davvero la riassegnazione — vedi
    security design notes § Vulnerabilità residua #2.
    """

    __tablename__ = "chat_id_reassignment_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    old_chat_id = Column(String, nullable=False, index=True)
    new_chat_id = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")  # pending|done|failed
    error_text = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)
