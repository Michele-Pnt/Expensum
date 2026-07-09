"""
trigger_trial_expiry.py — Forza il downgrade automatico a Free per un chat_id di test.

Serve a verificare manualmente il job di scadenza trial (_trial_expiry_job) senza
aspettare 30 giorni reali. Forza trial_ends_at nel passato per il chat_id indicato e
lancia il job, esattamente come farebbe APScheduler alle 04:00 in produzione.

Uso:
    python scripts/trigger_trial_expiry.py --chat-id 123456789
"""

import argparse
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ["TRIAL_AUTOMATION_ENABLED"] = "true"

import bot  # noqa: E402
from src.user_store import UserPlan  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Forza la scadenza trial per un chat_id di test.")
    parser.add_argument("--chat-id", required=True)
    args = parser.parse_args()
    chat_id = str(args.chat_id)

    if not bot._user_store.get_user(chat_id):
        print(f"[trigger_trial_expiry] Nessun utente {chat_id}, esco.")
        return

    with bot._user_store.Session() as s:
        plan = s.query(UserPlan).filter_by(chat_id=chat_id).first()
        if not plan or not plan.is_trial:
            print(f"[trigger_trial_expiry] {chat_id} non ha un trial attivo, esco.")
            return
        plan.trial_ends_at = datetime.utcnow() - timedelta(days=1)
        s.commit()
    print(f"[trigger_trial_expiry] trial_ends_at di {chat_id} forzato a ieri.")

    bot._trial_expiry_job(app=None, loop=None)

    plan = bot._user_store.get_user_plan(chat_id)
    print(f"[trigger_trial_expiry] Piano dopo il job: plan_type={plan['plan_type']}, is_trial={plan['is_trial']}")


if __name__ == "__main__":
    main()
