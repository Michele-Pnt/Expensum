import pytest
from datetime import date, datetime, timedelta
from src.user_store import (
    User, DailyMetrics, Feedback, OAuthSession, PlanChange, UserPlan, ChatMessage,
    LlmUsageEvent, LlmTokenReservation, DatabaseSchema, AuditLog, DataBreach,
    TrialLifecycleEvent, TallyLead, ReferralReward,
)
from src.storage.models import (
    Expense, Income, Account, UserCategory, UserCategoryNotionLink,
    Subscription, SavedReport,
)
import src.storage.models  # registra UserCategory e tabelle storage nella Base condivisa

pytestmark = pytest.mark.integration

def test_add_and_get_user(mock_db_session):
    store = mock_db_session
    chat_id = "12345"
    username = "testuser"
    
    # Test aggiunta utente
    store.add_user(chat_id=chat_id, username=username, expense_db_id="exp_123")
    
    user = store.get_user(chat_id)
    assert user is not None
    assert user.chat_id == chat_id
    assert user.username == username
    assert user.expense_db_id == "exp_123"
    assert user.is_active is True

def test_update_existing_user(mock_db_session):
    store = mock_db_session
    chat_id = "12345"
    
    store.add_user(chat_id=chat_id, username="old_name")
    store.add_user(chat_id=chat_id, username="new_name", income_db_id="inc_456")
    
    user = store.get_user(chat_id)
    assert user.username == "new_name"
    assert user.income_db_id == "inc_456"

def test_increment_usage(mock_db_session):
    store = mock_db_session
    chat_id = "12345"
    # Legacy daily-usage counters have been removed; increment_usage is a no-op.
    # Verifichiamo che la tabella legacy non esista e che la chiamata non sollevi errori.
    store.increment_usage(chat_id, "text")
    from sqlalchemy import inspect
    assert not inspect(store.engine).has_table("daily_usage")

def test_new_user_has_zero_token_version(mock_db_session):
    store = mock_db_session
    store.add_user(chat_id="tv_user")
    assert store.get_token_version("tv_user") == 0


def test_get_token_version_missing_user_returns_none(mock_db_session):
    store = mock_db_session
    assert store.get_token_version("does_not_exist") is None


def test_bump_token_version_increments_and_returns_new_value(mock_db_session):
    store = mock_db_session
    store.add_user(chat_id="tv_bump")
    assert store.bump_token_version("tv_bump") == 1
    assert store.bump_token_version("tv_bump") == 2
    assert store.get_token_version("tv_bump") == 2


def test_bump_token_version_missing_user_returns_none(mock_db_session):
    store = mock_db_session
    assert store.bump_token_version("nope") is None


def test_update_password_bumps_token_version(mock_db_session):
    """Cambiare password deve invalidare tutte le sessioni (bump della versione)."""
    store = mock_db_session
    store.add_user(chat_id="tv_pwd")
    store.set_credentials("tv_pwd", "tv-pwd@example.com", "OldPassword1")
    assert store.get_token_version("tv_pwd") == 0

    assert store.update_password("tv_pwd", "NewPassword1") is True
    assert store.get_token_version("tv_pwd") == 1


def test_save_feedback(mock_db_session):
    store = mock_db_session
    chat_id = "12345"
    message = "Ottimo bot!"
    
    store.save_feedback(chat_id, message)
    
    with store.Session() as session:
        fb = session.query(Feedback).filter_by(chat_id=chat_id).first()
        assert fb is not None
        assert fb.message == message
        assert fb.status == "unread"

def test_oauth_session_lifecycle(mock_db_session):
    store = mock_db_session
    chat_id = "12345"
    
    # Crea sessione
    state = store.create_oauth_session(chat_id)
    assert state.startswith("RT-")
    assert len(state) > 5
    
    # Verifica esistenza
    with store.Session() as session:
        sess = session.query(OAuthSession).filter_by(state=state).first()
        assert sess is not None
        assert sess.chat_id == chat_id
    
    # Recupera e cancella
    retrieved_chat_id = store.get_and_delete_oauth_session(state)
    assert retrieved_chat_id == chat_id
    
    # Verifica cancellazione
    with store.Session() as session:
        sess = session.query(OAuthSession).filter_by(state=state).first()
        assert sess is None

def test_get_non_active_user(mock_db_session):
    store = mock_db_session
    chat_id = "999"
    
    # Aggiungi e disattiva manualmente (o via metodo se esistesse, ma simuliamo)
    store.add_user(chat_id=chat_id)
    with store.Session() as session:
        user = session.query(User).filter_by(chat_id=chat_id).first()
        user.is_active = False
        session.commit()
    
    user = store.get_user(chat_id)
    assert user is None


def test_log_message_and_get_history(mock_db_session):
    store = mock_db_session
    chat_id = "42"
    store.add_user(chat_id=chat_id)

    store.log_message(chat_id, source="telegram", role="user", text="ho speso 20€")
    store.log_message(chat_id, source="webapp", role="bot", text="✅ Registrato", metadata={"amount": 20.0})

    history = store.get_chat_history(chat_id, limit=10)
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["source"] == "telegram"
    assert history[1]["role"] == "bot"
    assert history[1]["metadata"]["amount"] == 20.0


