"""
user_store.py — Gestione persistenza utenti tramite SQLAlchemy.
Supporta SQLite (locale) e predisposto per PostgreSQL/Oracle.
"""

import base64
import hashlib
import logging
import os
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
import secrets
import string
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
import json
from cryptography.fernet import Fernet
from sqlalchemy import (
    Column,
    String,
    Boolean,
    DateTime,
    Integer,
    BigInteger,
    Date,
    ForeignKey,
    Numeric,
    Text,
    UniqueConstraint,
    Index,
    JSON,
    func,
    create_engine,
    inspect,
    text,
    types,
)
from sqlalchemy.orm import declarative_base, sessionmaker


def _get_fernet() -> Fernet:
    """Ritorna un'istanza Fernet derivata da FLASK_SECRET_KEY."""
    secret = os.environ.get("FLASK_SECRET_KEY", "")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


# ---------------------------------------------------------------------------
# Report di riconciliazione categorie (cache Postgres ↔ Notion)
# ---------------------------------------------------------------------------

# Nome della categoria di fallback su cui riassegnare spese/abbonamenti quando
# una categoria con record dipendenti viene rimossa da Notion.
FALLBACK_CATEGORY_NAME = "Altro"


@dataclass
class CategoryReassignment:
    """Record di una riassegnazione forzata a `Altro` durante la riconciliazione."""

    category_name: str
    moved_expenses: int
    moved_subscriptions: int


@dataclass
class ReconcileReport:
    """Esito di `reconcile_user_categories`.

    `deleted_categories` elenca i nomi rimossi dalla cache; `reassignments` elenca
    le categorie che avevano record dipendenti spostati su `Altro` prima della
    cancellazione (il chiamante usa questo per notificare l'utente).
    """

    deleted_categories: list[str] = field(default_factory=list)
    reassignments: list["CategoryReassignment"] = field(default_factory=list)
    # Numero di categorie scaricate/aggiornate da Notion nell'upsert che precede
    # la riconciliazione (retro-compatibile col vecchio valore di ritorno int).
    synced_count: int = 0

    @property
    def has_reassignments(self) -> bool:
        return bool(self.reassignments)

    @property
    def changed(self) -> bool:
        return bool(self.deleted_categories or self.reassignments)


# ---------------------------------------------------------------------------
# Hashing password — Argon2id (con migrazione trasparente da bcrypt legacy)
# ---------------------------------------------------------------------------
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError, VerificationError

