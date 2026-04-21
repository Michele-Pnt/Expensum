"""
user_store.py — Gestione persistenza utenti tramite SQLAlchemy.
Supporta SQLite (locale) e predisposto per PostgreSQL/Oracle.
"""

import logging
from datetime import datetime, date
import secrets
import string
from typing import Optional
from sqlalchemy import Column, String, Boolean, DateTime, Integer, Date, ForeignKey, create_engine, text
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
    notion_access_token = Column(String, nullable=True)
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

    # Backend di storage
    storage_backend = Column(String, default="notion", nullable=False)
    

    def __repr__(self):
        return f"<User(chat_id={self.chat_id}, username='{self.username}')>"

# 3. DEFINIAMO LA TABELLA UTILIZZO GIORNALIERO (Fase 4D)
class DailyUsage(Base):
    __tablename__ = "daily_usage"
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(String, ForeignKey("users.chat_id"), nullable=False)
    usage_date = Column(Date, default=date.today, nullable=False)
    text_count = Column(Integer, default=0)
    voice_count = Column(Integer, default=0)
    photo_count = Column(Integer, default=0)

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

# 6. TABELLA SESSIONI OAUTH (Fase 2)
class OAuthSession(Base):
    __tablename__ = "oauth_sessions"
    state = Column(String, primary_key=True)
    chat_id = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