def test_log_message_returns_id(mock_db_session):
    store = mock_db_session
    chat_id = "43"
    store.add_user(chat_id=chat_id)

    msg_id = store.log_message(chat_id, source="webapp", role="user", text="test")
    assert isinstance(msg_id, int)
    assert msg_id > 0


def test_get_chat_history_order_and_limit(mock_db_session):
    store = mock_db_session
    chat_id = "44"
    store.add_user(chat_id=chat_id)

    for i in range(5):
        store.log_message(chat_id, source="telegram", role="user", text=f"msg {i}")

    history = store.get_chat_history(chat_id, limit=3)
    assert len(history) == 3
    # Deve essere in ordine cronologico asc (il più recente per ultimo)
    assert history[-1]["text"] == "msg 4"


def test_get_chat_history_empty(mock_db_session):
    store = mock_db_session
    chat_id = "45"
    store.add_user(chat_id=chat_id)

    history = store.get_chat_history(chat_id)
    assert history == []


def test_delete_user_completely_removes_all_tables(mock_db_session):
    """Verifica che delete_user_completely cancelli ogni traccia dell'utente in TUTTE le tabelle.

    Semina una riga in ogni tabella con FK su users.chat_id (incluse Expense, Income,
    Account, Subscription, SavedReport, ChatMessage, UserCategory, UserCategoryNotionLink,
    LlmUsageEvent, LlmTokenReservation, UserPlan, PlanChange, Feedback, DatabaseSchema,
    OAuthSession) e poi assicura 0 record residui.

    AuditLog è escluso intenzionalmente: non ha FK su users.chat_id e deve
    restare leggibile dopo la cancellazione (accountability GDPR Art. 30).
    """
    from sqlalchemy import event

    store = mock_db_session
    chat_id = "gdpr_delete_test"

    # Abilita FK enforcement su SQLite (default off) per rilevare ordini sbagliati
    @event.listens_for(store.engine, "connect")
    def _enable_fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    store.add_user(chat_id=chat_id, username="delete-me", storage_backend="postgres")
    store.get_user_plan(chat_id)  # crea UserPlan

    with store.Session() as s:
        # OAuthSession
        s.add(OAuthSession(
            state="test-oauth-state",
            chat_id=chat_id,
            expires_at=datetime.utcnow() + timedelta(minutes=15),
        ))
        # Feedback
        s.add(Feedback(chat_id=chat_id, message="ottimo bot"))
        # DatabaseSchema
        s.add(DatabaseSchema(chat_id=chat_id, db_key="expense_db_id"))
        # PlanChange
        s.add(PlanChange(chat_id=chat_id, from_plan="free", to_plan="pro", change_type="upgrade"))
        # ChatMessage
        s.add(ChatMessage(chat_id=chat_id, source="telegram", role="user", text="ciao"))
        # LlmTokenReservation
        reservation = LlmTokenReservation(
            chat_id=chat_id,
            request_key="test-reservation-key",
            expires_at=datetime.utcnow() + timedelta(minutes=5),
            operation="parse_expense",
            provider="mistral",
            model="mistral-small",
            reserved_tokens=1000,
            status="pending",
        )
        s.add(reservation)
        s.flush()
        # LlmUsageEvent (può referenziare la reservation)
        s.add(LlmUsageEvent(
            chat_id=chat_id,
            provider="mistral",
            model="mistral-small",
            operation="parse_expense",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            request_key="test-usage-key",
            reservation_id=reservation.id,
        ))
        # Account (necessario per Expense/Income/Subscription con account_id)
        acc = Account(user_id=chat_id, name="Conto Corrente", opening_balance=1000)
        s.add(acc)
        s.flush()
        # UserCategory (necessaria per Expense con category_id)
        cat = UserCategory(user_id=chat_id, name="Cibo")
        s.add(cat)
        s.flush()
        # UserCategoryNotionLink
        s.add(UserCategoryNotionLink(category_id=cat.id, notion_page_id="notion-page-abc"))
        # Expense
        s.add(Expense(
            user_id=chat_id,
            expense_date=date.today(),
            amount=25.50,
            name="Spesa supermercato",
            category_id=cat.id,
            account_id=acc.id,
        ))
        # Income
        s.add(Income(
            user_id=chat_id,
            income_date=date.today(),
            amount=2000.00,
            name="Stipendio",
            account_id=acc.id,
        ))
        # Subscription
        s.add(Subscription(user_id=chat_id, name="Netflix", amount=12.99, account_id=acc.id))
        # SavedReport
        s.add(SavedReport(
            user_id=chat_id,
            report_type="monthly",
            report_date=date.today(),
            text_content="Report mensile di test",
        ))
        s.commit()

    # Aggiungi una riga in AuditLog (no FK — deve sopravvivere alla cancellazione)
    with store.Session() as s:
        s.add(AuditLog(
            user_id=chat_id,
            actor="user",
            action="delete_account",
            resource="/account/delete",
        ))
        s.commit()

    result = store.delete_user_completely(chat_id)
    assert result == "postgres", f"Atteso 'postgres', ricevuto '{result}'"

    # --- Verifica: 0 record residui per ogni tabella con dati utente ---
    user_tables = [
        (User,                    "chat_id"),
        (UserPlan,                "chat_id"),
        (PlanChange,              "chat_id"),
        (Feedback,                "chat_id"),
        (OAuthSession,            "chat_id"),
        (DatabaseSchema,          "chat_id"),
        (ChatMessage,             "chat_id"),
        (LlmUsageEvent,           "chat_id"),
        (LlmTokenReservation,     "chat_id"),
        (Expense,                 "user_id"),
        (Income,                  "user_id"),
        (Account,                 "user_id"),
        (Subscription,            "user_id"),
        (UserCategory,            "user_id"),
        (SavedReport,             "user_id"),
    ]

    with store.Session() as s:
        for model, col in user_tables:
            count = s.query(model).filter(getattr(model, col) == chat_id).count()
            assert count == 0, (
                f"GDPR gap: {model.__tablename__}.{col} contiene ancora {count} "
                f"record per chat_id={chat_id} dopo delete_user_completely()"
            )

        # UserCategoryNotionLink: categorie già eliminate, nessun link orfano
        remaining_links = (
            s.query(UserCategoryNotionLink)
            .filter(UserCategoryNotionLink.notion_page_id == "notion-page-abc")
            .count()
        )
        assert remaining_links == 0, (
            f"GDPR gap: user_category_notion_links contiene ancora {remaining_links} record"
        )

        # AuditLog deve restare (accountability GDPR Art. 30 — no FK intenzionale)
        audit_count = s.query(AuditLog).filter(AuditLog.user_id == chat_id).count()
        assert audit_count == 1, (
            f"AuditLog non deve essere cancellato da delete_user_completely "
            f"(GDPR Art. 30 accountability): trovati {audit_count} record"
        )


