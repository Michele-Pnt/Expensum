import pytest
from datetime import date, datetime
from src.user_store import User, DailyMetrics, Feedback, OAuthSession, PlanChange, UserPlan
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
    """Verifica che delete_user_completely cancelli 0 record in TUTTE le tabelle collegate."""
    store = mock_db_session
    chat_id = "99999"
    store.add_user(chat_id=chat_id, username="delete-me")

    # Inizializza piano (crea UserPlan row)
    store.get_user_plan(chat_id)

    # Inserisce un record PlanChange
    with store.Session() as session:
        session.add(PlanChange(
            chat_id=chat_id,
            from_plan="free",
            to_plan="pro",
            change_type="upgrade",
            changed_at=datetime.utcnow(),
        ))
        session.add(Feedback(chat_id=chat_id, message="ciao"))
        session.commit()

    result = store.delete_user_completely(chat_id)
    assert result != "not_found"

    with store.Session() as session:
        assert session.query(PlanChange).filter_by(chat_id=chat_id).count() == 0
        assert session.query(UserPlan).filter_by(chat_id=chat_id).count() == 0
        assert session.query(Feedback).filter_by(chat_id=chat_id).count() == 0
        assert session.query(OAuthSession).filter_by(chat_id=chat_id).count() == 0
        assert session.query(User).filter_by(chat_id=chat_id).first() is None
