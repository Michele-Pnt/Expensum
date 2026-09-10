from datetime import date, datetime
import uuid

from sqlalchemy import (
    Boolean,
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
    func,
    text,
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
    # Provenienza: quale mutuo/finanziamento ha generato questa spesa (se nessuno,
    # è una spesa normale). Nullable e indipendente dalla categoria — permette il
    # rollup "costo totale di questo prestito" senza frammentare le categorie
    # condivise "Interessi"/"Costi mutuo/finanziamento" per tipo di prestito.
    loan_id = Column(Integer, ForeignKey("loans.id"), nullable=True)
    # Metadato di sola aggregazione grafici — mai usato al posto di `name` in UI.
    # Nullable: nullo per le spese storiche non ancora processate dal backfill.
    label_cluster_id = Column(Integer, ForeignKey("expense_label_clusters.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ExpenseLabelCluster(Base):
    """Ancora di normalizzazione per le voci di spesa (metadato di sola aggregazione).

    Non è una categoria: raggruppa varianti testuali della stessa voce di spesa
    ("coca", "coca cola", "coca-cola") sotto un'unica etichetta canonica (`anchor_text`)
    usata solo per raggruppare nei grafici — la descrizione originale della spesa non
    viene mai toccata né sostituita, vedi `Expense.name`.

    Guardrail: un cluster è scoperto sempre e solo tra le spese con lo stesso
    `category_id` (stessa spesa testuale in categorie diverse, es. "Coca Cola" al
    supermercato vs in discoteca, resta in due cluster separati by design — non è
    un errore da correggere).

    `variant_counts` traccia, per ogni variante testuale vista, quante volte è
    comparsa: l'ancora si aggiorna in tempo reale alla variante più frequente,
    incrementando il contatore a ogni nuovo membro — nessun job di audit periodico.
    Fa eccezione il caso `anchor_locked`: se l'utente ha scelto esplicitamente
    l'etichetta correggendo a mano il raggruppamento, quella scelta è definitiva e
    nessuna variante più frequente la sostituisce.
    """

    __tablename__ = "expense_label_clusters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    category_id = Column(Integer, ForeignKey("user_categories.id"), nullable=True)
    anchor_text = Column(String, nullable=False)
    variant_counts = Column(JSON, nullable=False, default=dict)
    # True quando l'ancora è stata scelta dall'utente (merge/split manuale): blocca
    # il ricalcolo automatico alla variante più frequente.
    anchor_locked = Column(Boolean, nullable=False, default=False,
                           server_default=text("false"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_expense_label_clusters_user_category", "user_id", "category_id"),
    )


class ExpenseLabelOverride(Base):
    """Correzione manuale dell'utente al raggruppamento automatico delle voci.

    Il matching fuzzy (`src/expense_label_normalizer.py`) è conservativo ma non
    infallibile: può separare voci che vanno insieme o unire voci diverse (es.
    `partial_ratio("ape", "ape 50 tagliando")` = 100). Quando l'utente corregge dal
    grafico Analytics ("Unisci" / "Dividi") la correzione va resa **durevole**: senza
    questa tabella la spesa successiva con lo stesso testo verrebbe ri-accorpata dal
    fuzzy, vanificando la correzione.

    Ogni riga forza un testo a un cluster preciso: `assign_label_cluster` consulta
    questa tabella **prima** del matching fuzzy e, se trova una regola, la applica
    senza calcolare alcuna similarità.

    Guardrail invariato: la regola vale solo dentro la stessa `category_id` della
    spesa (stesso testo in categorie diverse resta separato by design).

    `normalized_text` è contenuto libero dell'utente: non va mai loggato né incluso
    nei messaggi d'errore restituiti al client.
    """

    __tablename__ = "expense_label_overrides"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    category_id = Column(Integer, ForeignKey("user_categories.id"), nullable=True)
    # Chiave di lookup: output di `_light_normalize`, non il testo grezzo.
    normalized_text = Column(String, nullable=False)
    cluster_id = Column(
        Integer,
        ForeignKey("expense_label_clusters.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Diagnostica: da quale azione utente nasce la regola ("merge" | "split").
    source = Column(String(16), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index(
            "ix_expense_label_overrides_lookup",
            "user_id", "category_id", "normalized_text",
        ),
        Index("ix_expense_label_overrides_cluster", "cluster_id"),
        # Due indici parziali invece di un unico UNIQUE: in Postgres due NULL su
        # `category_id` non collidono, quindi un unique semplice non proteggerebbe
        # le spese senza categoria dai duplicati.
        Index(
            "uq_expense_label_overrides_cat",
            "user_id", "category_id", "normalized_text",
            unique=True,
            postgresql_where=text("category_id IS NOT NULL"),
            sqlite_where=text("category_id IS NOT NULL"),
        ),
        Index(
            "uq_expense_label_overrides_nocat",
            "user_id", "normalized_text",
            unique=True,
            postgresql_where=text("category_id IS NULL"),
            sqlite_where=text("category_id IS NULL"),
        ),
    )


class QuickExpenseShortcut(Base):
    """Bottone spesa rapida creato manualmente dall'utente (chat -> "Spese rapide").

    Distinto dal bottone automatico (calcolato al volo da `_build_quick_expenses`
    su name/category/account della spesa più frequente dell'ultimo mese): qui i
    campi sono scelti esplicitamente dall'utente una volta, e restano fissi finché
    non li cancella — non cambiano da soli col tempo.
    """

    __tablename__ = "quick_expense_shortcuts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    # Vincolo di lunghezza anche a schema, non solo in `api_chat_quick_expenses_custom_create`
    # (validazione applicativa che può cambiare/sparire senza che nessuno se ne accorga).
    name = Column(String(60), nullable=False)
    category_id = Column(Integer, ForeignKey("user_categories.id"), nullable=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    # Ordine scelto dall'utente (drag & drop in chat) — non l'ordine di creazione.
    # Assegnata in sequenza alla creazione, poi riscritta per intero a ogni riordino
    # (vedi /api/chat/quick-expenses/custom/reorder).
    position = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_quick_expense_shortcuts_user_id", "user_id"),
    )


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
    # Compatibility release: authoritative relationship, while income_type is
    # dual-written for old clients and the existing Notion select.
    income_category_id = Column(Integer, ForeignKey("user_income_categories.id"), nullable=True)
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

    `archived_at` è l'alternativa non distruttiva alla cancellazione: la categoria
    sparisce da ogni punto in cui se ne *sceglie* una (parser LLM, menù, obiettivi,
    suggerimenti budget) ma resta intatta nello storico, così i report già emessi
    non cambiano. Le letture aggregate la includono passando `include_archived=True`.
    Lo unique constraint resta attivo anche sulle archiviate: registrare una spesa
    col nome di una categoria archiviata la riattiva invece di crearne un duplicato.
    """

    __tablename__ = "user_categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    name = Column(String, nullable=False)
    monthly_budget = Column(Numeric(12, 2), nullable=True)
    description = Column(Text, nullable=True)
    description_summary = Column(Text, nullable=True)
    archived_at = Column(DateTime, nullable=True)
    budget_suggestion_dismissed_at = Column(DateTime, nullable=True)

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


class UserIncomeCategory(Base):
    """User-scoped category for incomes, mirroring ``UserCategory`` for expenses."""

    __tablename__ = "user_income_categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    name = Column(String, nullable=False)
    monthly_budget = Column(Numeric(12, 2), nullable=True)
    description = Column(Text, nullable=True)
    description_summary = Column(Text, nullable=True)
    archived_at = Column(DateTime, nullable=True)
    budget_suggestion_dismissed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_user_income_categories_user_name"),
        Index("ix_user_income_categories_user_id", "user_id"),
        Index(
            "uq_user_income_categories_user_lower_name",
            "user_id", func.lower(name), unique=True,
        ),
    )


class UserIncomeCategoryNotionLink(Base):
    """Local Notion metadata/cache for a user income category."""

    __tablename__ = "user_income_category_notion_links"

    category_id = Column(Integer, ForeignKey("user_income_categories.id"), primary_key=True)
    notion_page_id = Column(String, nullable=True, unique=True)
    synced_at = Column(DateTime, nullable=True)
    average = Column(Numeric(12, 2), nullable=True)


class IncomeCategoryNotionSyncTask(Base):
    """Durable retry state for a Notion income-category rename or deletion."""

    __tablename__ = "income_category_notion_sync_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    category_id = Column(Integer, ForeignKey("user_income_categories.id"), nullable=False)
    operation = Column(String(16), nullable=False)
    previous_name = Column(String, nullable=False)
    next_name = Column(String, nullable=False)
    page_ids = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("category_id", name="uq_income_category_notion_sync_task_category"),
        Index("ix_income_category_notion_sync_tasks_user_id", "user_id"),
    )


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
    cadence = Column(String(20), nullable=True)  # monthly|quarterly|semiannual|yearly
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    category_id = Column(Integer, ForeignKey("user_categories.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SubscriptionCandidate(Base):
    """Pattern di spesa ricorrenti non ancora promossi ad abbonamento tracciato.

    Popolata sia in tempo reale (hook a ogni nuova spesa, vedi
    `src/subscription_detector.py`) sia dal backfill una tantum sullo storico
    esistente (`scripts/backfill_subscription_candidates.py`). Il gruppo è
    identificato da `(user_id, category_name, amount)` con tolleranza applicativa,
    mai da matching sul nome libero della spesa — `category_name` (non l'id) per
    restare backend-agnostico (Notion non ha category_id interi, vedi CLAUDE.md).

    Superate `occurrences` occorrenze alla stessa cadenza, il candidate passa ad
    `awaiting_confirm` e l'utente viene interpellato (Sì/No). Alla conferma diventa
    un `Subscription` reale tramite `FinancialStorage.create_subscription`; al
    rifiuto passa a `dismissed` e non viene più riproposto (a differenza dei
    `CategoryCandidate` rifiutati, qui non si azzera per richiedere di nuovo: un
    "No" è una decisione definitiva dell'utente sui suoi soldi).
    """

    __tablename__ = "subscription_candidates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    category_name = Column(String, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    cadence = Column(String(20), nullable=True)  # weekly|monthly|quarterly|yearly, noto solo dalla 2a occorrenza
    display_name = Column(String, nullable=False)
    occurrences = Column(Integer, nullable=False, default=1)
    first_occurrence_date = Column(Date, nullable=False)
    last_occurrence_date = Column(Date, nullable=False)
    last_seen_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    status = Column(String(20), nullable=False, default="pending")
    promoted_subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=True)
    promoted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_subscription_candidates_user_id", "user_id"),
        Index("ix_subscription_candidates_status", "status"),
    )


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
    account_balance, net_worth, savings_rate, category_spending_reduction,
    emergency_fund. `current_snapshot` è solo una cache dell'ultimo valore
    calcolato dal job mensile — il valore "adesso" mostrato in dashboard resta
    ricalcolato on-read.
    `emergency_fund_months` è usato solo dal tipo `emergency_fund`: il target
    (mediana spesa mensile × questo numero) non è mai il `target_amount`
    persistito ma ricalcolato a ogni lettura in `savings_goals_service.py`.
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
    emergency_fund_months = Column(Integer, nullable=True)
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


class Loan(Base):
    """Mutuo/finanziamento tracciato dall'utente (feature Pro, solo backend PostgreSQL).

    `rate_type` è "fisso" o "variabile". Per "variabile" (solo il modello "classico":
    rata varia, durata fissa — vedi src/loan_calculator.py): `spread`+`euribor_current`
    compongono `tan` corrente, `review_frequency`/`next_review_date` guidano il job di
    notifica revisione tasso. L'aggiornamento dell'Euribor è manuale (nessuna licenza
    dati EMMI in v1): è l'utente a inserire il nuovo tasso quando riceve comunicazione
    dalla banca.

    `origination_fee` (istruttoria) è un costo una tantum registrato come spesa alla
    creazione del Loan; `monthly_fee` (spese incasso rata) è un costo ricorrente
    registrato insieme alla quota interessi a ogni ricalcolo mensile. L'assicurazione
    non è modellata qui: per design va nella categoria di assicurazione già esistente
    dell'utente, se ne ha una, non in una categoria specifica del prestito.
    `taeg` è informativo (inserito a mano dall'utente, calcolato da Expensum solo sul
    calcolatore pubblico/what-if): non guida mai il calcolo della rata.
    """

    __tablename__ = "loans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    name = Column(String, nullable=False)
    loan_type = Column(String(30), nullable=False)  # mutuo_casa|prestito_auto|altro|...
    principal_amount = Column(Numeric(12, 2), nullable=False)
    disbursement_date = Column(Date, nullable=False)
    duration_months = Column(Integer, nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    rate_type = Column(String(10), nullable=False)  # fisso|variabile
    tan = Column(Numeric(7, 4), nullable=False)
    taeg = Column(Numeric(7, 4), nullable=True)
    spread = Column(Numeric(7, 4), nullable=True)
    euribor_current = Column(Numeric(7, 4), nullable=True)
    euribor_tenor = Column(String(10), nullable=True)  # es. "3m"
    review_frequency = Column(String(20), nullable=True)  # trimestrale|semestrale|anniversario
    next_review_date = Column(Date, nullable=True)
    origination_fee = Column(Numeric(12, 2), nullable=True)
    monthly_fee = Column(Numeric(12, 2), nullable=True)
    payment_cadence = Column(String(20), nullable=False, default="monthly")
    # Rata corrente (French/ammortamento francese), calcolata alla creazione e
    # ricalcolata a ogni revisione tasso per i loan variabili (rata varia, durata
    # fissa restante). Cache derivata, mai la fonte di verità del piano: serve per
    # non dover ricalcolare da zero il piano intero a ogni addebito mensile.
    current_installment = Column(Numeric(12, 2), nullable=False)
    status = Column(String(20), nullable=False, default="active")  # active|closed
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("principal_amount > 0", name="ck_loans_principal_positive"),
        CheckConstraint("duration_months > 0", name="ck_loans_duration_positive"),
        Index("ix_loans_user_id", "user_id"),
        Index("ix_loans_user_status", "user_id", "status"),
    )


class LoanMonthlyCharge(Base):
    """Traccia i mesi già addebitati per un loan (idempotenza del job mensile).

    Senza questa tabella, un rerun del job (es. dopo un crash a metà esecuzione)
    genererebbe due `Expense` per lo stesso mese. `period_month` è il primo giorno
    del mese addebitato.
    """

    __tablename__ = "loan_monthly_charges"

    id = Column(Integer, primary_key=True, autoincrement=True)
    loan_id = Column(Integer, ForeignKey("loans.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    period_month = Column(Date, nullable=False)
    interest_amount = Column(Numeric(12, 2), nullable=False)
    fee_amount = Column(Numeric(12, 2), nullable=True)
    residual_balance = Column(Numeric(12, 2), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("loan_id", "period_month", name="uq_loan_monthly_charges_loan_period"),
        Index("ix_loan_monthly_charges_loan_id", "loan_id"),
        Index("ix_loan_monthly_charges_user_id", "user_id"),
    )


class MortgageSimulation(Base):
    """Bozza salvabile di una simulazione mutuo, separata dai contratti attivi."""

    __tablename__ = "mortgage_simulations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    name = Column(String, nullable=False)
    input_snapshot = Column(JSON, nullable=False)
    result_snapshot = Column(JSON, nullable=False)
    status = Column(String(20), nullable=False, default="active")
    converted_loan_id = Column(Integer, ForeignKey("loans.id"), nullable=True, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_mortgage_simulations_user_id", "user_id"),
        Index("ix_mortgage_simulations_user_status", "user_id", "status"),
    )


class Notification(Base):
    """Notifica in-app per eventi asincroni, indipendenti dalla presenza dell'utente
    in webapp (report periodici, soglie di budget, addebiti ricorrenti, inattività,
    anomalie di sicurezza, messaggi admin).

    Non copre eventi che sono risposta diretta e sincrona a un'azione dell'utente
    (es. alert budget mostrato subito dopo che l'utente registra una spesa a mano):
    quelli restano feedback UI immediato, non finiscono qui.

    `payload` porta dati per il deep-link (es. `{"share_token": ...}` per un report),
    mai contenuto libero dell'utente da non loggare — `body` è testo già pensato per
    essere mostrato, coerente con le altre superfici utente del progetto.
    """

    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    type = Column(String(30), nullable=False)
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=False)
    payload = Column(JSON, nullable=True)
    priority = Column(String(20), nullable=False, default="info")
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_notifications_user_id_read_at", "user_id", "read_at"),
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