def test_delete_user_completely_revokes_notion_token(mock_db_session, mocker):
    """delete_user_completely() deve revocare il token Notion lato API (Art. 17).

    Verifica sia che revoke_notion_token venga chiamata con il token corretto
    per un utente storage_backend='notion', sia che la cancellazione riesca
    comunque se la revoca fallisce (non deve mai bloccare l'eliminazione).
    """
    store = mock_db_session
    chat_id = "notion_delete_test"
    store.add_user(chat_id=chat_id, username="notion-user", storage_backend="notion",
                    notion_access_token="secret_test_token")

    mock_revoke = mocker.patch("src.notion_client.revoke_notion_token", return_value=True)

    result = store.delete_user_completely(chat_id)

    assert result == "notion"
    mock_revoke.assert_called_once_with("secret_test_token")

    with store.Session() as s:
        assert s.query(User).filter(User.chat_id == chat_id).count() == 0


def test_delete_user_completely_succeeds_even_if_notion_revoke_fails(mock_db_session, mocker):
    """La cancellazione account non deve mai bloccarsi se la revoca Notion fallisce."""
    store = mock_db_session
    chat_id = "notion_delete_test_2"
    store.add_user(chat_id=chat_id, username="notion-user-2", storage_backend="notion",
                    notion_access_token="secret_test_token")

    mocker.patch("src.notion_client.revoke_notion_token", side_effect=Exception("Notion API down"))

    result = store.delete_user_completely(chat_id)

    assert result == "notion"
    with store.Session() as s:
        assert s.query(User).filter(User.chat_id == chat_id).count() == 0


def test_reassign_user_chat_id_respects_foreign_keys(mock_db_session):
    """reassign_user_chat_id deve spostare TUTTE le tabelle figlie senza violare FK/UNIQUE.

    Regressione (3 bug trovati in produzione durante il login Telegram con
    riassegnazione account, PostgreSQL ha FK/UNIQUE enforcement rigido che SQLite
    di default non applica, va abilitato esplicitamente qui):
    1. Ordine di update sbagliato -> ForeignKeyViolation su user_plans
    2. Due righe users temporaneamente con la stessa email -> UniqueViolation
    3. plan_changes/chat_messages/saved_reports mancanti dall'elenco delle tabelle
       migrate -> ForeignKeyViolation alla cancellazione della vecchia riga users

    Questo test semina una riga in OGNI tabella con FK su users.chat_id, cosi'
    una futura tabella dimenticata fa fallire il test invece di rompersi in prod.
    """
    from sqlalchemy import event
    from src.user_store import LlmTokenReservation, LlmUsageEvent, DatabaseSchema
    from src.storage.models import Expense, Income, Account, Subscription, UserCategory, SavedReport

    store = mock_db_session

    @event.listens_for(store.engine, "connect")
    def _enable_fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    old_chat_id, new_chat_id = "old_chat_fk", "new_chat_fk"
    store.add_user(chat_id=old_chat_id, username="t", storage_backend="postgres")
    store.set_credentials(old_chat_id, "reassign-fk@example.com", "Password123")
    store.get_user_plan(old_chat_id)  # crea la riga in user_plans

    with store.Session() as s:
        s.add(ChatMessage(chat_id=old_chat_id, source="webapp", role="user", text="ciao"))
        s.add(PlanChange(chat_id=old_chat_id, to_plan="pro", change_type="upgrade"))
        s.add(DatabaseSchema(chat_id=old_chat_id, db_key="expense"))
        s.add(Feedback(chat_id=old_chat_id, message="test"))
        acc = Account(user_id=old_chat_id, name="Conto", opening_balance=0)
        s.add(acc)
        s.flush()
        s.add(Expense(user_id=old_chat_id, expense_date=datetime.utcnow().date(), amount=10, name="Spesa", account_id=acc.id))
        s.add(Income(user_id=old_chat_id, income_date=datetime.utcnow().date(), amount=10, name="Entrata", account_id=acc.id))
        s.add(Subscription(user_id=old_chat_id, name="Netflix", amount=10))
        s.add(UserCategory(user_id=old_chat_id, name="Cibo"))
        s.add(SavedReport(
            user_id=old_chat_id, report_type="weekly",
            report_date=datetime.utcnow().date(), text_content="report",
        ))
        s.commit()

    result = store.reassign_user_chat_id(old_chat_id, new_chat_id)

    assert result is True
    with store.Session() as s:
        # Nessuna tabella deve referenziare ancora old_chat_id
        for model, col in [
            (ChatMessage, "chat_id"), (PlanChange, "chat_id"),
            (DatabaseSchema, "chat_id"), (Feedback, "chat_id"),
            (UserPlan, "chat_id"), (Account, "user_id"),
            (Expense, "user_id"), (Income, "user_id"),
            (Subscription, "user_id"), (UserCategory, "user_id"),
            (SavedReport, "user_id"),
        ]:
            assert s.query(model).filter(getattr(model, col) == old_chat_id).first() is None, (
                f"{model.__name__}.{col} referenzia ancora old_chat_id"
            )
            assert s.query(model).filter(getattr(model, col) == new_chat_id).first() is not None, (
                f"{model.__name__}.{col} non e' stato spostato su new_chat_id"
            )

        new_user = s.query(User).filter_by(chat_id=new_chat_id).first()
        assert new_user.email == "reassign-fk@example.com"
        assert s.query(User).filter_by(chat_id=old_chat_id).first() is None