# Istanza condivisa con i parametri di default di argon2-cffi (Argon2id).
_password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Genera un hash Argon2id della password."""
    return _password_hasher.hash(password)


def verify_password_hash(password: str, stored_hash: str) -> tuple[bool, Optional[str]]:
    """Verifica la password contro l'hash memorizzato.

    Supporta sia hash **Argon2id** (nuovo standard) sia hash **bcrypt** legacy.
    Ritorna `(is_valid, new_hash)` dove `new_hash` è un nuovo hash Argon2id da
    persistere quando è opportuno ri-hashare (hash bcrypt legacy o parametri
    Argon2 obsoleti), altrimenti `None`.
    """
    if not stored_hash:
        return False, None

    if stored_hash.startswith("$argon2"):
        try:
            _password_hasher.verify(stored_hash, password)
        except (VerifyMismatchError, InvalidHashError, VerificationError):
            return False, None
        new_hash = None
        try:
            if _password_hasher.check_needs_rehash(stored_hash):
                new_hash = _password_hasher.hash(password)
        except InvalidHashError:
            new_hash = _password_hasher.hash(password)
        return True, new_hash

    # Fallback: hash bcrypt legacy → verifica e, se valido, ri-hasha ad Argon2id.
    import bcrypt
    try:
        ok = bcrypt.checkpw(password.encode(), stored_hash.encode())
    except (ValueError, TypeError):
        return False, None
    if not ok:
        return False, None
    return True, hash_password(password)


class EncryptedString(types.TypeDecorator):
    """Colonna String che cifra/decifra i valori con Fernet (AES-128-CBC + HMAC)."""

    impl = types.String
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        return _get_fernet().encrypt(value.encode()).decode()

    def process_result_value(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        try:
            return _get_fernet().decrypt(value.encode()).decode()
        except Exception:
            # Valore non ancora cifrato (migrazione in corso) — restituisce as-is
            return value

logger = logging.getLogger("financial_agent.user_store")


class QuotaExceededError(Exception):
    """Sollevata quando un utente Free ha esaurito la quota token del ciclo."""
    pass

# 1. DEFINIAMO LO STAMPO (BASE)
# Tutte le classi che erediteranno da Base diventeranno tabelle nel DB.
Base = declarative_base()

# 2. DEFINIAMO LA TABELLA UTENTI
class User(Base):
    __tablename__ = "users"

    # chat_id è la chiave primaria (ID univoco di Telegram)
    chat_id = Column(String, primary_key=True)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)

    # Credenziali Notion — Opzionali nel nuovo sistema OAuth (Fase 2)
    expense_db_id = Column(String, nullable=True)
    income_db_id = Column(String, nullable=True)
    categories_db_id = Column(String, nullable=True)
    monthly_balance_db_id = Column(String, nullable=True)
    accounts_db_id = Column(String, nullable=True)
    subscriptions_db_id = Column(String, nullable=True)
    pay_transfer_db_id = Column(String, nullable=True)
    accounts_schema_json = Column(String, nullable=True)
    categories_schema_json = Column(String, nullable=True)
    subscriptions_schema_json = Column(String, nullable=True)
    
    # OAuth Notion
    notion_access_token = Column(EncryptedString, nullable=True)
    notion_workspace_id = Column(String, nullable=True)
    
    # Metadati per sapere quando si sono registrati
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    # Metadati per sapere stato di inizializzazione del template
    setup_status = Column(String, default="WAIT_ACCOUNTS")
    setup_completed_at = Column(DateTime, nullable=True)

    # Autenticazione email+password
    email = Column(String, nullable=True, unique=True)
    password_hash = Column(String, nullable=True)

    # Versione della sessione: incrementata per invalidare tutte le sessioni
    # attive dell'utente (cambio password, "esci da tutti i dispositivi"). Il
    # valore viene salvato nel cookie di sessione al login e confrontato ad ogni
    # richiesta: se non combacia più, la sessione è considerata revocata.
    token_version = Column(Integer, default=0, nullable=False)

    # Backend di storage
    storage_backend = Column(String, default="notion", nullable=False)

    # Dashboard pinnata in chat Telegram
    pinned_dashboard_msg_id = Column(BigInteger, nullable=True)

    # Preferenze utente
    preferred_language = Column(String, default='it', nullable=False)
    currency = Column(String, default='EUR', nullable=False)
    timezone = Column(String, default='Europe/Rome', nullable=False)
    lifestyle_json = Column(Text, nullable=True)
    monthly_budget = Column(Numeric(12, 2), nullable=True)
    notification_time = Column(String, default='08:00')
    notifications_enabled = Column(Boolean, default=True)

    # Stato wizard onboarding
    onboarding_step = Column(String, default='pending')
    onboarding_completed_at = Column(DateTime, nullable=True)

    # Consenso privacy policy (GDPR Art. 7 — prova del consenso)
    privacy_policy_version_accepted = Column(String, nullable=True)
    privacy_accepted_at = Column(DateTime, nullable=True)

    # Attestazione età 18+ (D.Lgs. 101/2018 + capacità contrattuale Pro)
    age_attestation_at = Column(DateTime, nullable=True)

    # Flag demo data — True se l'utente ha caricato dati fittizi da esplorare
    has_demo_data = Column(Boolean, default=False, nullable=False)

    # Stato tour guidato webapp (10 step demo, vedi frontend/src/context/TourContext.tsx).
    # Prima non era persistito da nessuna parte (solo localStorage del browser): questi
    # campi arrivano da /api/track lato server, quando l'utente ha una sessione valida.
    tour_step = Column(String, nullable=True)          # ultimo step id raggiunto
    tour_status = Column(String, nullable=True)        # 'in_progress'|'completed'|'skipped'
    tour_completed_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<User(chat_id={self.chat_id}, username='{self.username}')>"

# 3. TABELLA METRICHE AI GIORNALIERE
class DailyMetrics(Base):
    __tablename__ = "daily_metrics"
    id = Column(Integer, primary_key=True, autoincrement=True)
    metrics_date = Column(Date, default=date.today, nullable=False, unique=True)
    goal_completions = Column(Integer, default=0)   # interazioni risolte con successo
    fallbacks = Column(Integer, default=0)          # intent non riconosciuti / fallback

# Note: legacy `DailyUsage` table removed — production uses `DailyMetrics`.
# 4. DEFINIAMO LA TABELLA FEEDBACK (Fase 4D)
class Feedback(Base):
    __tablename__ = "feedbacks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    message = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="unread")

# 5. TABELLA SCHEMI DATABASE (Fase 5 - Schema-Driven)
class DatabaseSchema(Base):
    __tablename__ = "database_schemas"
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    db_key = Column(String, nullable=False) # e.g. "expense_db_id"
    notion_db_id = Column(String, nullable=True)
    properties_json = Column(String, nullable=True) # Schema grezzo
    mapped_properties_json = Column(String, nullable=True) # Mapping logico

    __table_args__ = (
        UniqueConstraint("chat_id", "db_key", name="uq_database_schemas_chat_dbkey"),
    )

# 6. TABELLA SESSIONI OAUTH (Fase 2)
class OAuthSession(Base):
    __tablename__ = "oauth_sessions"
    state = Column(String, primary_key=True)
    chat_id = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False,
                        default=lambda: datetime.utcnow() + timedelta(minutes=15))

# 7. TABELLA PIANI E TOKEN (Fase 2.2)
class UserPlan(Base):
    """Piano utente. I token usati sono calcolati live da llm_usage_events."""
    __tablename__ = "user_plans"
    chat_id = Column(String, ForeignKey("users.chat_id"), primary_key=True)
    plan_type = Column(String, default="free", nullable=False)  # 'free' o 'pro'
    tokens_total = Column(Integer, default=150000, nullable=False)
    tokens_reset_at = Column(DateTime, nullable=False)

    # Trial Pro (concesso manualmente in beta, vedi UserStore.start_trial)
    is_trial = Column(Boolean, default=False, nullable=False)
    trial_started_at = Column(DateTime, nullable=True)
    trial_ends_at = Column(DateTime, nullable=True)


class PlanChange(Base):
    """Storico cambi piano utente. Usato per metriche upgrade/churn."""
    __tablename__ = "plan_changes"

    change_id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    from_plan = Column(String, nullable=True)
    to_plan = Column(String, nullable=False)
    change_type = Column(String, nullable=False)  # 'upgrade', 'downgrade', 'trial_expired', ecc.
    changed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    reason = Column(String, nullable=True)  # payment_reference o motivo testuale


class TrialLifecycleEvent(Base):
    """Traccia gli invii del drip lifecycle trial (D7/D14/D25/D29) per evitare doppi invii.

    Nessun contenuto libero salvato: solo step/canale/esito, coerente con le regole di
    logging del progetto (mai dati liberi utente).
    """
    __tablename__ = "trial_lifecycle_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    step = Column(String, nullable=False)       # 'd7' | 'd14' | 'd25' | 'd29'
    channel = Column(String, nullable=False)    # 'telegram' | 'email'
    sent_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    status = Column(String, nullable=False, default="sent")  # 'sent' | 'failed'

    __table_args__ = (
        UniqueConstraint("chat_id", "step", "channel", name="uq_trial_lifecycle_chat_step_channel"),
    )


class AuditLog(Base):
    """Audit trail per azioni GDPR-rilevanti (Art. 30 accountability).

    `user_id` non ha FK verso `users.chat_id`: deve restare leggibile anche
    dopo la cancellazione dell'utente, come prova che l'azione è avvenuta.
    """
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    user_id = Column(String, nullable=False)
    actor = Column(String(20), nullable=False)  # 'user' | 'admin' | 'system'
    action = Column(String(50), nullable=False)  # 'export_json' | 'export_csv' | 'delete_account'
    resource = Column(String(100), nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(255), nullable=True)
    metadata_json = Column(JSON, nullable=True)
    expires_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_audit_log_user_timestamp", "user_id", "timestamp"),
    )


class DataBreach(Base):
    """Registro delle violazioni di dati personali (Art. 33(5) GDPR).

    Deve documentare **ogni** violazione — anche quelle non notificate al
    Garante — così che l'Autorità possa verificarne la gestione. A differenza
    di `audit_log` (retention 365gg) questi record NON hanno `expires_at`:
    vanno conservati a lungo per accountability.
    """
    __tablename__ = "data_breaches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # Riferimento leggibile incident-YYYYMMDD-NNN
    breach_ref = Column(String(32), nullable=False, unique=True)
    detected_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    discovered_by = Column(String(100), nullable=True)  # es. 'sentry', 'utente', 'vendor:mistral'
    nature = Column(Text, nullable=True)                # descrizione della violazione
    affected_data_categories = Column(JSON, nullable=True)  # es. ["identita", "transazioni"]
    affected_users_count = Column(Integer, nullable=True)
    risk_level = Column(String(10), nullable=True)      # 'low' | 'medium' | 'high'
    # Notifica al Garante (Art. 33)
    garante_notified = Column(Boolean, nullable=False, default=False)
    garante_notified_at = Column(DateTime, nullable=True)
    garante_receipt_ref = Column(String(100), nullable=True)  # protocollo/ricevuta portale
    # Comunicazione agli interessati (Art. 34)
    users_notified = Column(Boolean, nullable=False, default=False)
    users_notified_at = Column(DateTime, nullable=True)
    art34_exempt_reason = Column(Text, nullable=True)   # motivo esenzione Art. 34(3), se applicabile
    # Gestione
    containment_measures = Column(Text, nullable=True)
    root_cause = Column(Text, nullable=True)
    status = Column(String(12), nullable=False, default="open")  # open|contained|notified|closed
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_data_breaches_detected_at", "detected_at"),
    )


class LlmPricing(Base):
    __tablename__ = "llm_pricing"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String, nullable=False)
    model = Column(String, nullable=False)
    valid_from = Column(DateTime, nullable=False)
    valid_to = Column(DateTime, nullable=True)
    input_cost_per_1k = Column(Numeric(12, 8), nullable=False, default=0.0)
    output_cost_per_1k = Column(Numeric(12, 8), nullable=False, default=0.0)
    cached_input_cost_per_1k = Column(Numeric(12, 8), nullable=True)
    thinking_cost_per_1k = Column(Numeric(12, 8), nullable=True)
    currency = Column(String, nullable=False, default="USD")


class LlmTokenReservation(Base):
    __tablename__ = "llm_token_reservations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    request_key = Column(String, nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    operation = Column(String, nullable=False)
    provider = Column(String, nullable=False)
    model = Column(String, nullable=False)
    reserved_tokens = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="pending")
    release_reason = Column(String, nullable=True)


class LlmUsageEvent(Base):
    __tablename__ = "llm_usage_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    occurred_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    provider = Column(String, nullable=False)
    model = Column(String, nullable=False)
    operation = Column(String, nullable=False)
    # Modalità di input dell'utente: 'text'|'voice'|'photo'. NULL sulle righe
    # storiche precedenti a questa colonna (non retroattivo: non era catturata
    # prima). Serve a distinguere testo/voce/foto nei grafici admin, cosa che
    # 'operation' da sola non permette (es. 'expense_parse' mescola testo e foto,
    # 'chat_parse' lato webapp mescola tutte e tre le modalità).
    input_method = Column(String, nullable=True)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    thinking_tokens = Column(Integer, nullable=True)
    cached_tokens = Column(Integer, nullable=True)
    estimated_cost_amount = Column(Numeric(12, 8), nullable=True)
    estimated_cost_currency = Column(String, nullable=False, default="USD")
    request_key = Column(String, nullable=False, unique=True)
    reservation_id = Column(Integer, ForeignKey("llm_token_reservations.id"), nullable=True)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    chat_id       = Column(String, ForeignKey("users.chat_id"), nullable=False, index=True)
    source        = Column(String, nullable=False)   # 'telegram' | 'webapp'
    role          = Column(String, nullable=False)   # 'user' | 'bot'
    text          = Column(Text, nullable=False)
    metadata_json = Column(Text, nullable=True)      # JSON: dati transazione parsata
    created_at    = Column(DateTime, default=datetime.utcnow, index=True)


class TallyLead(Base):
    """Backup locale dei submit del form Tally (waitlist beta), per audit/debug.

    Il sync verso Brevo (lista Beta Waitlist) è gestito da questo modulo
    (src/dashboard/app.py::_sync_tally_lead_to_brevo). La creazione account +
    invio credenziali (fase beta, automatica con tetto) è tracciata dai campi
    beta_account_granted*.
    """
    __tablename__ = "tally_leads"

    id                    = Column(Integer, primary_key=True, autoincrement=True)
    tally_submission_id   = Column(String, nullable=False, unique=True, index=True)
    email                 = Column(String, nullable=True)
    raw_payload           = Column(Text, nullable=True)  # JSON grezzo del submit Tally
    received_at           = Column(DateTime, default=datetime.utcnow)
    synced_to_brevo       = Column(Boolean, default=False, nullable=False)
    beta_account_granted    = Column(Boolean, default=False, nullable=False)
    beta_account_granted_at = Column(DateTime, nullable=True)
    # Referral: codice opaco assegnato a questo lead (usabile come referrer da altri) e,
    # se questo lead è arrivato tramite un link di invito, il codice di chi lo ha invitato.
    referral_code                  = Column(String, unique=True, index=True, nullable=True)
    referred_by_code                = Column(String, index=True, nullable=True)
    # Sbloccato quando questo lead (come referrer) accumula 3 referred lead: da onorare
    # quando il flusso di acquisto Lifetime Founder (oggi solo marketing) verrà costruito.
    lifetime_founder_guaranteed     = Column(Boolean, default=False, nullable=False)
    lifetime_founder_guaranteed_at  = Column(DateTime, nullable=True)


class ReferralReward(Base):
    """Reward Pro (60gg) da un referral: uno per il 'referred', uno (a occorrenza
    singola) per il 'referrer' — il tetto massimo per il referrer è fisso a
    days_granted indipendentemente dal numero di persone invitate.
    """
    __tablename__ = "referral_rewards"

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    beneficiary_email    = Column(String, nullable=False, index=True)
    beneficiary_chat_id  = Column(String, nullable=True)
    role                 = Column(String, nullable=False)  # 'referrer' | 'referred'
    days_granted         = Column(Integer, nullable=False, default=60)
    source_tally_lead_id = Column(Integer, ForeignKey("tally_leads.id"), nullable=True)
    status               = Column(String, nullable=False, default="pending")  # 'pending'|'applied'
    created_at           = Column(DateTime, default=datetime.utcnow)
    applied_at           = Column(DateTime, nullable=True)


class JobRun(Base):
    """Esito di un'esecuzione di job schedulato, per il monitoraggio in dashboard.

    Tabella operativa (nessun dato personale): registra ogni esecuzione dei job
    APScheduler (via listener EVENT_JOB_EXECUTED/ERROR/MISSED) e dei job di sistema
    (es. backup pg_dump, che vi scrive il proprio exit code reale). Consente alla
    dashboard admin di sapere se i job di oggi sono girati e con che esito, e di
    rilevare i "no-show" (job attesi ma mai eseguiti).

    `error_text` non contiene mai dati liberi utente: solo tipo/messaggio di
    eccezione, coerente con le regole di logging del progetto.
    """
    __tablename__ = "job_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String, nullable=False, index=True)        # id logico del job
    trigger_type = Column(String, nullable=True)               # 'cron'|'interval'|'manual'|'system'
    scheduled_at = Column(DateTime, nullable=True)             # orario previsto (se noto)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    status = Column(String, nullable=False)                    # 'success'|'error'|'missed'
    duration_ms = Column(Integer, nullable=True)
    return_code = Column(Integer, nullable=True)               # solo job-processo (es. backup)
    error_text = Column(String, nullable=True)                 # breve, senza dati sensibili

    __table_args__ = (
        Index("ix_job_runs_job_finished", "job_id", "finished_at"),
    )


class TxEvent(Base):
    """Esito di un tentativo di registrazione transazione (spesa/entrata/trasferimento).

    Rispecchia in Postgres gli eventi già inviati a PostHog via `analytics.track`
    (`expense_tracked` / `expense_tracking_failed`), così la dashboard admin può
    interrogarli senza dipendere dal vendor esterno. "Successo" = l'utente ha
    cliccato Conferma e la transazione è stata salvata (`outcome='confirmed'`).

    Cross-canale: `source` distingue Telegram e webapp. `reason` è breve e senza
    dati liberi utente (stessi valori già usati per PostHog: 'user_cancelled',
    'no_account', 'ai_unavailable', 'save_error').
    """
    __tablename__ = "tx_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(String, ForeignKey("users.chat_id"), nullable=False, index=True)
    occurred_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    tx_type = Column(String, nullable=False)         # 'expense'|'income'|'transfer'|'unknown'
    input_method = Column(String, nullable=False)    # 'text'|'voice'|'photo'|'button'
    outcome = Column(String, nullable=False)         # 'confirmed'|'cancelled'|'failed'
    source = Column(String, nullable=False)          # 'telegram'|'webapp'
    reason = Column(String, nullable=True)           # solo per cancelled/failed

    __table_args__ = (
        Index("ix_tx_events_type_method_occurred", "tx_type", "input_method", "occurred_at"),
    )


# 5. IL MANAGER DEL DATABASE
class UserStore:
    def __init__(
        self,
        db_url="sqlite:///users.db",
        pool_size: int = 5,
        max_overflow: int = 10,
    ):
        # create_engine è il "motore" che parla col database fisico
        engine_kwargs = {}
        if db_url.startswith("sqlite"):
            engine_kwargs["connect_args"] = {"check_same_thread": False}
            if ":memory:" in db_url:
                # SQLite :memory: crea un DB separato per ogni nuova connessione: senza
                # StaticPool, i job schedulati che girano su un thread diverso (come fa
                # davvero APScheduler in produzione) vedrebbero un DB vuoto. In produzione
                # (Postgres) questo non serve, qui è solo per coerenza con l'uso reale
                # multi-thread dei job.
                from sqlalchemy.pool import StaticPool
                engine_kwargs["poolclass"] = StaticPool
        else:
            # pool_size/max_overflow espliciti: bot e dashboard aprono ciascuno il proprio
            # engine verso lo stesso Postgres (max_connections condiviso e limitato sulla
            # VPS) — vanno dimensionati per processo, non lasciati al default SQLAlchemy
            # (5+10), altrimenti la somma dei pool di più processi rischia di saturare
            # Postgres da sola. pool_pre_ping evita di riusare connessioni cadute in
            # silenzio (timeout di rete/Postgres) su una VPS piccola.
            engine_kwargs["pool_size"] = pool_size
            engine_kwargs["max_overflow"] = max_overflow
            engine_kwargs["pool_pre_ping"] = True
        self.engine = create_engine(db_url, **engine_kwargs)
        # sessionmaker crea le "sessioni" di lavoro (come aprire una transazione)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

        # DDL a runtime (create_all + migrazioni colonne) — gestione dei privilegi:
        # su SQLite (dev/test) gira sempre, non c'è separazione di ruoli né Alembic.
        # Su Postgres gira SOLO se RUN_RUNTIME_MIGRATIONS=true: in produzione il
        # runtime usa un ruolo DML-only senza privilegi DDL, e lo schema lo gestisce
        # esclusivamente Alembic. Vedi deployment documentation e development documentation.
        is_sqlite = self.engine.dialect.name == "sqlite"
        run_runtime_ddl = is_sqlite or os.getenv("RUN_RUNTIME_MIGRATIONS", "false").lower() == "true"
        if run_runtime_ddl:
            # Questa riga crea fisicamente le tabelle se non esistono ancora
            Base.metadata.create_all(self.engine)
            self._ensure_sqlite_schema()
        else:
            logger.info("DDL a runtime disattivato (RUN_RUNTIME_MIGRATIONS=false): schema gestito da Alembic.")
        self._seed_default_pricing()
        # Engine OWNER (bypassa RLS) costruito on-demand: usato SOLO per le rare
        # operazioni cross-tenant che la RLS non può soddisfare (vedi _owner_session).
        self._owner_engine = None
        self._owner_Session = None
        logger.info(f"UserStore inizializzato correttamente.")

    @contextmanager
    def _user_session(self, user_id: str):
        """Sessione bindata al tenant `user_id`: imposta app.user_id per la RLS.

        Va usata da tutti i metodi che toccano le tabelle finanziarie (Option A:
        la RLS vincola anche il layer UserStore). No-op su SQLite. Fail-closed: se
        un metodo dimentica di usarla, sotto RLS non vede righe invece di leggere
        quelle di altri utenti.
        """
        from src.storage import rls
        session = self.Session()
        rls.bind_user(session, user_id)
        try:
            yield session
        finally:
            session.close()

    @contextmanager
    def _owner_session(self):
        """Sessione col ruolo OWNER che BYPASSA la RLS. Superficie deliberatamente
        minima: usarla SOLO per operazioni cross-tenant impossibili sotto RLS
        (es. reassign_user_chat_id, old→new user_id). Mai per flussi per-utente.

        In prod usa MIGRATION_DATABASE_URL (ruolo owner); in dev/sqlite ricade
        sull'engine applicativo (stesso ruolo, nessuna separazione).
        """
        if self._owner_Session is None:
            owner_url = os.getenv("MIGRATION_DATABASE_URL", "")
            if owner_url and self.engine.dialect.name != "sqlite":
                self._owner_engine = create_engine(owner_url)
                self._owner_Session = sessionmaker(bind=self._owner_engine, expire_on_commit=False)
            else:
                # Nessun ruolo owner separato (dev/sqlite): riusa l'engine applicativo.
                self._owner_Session = self.Session
        session = self._owner_Session()
        try:
            yield session
        finally:
            session.close()

    def _next_cycle_reset(self, now: datetime) -> datetime:
        next_month = now.month % 12 + 1
        year_offset = now.month // 12
        return datetime(now.year + year_offset, next_month, 1)

    def _seed_default_pricing(self) -> None:
        from config import Config

        defaults = [
            {
                "provider": "mistral",
                "model": Config.MISTRAL_SMALL_MODEL,
                "input_cost_per_1k": 0.0001,
                "output_cost_per_1k": 0.0003,
            },
            {
                "provider": "mistral",
                "model": Config.MISTRAL_LARGE_MODEL,
                "input_cost_per_1k": 0.0005,
                "output_cost_per_1k": 0.0015,
            },
            {
                "provider": "gemini",
                "model": Config.GEMINI_MODEL,
                "input_cost_per_1k": 0.0003,
                "output_cost_per_1k": 0.0025,
            },
            {
                "provider": "gemini-audio",
                "model": Config.GEMINI_MODEL,
                "input_cost_per_1k": 0.001,
                "output_cost_per_1k": 0.0025,
            },
        ]

        with self.Session() as session:
            for row in defaults:
                existing = session.query(LlmPricing).filter(
                    LlmPricing.provider == row["provider"],
                    LlmPricing.model == row["model"],
                    LlmPricing.valid_to.is_(None),
                ).first()
                if existing:
                    continue
                session.add(
                    LlmPricing(
                        provider=row["provider"],
                        model=row["model"],
                        valid_from=datetime(2026, 5, 1),
                        input_cost_per_1k=row["input_cost_per_1k"],
                        output_cost_per_1k=row["output_cost_per_1k"],
                        currency="USD",
                    )
                )
            session.commit()

    def _ensure_sqlite_schema(self) -> None:
        """Esegue migrazioni minime aggiungendo colonne mancanti senza perdita dati."""

        expected_user_columns = {
            "username": "TEXT",
            "expense_db_id": "TEXT",
            "income_db_id": "TEXT",
            "categories_db_id": "TEXT",
            "monthly_balance_db_id": "TEXT",
            "accounts_db_id": "TEXT",
            "subscriptions_db_id": "TEXT",
            "pay_transfer_db_id": "TEXT",
            "accounts_schema_json": "TEXT",
            "categories_schema_json": "TEXT",
            "subscriptions_schema_json": "TEXT",
            "notion_access_token": "TEXT",
            "notion_workspace_id": "TEXT",
            "created_at": "DATETIME",
            "is_active": "BOOLEAN DEFAULT 1",
            "setup_status": "TEXT DEFAULT 'WAIT_ACCOUNTS'",
            "setup_completed_at": "DATETIME",
            "email": "TEXT",
            "password_hash": "TEXT",
            "token_version": "INTEGER DEFAULT 0",
            "pinned_dashboard_msg_id": "INTEGER",
            "storage_backend": "TEXT DEFAULT 'notion'",
            "preferred_language": "TEXT DEFAULT 'it'",
            "currency": "TEXT DEFAULT 'EUR'",
            "timezone": "TEXT DEFAULT 'Europe/Rome'",
            "lifestyle_json": "TEXT",
            "monthly_budget": "REAL",
            "notification_time": "TEXT DEFAULT '08:00'",
            "notifications_enabled": "BOOLEAN DEFAULT 1",
            "onboarding_step": "TEXT DEFAULT 'pending'",
            "onboarding_completed_at": "DATETIME",
            "privacy_policy_version_accepted": "TEXT",
            "privacy_accepted_at": "DATETIME",
            "age_attestation_at": "DATETIME",
            "has_demo_data": "BOOLEAN DEFAULT 0",
            "tour_step": "TEXT",
            "tour_status": "TEXT",
            "tour_completed_at": "DATETIME",
        }

        dialect = self.engine.dialect.name

        def _existing_columns(conn, table: str) -> set[str]:
            if dialect == "sqlite":
                rows = conn.execute(text(f"PRAGMA table_info({table})")).mappings().all()
                return {r["name"] for r in rows}
            else:
                rows = conn.execute(text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = :t"
                ), {"t": table}).mappings().all()
                return {r["column_name"] for r in rows}

        def _pg_type(sqlite_type: str) -> str:
            """Converti tipo SQLite in tipo PostgreSQL."""
            upper = sqlite_type.split()[0].upper()
            mapping = {"TEXT": "TEXT", "BOOLEAN": "BOOLEAN", "DATETIME": "TIMESTAMP",
                       "INTEGER": "INTEGER", "FLOAT": "FLOAT", "REAL": "REAL"}
            return mapping.get(upper, "TEXT")

        with self.engine.begin() as connection:
            # 1. Verifica colonne tabella users
            existing = _existing_columns(connection, "users")
            if existing:
                for column_name, column_type in expected_user_columns.items():
                    if column_name in existing:
                        continue
                    col_type = column_type if dialect == "sqlite" else _pg_type(column_type)
                    connection.execute(text(f"ALTER TABLE users ADD COLUMN {column_name} {col_type}"))
                    logger.info(f"[DB Migration] Aggiunta colonna users.{column_name}")

                if dialect == "sqlite" and "notion_api_key" in existing:
                    try:
                        connection.execute(text("ALTER TABLE users DROP COLUMN notion_api_key"))
                        logger.info("[DB Migration] Rimossa colonna legacy users.notion_api_key")
                    except Exception:
                        logger.debug("[DB Migration] SQLite non supporta DROP COLUMN su notion_api_key, lascio la colonna legacy.")

            # 1b. Verifica colonne tabella subscriptions
            sub_cols = _existing_columns(connection, "subscriptions")
            if sub_cols and "amount" not in sub_cols:
                col_type = "REAL" if dialect == "sqlite" else "FLOAT"
                connection.execute(text(f"ALTER TABLE subscriptions ADD COLUMN amount {col_type}"))
                logger.info("[DB Migration] Aggiunta colonna subscriptions.amount")

            # 1c. Finance tables migrate toward 3NF-compatible shape
            acc_cols = _existing_columns(connection, "accounts")
            if acc_cols and "opening_balance" not in acc_cols:
                connection.execute(text("ALTER TABLE accounts ADD COLUMN opening_balance REAL DEFAULT 0"))
                connection.execute(text(
                    "UPDATE accounts SET opening_balance = COALESCE(balance, 0)"
                ))
                logger.info("[DB Migration] Aggiunta colonna accounts.opening_balance con backfill iniziale.")

            exp_cols = _existing_columns(connection, "expenses")
            if exp_cols and "category_id" not in exp_cols:
                connection.execute(text("ALTER TABLE expenses ADD COLUMN category_id INTEGER"))
                logger.info("[DB Migration] Aggiunta colonna expenses.category_id.")

            if exp_cols and "created_at" not in exp_cols:
                connection.execute(text("ALTER TABLE expenses ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"))

            inc_cols = _existing_columns(connection, "incomes")
            if inc_cols and "created_at" not in inc_cols:
                connection.execute(text("ALTER TABLE incomes ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"))

            cat_cols = _existing_columns(connection, "user_categories")
            if cat_cols and "monthly_budget" not in cat_cols:
                connection.execute(text("ALTER TABLE user_categories ADD COLUMN monthly_budget REAL"))

            if dialect == "sqlite":
                # Ripulisce la tabella legacy non più usata.
                try:
                    connection.execute(text("DROP TABLE IF EXISTS daily_usage"))
                except Exception:
                    logger.debug("[DB Migration] Impossibile droppare daily_usage, continuo.")

                # Popola i link Notion separati dalla tabella legacy user_categories.
                link_cols = _existing_columns(connection, "user_category_notion_links")
                if link_cols and cat_cols and "notion_page_id" in cat_cols:
                    rows = connection.execute(text(
                        "SELECT id, notion_page_id, synced_at, average "
                        "FROM user_categories "
                        "WHERE notion_page_id IS NOT NULL"
                    )).mappings().all()
                    for row in rows:
                        connection.execute(text(
                            "INSERT OR REPLACE INTO user_category_notion_links "
                            "(category_id, notion_page_id, synced_at, average) "
                            "VALUES (:cid, :pid, :synced_at, :avg)"
                        ), {
                            "cid": row["id"],
                            "pid": row["notion_page_id"],
                            "synced_at": row["synced_at"],
                            "avg": row["average"],
                        })

                # Backfill category_id dai nomi categoria legacy.
                exp_cols = _existing_columns(connection, "expenses")
                if exp_cols and "category_name" in exp_cols and "category_id" in exp_cols:
                    missing_cats = connection.execute(text(
                        "SELECT DISTINCT e.user_id, e.category_name "
                        "FROM expenses e "
                        "LEFT JOIN user_categories c "
                        "  ON c.user_id = e.user_id AND c.name = e.category_name "
                        "WHERE e.category_name IS NOT NULL AND c.id IS NULL"
                    )).mappings().all()
                    for row in missing_cats:
                        connection.execute(text(
                            # average inclusa con valore di default perché il DB SQLite
                            # legacy ha ancora il vincolo NOT NULL su questa colonna.
                            "INSERT INTO user_categories (user_id, name, monthly_budget, average) "
                            "VALUES (:uid, :name, NULL, 0.0)"
                        ), {"uid": row["user_id"], "name": row["category_name"]})

                    connection.execute(text(
                        "UPDATE expenses "
                        "SET category_id = ("
                        "  SELECT c.id FROM user_categories c "
                        "  WHERE c.user_id = expenses.user_id AND c.name = expenses.category_name "
                        "  LIMIT 1"
                        ") "
                        "WHERE category_id IS NULL AND category_name IS NOT NULL"
                    ))

                # Backfill opening_balance usando la formula corrente - entrate + uscite.
                if acc_cols and "balance" in acc_cols:
                    connection.execute(text(
                        "UPDATE accounts "
                        "SET opening_balance = COALESCE(balance, 0)"
                        " - COALESCE((SELECT SUM(amount) FROM incomes i WHERE i.user_id = accounts.user_id AND i.account_id = accounts.id), 0)"
                        " + COALESCE((SELECT SUM(amount) FROM expenses e WHERE e.user_id = accounts.user_id AND e.account_id = accounts.id), 0)"
                    ))

            # 2. Migrazione dati da users a database_schemas (se necessario)
            # Verifichiamo se database_schemas ha già dati
            schema_count = connection.execute(text("SELECT COUNT(*) FROM database_schemas")).scalar()
            if schema_count == 0:
                # Proviamo a svuotare i vecchi dati schema da User e portarli nella nuova tabella
                old_data = connection.execute(text(
                    "SELECT chat_id, accounts_db_id, accounts_schema_json, "
                    "categories_db_id, categories_schema_json, "
                    "subscriptions_db_id, subscriptions_schema_json FROM users"
                )).mappings().all()

                for row in old_data:
                    c_id = row["chat_id"]
                    # Mapping chiavi vecchie -> nuove
                    mappings = [
                        ("accounts_db_id", row["accounts_db_id"], row["accounts_schema_json"]),
                        ("categories_db_id", row["categories_db_id"], row["categories_schema_json"]),
                        ("subscriptions_db_id", row["subscriptions_db_id"], row["subscriptions_schema_json"]),
                    ]
                    for db_key, db_id, schema in mappings:
                        if db_id or schema:
                            connection.execute(text(
                                "INSERT INTO database_schemas (chat_id, db_key, notion_db_id, properties_json) "
                                "VALUES (:chat_id, :db_key, :db_id, :schema)"
                            ), {"chat_id": c_id, "db_key": db_key, "db_id": db_id, "schema": schema})
                
                if old_data:
                    logger.info(f"[DB Migration] Migrati schemi per {len(old_data)} utenti verso database_schemas.")

    def get_user(self, chat_id: str) -> User | None:
        """Cerca un utente per chat_id. Se non esiste o è disattivato, torna None."""
        chat_id = str(chat_id)
        with self.Session() as session:
            return session.query(User).filter(User.chat_id == chat_id, User.is_active == True).first()

    def get_user_any_status(self, chat_id: str) -> User | None:
        """Cerca un utente per chat_id indipendentemente da is_active (utile per distinguere sospeso da mai registrato)."""
        chat_id = str(chat_id)
        with self.Session() as session:
            return session.query(User).filter(User.chat_id == chat_id).first()

    def update_telegram_identity(self, chat_id: str, first_name: str | None, last_name: str | None) -> None:
        """Aggiorna first_name/last_name da Telegram se cambiati (no-op se l'utente non esiste)."""
        chat_id = str(chat_id)
        with self.Session() as session:
            user = session.query(User).filter(User.chat_id == chat_id).first()
            if not user:
                return
            if user.first_name != first_name or user.last_name != last_name:
                user.first_name = first_name
                user.last_name = last_name
                session.commit()

    def add_user(self, chat_id: str, notion_api_key: str = None, expense_db_id: str = None, income_db_id: str = None, **kwargs):
        """Aggiunge un nuovo utente o aggiorna uno esistente."""
        chat_id = str(chat_id)
        with self.Session() as session:
            user = session.query(User).filter(User.chat_id == chat_id).first()
            if not user:
                user = User(chat_id=chat_id)
                session.add(user)
                user.setup_status = "WAIT_ACCOUNTS"
            
            user.notion_api_key = notion_api_key
            user.expense_db_id = expense_db_id
            user.income_db_id = income_db_id
            user.is_active = True
            
            # Applichiamo i parametri extra (es. username o altri DB ID)
            for key, value in kwargs.items():
                if hasattr(user, key):
                    setattr(user, key, value)
            
            session.commit() # Salvataggio definitivo su disco!
            return user

    def update_setup_status(self, chat_id: str, setup_status: str) -> None:
        """Aggiorna lo stato del setup utente."""
        chat_id = str(chat_id)
        with self.Session() as session:
            user = session.query(User).filter(User.chat_id == chat_id).first()
            if not user:
                return
            user.setup_status = setup_status
            session.commit()

    def mark_setup_completed(self, chat_id: str) -> None:
        """Marca il setup come completato con timestamp."""
        chat_id = str(chat_id)
        with self.Session() as session:
            user = session.query(User).filter(User.chat_id == chat_id).first()
            if not user:
                return
            user.setup_status = "DONE"
            user.setup_completed_at = datetime.utcnow()
            session.commit()

    def save_onboarding_progress(self, chat_id: str, step: str, data: dict) -> None:
        """Salva lo step corrente e mappa i dati ai campi utente corrispondenti."""
        chat_id = str(chat_id)
        with self.Session() as session:
            user = session.query(User).filter(User.chat_id == chat_id).first()
            if not user:
                return
            user.onboarding_step = step
            if 'language' in data:
                user.preferred_language = data['language']
            if 'currency' in data:
                user.currency = data['currency']
            if 'timezone' in data:
                user.timezone = data['timezone']
            if any(k in data for k in ('transport', 'dining', 'hobbies')):
                current = json.loads(user.lifestyle_json) if user.lifestyle_json else {}
                for key in ('transport', 'dining', 'hobbies'):
                    if key in data:
                        current[key] = data[key]
                user.lifestyle_json = json.dumps(current)
            if 'budget' in data:
                user.monthly_budget = data['budget']
            if 'notification_time' in data:
                user.notification_time = data['notification_time']
            if 'notifications_enabled' in data:
                user.notifications_enabled = data['notifications_enabled']
            session.commit()

    def complete_onboarding(self, chat_id: str) -> None:
        """Marca l'onboarding come completato con timestamp."""
        chat_id = str(chat_id)
        with self.Session() as session:
            user = session.query(User).filter(User.chat_id == chat_id).first()
            if not user:
                return
            user.onboarding_completed_at = datetime.utcnow()
            user.onboarding_step = 'completed'
            session.commit()

    def set_has_demo_data(self, chat_id: str, value: bool) -> None:
        """Imposta il flag has_demo_data per l'utente."""
        chat_id = str(chat_id)
        with self.Session() as session:
            user = session.query(User).filter(User.chat_id == chat_id).first()
            if not user:
                return
            user.has_demo_data = value
            session.commit()

    def clear_demo_data(self, chat_id: str, storage) -> int:
        """Cancella le spese demo e resetta il flag. Ritorna il numero di spese cancellate."""
        count = -1
        if hasattr(storage, "delete_expenses_by_prefix"):
            from src.demo_data import DEMO_PREFIX
            count = storage.delete_expenses_by_prefix(DEMO_PREFIX)
        self.set_has_demo_data(chat_id, False)
        return count

    def get_user_preferences(self, chat_id: str) -> dict:
        """Restituisce le preferenze utente come dizionario."""
        chat_id = str(chat_id)
        with self.Session() as session:
            user = session.query(User).filter(User.chat_id == chat_id).first()
            if not user:
                return {}
            return {
                'preferred_language': user.preferred_language,
                'currency': user.currency,
                'timezone': user.timezone,
                'lifestyle': json.loads(user.lifestyle_json) if user.lifestyle_json else {},
                'monthly_budget': user.monthly_budget,
                'notification_time': user.notification_time,
                'notifications_enabled': user.notifications_enabled,
                'onboarding_step': user.onboarding_step,
                'onboarding_completed_at': user.onboarding_completed_at.isoformat() if user.onboarding_completed_at else None,
            }

    def set_credentials(self, chat_id: str, email: str, password: str) -> None:
        """Salva email e hash Argon2id della password per un utente."""
        chat_id = str(chat_id)
        hashed = hash_password(password)
        with self.Session() as session:
            user = session.query(User).filter(User.chat_id == chat_id).first()
            if user:
                user.email = email.lower().strip()
                user.password_hash = hashed
                session.commit()

    def update_email(self, chat_id: str, new_email: str) -> bool:
        """Aggiorna solo l'email di un utente già registrato. Ritorna False se l'utente non esiste."""
        chat_id = str(chat_id)
        with self.Session() as session:
            user = session.query(User).filter(User.chat_id == chat_id).first()
            if not user:
                return False
            user.email = new_email.lower().strip()
            session.commit()
            return True

    def update_password(self, chat_id: str, new_password: str) -> bool:
        """Aggiorna l'hash della password di un utente già registrato.

        Incrementa anche `token_version` per invalidare tutte le sessioni esistenti:
        un cambio password deve sloggare ovunque (standard di sicurezza). Il device
        che effettua il cambio dovrà riallineare la propria sessione al nuovo valore.
        Ritorna False se l'utente non esiste.
        """
        chat_id = str(chat_id)
        hashed = hash_password(new_password)
        with self.Session() as session:
            user = session.query(User).filter(User.chat_id == chat_id).first()
            if not user:
                return False
            user.password_hash = hashed
            user.token_version = (user.token_version or 0) + 1
            session.commit()
            return True

    def get_token_version(self, chat_id: str) -> int | None:
        """Ritorna la `token_version` corrente dell'utente, o None se non esiste."""
        chat_id = str(chat_id)
        with self.Session() as session:
            row = (
                session.query(User.token_version)
                .filter(User.chat_id == chat_id)
                .first()
            )
            if row is None:
                return None
            return row[0] or 0

    def bump_token_version(self, chat_id: str) -> int | None:
        """Incrementa `token_version` per revocare tutte le sessioni dell'utente.

        Usato da "esci da tutti i dispositivi". Ritorna il nuovo valore, o None
        se l'utente non esiste.
        """
        chat_id = str(chat_id)
        with self.Session() as session:
            user = session.query(User).filter(User.chat_id == chat_id).first()
            if not user:
                return None
            user.token_version = (user.token_version or 0) + 1
            new_version = user.token_version
            session.commit()
            return new_version

    def get_user_by_email(self, email: str) -> User | None:
        """Cerca un utente attivo per email (case-insensitive)."""
        with self.Session() as session:
            return session.query(User).filter(
                User.email == email.lower().strip(),
                User.is_active == True,
            ).first()

    def get_user_by_email_any_status(self, email: str) -> User | None:
        """Cerca un utente per email senza filtrare per is_active (utile per riattivare account sospesi)."""
        with self.Session() as session:
            return session.query(User).filter(
                User.email == email.lower().strip(),
            ).first()

    def _persist_password_hash(self, chat_id: str, new_hash: str) -> None:
        """Aggiorna in modo mirato l'hash password (usato per il rehash trasparente)."""
        with self.Session() as session:
            session.query(User).filter(User.chat_id == str(chat_id)).update(
                {"password_hash": new_hash}
            )
            session.commit()

    def verify_password(self, email: str, password: str) -> User | None:
        """Verifica email+password. Ritorna l'utente se le credenziali sono corrette, None altrimenti.

        Supporta hash Argon2id e bcrypt legacy: se la verifica ha successo su un
        hash legacy/obsoleto, la password viene ri-hashata ad Argon2id e salvata.
        """
        user = self.get_user_by_email(email)
        if not user or not user.password_hash:
            return None
        ok, new_hash = verify_password_hash(password, user.password_hash)
        if not ok:
            return None
        if new_hash:
            self._persist_password_hash(user.chat_id, new_hash)
            user.password_hash = new_hash
        return user

    def verify_password_any_status(self, email: str, password: str) -> User | None:
        """Come verify_password ma cerca anche utenti sospesi (is_active=False). Usato per il re-login."""
        user = self.get_user_by_email_any_status(email)
        if not user or not user.password_hash:
            return None
        ok, new_hash = verify_password_hash(password, user.password_hash)
        if not ok:
            return None
        if new_hash:
            self._persist_password_hash(user.chat_id, new_hash)
            user.password_hash = new_hash
        return user

    def logout_user(self, chat_id: str) -> None:
        """Sospende temporaneamente l'account impostando is_active=False. I dati sono preservati."""
        chat_id = str(chat_id)
        with self.Session() as session:
            session.query(User).filter(User.chat_id == chat_id).update({"is_active": False})
            session.commit()

    def reactivate_user(self, chat_id: str) -> None:
        """Riattiva un account sospeso impostando is_active=True."""
        chat_id = str(chat_id)
        with self.Session() as session:
            session.query(User).filter(User.chat_id == chat_id).update({"is_active": True})
            session.commit()

    def reassign_user_chat_id(self, old_chat_id: str, new_chat_id: str) -> bool:
        """Ricollega un account esistente a un nuovo chat_id Telegram.

        Aggiorna anche tutte le tabelle locali che referenziano `users.chat_id`.
        Se il `new_chat_id` è già occupato da un altro account reale, solleva ValueError.
        """
        from src.storage.models import (
            Expense, Income, Account, Subscription, UserCategory, SavedReport
        )

        old_chat_id = str(old_chat_id)
        new_chat_id = str(new_chat_id)

        if old_chat_id == new_chat_id:
            return False

        # BYPASS RLS CHIRURGICO: operazione cross-tenant (sposta righe da old→new
        # user_id) impossibile sotto RLS con WITH CHECK. Unico uso di _owner_session
        # nei flussi per-utente; query rigorosamente parametrizzate. Vedi Option A.
        with self._owner_session() as session:
            user = session.query(User).filter(User.chat_id == old_chat_id).first()
            if not user:
                return False

            target_user = session.query(User).filter(User.chat_id == new_chat_id).first()
            if target_user:
                same_email = bool(user.email and target_user.email and user.email == target_user.email)
                target_is_placeholder = not any([
                    target_user.email,
                    target_user.password_hash,
                    target_user.notion_access_token,
                    target_user.expense_db_id,
                    target_user.income_db_id,
                    target_user.categories_db_id,
                    target_user.accounts_db_id,
                    target_user.subscriptions_db_id,
                    target_user.pay_transfer_db_id,
                ])
                if not same_email and not target_is_placeholder:
                    raise ValueError(f"chat_id {new_chat_id} gia associato a un altro account")

                if target_is_placeholder:
                    # Un placeholder puo' comunque avere righe figlie (es. categorie di
                    # default create al primo /start, o la riga UserPlan — chat_id e'
                    # la sua primary key). Senza pulirle: su Postgres la FK blocca subito
                    # `session.delete(target_user)`; su SQLite (FK non enforced di
                    # default) l'errore emerge piu' avanti, sui vincoli UNIQUE, quando il
                    # bulk update sposta old_chat_id -> new_chat_id. ChatMessage non ha
                    # vincoli unique e puo' contenere cronologia reale: non la tocchiamo.
                    session.query(Expense).filter(Expense.user_id == new_chat_id).delete()
                    session.query(Income).filter(Income.user_id == new_chat_id).delete()
                    session.query(Account).filter(Account.user_id == new_chat_id).delete()
                    session.query(Subscription).filter(Subscription.user_id == new_chat_id).delete()
                    session.query(UserCategory).filter(UserCategory.user_id == new_chat_id).delete()
                    session.query(SavedReport).filter(SavedReport.user_id == new_chat_id).delete()
                    session.query(Feedback).filter(Feedback.chat_id == new_chat_id).delete()
                    session.query(DatabaseSchema).filter(DatabaseSchema.chat_id == new_chat_id).delete()
                    session.query(OAuthSession).filter(OAuthSession.chat_id == new_chat_id).delete()
                    session.query(UserPlan).filter(UserPlan.chat_id == new_chat_id).delete()
                    session.query(PlanChange).filter(PlanChange.chat_id == new_chat_id).delete()

                session.delete(target_user)
                session.flush()

            # Non si puo' aggiornare users.chat_id in-place in nessun ordine: la FK
            # (senza ON UPDATE CASCADE) blocca sia l'update della tabella padre mentre
            # le figlie referenziano ancora old_chat_id, sia l'update delle figlie verso
            # un new_chat_id che non esiste ancora nella tabella padre. Si clona la riga
            # users con make_transient (nuovo INSERT con new_chat_id), si spostano le
            # tabelle figlie sul nuovo valore, e solo alla fine si cancella la vecchia
            # riga users (quando nessuna FK la referenzia piu').
            from sqlalchemy.orm import make_transient

            # email ha un vincolo UNIQUE: finche' la vecchia riga non e' cancellata,
            # la nuova riga non puo' avere la stessa email. La "libera" temporaneamente
            # sulla vecchia riga (verra' comunque cancellata a fine funzione).
            old_email = user.email
            if old_email:
                session.query(User).filter(User.chat_id == old_chat_id).update(
                    {"email": f"_reassigning_{old_chat_id}"}
                )
                session.flush()

            session.expunge(user)
            make_transient(user)
            user.email = old_email
            user.chat_id = new_chat_id
            session.add(user)
            session.flush()

            # Tabelle di supporto
            session.query(Feedback).filter(Feedback.chat_id == old_chat_id).update({"chat_id": new_chat_id})
            session.query(DatabaseSchema).filter(DatabaseSchema.chat_id == old_chat_id).update({"chat_id": new_chat_id})
            session.query(OAuthSession).filter(OAuthSession.chat_id == old_chat_id).update({"chat_id": new_chat_id})
            session.query(UserPlan).filter(UserPlan.chat_id == old_chat_id).update({"chat_id": new_chat_id})
            session.query(PlanChange).filter(PlanChange.chat_id == old_chat_id).update({"chat_id": new_chat_id})
            session.query(LlmTokenReservation).filter(LlmTokenReservation.chat_id == old_chat_id).update({"chat_id": new_chat_id})
            session.query(LlmUsageEvent).filter(LlmUsageEvent.chat_id == old_chat_id).update({"chat_id": new_chat_id})
            session.query(ChatMessage).filter(ChatMessage.chat_id == old_chat_id).update({"chat_id": new_chat_id})

            # Tabelle finanziarie
            session.query(Expense).filter(Expense.user_id == old_chat_id).update({"user_id": new_chat_id})
            session.query(Income).filter(Income.user_id == old_chat_id).update({"user_id": new_chat_id})
            session.query(Account).filter(Account.user_id == old_chat_id).update({"user_id": new_chat_id})
            session.query(Subscription).filter(Subscription.user_id == old_chat_id).update({"user_id": new_chat_id})
            session.query(UserCategory).filter(UserCategory.user_id == old_chat_id).update({"user_id": new_chat_id})
            session.query(SavedReport).filter(SavedReport.user_id == old_chat_id).update({"user_id": new_chat_id})

            # Ora nessuna FK referenzia piu' old_chat_id: la vecchia riga users si puo' cancellare
            session.query(User).filter(User.chat_id == old_chat_id).delete()

            session.commit()
            return True

    def increment_usage(self, chat_id: str, msg_type: str) -> None:
        """Legacy no-op: i contatori daily_usage sono stati rimossi nel refactor 3NF.

        La firma è mantenuta per retrocompatibilità con bot.py che la chiama.
        Il consumo reale viene ora tracciato via `finalize_llm_usage`.
        """
        logger.debug("[User %s] increment_usage ignorato: daily_usage rimosso.", chat_id)

    def increment_ai_metrics(self, success: bool) -> None:
        """Incrementa il contatore giornaliero di goal_completions o fallbacks.

        Chiamare con success=True quando l'AI ha estratto correttamente l'intent
        (es. spesa/entrata registrata), con success=False in caso di fallback
        (es. ConversationHandler che non riesce a parsare l'importo).
        """
        today = date.today()
        with self.Session() as session:
            row = session.query(DailyMetrics).filter_by(metrics_date=today).first()
            if not row:
                row = DailyMetrics(metrics_date=today)
                session.add(row)
            if success:
                row.goal_completions = (row.goal_completions or 0) + 1
            else:
                row.fallbacks = (row.fallbacks or 0) + 1
            session.commit()
            logger.debug(f"[AI Metrics] {'completion' if success else 'fallback'} (+1) — {today}")

    def save_feedback(self, chat_id: str, message: str):
        """Salva un feedback utente."""
        chat_id = str(chat_id)
        with self.Session() as session:
            fb = Feedback(chat_id=chat_id, message=message)
            session.add(fb)
            session.commit()
            logger.info(f"[User {chat_id}] Salvato nuovo feedback.")

    # --- METODI OAUTH (Fase 2) ---
    def generate_secure_token(self, length=12) -> str:
        """Genera un token alfanumerico casuale (es: RT-Hkd83L)."""
        alphabet = string.ascii_letters + string.digits
        return "RT-" + "".join(secrets.choice(alphabet) for _ in range(length))

    def create_oauth_session(self, chat_id: str) -> str:
        """Crea una sessione temporanea con un token casuale e ritorna il token."""
        state = self.generate_secure_token()
        with self.Session() as session:
            # Rimuoviamo eventuali sessioni vecchie dello stesso utente (pulizia)
            session.query(OAuthSession).filter_by(chat_id=chat_id).delete()
            
            new_session = OAuthSession(chat_id=chat_id, state=state)
            session.add(new_session)
            session.commit()
            logger.info(f"[Auth] Magic Token generato per chat_id={chat_id} (token={state})")
            return state

    def get_and_delete_oauth_session(self, state: str) -> str | None:
        """Controlla se lo state è valido e non scaduto, ritorna il chat_id e cancella la sessione."""
        with self.Session() as session:
            oauth_sess = session.query(OAuthSession).filter_by(state=state).first()
            if not oauth_sess:
                return None
            if oauth_sess.expires_at < datetime.utcnow():
                session.delete(oauth_sess)
                session.commit()
                logger.warning("[Auth] Token OAuth scaduto per state=%s", state)
                return None
            chat_id = oauth_sess.chat_id
            session.delete(oauth_sess)
            session.commit()
            return chat_id

    def peek_oauth_session(self, state: str) -> str | None:
        """Legge il chat_id associato a uno state senza consumare la sessione.

        Usato quando l'operazione successiva puo' fallire (es. reassign_user_chat_id):
        il token va consumato con get_and_delete_oauth_session solo a operazione riuscita,
        cosi' un fallimento permette di ritentare con lo stesso link entro la scadenza.
        """
        with self.Session() as session:
            oauth_sess = session.query(OAuthSession).filter_by(state=state).first()
            if not oauth_sess or oauth_sess.expires_at < datetime.utcnow():
                return None
            return oauth_sess.chat_id

    def cleanup_expired_oauth_sessions(self) -> int:
        """Rimuove le sessioni OAuth scadute. Chiamata dal job APScheduler notturno."""
        with self.Session() as session:
            deleted = session.query(OAuthSession).filter(
                OAuthSession.expires_at < datetime.utcnow()
            ).delete(synchronize_session=False)
            session.commit()
        if deleted:
            logger.info("[Auth] Cleanup OAuth: rimossi %d token scaduti.", deleted)
        return deleted

    def save_database_schema(self, chat_id: str, db_key: str, notion_db_id: str, properties_json: str, mapped_properties_json: str = None) -> None:
        """Salva o aggiorna lo schema di un database per un utente."""
        chat_id = str(chat_id)
        with self.Session() as session:
            schema = session.query(DatabaseSchema).filter_by(chat_id=chat_id, db_key=db_key).first()
            if not schema:
                schema = DatabaseSchema(chat_id=chat_id, db_key=db_key)
                session.add(schema)
            
            schema.notion_db_id = notion_db_id
            schema.properties_json = properties_json
            if mapped_properties_json:
                schema.mapped_properties_json = mapped_properties_json
            
            session.commit()
            logger.info(f"[User {chat_id}] Schema salvato per {db_key}.")

    def get_active_notion_users(self) -> list:
        """Ritorna tutti gli utenti attivi con storage_backend Notion."""
        with self.Session() as session:
            return session.query(User).filter(
                User.is_active == True,
                User.storage_backend == "notion",
                User.setup_status == "DONE",
            ).all()

    def get_active_postgres_users(self) -> list:
        """Ritorna tutti gli utenti attivi con storage_backend Postgres.

        Il flow di onboarding beta (create_beta_account) imposta setup_status
        a "COMPLETED" invece di "DONE" (usato dal flow Notion) — accettiamo
        entrambi i valori per non escludere gli utenti Postgres dai job.
        """
        with self.Session() as session:
            return session.query(User).filter(
                User.is_active == True,
                User.storage_backend == "postgres",
                User.setup_status.in_(["DONE", "COMPLETED"]),
            ).all()

    def get_pro_users(self) -> list[User]:
        """Ritorna tutti gli utenti attivi con piano PRO."""
        with self.Session() as session:
            return session.query(User).join(UserPlan, User.chat_id == UserPlan.chat_id).filter(
                User.is_active == True,
                UserPlan.plan_type == "pro"
            ).all()

    # --- METODI USER CATEGORIES ---

    def upsert_user_categories(self, user_id: str, categories: list[dict]) -> None:
        """Inserisce o aggiorna le categorie di un utente.

        Ogni dict deve avere: `name` (str) e opzionalmente `average` (float),
        `notion_page_id` (str), `synced_at` (datetime), `monthly_budget` (float).
        I metadati Notion sono salvati in `user_category_notion_links`.
        """
        from src.storage.models import UserCategory, UserCategoryNotionLink
        user_id = str(user_id)
        now = datetime.utcnow()
        with self._user_session(user_id) as session:
            for cat in categories:
                notion_page_id = cat.get("notion_page_id")
                cat_row = None

                # 1. Match per notion_page_id: gestisce i rinomini (il page_id è
                #    stabile, il nome cambia) senza creare duplicati.
                if notion_page_id:
                    link = (
                        session.query(UserCategoryNotionLink)
                        .join(UserCategory, UserCategory.id == UserCategoryNotionLink.category_id)
                        .filter(
                            UserCategory.user_id == user_id,
                            UserCategoryNotionLink.notion_page_id == notion_page_id,
                        )
                        .first()
                    )
                    if link:
                        cat_row = session.get(UserCategory, link.category_id)

                # 2. Fallback: match per nome (righe legacy senza link).
                if cat_row is None:
                    cat_row = session.query(UserCategory).filter_by(
                        user_id=user_id, name=cat["name"]
                    ).first()

                # 3. Crea se non esiste.
                if cat_row is None:
                    cat_row = UserCategory(
                        user_id=user_id,
                        name=cat["name"],
                        monthly_budget=cat.get("monthly_budget"),
                    )
                    session.add(cat_row)
                    session.flush()  # ottieni l'id
                else:
                    # Rinomina: aggiorna il nome evitando la collisione col vincolo
                    # unique (user_id, name). Se esiste già una riga col nuovo nome,
                    # si fondono (i dipendenti passano alla riga corrente).
                    if cat_row.name != cat["name"]:
                        dup = session.query(UserCategory).filter_by(
                            user_id=user_id, name=cat["name"]
                        ).first()
                        if dup is not None and dup.id != cat_row.id:
                            self._merge_category_into(session, user_id, cat_row, dup)
                        cat_row.name = cat["name"]
                    if cat.get("monthly_budget") is not None:
                        cat_row.monthly_budget = cat["monthly_budget"]

                # Upsert user_category_notion_links se ci sono metadati Notion
                if notion_page_id:
                    link = session.query(UserCategoryNotionLink).filter_by(
                        category_id=cat_row.id
                    ).first()
                    if not link:
                        link = UserCategoryNotionLink(category_id=cat_row.id)
                        session.add(link)
                    link.notion_page_id = notion_page_id
                    link.synced_at = cat.get("synced_at", now)
                    link.average = cat.get("average", 0.0)

            session.commit()

    @staticmethod
    def _merge_category_into(session, user_id: str, keep, dup) -> None:
        """Fonde la categoria `dup` in `keep`: sposta i record dipendenti e la elimina.

        Serve quando un rinomina su Notion porta il nome a collidere con un'altra
        riga esistente (caso limite). I metadati Notion di `keep` restano quelli
        authoritative.
        """
        from src.storage.models import Expense, Subscription, UserCategoryNotionLink

        session.query(Expense).filter_by(user_id=user_id, category_id=dup.id).update(
            {"category_id": keep.id}, synchronize_session=False
        )
        session.query(Subscription).filter_by(user_id=user_id, category_id=dup.id).update(
            {"category_id": keep.id}, synchronize_session=False
        )
        dup_link = session.query(UserCategoryNotionLink).filter_by(category_id=dup.id).first()
        if dup_link is not None:
            session.delete(dup_link)
        session.delete(dup)
        session.flush()
        logger.warning(
            "[Categories] Rinomina con collisione: fusa categoria duplicata id=%s in id=%s per %s.",
            dup.id, keep.id, user_id,
        )

    def reconcile_user_categories(self, user_id: str, valid_page_ids: set) -> "ReconcileReport":
        """Allinea `user_categories` allo stato corrente di Notion.

        Cancella dalla cache le categorie il cui `notion_page_id` non è più tra i
        `valid_page_ids` (cioè sono state rimosse/archiviate su Notion). Le categorie
        con spese/abbonamenti dipendenti vengono prima riassegnate alla categoria di
        fallback `Altro` (creata se assente), poi cancellate.

        IMPORTANTE: il chiamante deve invocare questo metodo SOLO dopo un fetch Notion
        andato a buon fine — altrimenti un errore transitorio azzererebbe la cache.

        Ritorna un `ReconcileReport` con le cancellazioni e le riassegnazioni.
        """
        from src.storage.models import (
            UserCategory,
            UserCategoryNotionLink,
            Expense,
            Subscription,
        )

        user_id = str(user_id)
        valid = set(valid_page_ids or [])
        report = ReconcileReport()

        with self._user_session(user_id) as session:
            rows = (
                session.query(UserCategory, UserCategoryNotionLink)
                .join(
                    UserCategoryNotionLink,
                    UserCategoryNotionLink.category_id == UserCategory.id,
                )
                .filter(UserCategory.user_id == user_id)
                .all()
            )

            fallback_row = None  # risolta pigramente solo se serve

            for cat, link in rows:
                # Solo le categorie mappate a Notion sono soggette a riconciliazione.
                if link is None or link.notion_page_id is None:
                    continue
                if link.notion_page_id in valid:
                    continue

                cat_id = cat.id
                cat_name = cat.name

                expenses = session.query(Expense).filter_by(
                    user_id=user_id, category_id=cat_id
                ).all()
                subs = session.query(Subscription).filter_by(
                    user_id=user_id, category_id=cat_id
                ).all()

                if expenses or subs:
                    # Non cancellare il fallback stesso: farebbe da rete di sicurezza
                    # per i propri dipendenti. Lo si mantiene.
                    if cat_name == FALLBACK_CATEGORY_NAME:
                        logger.warning(
                            "[Reconcile] '%s' con dipendenti è fuori da Notion ma è il "
                            "fallback: mantenuta per %s.", cat_name, user_id,
                        )
                        continue

                    if fallback_row is None:
                        fallback_row = self._ensure_fallback_category(session, user_id)
                    # Evita di riassegnare al fallback se coincide (paranoia).
                    if fallback_row.id != cat_id:
                        for e in expenses:
                            e.category_id = fallback_row.id
                        for sub in subs:
                            sub.category_id = fallback_row.id
                        report.reassignments.append(
                            CategoryReassignment(
                                category_name=cat_name,
                                moved_expenses=len(expenses),
                                moved_subscriptions=len(subs),
                            )
                        )
                        session.flush()

                session.delete(link)
                session.delete(cat)
                report.deleted_categories.append(cat_name)

            if report.changed:
                session.commit()
                logger.info(
                    "[Reconcile] %s: rimosse %d categorie fantasma, %d riassegnazioni.",
                    user_id, len(report.deleted_categories), len(report.reassignments),
                )

        return report

    @staticmethod
    def _ensure_fallback_category(session, user_id: str):
        """Ritorna la categoria di fallback `Altro` dell'utente, creandola se assente."""
        from src.storage.models import UserCategory

        row = session.query(UserCategory).filter_by(
            user_id=user_id, name=FALLBACK_CATEGORY_NAME
        ).first()
        if row is None:
            row = UserCategory(user_id=user_id, name=FALLBACK_CATEGORY_NAME)
            session.add(row)
            session.flush()
        return row

    def get_user_category_names(self, user_id: str) -> list[str]:
        """Ritorna i nomi delle categorie dell'utente."""
        user_id = str(user_id)
        with self._user_session(user_id) as session:
            rows = session.execute(
                text("SELECT name FROM user_categories WHERE user_id = :uid ORDER BY name"),
                {"uid": user_id},
            ).fetchall()
            return [r[0] for r in rows]

    def get_category_by_notion_page_id(self, user_id: str, page_id: str) -> dict:
        """Ritorna {name, average} per un page_id Notion. Fallback su Sconosciuta."""
        user_id = str(user_id)
        with self._user_session(user_id) as session:
            row = session.execute(
                text(
                    "SELECT uc.name, ucnl.average "
                    "FROM user_categories uc "
                    "JOIN user_category_notion_links ucnl ON ucnl.category_id = uc.id "
                    "WHERE uc.user_id = :uid AND ucnl.notion_page_id = :pid"
                ),
                {"uid": user_id, "pid": page_id},
            ).fetchone()
            if row:
                return {"name": row[0], "average": row[1] or 0.0}
            return {"name": "Sconosciuta", "average": 0.0}

    def get_notion_page_id_for_category(self, user_id: str, name: str) -> Optional[str]:
        """Ritorna il notion_page_id per un nome categoria. None se non trovato."""
        user_id = str(user_id)
        with self._user_session(user_id) as session:
            row = session.execute(
                text(
                    "SELECT ucnl.notion_page_id "
                    "FROM user_categories uc "
                    "JOIN user_category_notion_links ucnl ON ucnl.category_id = uc.id "
                    "WHERE uc.user_id = :uid AND LOWER(uc.name) = LOWER(:name)"
                ),
                {"uid": user_id, "name": name},
            ).fetchone()
            if row:
                return row[0]
            # Ricerca parziale
            row = session.execute(
                text(
                    "SELECT ucnl.notion_page_id "
                    "FROM user_categories uc "
                    "JOIN user_category_notion_links ucnl ON ucnl.category_id = uc.id "
                    "WHERE uc.user_id = :uid AND ("
                    "LOWER(uc.name) LIKE LOWER(:pattern) OR LOWER(:name) LIKE LOWER('%' || uc.name || '%')"
                    ")"
                ),
                {"uid": user_id, "name": name, "pattern": f"%{name}%"},
            ).fetchone()
            return row[0] if row else None

    def update_category_average(self, user_id: str, category_name: str, new_average: float) -> None:
        """Aggiorna la media storica per una singola categoria in user_category_notion_links."""
        user_id = str(user_id)
        with self._user_session(user_id) as session:
            session.execute(
                text(
                    "UPDATE user_category_notion_links "
                    "SET average = :avg "
                    "WHERE category_id = ("
                    "  SELECT id FROM user_categories "
                    "  WHERE user_id = :uid AND name = :name LIMIT 1"
                    ")"
                ),
                {"avg": new_average, "uid": user_id, "name": category_name},
            )
            session.commit()

    def get_database_schemas(self, chat_id: str) -> dict[str, dict]:
        """Recupera tutti gli schemi salvati per un utente, ritornando una dict {db_key: schema_data}."""
        chat_id = str(chat_id)
        with self.Session() as session:
            schemas = session.query(DatabaseSchema).filter_by(chat_id=chat_id).all()
            result = {}
            for s in schemas:
                result[s.db_key] = {
                    "database_id": s.notion_db_id,
                    "properties": s.properties_json,
                    "mapped": s.mapped_properties_json
                }
            return result

    # --- METODI DASHBOARD PINNED MESSAGE ---

    def get_pinned_dashboard_msg_id(self, chat_id: str) -> int | None:
        """Recupera l'ID del messaggio dashboard pinnato per un utente."""
        chat_id = str(chat_id)
        with self.Session() as session:
            user = session.query(User).filter(User.chat_id == chat_id).first()
            return user.pinned_dashboard_msg_id if user else None

    def set_pinned_dashboard_msg_id(self, chat_id: str, msg_id: int | None) -> None:
        """Salva (o resetta) l'ID del messaggio dashboard pinnato."""
        chat_id = str(chat_id)
        with self.Session() as session:
            user = session.query(User).filter(User.chat_id == chat_id).first()
            if user:
                user.pinned_dashboard_msg_id = msg_id
                session.commit()

    def get_user_categories_with_budget(self, user_id: str) -> list[dict]:
        """Ritorna nome, budget mensile e average storica per ogni categoria dell'utente.

        Funziona per entrambi i backend (Notion e Postgres): i dati sono sempre
        nel DB locale (user_categories + user_category_notion_links).
        """
        user_id = str(user_id)
        with self._user_session(user_id) as session:
            rows = session.execute(
                text(
                    "SELECT uc.name, uc.monthly_budget, ucnl.average "
                    "FROM user_categories uc "
                    "LEFT JOIN user_category_notion_links ucnl ON ucnl.category_id = uc.id "
                    "WHERE uc.user_id = :uid ORDER BY uc.name"
                ),
                {"uid": user_id},
            ).fetchall()
            return [
                {"name": r[0], "monthly_budget": r[1], "average": r[2] or 0.0}
                for r in rows
            ]

    def get_user_categories_with_averages(self, user_id: str) -> list[dict]:
        """Ritorna nome e media storica di ogni categoria dell'utente.

        `average` viene da `user_category_notion_links` (None per categorie senza link Notion).
        """
        user_id = str(user_id)
        with self._user_session(user_id) as session:
            rows = session.execute(
                text(
                    "SELECT uc.name, ucnl.average "
                    "FROM user_categories uc "
                    "LEFT JOIN user_category_notion_links ucnl ON ucnl.category_id = uc.id "
                    "WHERE uc.user_id = :uid ORDER BY uc.name"
                ),
                {"uid": user_id},
            ).fetchall()
            return [{"name": r[0], "average": r[1] or 0.0} for r in rows]

    def accept_privacy_policy(self, chat_id: str, version: str) -> bool:
        """Registra l'accettazione di una versione della privacy policy. Ritorna False se l'utente non esiste."""
        chat_id = str(chat_id)
        with self.Session() as session:
            user = session.query(User).filter(User.chat_id == chat_id).first()
            if not user:
                return False
            user.privacy_policy_version_accepted = version
            user.privacy_accepted_at = datetime.utcnow()
            session.commit()
            return True

    def write_audit_log(
        self,
        user_id: str,
        actor: str,
        action: str,
        resource: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        """Registra un'azione GDPR-rilevante (export, cancellazione) in audit_log.

        Non propaga eccezioni: un fallimento di audit non deve mai bloccare
        l'operazione che lo ha generato (export o cancellazione account).
        """
        try:
            with self.Session() as session:
                session.add(AuditLog(
                    user_id=str(user_id),
                    actor=actor,
                    action=action,
                    resource=resource,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    metadata_json=metadata,
                    expires_at=datetime.utcnow() + timedelta(days=365),
                ))
                session.commit()
        except Exception:
            logger.exception("[AuditLog] Scrittura fallita per user_id=%s action=%s", user_id, action)

    def set_age_attestation(
        self,
        chat_id: str,
        ip_address: Optional[str],
        platform: str = "web",
    ) -> None:
        """Registra l'attestazione età 18+ dell'utente.

        Salva il timestamp su users.age_attestation_at e scrive una riga
        in audit_log con l'IP (None per Telegram, dove non è disponibile).
        """
        try:
            with self.Session() as session:
                user = session.query(User).filter_by(chat_id=chat_id).first()
                if user:
                    user.age_attestation_at = datetime.utcnow()
                    session.commit()
        except Exception:
            logger.exception("[AgeAttestation] Aggiornamento user fallito per chat_id=%s", chat_id)
        self.write_audit_log(
            user_id=chat_id,
            actor="user",
            action="age_attestation",
            ip_address=ip_address,
            metadata={"platform": platform},
        )

    # ---------------------------------------------------------------------
    # Registro violazioni dati personali (Art. 33(5) GDPR)
    # ---------------------------------------------------------------------
    def _next_breach_ref(self, session, detected_at: datetime) -> str:
        """Genera il prossimo riferimento incident-YYYYMMDD-NNN per la data indicata."""
        prefix = f"incident-{detected_at:%Y%m%d}-"
        last = (
            session.query(DataBreach)
            .filter(DataBreach.breach_ref.like(prefix + "%"))
            .order_by(DataBreach.breach_ref.desc())
            .first()
        )
        seq = 1
        if last is not None:
            try:
                seq = int(last.breach_ref.rsplit("-", 1)[1]) + 1
            except (ValueError, IndexError):
                seq = 1
        return f"{prefix}{seq:03d}"

    def create_breach_record(
        self,
        nature: Optional[str] = None,
        *,
        breach_ref: Optional[str] = None,
        detected_at: Optional[datetime] = None,
        discovered_by: Optional[str] = None,
        affected_data_categories: Optional[list] = None,
        affected_users_count: Optional[int] = None,
        risk_level: Optional[str] = None,
        containment_measures: Optional[str] = None,
    ) -> str:
        """Apre un nuovo record nel registro violazioni e ritorna il suo `breach_ref`.

        Se `breach_ref` non è fornito viene generato come incident-YYYYMMDD-NNN
        sulla base di `detected_at` (default: adesso).
        """
        detected = detected_at or datetime.utcnow()
        with self.Session() as session:
            ref = breach_ref or self._next_breach_ref(session, detected)
            session.add(DataBreach(
                breach_ref=ref,
                detected_at=detected,
                discovered_by=discovered_by,
                nature=nature,
                affected_data_categories=affected_data_categories,
                affected_users_count=affected_users_count,
                risk_level=risk_level,
                containment_measures=containment_measures,
                status="open",
            ))
            session.commit()
        logger.info("[DataBreach] Aperto record %s (risk=%s)", ref, risk_level)
        return ref

    def update_breach_record(self, breach_ref: str, **fields) -> bool:
        """Aggiorna i campi di un record violazione. Ritorna False se non trovato.

        Accetta solo attributi realmente presenti sul modello `DataBreach`.
        """
        with self.Session() as session:
            record = session.query(DataBreach).filter(
                DataBreach.breach_ref == breach_ref
            ).first()
            if record is None:
                logger.warning("[DataBreach] update su ref inesistente: %s", breach_ref)
                return False
            for key, value in fields.items():
                if not hasattr(record, key):
                    raise AttributeError(f"DataBreach non ha il campo '{key}'")
                setattr(record, key, value)
            session.commit()
        return True

    def get_breach_record(self, breach_ref: str) -> Optional["DataBreach"]:
        """Ritorna un singolo record violazione, o None."""
        with self.Session() as session:
            return session.query(DataBreach).filter(
                DataBreach.breach_ref == breach_ref
            ).first()

    def list_breach_records(self, *, status: Optional[str] = None) -> list["DataBreach"]:
        """Elenca i record violazione (opzionalmente filtrati per stato), più recenti prima."""
        with self.Session() as session:
            query = session.query(DataBreach)
            if status is not None:
                query = query.filter(DataBreach.status == status)
            return query.order_by(DataBreach.detected_at.desc()).all()

    def get_users_for_breach_notification(self) -> list[tuple[str, Optional[str]]]:
        """Ritorna (chat_id, email) di tutti gli utenti attivi da avvisare (Art. 34)."""
        with self.Session() as session:
            rows = (
                session.query(User.chat_id, User.email)
                .filter(User.is_active == True)  # noqa: E712
                .all()
            )
            return [(row[0], row[1]) for row in rows]

    def save_tally_lead(
        self,
        tally_submission_id: str,
        email: Optional[str],
        raw_payload: str,
        referral_code: Optional[str] = None,
        referred_by_code: Optional[str] = None,
    ) -> tuple["TallyLead", bool]:
        """Salva un submit del form Tally in modo idempotente su tally_submission_id.

        Ritorna (lead, is_new): is_new è False se il submission_id esisteva già
        (retry del webhook Tally), utile al chiamante per evitare un secondo sync Brevo.
        """
        with self.Session() as session:
            existing = (
                session.query(TallyLead)
                .filter(TallyLead.tally_submission_id == tally_submission_id)
                .first()
            )
            if existing:
                return existing, False

            lead = TallyLead(
                tally_submission_id=tally_submission_id,
                email=email,
                raw_payload=raw_payload,
                referral_code=referral_code,
                referred_by_code=referred_by_code,
            )
            session.add(lead)
            session.commit()
            session.refresh(lead)
            return lead, True

    def get_tally_lead_by_referral_code(self, referral_code: str) -> Optional["TallyLead"]:
        """Risolve il lead Tally (referrer) a partire dal suo referral_code."""
        with self.Session() as session:
            return (
                session.query(TallyLead)
                .filter(TallyLead.referral_code == referral_code)
                .first()
            )

    def create_referral_rewards(
        self, lead: "TallyLead", referrer_lead: "TallyLead"
    ) -> dict:
        """Crea i ReferralReward per un nuovo lead 'referred' e, se non ne ha già
        uno, per il referrer. Il referrer riceve un solo reward in assoluto
        (tetto fisso, non additivo per numero di referral). Al 3° referral andato
        a buon fine, marca il referrer come 'lifetime_founder_guaranteed' — e da lì
        in poi il link smette di generare reward: i referral oltre il 3° vengono
        comunque registrati (referred_by_code resta valorizzato, per tracciamento),
        ma non creano più alcun ReferralReward, né per il referrer né per l'invitato.

        Ritorna {'referrer_first_reward': bool, 'lifetime_founder_unlocked': bool,
        'reward_cap_reached': bool} per permettere al chiamante di decidere quali
        email inviare.
        """
        result = {
            "referrer_first_reward": False,
            "lifetime_founder_unlocked": False,
            "reward_cap_reached": False,
        }
        if not lead.email or not referrer_lead.email:
            return result

        with self.Session() as session:
            referred_count = (
                session.query(TallyLead)
                .filter(TallyLead.referred_by_code == referrer_lead.referral_code)
                .count()
            )
            if referred_count > 3:
                result["reward_cap_reached"] = True
                return result

            session.add(ReferralReward(
                beneficiary_email=lead.email,
                role="referred",
                days_granted=60,
                source_tally_lead_id=lead.id,
                status="pending",
            ))

            existing_referrer_reward = (
                session.query(ReferralReward)
                .filter(
                    ReferralReward.role == "referrer",
                    ReferralReward.beneficiary_email == referrer_lead.email,
                )
                .first()
            )
            if not existing_referrer_reward:
                session.add(ReferralReward(
                    beneficiary_email=referrer_lead.email,
                    role="referrer",
                    days_granted=60,
                    source_tally_lead_id=lead.id,
                    status="pending",
                ))
                result["referrer_first_reward"] = True

            referrer_row = (
                session.query(TallyLead)
                .filter(TallyLead.id == referrer_lead.id)
                .first()
            )
            if referred_count >= 3 and referrer_row and not referrer_row.lifetime_founder_guaranteed:
                referrer_row.lifetime_founder_guaranteed = True
                referrer_row.lifetime_founder_guaranteed_at = datetime.utcnow()
                result["lifetime_founder_unlocked"] = True

            session.commit()
            logger.info(
                "[Referral] Reward creati per lead %s (referrer=%s)",
                lead.id, referrer_lead.id,
                extra={
                    "domain": "dashboard",
                    "event": "referral_rewards_created",
                    "meta": {
                        "referrer_first_reward": result["referrer_first_reward"],
                        "lifetime_founder_unlocked": result["lifetime_founder_unlocked"],
                    },
                },
            )
            return result

    def apply_pending_referral_rewards(self, email: str) -> list["ReferralReward"]:
        """Applica i reward referral 'pending' per un'email appena diventata un
        account reale (chat_id risolvibile). Ritorna i reward applicati con
        successo, per permettere al chiamante di inviare le email di notifica.
        """
        email = (email or "").strip().lower()
        if not email:
            return []

        user = self.get_user_by_email_any_status(email)
        if not user:
            return []

        applied: list["ReferralReward"] = []
        with self.Session() as session:
            pending = (
                session.query(ReferralReward)
                .filter(
                    ReferralReward.status == "pending",
                    ReferralReward.beneficiary_email == email,
                )
                .all()
            )
            for reward in pending:
                self.extend_trial_days(user.chat_id, reward.days_granted)
                reward.status = "applied"
                reward.applied_at = datetime.utcnow()
                reward.beneficiary_chat_id = user.chat_id
                applied.append(reward)
            session.commit()
            for reward in applied:
                session.refresh(reward)

        return applied

    def get_or_create_referral_code(self, email: str) -> str:
        """Risolve il referral_code di un utente a partire dalla sua email.

        Normalmente l'utente ha già un TallyLead (arrivato dalla waitlist) con
        un referral_code assegnato al submit. Per gli account creati fuori da quel
        flusso (es. administrative provisioning) crea un TallyLead sintetico solo
        per ospitare il referral_code, così la web app può sempre mostrare un link.
        """
        email = (email or "").strip().lower()
        with self.Session() as session:
            lead = (
                session.query(TallyLead)
                .filter(TallyLead.email == email, TallyLead.referral_code.isnot(None))
                .first()
            )
            if lead:
                return lead.referral_code

            lead = session.query(TallyLead).filter(TallyLead.email == email).first()
            if lead:
                lead.referral_code = secrets.token_urlsafe(6)
                session.commit()
                return lead.referral_code

            new_lead = TallyLead(
                tally_submission_id=f"manual_{uuid.uuid4().hex}",
                email=email,
                referral_code=secrets.token_urlsafe(6),
            )
            session.add(new_lead)
            session.commit()
            return new_lead.referral_code

    def get_referral_status(self, email: str) -> dict:
        """Stato referral di un utente: codice, numero di inviti andati a buon
        fine, e se ha già sbloccato l'accesso garantito a Lifetime Founder.
        """
        email = (email or "").strip().lower()
        referral_code = self.get_or_create_referral_code(email)
        with self.Session() as session:
            referred_count = (
                session.query(TallyLead)
                .filter(TallyLead.referred_by_code == referral_code)
                .count()
            )
            lead = (
                session.query(TallyLead)
                .filter(TallyLead.referral_code == referral_code)
                .first()
            )
            lifetime_founder_guaranteed = bool(lead and lead.lifetime_founder_guaranteed)

        return {
            "referral_code": referral_code,
            "referred_count": referred_count,
            "lifetime_founder_guaranteed": lifetime_founder_guaranteed,
        }

    def mark_tally_lead_synced(self, tally_submission_id: str) -> None:
        """Marca un lead Tally come sincronizzato su Brevo."""
        with self.Session() as session:
            lead = (
                session.query(TallyLead)
                .filter(TallyLead.tally_submission_id == tally_submission_id)
                .first()
            )
            if lead:
                lead.synced_to_brevo = True
                session.commit()

    def count_beta_accounts_granted(self) -> int:
        """Conta i lead Tally a cui è già stato creato un account beta automatico."""
        with self.Session() as session:
            return (
                session.query(TallyLead)
                .filter(TallyLead.beta_account_granted == True)
                .count()
            )

    def mark_tally_lead_beta_access_granted(self, tally_submission_id: str) -> None:
        """Marca un lead Tally come già dotato di account beta (evita doppie creazioni)."""
        with self.Session() as session:
            lead = (
                session.query(TallyLead)
                .filter(TallyLead.tally_submission_id == tally_submission_id)
                .first()
            )
            if lead:
                lead.beta_account_granted = True
                lead.beta_account_granted_at = datetime.utcnow()
                session.commit()

    def create_beta_account(self, email: str, name: str = "") -> tuple[str, str] | None:
        """Crea un account web per un beta tester con password casuale.

        Ritorna (chat_id, password) oppure None se esiste già un account per
        quell'email (a qualunque stato). Stessa logica usata sia dal comando
        manuale (administrative provisioning) sia dalla creazione automatica
        al submit del form Tally (src/dashboard/app.py).
        """
        from config import Config

        email = email.strip().lower()
        if self.get_user_by_email_any_status(email):
            return None

        password = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))
        chat_id = f"web_{uuid.uuid4().hex}"

        self.add_user(
            chat_id=chat_id,
            storage_backend="postgres",
            setup_status="COMPLETED",
            setup_completed_at=datetime.utcnow(),
            username=name or email,
            is_active=True,
        )
        self.set_credentials(chat_id, email, password)
        self.accept_privacy_policy(chat_id, Config.CURRENT_PRIVACY_POLICY_VERSION)
        self.write_audit_log(
            chat_id, actor="admin", action="consent_change",
            metadata={"consent_type": "privacy_policy", "version": Config.CURRENT_PRIVACY_POLICY_VERSION},
            ip_address=None, user_agent="create_beta_account",
        )
        # Pro di default per tutta la fase beta (reason="beta_default" per poterlo
        # revocare in blocco al lancio pubblico senza toccare i Pro pagati veri).
        self.set_user_plan(chat_id, "pro", payment_reference="beta_default")
        return chat_id, password

    def delete_user_completely(self, chat_id: str) -> str:
        """Elimina l'account e tutti i dati locali dell'utente in modo atomico.

        Restituisce il backend dell'utente eliminato ('notion'/'postgres') o
        'not_found' se l'utente non esiste.
        """
        from src.storage.models import (
            Expense, Income, Account, Subscription, UserCategory, UserCategoryNotionLink,
            SavedReport,
        )

        chat_id = str(chat_id)
        # Cancellazione dei propri dati: bindata al tenant, la RLS consente il DELETE
        # delle proprie righe (GDPR erasure). Vedi _user_session.
        with self._user_session(chat_id) as session:
            user = session.query(User).filter(User.chat_id == chat_id).first()
            if not user:
                return "not_found"

            backend = user.storage_backend or "notion"

            if backend == "notion" and user.notion_access_token:
                from src.notion_client import revoke_notion_token
                try:
                    revoked = revoke_notion_token(user.notion_access_token)
                except Exception:
                    revoked = False
                    logger.warning(
                        "revoke_notion_token ha sollevato un'eccezione per chat_id=%s", chat_id, exc_info=True,
                    )
                logger.info(
                    "Revoca token Notion per chat_id=%s: %s",
                    chat_id, "riuscita" if revoked else "fallita (procedo comunque con la cancellazione)",
                )

            # Elimina i link Notion delle categorie (FK su user_categories.id) prima
            # di eliminare le categorie stesse — vale sia per Notion che per postgres.
            cat_ids = [
                r[0] for r in session.execute(
                    text("SELECT id FROM user_categories WHERE user_id = :uid"),
                    {"uid": chat_id},
                ).fetchall()
            ]
            if cat_ids:
                session.query(UserCategoryNotionLink).filter(
                    UserCategoryNotionLink.category_id.in_(cat_ids)
                ).delete(synchronize_session=False)

            if backend == "postgres":
                # Ordine obbligato dalle FK:
                # transfers → from_account_id/to_account_id → accounts.id
                # Expense/Income/Subscription → account_id → accounts.id
                # Expense/Subscription → category_id → user_categories.id
                #
                # "transfers" non ha un modello ORM locale (schema gestito da
                # Alembic, tabella aggiunta dopo l'ultima sincronizzazione di
                # src/storage/models.py) — cancellazione via SQL diretto, come
                # per user_categories sopra. Condizionata all'esistenza della
                # tabella: gli ambienti di test (SQLite) non la hanno ancora.
                if inspect(session.connection()).has_table("transfers"):
                    session.execute(
                        text(
                            "DELETE FROM transfers WHERE "
                            "from_account_id IN (SELECT id FROM accounts WHERE user_id = :uid) "
                            "OR to_account_id IN (SELECT id FROM accounts WHERE user_id = :uid)"
                        ),
                        {"uid": chat_id},
                    )
                session.query(Expense).filter(Expense.user_id == chat_id).delete()
                session.query(Income).filter(Income.user_id == chat_id).delete()
                session.query(Subscription).filter(Subscription.user_id == chat_id).delete()
                session.query(Account).filter(Account.user_id == chat_id).delete()

            session.query(UserCategory).filter(UserCategory.user_id == chat_id).delete()
            session.query(SavedReport).filter(SavedReport.user_id == chat_id).delete()
            session.query(ChatMessage).filter(ChatMessage.chat_id == chat_id).delete()
            # Ledger token
            session.query(LlmUsageEvent).filter(LlmUsageEvent.chat_id == chat_id).delete()
            session.query(LlmTokenReservation).filter(LlmTokenReservation.chat_id == chat_id).delete()
            session.query(UserPlan).filter(UserPlan.chat_id == chat_id).delete()
            session.query(PlanChange).filter(PlanChange.chat_id == chat_id).delete()
            session.query(Feedback).filter(Feedback.chat_id == chat_id).delete()
            session.query(DatabaseSchema).filter(DatabaseSchema.chat_id == chat_id).delete()
            session.query(OAuthSession).filter(OAuthSession.chat_id == chat_id).delete()
            session.delete(user)
            session.commit()

        return backend

    def get_user_subscriptions(self, user_id: str) -> list[dict]:
        """Ritorna gli abbonamenti dell'utente dal DB locale (tabella subscriptions)."""
        user_id = str(user_id)
        with self._user_session(user_id) as session:
            rows = session.execute(
                text(
                    "SELECT name, amount, last_billed, sub_type FROM subscriptions "
                    "WHERE user_id = :uid ORDER BY name"
                ),
                {"uid": user_id},
            ).fetchall()
            return [
                {
                    "name": r[0],
                    "amount": r[1],
                    # SQLite restituisce date come str, Postgres come oggetto date
                    "last_billed": (
                        r[2].isoformat() if hasattr(r[2], "isoformat") else r[2]
                    ) if r[2] else None,
                    "sub_type": r[3],
                }
                for r in rows
            ]

    # --- METODI PIANI E TOKEN (Fase 2.2) ---

    def get_user_plan(self, chat_id: str) -> dict:
        """Ritorna i dettagli del piano utente. Se non esiste, lo crea (Free default).

        I token usati e riservati sono calcolati live dal ledger (`llm_usage_events`
        e `llm_token_reservations`) — nessun contatore persistito ridondante.
        """
        chat_id = str(chat_id)
        now = datetime.utcnow()

        with self.Session() as session:
            plan = session.query(UserPlan).filter_by(chat_id=chat_id).first()

            if not plan:
                reset_date = self._next_cycle_reset(now)
                plan = UserPlan(
                    chat_id=chat_id,
                    plan_type="free",
                    tokens_total=150000,
                    tokens_reset_at=reset_date,
                )
                session.add(plan)
                session.commit()

            # Reset automatico del ciclo se scaduto
            if now >= plan.tokens_reset_at:
                plan.tokens_reset_at = self._next_cycle_reset(now)
                session.commit()

            cycle_start = plan.tokens_reset_at - timedelta(days=32)
            # Calcola token effettivamente usati nel ciclo corrente
            tokens_used = session.query(
                func.coalesce(func.sum(LlmUsageEvent.total_tokens), 0)
            ).filter(
                LlmUsageEvent.chat_id == chat_id,
                LlmUsageEvent.occurred_at >= cycle_start,
                LlmUsageEvent.occurred_at < plan.tokens_reset_at,
            ).scalar() or 0

            # Calcola token attualmente riservati (reservation pending non scadute)
            tokens_reserved = session.query(
                func.coalesce(func.sum(LlmTokenReservation.reserved_tokens), 0)
            ).filter(
                LlmTokenReservation.chat_id == chat_id,
                LlmTokenReservation.status == "pending",
                LlmTokenReservation.expires_at > now,
            ).scalar() or 0

            tokens_remaining = max(0, plan.tokens_total - tokens_used - tokens_reserved)

            # Soglie di allerta
            percent_used = (tokens_used + tokens_reserved) / plan.tokens_total if plan.tokens_total else 0
            alert = None
            if tokens_remaining == 0:
                alert = "exhausted"
            elif percent_used >= 0.9:
                alert = "warning_90"
            elif percent_used >= 0.7:
                alert = "warning_70"

            return {
                "plan_type": plan.plan_type,
                "tokens_total": plan.tokens_total,
                "tokens_used_current_cycle": tokens_used,
                "tokens_reserved_current_cycle": tokens_reserved,
                "tokens_remaining": tokens_remaining,
                "tokens_reset_at": plan.tokens_reset_at,
                "alert": alert,
                "is_trial": plan.is_trial,
                "trial_started_at": plan.trial_started_at,
                "trial_ends_at": plan.trial_ends_at,
            }

    def consume_tokens(self, chat_id: str, amount: int) -> dict:
        """Deprecato: il consumo reale avviene via finalize_llm_usage.

        Mantenuto per retrocompatibilità — non fa nulla.
        """
        logger.warning(
            "[User %s] consume_tokens() chiamato: DEPRECATO. Usare finalize_llm_usage().",
            chat_id,
        )
        plan_info = self.get_user_plan(chat_id)
        return {
            "success": True,
            "tokens_remaining": plan_info["tokens_remaining"],
            "alert": plan_info.get("alert"),
        }

    def set_user_plan(
        self,
        chat_id: str,
        plan_type: str,
        payment_reference: str | None = None,
    ) -> None:
        """Aggiorna il piano dell'utente (es. 'pro'). Ricalcola subito il totale token.

        Chiude sempre un eventuale trial in corso (`is_trial=False`): sia che si tratti di
        un downgrade a scadenza trial, sia di un futuro upgrade a pagamento reale a metà
        trial, lo stato trial va considerato concluso.

        Args:
            payment_reference: Riferimento pagamento (Stripe event ID, ecc.) o
                "trial_expired" per il downgrade automatico a fine trial.
                La validazione del pagamento è responsabilità del caller.
        """
        chat_id = str(chat_id)
        if plan_type not in ("free", "pro"):
            raise ValueError("Il piano deve essere 'free' o 'pro'")

        with self.Session() as session:
            plan = session.query(UserPlan).filter_by(chat_id=chat_id).first()
            if not plan:
                self.get_user_plan(chat_id)
                plan = session.query(UserPlan).filter_by(chat_id=chat_id).first()

            old_plan = plan.plan_type
            plan.plan_type = plan_type
            plan.tokens_total = 3000000 if plan_type == "pro" else 150000
            plan.is_trial = False

            if payment_reference == "trial_expired":
                change_type = "trial_expired"
            else:
                change_type = "upgrade" if plan_type == "pro" else "downgrade"
            session.add(PlanChange(
                chat_id=chat_id,
                from_plan=old_plan,
                to_plan=plan_type,
                change_type=change_type,
                changed_at=datetime.utcnow(),
                reason=payment_reference,
            ))

            session.commit()
            logger.info(
                "[User %s] Piano aggiornato: %s → %s | payment_ref=%s",
                chat_id, old_plan.upper(), plan_type.upper(), payment_reference or "N/A",
            )

    def start_trial(self, chat_id: str, days: int = 30) -> None:
        """Concede un trial Pro di N giorni (grant amministrativo manuale, beta).

        Durante la beta il trial non è self-serve: viene attivato via
        `scripts/grant_trial.py` per gli utenti indicati manualmente.
        """
        chat_id = str(chat_id)
        now = datetime.utcnow()

        with self.Session() as session:
            plan = session.query(UserPlan).filter_by(chat_id=chat_id).first()
            if not plan:
                self.get_user_plan(chat_id)
                plan = session.query(UserPlan).filter_by(chat_id=chat_id).first()

            old_plan = plan.plan_type
            plan.plan_type = "pro"
            plan.is_trial = True
            plan.trial_started_at = now
            plan.trial_ends_at = now + timedelta(days=days)
            plan.tokens_total = 3000000

            session.add(PlanChange(
                chat_id=chat_id,
                from_plan=old_plan,
                to_plan="pro",
                change_type="trial_started",
                changed_at=now,
            ))

            session.commit()
            logger.info("[User %s] Trial Pro avviato (%d giorni).", chat_id, days)

    def extend_trial_days(self, chat_id: str, days: int = 60) -> None:
        """Estende (additivamente) il Pro dell'utente di N giorni — reward referral.

        Se un trial è già attivo e non ancora scaduto, i giorni si sommano alla
        scadenza esistente invece di sovrascriverla (altrimenti referral multipli
        si cancellerebbero a vicenda). Se non c'è trial attivo (piano free, o Pro
        permanente beta senza scadenza), parte da ora. Applicato anche agli account
        Pro permanenti (beta_default): li trasforma in un Pro con scadenza — scelta
        esplicita del reward referral, non un effetto collaterale.
        """
        chat_id = str(chat_id)
        now = datetime.utcnow()

        with self.Session() as session:
            plan = session.query(UserPlan).filter_by(chat_id=chat_id).first()
            if not plan:
                self.get_user_plan(chat_id)
                plan = session.query(UserPlan).filter_by(chat_id=chat_id).first()

            old_plan = plan.plan_type
            base = plan.trial_ends_at if (plan.trial_ends_at and plan.trial_ends_at > now) else now

            plan.plan_type = "pro"
            plan.is_trial = True
            plan.trial_started_at = plan.trial_started_at or now
            plan.trial_ends_at = base + timedelta(days=days)
            plan.tokens_total = 3000000

            session.add(PlanChange(
                chat_id=chat_id,
                from_plan=old_plan,
                to_plan="pro",
                change_type="referral_reward",
                changed_at=now,
                reason="referral_reward",
            ))

            session.commit()
            logger.info(
                "[User %s] Pro esteso di %d giorni (reward referral), nuova scadenza %s.",
                chat_id, days, plan.trial_ends_at.isoformat(),
            )

    def get_expired_trials(self, reference_time: datetime | None = None) -> list["User"]:
        """Utenti con trial attivo la cui scadenza è già passata (o oggi)."""
        reference_time = reference_time or datetime.utcnow()
        with self.Session() as session:
            return (
                session.query(User)
                .join(UserPlan, User.chat_id == UserPlan.chat_id)
                .filter(
                    UserPlan.is_trial == True,  # noqa: E712
                    UserPlan.trial_ends_at <= reference_time,
                )
                .all()
            )

    def get_active_trial_users(self) -> list["User"]:
        """Utenti con trial Pro attualmente in corso, candidati al drip lifecycle."""
        with self.Session() as session:
            return (
                session.query(User)
                .join(UserPlan, User.chat_id == UserPlan.chat_id)
                .filter(UserPlan.is_trial == True)  # noqa: E712
                .all()
            )

    def get_lifecycle_sent_steps(self, chat_id: str, channel: str) -> set[str]:
        """Step del drip lifecycle già inviati con successo su un dato canale."""
        chat_id = str(chat_id)
        with self.Session() as session:
            rows = (
                session.query(TrialLifecycleEvent.step)
                .filter(
                    TrialLifecycleEvent.chat_id == chat_id,
                    TrialLifecycleEvent.channel == channel,
                    TrialLifecycleEvent.status == "sent",
                )
                .all()
            )
            return {row[0] for row in rows}

    def record_lifecycle_event(
        self, chat_id: str, step: str, channel: str, status: str = "sent"
    ) -> None:
        """Registra l'invio di uno step del drip lifecycle (dedup via vincolo unico)."""
        chat_id = str(chat_id)
        with self.Session() as session:
            session.add(TrialLifecycleEvent(
                chat_id=chat_id, step=step, channel=channel, status=status,
            ))
            try:
                session.commit()
            except Exception:
                session.rollback()
                logger.debug(
                    "[TrialLifecycle] Evento già registrato (race/duplicato): %s/%s/%s",
                    chat_id, step, channel,
                )

    # --- METODI LEDGER TOKEN (Fase 2.2 — Token System Reale) ---

    def reserve_llm_tokens(
        self,
        chat_id: str,
        request_key: str,
        operation: str,
        provider: str,
        model: str,
        reserved_tokens: int,
        ttl_minutes: int = 5,
    ) -> "LlmTokenReservation":
        """Crea una reservation di token prima di una chiamata AI.

        Per utenti Free: verifica che la quota residua copra la prenotazione.
        Solleva `QuotaExceededError` se non sufficiente.
        Per utenti Pro: crea sempre la reservation (soft cap — solo log se anomalia).

        Args:
            request_key: chiave idempotente stabile per il retry applicativo.
        """
        chat_id = str(chat_id)
        now = datetime.utcnow()
        expires_at = now + timedelta(minutes=ttl_minutes)

        plan_info = self.get_user_plan(chat_id)

        if plan_info["plan_type"] == "free" and plan_info["tokens_remaining"] < reserved_tokens:
            raise QuotaExceededError(
                f"Quota esaurita: {plan_info['tokens_remaining']} token rimasti, "
                f"richiesti {reserved_tokens}."
            )

        if plan_info["plan_type"] == "pro" and plan_info["tokens_remaining"] < reserved_tokens:
            logger.warning(
                "[User %s] Pro ha toccato il cap: %s token rimasti (richiesti %s). Anomalia.",
                chat_id, plan_info["tokens_remaining"], reserved_tokens,
            )

        with self.Session() as session:
            # Idempotenza: se esiste già una reservation con lo stesso request_key, la ritorna
            existing = session.query(LlmTokenReservation).filter_by(
                request_key=request_key
            ).first()
            if existing:
                logger.debug(
                    "[User %s] Reservation già esistente per request_key=%s", chat_id, request_key
                )
                return existing

            reservation = LlmTokenReservation(
                chat_id=chat_id,
                request_key=request_key,
                created_at=now,
                expires_at=expires_at,
                operation=operation,
                provider=provider,
                model=model,
                reserved_tokens=reserved_tokens,
                status="pending",
            )
            session.add(reservation)
            session.commit()
            logger.debug(
                "[User %s] Reservation creata: %s token, op=%s, key=%s",
                chat_id, reserved_tokens, operation, request_key,
            )
            return reservation

    def finalize_llm_usage(
        self,
        chat_id: str,
        request_key: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        provider: str,
        model: str,
        operation: str,
        thinking_tokens: int | None = None,
        cached_tokens: int | None = None,
        input_method: str | None = None,
    ) -> "LlmUsageEvent":
        """Registra il consumo reale dopo una chiamata AI e finalizza la reservation.

        Calcola il costo stimato usando `llm_pricing` (se disponibile).
        Idempotente: se esiste già un evento con lo stesso `request_key`, lo ritorna.
        """
        chat_id = str(chat_id)
        now = datetime.utcnow()

        with self.Session() as session:
            # Idempotenza
            existing_event = session.query(LlmUsageEvent).filter_by(
                request_key=request_key
            ).first()
            if existing_event:
                logger.debug(
                    "[User %s] Usage event già esistente per request_key=%s", chat_id, request_key
                )
                return existing_event

            # Calcola costo stimato
            pricing = session.query(LlmPricing).filter(
                LlmPricing.provider == provider,
                LlmPricing.model == model,
                LlmPricing.valid_to.is_(None),
            ).first()

            estimated_cost = None
            if pricing:
                input_cost = (Decimal(prompt_tokens) / 1000) * pricing.input_cost_per_1k
                output_cost = (Decimal(completion_tokens) / 1000) * pricing.output_cost_per_1k
                estimated_cost = (input_cost + output_cost).quantize(
                    Decimal("0.00000001"), rounding="ROUND_HALF_UP"
                )

            # Trova la reservation associata (se esiste)
            reservation = session.query(LlmTokenReservation).filter_by(
                request_key=request_key
            ).first()
            reservation_id = None
            if reservation:
                reservation.status = "finalized"
                reservation_id = reservation.id

            event = LlmUsageEvent(
                chat_id=chat_id,
                occurred_at=now,
                provider=provider,
                model=model,
                operation=operation,
                input_method=input_method,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                thinking_tokens=thinking_tokens,
                cached_tokens=cached_tokens,
                estimated_cost_amount=estimated_cost,
                estimated_cost_currency=pricing.currency if pricing else "USD",
                request_key=request_key,
                reservation_id=reservation_id,
            )
            session.add(event)
            session.commit()
            logger.debug(
                "[User %s] Usage finalizzato: %s token totali, costo ~$%s, op=%s",
                chat_id, total_tokens, estimated_cost, operation,
            )
            return event

    def release_llm_reservation(self, chat_id: str, request_key: str, reason: str = "") -> None:
        """Rilascia una reservation pending (es. in caso di errore non recuperabile).

        Imposta lo status a 'released' in modo che i token tornino disponibili.
        """
        chat_id = str(chat_id)
        with self.Session() as session:
            reservation = session.query(LlmTokenReservation).filter_by(
                request_key=request_key,
                chat_id=chat_id,
            ).first()
            if reservation and reservation.status == "pending":
                reservation.status = "released"
                reservation.release_reason = reason
                session.commit()
                logger.debug(
                    "[User %s] Reservation rilasciata: key=%s, motivo=%s",
                    chat_id, request_key, reason,
                )

    def expire_stale_reservations(self) -> int:
        """Marca come 'expired' tutte le reservation pending con expires_at passato.

        Da chiamare periodicamente (es. nel job notturno).
        Restituisce il numero di reservation scadute.
        """
        now = datetime.utcnow()
        with self.Session() as session:
            count = session.query(LlmTokenReservation).filter(
                LlmTokenReservation.status == "pending",
                LlmTokenReservation.expires_at < now,
            ).update({"status": "expired"})
            session.commit()
            if count:
                logger.info("[Ledger] %s reservation scadute marcate come expired.", count)
            return count

    def log_message(
        self,
        chat_id: str,
        source: str,
        role: str,
        text: str,
        metadata: dict | None = None,
    ) -> int:
        """Salva un messaggio nella cronologia condivisa. Ritorna l'id del record creato."""
        with self.Session() as session:
            msg = ChatMessage(
                chat_id=str(chat_id),
                source=source,
                role=role,
                text=text,
                metadata_json=json.dumps(metadata, default=str) if metadata else None,
            )
            session.add(msg)
            session.commit()
            return msg.id

    def cleanup_old_chat_messages(self, days: int = 90) -> int:
        """Rimuove i messaggi più vecchi di `days` giorni. Chiamata dal job APScheduler notturno."""
        cutoff = datetime.utcnow() - timedelta(days=days)
        with self.Session() as session:
            deleted = session.query(ChatMessage).filter(
                ChatMessage.created_at < cutoff
            ).delete(synchronize_session=False)
            session.commit()
        if deleted:
            logger.info("[Cleanup] Rimossi %d chat_messages più vecchi di %d giorni.", deleted, days)
        return deleted

    def cleanup_old_job_runs(self, days: int = 90) -> int:
        """Rimuove le esecuzioni job più vecchie di `days` giorni.

        La tabella `job_runs` cresce a ogni esecuzione: senza questa pulizia
        (chiamata dal job notturno di retention) crescerebbe indefinitamente.
        """
        cutoff = datetime.utcnow() - timedelta(days=days)
        with self.Session() as session:
            deleted = session.query(JobRun).filter(
                JobRun.finished_at < cutoff
            ).delete(synchronize_session=False)
            session.commit()
        if deleted:
            logger.info("[Cleanup] Rimosse %d job_runs più vecchie di %d giorni.", deleted, days)
        return deleted

    def record_job_run(
        self,
        job_id: str,
        status: str,
        *,
        trigger_type: str | None = None,
        scheduled_at: "datetime | None" = None,
        started_at: "datetime | None" = None,
        finished_at: "datetime | None" = None,
        duration_ms: int | None = None,
        return_code: int | None = None,
        error_text: str | None = None,
    ) -> None:
        """Registra l'esito di un'esecuzione di job schedulato (best-effort).

        Non solleva mai: il monitoraggio non deve poter far fallire un job.
        `error_text` viene troncato e non deve contenere dati liberi utente.
        """
        try:
            with self.Session() as session:
                session.add(JobRun(
                    job_id=job_id,
                    status=status,
                    trigger_type=trigger_type,
                    scheduled_at=scheduled_at,
                    started_at=started_at,
                    finished_at=finished_at or datetime.utcnow(),
                    duration_ms=duration_ms,
                    return_code=return_code,
                    error_text=(error_text or "")[:500] or None,
                ))
                session.commit()
        except Exception as exc:  # noqa: BLE001 — monitoraggio best-effort
            logger.warning("[JobRun] Impossibile registrare l'esito del job %s: %s", job_id, exc)

    def record_tx_event(
        self,
        chat_id: str,
        tx_type: str,
        input_method: str,
        outcome: str,
        source: str,
        reason: str | None = None,
    ) -> None:
        """Registra l'esito di un tentativo di registrazione transazione (best-effort).

        Chiamata accanto a `analytics.track` nei punti in cui il bot/webapp già
        emettono `expense_tracked`/`expense_tracking_failed` verso PostHog: non
        sostituisce quell'invio, lo rispecchia in Postgres per la dashboard admin.
        Non solleva mai: il tracking non deve poter interrompere il salvataggio.
        """
        try:
            with self.Session() as session:
                session.add(TxEvent(
                    chat_id=chat_id,
                    tx_type=tx_type or "unknown",
                    input_method=input_method or "text",
                    outcome=outcome,
                    source=source,
                    reason=(reason or "")[:200] or None,
                ))
                session.commit()
        except Exception as exc:  # noqa: BLE001 — tracking best-effort
            logger.warning("[TxEvent] Impossibile registrare l'evento per %s: %s", chat_id, exc)

    def record_tour_event(self, chat_id: str, event: str, step_id: str | None) -> None:
        """Persiste lo stato del tour guidato webapp sull'utente (best-effort).

        Chiamata da POST /api/track quando arriva un evento 'tour_*' con una
        sessione autenticata valida. Non sostituisce l'invio a PostHog, lo
        rispecchia: prima lo stato del tour viveva solo in localStorage del
        browser, quindi la dashboard admin non poteva sapere chi lo salta o a
        quale step si ferma.
        """
        try:
            with self.Session() as session:
                user = session.query(User).filter(User.chat_id == chat_id).first()
                if not user:
                    return
                if step_id:
                    user.tour_step = step_id
                if event == "tour_started":
                    user.tour_status = "in_progress"
                elif event == "tour_completed":
                    user.tour_status = "completed"
                    user.tour_completed_at = datetime.utcnow()
                elif event == "tour_skipped":
                    user.tour_status = "skipped"
                session.commit()
        except Exception as exc:  # noqa: BLE001 — tracking best-effort
            logger.warning("[TourEvent] Impossibile registrare l'evento tour per %s: %s", chat_id, exc)

    def get_chat_history(self, chat_id: str, limit: int = 60) -> list[dict]:
        """Ritorna gli ultimi `limit` messaggi della cronologia, in ordine cronologico asc."""
        with self.Session() as session:
            rows = (
                session.query(ChatMessage)
                .filter(ChatMessage.chat_id == str(chat_id))
                .order_by(ChatMessage.created_at.desc())
                .limit(limit)
                .all()
            )
        result = []
        for r in reversed(rows):
            entry: dict = {
                "id": r.id,
                "source": r.source,
                "role": r.role,
                "text": r.text,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            if r.metadata_json:
                try:
                    entry["metadata"] = json.loads(r.metadata_json)
                except Exception:
                    pass
            result.append(entry)
        return result
