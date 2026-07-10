"""
trigger_trial_drip.py — Forza l'invio immediato del drip trial per un chat_id di test.

Serve a verificare manualmente (Telegram + email reali) i messaggi D7/D14/D25/D29 senza
aspettare i giorni reali e senza toccare TRIAL_AUTOMATION_ENABLED in produzione: questo
script lo forza a True solo per la propria esecuzione, in memoria.

Uso:
    # Concede/backdata il trial al chat_id indicato e invia lo step dovuto per quel giorno
    python scripts/trigger_trial_drip.py --chat-id 123456789 --days 7

    # Come sopra ma senza inviare davvero l'email (solo Telegram, utile se non hai
    # BREVO_API_KEY configurata in locale)
    python scripts/trigger_trial_drip.py --chat-id 123456789 --days 29 --skip-email

Il chat_id deve essere un chat_id Telegram reale che ha già parlato col bot (altrimenti
Telegram rifiuta l'invio con "chat not found"). Il tuo lo trovi mandando /start al bot di
sviluppo e leggendolo dai log, o da store.get_user(...).
"""

import argparse
import asyncio
import os
import sys
import threading
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Forza il flag PRIMA di importare bot/config, così Config.TRIAL_AUTOMATION_ENABLED
# risulta True solo per questa esecuzione (niente modifiche a .env).
os.environ["TRIAL_AUTOMATION_ENABLED"] = "true"

import bot  # noqa: E402
from src.user_store import UserPlan  # noqa: E402


def _backdate_trial(chat_id: str, days: int) -> None:
    with bot._user_store.Session() as s:
        plan = s.query(UserPlan).filter_by(chat_id=chat_id).first()
        plan.trial_started_at = datetime.utcnow() - timedelta(days=days)
        s.commit()


def _run_job_sync(job_fn, app) -> None:
    """Stesso pattern usato in produzione da APScheduler: loop dedicato su un thread."""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        job_fn(app, loop)
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
        loop.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Forza l'invio del drip trial per un chat_id di test.")
    parser.add_argument("--chat-id", required=True, help="Chat ID Telegram reale (deve aver già parlato col bot)")
    parser.add_argument("--days", type=int, required=True, help="Giorni di trial da simulare (es. 7, 14, 25, 29)")
    parser.add_argument("--skip-email", action="store_true", help="Non chiamare davvero Brevo, solo Telegram")
    args = parser.parse_args()

    chat_id = str(args.chat_id)

    if not bot._user_store.get_user(chat_id):
        bot._user_store.add_user(chat_id=chat_id)
        print(f"[trigger_trial_drip] Utente {chat_id} non esisteva, creato al volo.")

    bot._user_store.start_trial(chat_id, days=30)
    _backdate_trial(chat_id, args.days)
    print(f"[trigger_trial_drip] Trial di {chat_id} backdatato a {args.days} giorni fa.")

    from telegram.ext import Application
    app = Application.builder().token(bot.Config.TELEGRAM_BOT_TOKEN).build()

    if args.skip_email:
        with patch("bot.brevo_client.send_transactional_email") as mock_email:
            _run_job_sync(bot._trial_lifecycle_job, app)
            print(f"[trigger_trial_drip] Email saltata (mock), chiamata {mock_email.call_count} volte.")
    else:
        _run_job_sync(bot._trial_lifecycle_job, app)

    sent_tg = bot._user_store.get_lifecycle_sent_steps(chat_id, "telegram")
    sent_email = bot._user_store.get_lifecycle_sent_steps(chat_id, "email")
    print(f"[trigger_trial_drip] Step inviati — telegram: {sent_tg or '(nessuno)'}, email: {sent_email or '(nessuno)'}")


if __name__ == "__main__":
    main()