def test_reassign_user_chat_id_cleans_up_placeholder_target_children(mock_db_session):
    """Regressione: collegare un web account a un chat_id Telegram che ha gia'
    usato il bot (placeholder con categorie di default + riga user_plans gia'
    seedate) falliva con UNIQUE/PK violation sul bulk update, perche' le righe
    figlie del placeholder cancellato non venivano ripulite prima dello spostamento.
    """
    from src.storage.models import UserCategory

    store = mock_db_session

    old_chat_id, new_chat_id = "web_test", "telegram_real_user"

    # old_chat_id: account web completo con la categoria di default "Cibo" e un piano
    store.add_user(chat_id=old_chat_id, username="t", storage_backend="postgres")
    store.set_credentials(old_chat_id, "webuser@example.com", "Password123")
    store.get_user_plan(old_chat_id)
    with store.Session() as s:
        s.add(UserCategory(user_id=old_chat_id, name="Cibo"))
        s.commit()

    # new_chat_id: placeholder Telegram (nessuna email/password/token) che ha
    # gia' seedato la stessa categoria di default e la propria riga user_plans
    store.add_user(chat_id=new_chat_id, username="placeholder")
    store.get_user_plan(new_chat_id)
    with store.Session() as s:
        s.add(UserCategory(user_id=new_chat_id, name="Cibo"))
        s.commit()

    result = store.reassign_user_chat_id(old_chat_id, new_chat_id)

    assert result is True
    with store.Session() as s:
        categories = s.query(UserCategory).filter_by(user_id=new_chat_id).all()
        assert [c.name for c in categories] == ["Cibo"]

        plan = s.query(UserPlan).filter_by(chat_id=new_chat_id).one()
        assert plan is not None

        assert s.query(User).filter_by(chat_id=old_chat_id).first() is None
        merged_user = s.query(User).filter_by(chat_id=new_chat_id).first()
        assert merged_user.email == "webuser@example.com"


# ---------------------------------------------------------------------------
# Coda riassegnazione chat_id (Opzione B — security design notes § Vuln. residua #2)
# ---------------------------------------------------------------------------

def test_enqueue_chat_id_reassignment_creates_pending_job(mock_db_session):
    """enqueue_chat_id_reassignment deve solo arruolare, mai eseguire in-line: il
    ruolo DML-only che la chiama (bot/dashboard) non ha i privilegi per l'operazione
    cross-tenant, solo il worker fuori banda (process_pending_reassignment_jobs)."""
    from src.storage.models import ChatIdReassignmentJob

    store = mock_db_session
    job_id = store.enqueue_chat_id_reassignment("old_q1", "new_q1")

    with store.Session() as s:
        job = s.query(ChatIdReassignmentJob).filter_by(id=job_id).first()
        assert job is not None
        assert job.status == "pending"
        assert job.old_chat_id == "old_q1"
        assert job.new_chat_id == "new_q1"

    # Nessun account riassegnato finche' nessuno processa la coda
    assert store.get_user("old_q1") is None
    assert store.get_user("new_q1") is None


def test_process_pending_reassignment_jobs_executes_and_marks_done(mock_db_session):
    from src.storage.models import ChatIdReassignmentJob

    store = mock_db_session
    store.add_user(chat_id="old_q2", username="t", storage_backend="postgres")

    job_id = store.enqueue_chat_id_reassignment("old_q2", "new_q2")
    processed = store.process_pending_reassignment_jobs()

    assert processed == 1
    assert store.get_user("new_q2") is not None
    assert store.get_user("old_q2") is None
    with store.Session() as s:
        job = s.query(ChatIdReassignmentJob).filter_by(id=job_id).first()
        assert job.status == "done"
        assert job.processed_at is not None


