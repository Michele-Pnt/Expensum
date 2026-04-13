import pytest
from datetime import date
from src.user_store import User, DailyUsage, Feedback, OAuthSession

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
    today = date.today()
    
    # Primo incremento (crea il record DailyUsage)
    store.increment_usage(chat_id, "text")
    store.increment_usage(chat_id, "text")
    store.increment_usage(chat_id, "voice")
    store.increment_usage(chat_id, "photo")
    
    with store.Session() as session:
        usage = session.query(DailyUsage).filter_by(chat_id=chat_id, usage_date=today).first()
        assert usage is not None
        assert usage.text_count == 2
        assert usage.voice_count == 1
        assert usage.photo_count == 1

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
