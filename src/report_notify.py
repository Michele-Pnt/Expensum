"""src/report_notify.py — Notifica condivisa in chat webapp del completamento di un report.

Usato sia dai piani leggeri (bot.py) sia dalla pipeline mensile pesante (main.py) per
mantenere lo stesso messaggio di saluto con link al report, indipendentemente da chi
ha generato il report.
"""

from src.user_store import UserStore


def display_name(store: UserStore, chat_id: str) -> str:
    """Ritorna un nome utente amichevole (first_name, username, email o generico)."""
    try:
        user = store.get_user(chat_id)
    except Exception:
        user = None
    if user and user.first_name:
        return user.first_name
    if user and user.username:
        return user.username
    if user and user.email:
        return user.email.split("@")[0]
    return "👋"


def notify_webapp_report(
    store: UserStore, chat_id: str, report_type: str, period_label: str, share_token: str
) -> None:
    """Logga in chat webapp un messaggio di saluto con link cliccabile al report."""
    name = display_name(store, chat_id)
    greeting = "Ehi" if name == "👋" else f"Ehi {name}"
    period_desc = "di questa settimana" if report_type == "weekly" else "del mese scorso"
    text = f"{greeting}, ho analizzato le tue finanze {period_desc} ({period_label})! Clicca qui per vedere il report."
    try:
        store.log_message(
            str(chat_id), source="webapp", role="bot", text=text,
            metadata={"report_type": report_type, "share_token": share_token},
        )
    except Exception:
        pass