def test_process_pending_reassignment_jobs_marks_failed_on_conflict(mock_db_session):
    """Se new_chat_id e' gia' un account reale, reassign_user_chat_id solleva
    ValueError: il job va marcato 'failed' con l'errore, non far esplodere il worker."""
    from src.storage.models import ChatIdReassignmentJob

    store = mock_db_session
    store.add_user(chat_id="old_q3", username="t", storage_backend="postgres")
    store.add_user(chat_id="new_q3", username="t2", storage_backend="postgres")
    store.set_credentials("new_q3", "already-real@example.com", "Password123")

    job_id = store.enqueue_chat_id_reassignment("old_q3", "new_q3")
    processed = store.process_pending_reassignment_jobs()

    assert processed == 1
    with store.Session() as s:
        job = s.query(ChatIdReassignmentJob).filter_by(id=job_id).first()
        assert job.status == "failed"
        assert "gia associato" in job.error_text
    # Entrambi gli account restano intatti, nessuno cancellato a meta'
    assert store.get_user("old_q3") is not None
    assert store.get_user("new_q3") is not None


def test_wait_for_reassignment_job_returns_pending_on_timeout(mock_db_session, monkeypatch):
    """Se nessun worker processa il job entro il timeout, ritorna 'pending' (non
    solleva e non blocca a lungo: qui simuliamo il timeout gia' scaduto)."""
    store = mock_db_session
    job_id = store.enqueue_chat_id_reassignment("old_q4", "new_q4")

    monkeypatch.setattr("src.user_store.time.sleep", lambda _: None)
    status, error_text = store.wait_for_reassignment_job(job_id, timeout=0, poll_interval=0.01)

    assert status == "pending"
    assert error_text is None


def test_wait_for_reassignment_job_returns_done_once_processed(mock_db_session, monkeypatch):
    """Simula il worker che processa la coda al posto dello sleep del polling —
    stesso pattern usato nei test end-to-end di bot.py/dashboard app.py."""
    store = mock_db_session
    store.add_user(chat_id="old_q5", username="t", storage_backend="postgres")
    job_id = store.enqueue_chat_id_reassignment("old_q5", "new_q5")

    monkeypatch.setattr(
        "src.user_store.time.sleep",
        lambda _: store.process_pending_reassignment_jobs(),
    )
    status, error_text = store.wait_for_reassignment_job(job_id, timeout=5, poll_interval=0.01)

    assert status == "done"
    assert error_text is None


# ---------------------------------------------------------------------------
# Registro violazioni dati personali (Art. 33(5) GDPR)
# ---------------------------------------------------------------------------

def test_create_breach_record_generates_ref(mock_db_session):
    store = mock_db_session

    ref = store.create_breach_record(
        "Accesso non autorizzato al DB",
        detected_at=datetime(2026, 7, 1, 10, 0, 0),
        discovered_by="sentry",
        affected_data_categories=["identita", "transazioni"],
        affected_users_count=42,
        risk_level="high",
    )

    assert ref == "incident-20260701-001"
    record = store.get_breach_record(ref)
    assert record is not None
    assert record.status == "open"
    assert record.risk_level == "high"
    assert record.affected_users_count == 42
    assert record.affected_data_categories == ["identita", "transazioni"]
    assert record.garante_notified is False
    assert record.users_notified is False


def test_create_breach_record_increments_sequence(mock_db_session):
    store = mock_db_session
    same_day = datetime(2026, 7, 1, 9, 0, 0)

    ref1 = store.create_breach_record("prima", detected_at=same_day)
    ref2 = store.create_breach_record("seconda", detected_at=same_day)
    ref_other_day = store.create_breach_record(
        "altro giorno", detected_at=datetime(2026, 7, 2, 9, 0, 0)
    )

    assert ref1 == "incident-20260701-001"
    assert ref2 == "incident-20260701-002"
    assert ref_other_day == "incident-20260702-001"


def test_update_breach_record(mock_db_session):
    store = mock_db_session
    ref = store.create_breach_record("test", detected_at=datetime(2026, 7, 1))

    now = datetime(2026, 7, 1, 12, 0, 0)
    ok = store.update_breach_record(
        ref,
        status="notified",
        garante_notified=True,
        garante_notified_at=now,
        garante_receipt_ref="PROT-123",
        root_cause="SQL injection",
    )
    assert ok is True

    record = store.get_breach_record(ref)
    assert record.status == "notified"
    assert record.garante_notified is True
    assert record.garante_receipt_ref == "PROT-123"
    assert record.root_cause == "SQL injection"


def test_update_breach_record_unknown_ref_returns_false(mock_db_session):
    store = mock_db_session
    assert store.update_breach_record("incident-19990101-001", status="closed") is False


def test_update_breach_record_invalid_field_raises(mock_db_session):
    store = mock_db_session
    ref = store.create_breach_record("test", detected_at=datetime(2026, 7, 1))
    with pytest.raises(AttributeError):
        store.update_breach_record(ref, non_existent_field="x")