# 5. IL MANAGER DEL DATABASE
class UserStore:
    def __init__(self, db_url="sqlite:///users.db"):
        # create_engine è il "motore" che parla col database fisico
        self.engine = create_engine(db_url)
        # Questa riga crea fisicamente le tabelle se non esistono ancora
        Base.metadata.create_all(self.engine)
        self._ensure_sqlite_schema()
        # sessionmaker crea le "sessioni" di lavoro (come aprire una transazione)
        self.Session = sessionmaker(bind=self.engine)
        logger.info(f"UserStore inizializzato correttamente.")

    def _ensure_sqlite_schema(self) -> None:
        """Esegue migrazioni minime per SQLite aggiungendo colonne mancanti senza perdita dati."""
        if self.engine.dialect.name != "sqlite":
            return

        expected_user_columns = {
            "username": "TEXT",
            "notion_api_key": "TEXT",
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
        }

        with self.engine.begin() as connection:
            # 1. Verifica colonne tabella users
            rows = connection.execute(text("PRAGMA table_info(users)")).mappings().all()
            if rows:
                existing_columns = {row["name"] for row in rows}
                for column_name, column_type in expected_user_columns.items():
                    if column_name in existing_columns:
                        continue
                    connection.execute(text(f"ALTER TABLE users ADD COLUMN {column_name} {column_type}"))
                    logger.info(f"[DB Migration] Aggiunta colonna users.{column_name}")

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

    def set_credentials(self, chat_id: str, email: str, password: str) -> None:
        """Salva email e hash bcrypt della password per un utente."""
        import bcrypt
        chat_id = str(chat_id)
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        with self.Session() as session:
            user = session.query(User).filter(User.chat_id == chat_id).first()
            if user:
                user.email = email.lower().strip()
                user.password_hash = hashed
                session.commit()

    def get_user_by_email(self, email: str) -> User | None:
        """Cerca un utente attivo per email (case-insensitive)."""
        with self.Session() as session:
            return session.query(User).filter(
                User.email == email.lower().strip(),
                User.is_active == True,
            ).first()

    def verify_password(self, email: str, password: str) -> User | None:
        """Verifica email+password. Ritorna l'utente se le credenziali sono corrette, None altrimenti."""
        import bcrypt
        user = self.get_user_by_email(email)
        if not user or not user.password_hash:
            return None
        if bcrypt.checkpw(password.encode(), user.password_hash.encode()):
            return user
        return None

    def increment_usage(self, chat_id: str, msg_type: str):
        """Incrementa il contatore giornaliero per tipo di messaggio (text, voice, photo)."""
        chat_id = str(chat_id)
        valid_types = {"text", "voice", "photo"}
        if msg_type not in valid_types:
            logger.warning(f"Tipo messaggio '{msg_type}' non valido per l'increment_usage.")
            return

        today = date.today()
        with self.Session() as session:
            # Cerca il record per l'user loggato di oggi
            usage = session.query(DailyUsage).filter_by(chat_id=chat_id, usage_date=today).first()
            if not usage:
                usage = DailyUsage(chat_id=chat_id, usage_date=today)
                session.add(usage)
            
            # Incrementa in base al tipo (con fallback a 0 se il valore è NULL)
            if msg_type == "text":
                usage.text_count = (usage.text_count or 0) + 1
            elif msg_type == "voice":
                usage.voice_count = (usage.voice_count or 0) + 1
            elif msg_type == "photo":
                usage.photo_count = (usage.photo_count or 0) + 1
            
            session.commit()
            logger.debug(f"[User {chat_id}] DailyUsage aggiornato: {msg_type} (+1)")

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
        """Controlla se lo state è valido, ritorna il chat_id e cancella la sessione."""
        with self.Session() as session:
            oauth_sess = session.query(OAuthSession).filter_by(state=state).first()
            if oauth_sess:
                chat_id = oauth_sess.chat_id
                session.delete(oauth_sess)
                session.commit()
                return chat_id
        return None

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
        """Ritorna tutti gli utenti attivi con storage_backend Postgres."""
        with self.Session() as session:
            return session.query(User).filter(
                User.is_active == True,
                User.storage_backend == "postgres",
                User.setup_status == "DONE",
            ).all()

    # --- METODI USER CATEGORIES ---

    def upsert_user_categories(self, user_id: str, categories: list[dict]) -> None:
        """Inserisce o aggiorna le categorie di un utente.

        Ogni dict deve avere: name (str), average (float),
        e opzionalmente notion_page_id (str) e synced_at (datetime).
        """
        user_id = str(user_id)
        now = datetime.utcnow()
        with self.Session() as session:
            for cat in categories:
                existing = session.execute(
                    text(
                        "SELECT id FROM user_categories "
                        "WHERE user_id = :uid AND name = :name"
                    ),
                    {"uid": user_id, "name": cat["name"]},
                ).fetchone()
                if existing:
                    session.execute(
                        text(
                            "UPDATE user_categories "
                            "SET average = :avg, notion_page_id = :pid, synced_at = :ts "
                            "WHERE user_id = :uid AND name = :name"
                        ),
                        {
                            "avg": cat.get("average", 0.0),
                            "pid": cat.get("notion_page_id"),
                            "ts": cat.get("synced_at", now),
                            "uid": user_id,
                            "name": cat["name"],
                        },
                    )
                else:
                    session.execute(
                        text(
                            "INSERT INTO user_categories "
                            "(user_id, name, average, notion_page_id, synced_at) "
                            "VALUES (:uid, :name, :avg, :pid, :ts)"
                        ),
                        {
                            "uid": user_id,
                            "name": cat["name"],
                            "avg": cat.get("average", 0.0),
                            "pid": cat.get("notion_page_id"),
                            "ts": cat.get("synced_at", now),
                        },
                    )
            session.commit()

    def get_user_category_names(self, user_id: str) -> list[str]:
        """Ritorna i nomi delle categorie dell'utente."""
        user_id = str(user_id)
        with self.Session() as session:
            rows = session.execute(
                text("SELECT name FROM user_categories WHERE user_id = :uid ORDER BY name"),
                {"uid": user_id},
            ).fetchall()
            return [r[0] for r in rows]

    def get_category_by_notion_page_id(self, user_id: str, page_id: str) -> dict:
        """Ritorna {name, average} per un page_id Notion. Fallback su Sconosciuta."""
        user_id = str(user_id)
        with self.Session() as session:
            row = session.execute(
                text(
                    "SELECT name, average FROM user_categories "
                    "WHERE user_id = :uid AND notion_page_id = :pid"
                ),
                {"uid": user_id, "pid": page_id},
            ).fetchone()
            if row:
                return {"name": row[0], "average": row[1]}
            return {"name": "Sconosciuta", "average": 0.0}

    def get_notion_page_id_for_category(self, user_id: str, name: str) -> Optional[str]:
        """Ritorna il notion_page_id per un nome categoria. None se non trovato."""
        user_id = str(user_id)
        with self.Session() as session:
            row = session.execute(
                text(
                    "SELECT notion_page_id FROM user_categories "
                    "WHERE user_id = :uid AND LOWER(name) = LOWER(:name)"
                ),
                {"uid": user_id, "name": name},
            ).fetchone()
            if row:
                return row[0]
            # Ricerca parziale
            row = session.execute(
                text(
                    "SELECT notion_page_id FROM user_categories "
                    "WHERE user_id = :uid AND ("
                    "LOWER(name) LIKE LOWER(:pattern) OR LOWER(:name) LIKE LOWER('%' || name || '%')"
                    ")"
                ),
                {"uid": user_id, "name": name, "pattern": f"%{name}%"},
            ).fetchone()
            return row[0] if row else None

    def update_category_average(self, user_id: str, category_name: str, new_average: float) -> None:
        """Aggiorna la media storica per una singola categoria."""
        user_id = str(user_id)
        with self.Session() as session:
            session.execute(
                text(
                    "UPDATE user_categories SET average = :avg "
                    "WHERE user_id = :uid AND name = :name"
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
