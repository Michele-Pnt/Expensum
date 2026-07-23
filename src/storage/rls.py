"""
rls.py — plumbing della Row-Level Security per il backend PostgreSQL.

Le policy RLS (definite nella migration Alembic `s0t1u2v3w4x5`) filtrano le tabelle
finanziarie con `user_id = current_setting('app.user_id')`. Perché funzionino, ogni
transazione deve impostare quella variabile di sessione con lo user_id corrente.

Questo modulo lo fa in modo sicuro rispetto al connection pooling: la variabile è
impostata **transaction-local** (`set_config(..., is_local=true)`), quindi vale solo
per la transazione in corso e non "sporca" la connessione quando torna nel pool.

Registrazione: l'import del modulo installa un listener globale sull'evento
`after_begin` delle sessioni SQLAlchemy. Il listener è un no-op su SQLite (dev/test,
niente RLS) e per le sessioni che non hanno uno user_id associato (es. tabelle di
auth non soggette a RLS).
"""

from sqlalchemy import event, text
from sqlalchemy.orm import Session

# Chiave in `session.info` che porta lo user_id del tenant corrente.
APP_USER_ID_KEY = "app_user_id"


def bind_user(session: Session, user_id: str) -> None:
    """Associa `user_id` alla sessione: verrà applicato come `app.user_id`
    all'inizio di ogni transazione, alimentando le policy RLS.

    Va chiamata prima di usare la sessione per query sui dati finanziari.
    """
    session.info[APP_USER_ID_KEY] = str(user_id)


def rebind_user(session: Session, user_id: str) -> None:
    """Come `bind_user`, ma da usare quando sulla sessione sono già state eseguite
    query (es. lookup di `OAuthSession`/`User` per risolvere un reg_token) prima
    che lo user_id fosse noto.

    `after_begin` scatta una sola volta, all'inizio della transazione: se `bind_user`
    arriva a transazione già aperta è troppo tardi, e ogni query RLS-protetta in
    quella transazione vede `app.user_id` non impostato (fail-closed → 0 righe in
    SELECT, violazione WITH CHECK in INSERT/UPDATE). Il rollback qui chiude la
    transazione già aperta (nessuna scrittura pendente in questi flussi) così il
    binding si applica alla prossima query, che ne apre una nuova.
    """
    session.rollback()
    bind_user(session, user_id)


@event.listens_for(Session, "after_begin")
def _apply_rls_user_id(session: Session, transaction, connection) -> None:
    """All'inizio di ogni transazione imposta `app.user_id` sulla connessione.

    No-op se il backend non è PostgreSQL o se alla sessione non è associato uno
    user_id (sessioni di auth/admin che non passano dalle tabelle RLS).
    """
    if connection.dialect.name != "postgresql":
        return
    user_id = session.info.get(APP_USER_ID_KEY)
    if user_id is None:
        return
    # is_local=true → la variabile vive solo per questa transazione: safe col pooling.
    connection.execute(
        text("SELECT set_config('app.user_id', :uid, true)"),
        {"uid": str(user_id)},
    )