def test_list_breach_records_filter_by_status(mock_db_session):
    store = mock_db_session
    r1 = store.create_breach_record("a", detected_at=datetime(2026, 7, 1))
    r2 = store.create_breach_record("b", detected_at=datetime(2026, 7, 2))
    store.update_breach_record(r2, status="closed")

    all_records = store.list_breach_records()
    assert len(all_records) == 2
    # ordinamento: più recente prima
    assert all_records[0].breach_ref == r2

    open_only = store.list_breach_records(status="open")
    assert [r.breach_ref for r in open_only] == [r1]


def test_get_users_for_breach_notification_only_active(mock_db_session):
    store = mock_db_session
    store.add_user(chat_id="1001", email="a@example.com")
    store.add_user(chat_id="1002", email="b@example.com")
    store.add_user(chat_id="1003")  # attivo, senza email

    # Disattiva un utente: non deve comparire tra i destinatari.
    with store.Session() as s:
        u = s.query(User).filter_by(chat_id="1002").first()
        u.is_active = False
        s.commit()

    recipients = store.get_users_for_breach_notification()
    by_chat = dict(recipients)
    assert "1001" in by_chat and by_chat["1001"] == "a@example.com"
    assert "1003" in by_chat and by_chat["1003"] is None
    assert "1002" not in by_chat


# ---------------------------------------------------------------------------
# Hashing password — Argon2id + migrazione trasparente da bcrypt
# ---------------------------------------------------------------------------

def test_set_credentials_uses_argon2id(mock_db_session):
    store = mock_db_session
    store.add_user(chat_id="pw1")
    store.set_credentials("pw1", "user@example.com", "S3cret!")

    user = store.get_user_by_email("user@example.com")
    assert user.password_hash.startswith("$argon2id$")
    assert store.verify_password("user@example.com", "S3cret!") is not None
    assert store.verify_password("user@example.com", "sbagliata") is None


def test_update_password_uses_argon2id(mock_db_session):
    store = mock_db_session
    store.add_user(chat_id="pw2")
    store.set_credentials("pw2", "user2@example.com", "vecchia")
    assert store.update_password("pw2", "nuova-password") is True

    user = store.get_user_by_email("user2@example.com")
    assert user.password_hash.startswith("$argon2id$")
    assert store.verify_password("user2@example.com", "nuova-password") is not None
    assert store.verify_password("user2@example.com", "vecchia") is None


def test_legacy_bcrypt_hash_is_verified_and_rehashed(mock_db_session):
    """Un utente con hash bcrypt legacy fa login e viene migrato ad Argon2id (rehash trasparente)."""
    import bcrypt
    store = mock_db_session
    store.add_user(chat_id="pw3")
    legacy = bcrypt.hashpw(b"old-pass", bcrypt.gensalt()).decode()
    with store.Session() as s:
        u = s.query(User).filter_by(chat_id="pw3").first()
        u.email = "legacy@example.com"
        u.password_hash = legacy
        s.commit()

    # Login corretto con l'hash legacy.
    user = store.verify_password("legacy@example.com", "old-pass")
    assert user is not None

    # Dopo il login l'hash è stato migrato ad Argon2id e persistito.
    migrated = store.get_user_by_email("legacy@example.com")
    assert migrated.password_hash.startswith("$argon2id$")
    assert migrated.password_hash != legacy

    # La password continua a funzionare col nuovo hash; quella sbagliata no.
    assert store.verify_password("legacy@example.com", "old-pass") is not None
    assert store.verify_password("legacy@example.com", "old-pass-sbagliata") is None


# --- Trial lifecycle ---

def test_start_trial_sets_fields(mock_db_session):
    store = mock_db_session
    store.add_user(chat_id="trial1")

    store.start_trial("trial1", days=30)

    plan = store.get_user_plan("trial1")
    assert plan["plan_type"] == "pro"
    assert plan["is_trial"] is True
    assert plan["trial_started_at"] is not None
    assert plan["trial_ends_at"] is not None
    assert (plan["trial_ends_at"] - plan["trial_started_at"]).days == 30

    with store.Session() as s:
        change = s.query(PlanChange).filter_by(chat_id="trial1").first()
        assert change.change_type == "trial_started"


def test_set_user_plan_clears_is_trial_on_expiry(mock_db_session):
    store = mock_db_session
    store.add_user(chat_id="trial2")
    store.start_trial("trial2", days=30)

    store.set_user_plan("trial2", "free", payment_reference="trial_expired")

    plan = store.get_user_plan("trial2")
    assert plan["plan_type"] == "free"
    assert plan["is_trial"] is False

    with store.Session() as s:
        change = (
            s.query(PlanChange)
            .filter_by(chat_id="trial2", change_type="trial_expired")
            .first()
        )
        assert change is not None


def test_set_user_plan_clears_is_trial_on_real_upgrade_mid_trial(mock_db_session):
    """Un pagamento reale a metà trial chiude comunque lo stato trial."""
    store = mock_db_session
    store.add_user(chat_id="trial3")
    store.start_trial("trial3", days=30)

    store.set_user_plan("trial3", "pro", payment_reference="stripe_evt_123")

    plan = store.get_user_plan("trial3")
    assert plan["plan_type"] == "pro"
    assert plan["is_trial"] is False


