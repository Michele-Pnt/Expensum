"""
user_store.py — Gestione persistenza utenti tramite SQLAlchemy.
Supporta SQLite (locale) e predisposto per PostgreSQL/Oracle.
"""

import logging
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger("financial_agent.user_store")

# 1. DEFINIAMO LO STAMPO (BASE)
# Tutte le classi che erediteranno da Base diventeranno tabelle nel DB.
Base = declarative_base()

# 2. DEFINIAMO LA TABELLA UTENTI
class User(Base):
    __tablename__ = "users"

    # chat_id è la chiave primaria (ID univoco di Telegram)
    chat_id = Column(String, primary_key=True)
    username = Column(String, nullable=True)
    
    # Credenziali Notion specifiche per questo utente
    notion_api_key = Column(String, nullable=False)
    expense_db_id = Column(String, nullable=False)
    income_db_id = Column(String, nullable=False)
    
    # Campi opzionali (alcuni utenti potrebbero non averli)
    accounts_db_id = Column(String, nullable=True)
    categories_db_id = Column(String, nullable=True)
    
    # Metadati per sapere quando si sono registrati
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    def __repr__(self):
        return f"<User(chat_id={self.chat_id}, username='{self.username}')>"

# 3. IL MANAGER DEL DATABASE
class UserStore:
    def __init__(self, db_url="sqlite:///users.db"):
        # create_engine è il "motore" che parla col database fisico
        self.engine = create_engine(db_url)
        # Questa riga crea fisicamente le tabelle se non esistono ancora
        Base.metadata.create_all(self.engine)
        # sessionmaker crea le "sessioni" di lavoro (come aprire una transazione)
        self.Session = sessionmaker(bind=self.engine)
        logger.info(f"UserStore inizializzato correttamente.")

    def get_user(self, chat_id: str) -> User | None:
        """Cerca un utente per chat_id. Se non esiste o è disattivato, torna None."""
        chat_id = str(chat_id)
        with self.Session() as session:
            return session.query(User).filter(User.chat_id == chat_id, User.is_active == True).first()

    def add_user(self, chat_id: str, notion_api_key: str, expense_db_id: str, income_db_id: str, **kwargs):
        """Aggiunge un nuovo utente o aggiorna uno esistente."""
        chat_id = str(chat_id)
        with self.Session() as session:
            user = session.query(User).filter(User.chat_id == chat_id).first()
            if not user:
                user = User(chat_id=chat_id)
                session.add(user)
            
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