def test_get_expired_trials(mock_db_session):
    store = mock_db_session
    store.add_user(chat_id="expired1")
    store.add_user(chat_id="active1")
    store.start_trial("expired1", days=30)
    store.start_trial("active1", days=30)

    with store.Session() as s:
        plan = s.query(UserPlan).filter_by(chat_id="expired1").first()
        plan.trial_ends_at = datetime.utcnow() - timedelta(days=1)
        s.commit()

    expired = store.get_expired_trials(datetime.utcnow())
    assert [u.chat_id for u in expired] == ["expired1"]


def test_get_active_trial_users(mock_db_session):
    store = mock_db_session
    store.add_user(chat_id="trial_active")
    store.add_user(chat_id="never_trial")
    store.start_trial("trial_active", days=30)
    store.get_user_plan("never_trial")  # crea piano free di default

    active = store.get_active_trial_users()
    assert [u.chat_id for u in active] == ["trial_active"]


def test_lifecycle_sent_steps_and_record_dedup(mock_db_session):
    store = mock_db_session
    store.add_user(chat_id="lc1")

    assert store.get_lifecycle_sent_steps("lc1", "telegram") == set()

    store.record_lifecycle_event("lc1", "d7", "telegram")
    assert store.get_lifecycle_sent_steps("lc1", "telegram") == {"d7"}
    assert store.get_lifecycle_sent_steps("lc1", "email") == set()

    # Doppio invio dello stesso step/canale: non deve sollevare eccezioni né duplicare.
    store.record_lifecycle_event("lc1", "d7", "telegram")
    with store.Session() as s:
        count = s.query(TrialLifecycleEvent).filter_by(
            chat_id="lc1", step="d7", channel="telegram"
        ).count()
        assert count == 1


# --- Referral ---

def test_extend_trial_days_from_free_plan(mock_db_session):
    store = mock_db_session
    store.add_user(chat_id="ref_free")

    store.extend_trial_days("ref_free", days=60)

    plan = store.get_user_plan("ref_free")
    assert plan["plan_type"] == "pro"
    assert plan["is_trial"] is True
    assert (plan["trial_ends_at"] - datetime.utcnow()).days in (59, 60)

    with store.Session() as s:
        change = s.query(PlanChange).filter_by(chat_id="ref_free", change_type="referral_reward").first()
        assert change is not None


def test_extend_trial_days_is_additive_on_active_trial(mock_db_session):
    store = mock_db_session
    store.add_user(chat_id="ref_trial")
    store.start_trial("ref_trial", days=30)

    plan_before = store.get_user_plan("ref_trial")
    store.extend_trial_days("ref_trial", days=60)
    plan_after = store.get_user_plan("ref_trial")

    assert plan_after["trial_ends_at"] > plan_before["trial_ends_at"]
    delta = (plan_after["trial_ends_at"] - plan_before["trial_ends_at"]).days
    assert delta in (59, 60)


def test_extend_trial_days_on_permanent_beta_pro(mock_db_session):
    """Applicato anche a un Pro permanente beta_default: scelta esplicita del reward
    referral, lo trasforma in Pro con scadenza (vedi extend_trial_days docstring).
    """
    store = mock_db_session
    store.add_user(chat_id="ref_beta")
    store.set_user_plan("ref_beta", "pro", payment_reference="beta_default")

    plan_before = store.get_user_plan("ref_beta")
    assert plan_before["is_trial"] is False
    assert plan_before["trial_ends_at"] is None

    store.extend_trial_days("ref_beta", days=60)

    plan_after = store.get_user_plan("ref_beta")
    assert plan_after["is_trial"] is True
    assert plan_after["trial_ends_at"] is not None


def _make_lead(store, submission_id, email, referral_code=None, referred_by_code=None):
    lead, _ = store.save_tally_lead(
        tally_submission_id=submission_id,
        email=email,
        raw_payload="{}",
        referral_code=referral_code,
        referred_by_code=referred_by_code,
    )
    return lead


def test_create_referral_rewards_first_referral(mock_db_session):
    store = mock_db_session
    referrer = _make_lead(store, "sub_referrer", "referrer@example.com", referral_code="REFCODE1")
    referred = _make_lead(store, "sub_referred1", "friend1@example.com", referred_by_code="REFCODE1")

    result = store.create_referral_rewards(referred, referrer)

    assert result["referrer_first_reward"] is True
    assert result["lifetime_founder_unlocked"] is False

    with store.Session() as s:
        rewards = s.query(ReferralReward).all()
        roles = sorted((r.role, r.beneficiary_email) for r in rewards)
        assert roles == [
            ("referred", "friend1@example.com"),
            ("referrer", "referrer@example.com"),
        ]
        assert all(r.days_granted == 60 and r.status == "pending" for r in rewards)


def test_create_referral_rewards_caps_referrer_at_one_reward(mock_db_session):
    """Il tetto è fisso a 60gg totali: il referrer non riceve un secondo reward
    anche se porta più persone (spec: 1, 2 o 3 inviti danno sempre 60gg, mai di più)."""
    store = mock_db_session
    referrer = _make_lead(store, "sub_referrer2", "referrer2@example.com", referral_code="REFCODE2")
    referred1 = _make_lead(store, "sub_r2_1", "friend_a@example.com", referred_by_code="REFCODE2")
    referred2 = _make_lead(store, "sub_r2_2", "friend_b@example.com", referred_by_code="REFCODE2")

    result1 = store.create_referral_rewards(referred1, referrer)
    result2 = store.create_referral_rewards(referred2, referrer)

    assert result1["referrer_first_reward"] is True
    assert result2["referrer_first_reward"] is False

    with store.Session() as s:
        referrer_rewards = s.query(ReferralReward).filter_by(
            role="referrer", beneficiary_email="referrer2@example.com"
        ).count()
        assert referrer_rewards == 1
        referred_rewards = s.query(ReferralReward).filter_by(role="referred").count()
        assert referred_rewards == 2


def test_create_referral_rewards_unlocks_lifetime_founder_on_third(mock_db_session):
    store = mock_db_session
    referrer = _make_lead(store, "sub_referrer3", "referrer3@example.com", referral_code="REFCODE3")

    for i in range(1, 4):
        referred = _make_lead(store, f"sub_r3_{i}", f"friend{i}@example.com", referred_by_code="REFCODE3")
        result = store.create_referral_rewards(referred, referrer)

    assert result["lifetime_founder_unlocked"] is True

    with store.Session() as s:
        lead = s.query(TallyLead).filter_by(referral_code="REFCODE3").first()
        assert lead.lifetime_founder_guaranteed is True
        assert lead.lifetime_founder_guaranteed_at is not None

    # Un 4° referral non ri-attiva né duplica lo sblocco: il link smette di
    # generare reward dopo il 3°, sia per il referrer sia per il nuovo invitato.
    referred4 = _make_lead(store, "sub_r3_4", "friend4@example.com", referred_by_code="REFCODE3")
    result4 = store.create_referral_rewards(referred4, referrer)
    assert result4["lifetime_founder_unlocked"] is False
    assert result4["reward_cap_reached"] is True

    with store.Session() as s:
        reward_for_friend4 = s.query(ReferralReward).filter_by(beneficiary_email="friend4@example.com").first()
        assert reward_for_friend4 is None


def test_apply_pending_referral_rewards(mock_db_session):
    store = mock_db_session
    store.add_user(chat_id="applied1")
    store.set_credentials("applied1", "reward@example.com", "password123")

    referrer = _make_lead(store, "sub_apply_referrer", "referrer_apply@example.com", referral_code="REFAPPLY")
    referred = _make_lead(store, "sub_apply_referred", "reward@example.com", referred_by_code="REFAPPLY")
    store.create_referral_rewards(referred, referrer)

    applied = store.apply_pending_referral_rewards("reward@example.com")
    assert len(applied) == 1
    assert applied[0].role == "referred"
    assert applied[0].status == "applied"
    assert applied[0].beneficiary_chat_id == "applied1"

    plan = store.get_user_plan("applied1")
    assert plan["plan_type"] == "pro"
    assert plan["is_trial"] is True

    # Idempotente: una seconda chiamata non trova più nulla di pending.
    applied_again = store.apply_pending_referral_rewards("reward@example.com")
    assert applied_again == []


def test_apply_pending_referral_rewards_no_account_stays_pending(mock_db_session):
    store = mock_db_session
    referrer = _make_lead(store, "sub_np_referrer", "np_referrer@example.com", referral_code="REFNOACC")
    referred = _make_lead(store, "sub_np_referred", "np_friend@example.com", referred_by_code="REFNOACC")
    store.create_referral_rewards(referred, referrer)

    applied = store.apply_pending_referral_rewards("np_friend@example.com")
    assert applied == []

    with store.Session() as s:
        reward = s.query(ReferralReward).filter_by(beneficiary_email="np_friend@example.com").first()
        assert reward.status == "pending"


def test_get_or_create_referral_code_reuses_existing_lead(mock_db_session):
    store = mock_db_session
    _make_lead(store, "sub_code1", "coded@example.com", referral_code="EXISTINGCODE")

    code = store.get_or_create_referral_code("coded@example.com")
    assert code == "EXISTINGCODE"


def test_get_or_create_referral_code_synthesizes_lead_for_manual_account(mock_db_session):
    store = mock_db_session
    store.add_user(chat_id="manual1")
    store.set_credentials("manual1", "manual@example.com", "password123")

    code = store.get_or_create_referral_code("manual@example.com")
    assert code

    with store.Session() as s:
        lead = s.query(TallyLead).filter_by(referral_code=code).first()
        assert lead is not None
        assert lead.email == "manual@example.com"


def test_get_referral_status(mock_db_session):
    store = mock_db_session
    referrer = _make_lead(store, "sub_status_referrer", "status_referrer@example.com", referral_code="REFSTATUS")
    _make_lead(store, "sub_status_1", "status1@example.com", referred_by_code="REFSTATUS")
    _make_lead(store, "sub_status_2", "status2@example.com", referred_by_code="REFSTATUS")

    status = store.get_referral_status("status_referrer@example.com")
    assert status["referral_code"] == "REFSTATUS"
    assert status["referred_count"] == 2
    assert status["lifetime_founder_guaranteed"] is False
