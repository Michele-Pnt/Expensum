"""
simulate_streak.py — Forza lo stato della streak per un chat_id di test, senza aspettare
giorni reali.

Il chat_id deve essere un chat_id Telegram reale che ha già parlato col bot di sviluppo
(altrimenti Telegram rifiuta l'invio con "chat not found"). Lo trovi mandando /start al bot
di sviluppo e leggendolo dai log, o da bot._user_store.get_user(...).

Uso:
    # Mostra lo stato attuale della streak
    python scripts/simulate_streak.py --chat-id 123456789 --show

    # Porta l'utente a un giorno dal completare il ciclo corrente (default target 14):
    # dopo questo, manda 2 spese/entrate reali al bot di sviluppo e osservi sia il
    # messaggio di congratulazioni sia la barra in /status passare a "premio attivo".
    python scripts/simulate_streak.py --chat-id 123456789 --set-near-target

    # Forza direttamente lo stato "premio Pro attivo, streak in pausa" (per vedere la
    # didascalia "in pausa" in /status senza dover completare un ciclo davvero)
    python scripts/simulate_streak.py --chat-id 123456789 --set-reward-active --target 28

    # Fa scadere il premio nel passato: la prossima spesa/entrata reale che mandi al bot
    # deve far ripartire il conteggio (cycle_state -> counting) al target già aumentato
    python scripts/simulate_streak.py --chat-id 123456789 --expire-reward

    # Lancia subito il job notturno di reset (03:15 in produzione) invece di aspettarlo
    python scripts/simulate_streak.py --run-reset-job
"""

import argparse
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import bot  # noqa: E402
from src.user_store import UserStreak  # noqa: E402


def _get_or_create(chat_id: str) -> None:
    if not bot._user_store.get_user(chat_id):
        bot._user_store.add_user(chat_id=chat_id)
        print(f"[simulate_streak] Utente {chat_id} non esisteva, creato al volo.")


def _set_streak(chat_id: str, **fields) -> None:
    with bot._user_store.Session() as s:
        streak = s.query(UserStreak).filter_by(chat_id=chat_id).first()
        if not streak:
            streak = UserStreak(chat_id=chat_id)
            s.add(streak)
        for key, value in fields.items():
            setattr(streak, key, value)
        s.commit()


def _print_state(chat_id: str) -> None:
    streak = bot._user_store.get_user_streak(chat_id)
    print(f"[simulate_streak] Stato {chat_id}: {streak}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Simula lo stato della streak per un chat_id di test.")
    parser.add_argument("--chat-id", help="Chat ID Telegram reale (deve aver già parlato col bot)")
    parser.add_argument("--target", type=int, default=14, help="Target del ciclo da simulare (default 14)")
    parser.add_argument("--show", action="store_true", help="Mostra solo lo stato attuale")
    parser.add_argument(
        "--set-near-target", action="store_true",
        help="Porta la streak a un giorno dal completare --target (poi manda 2 tx reali al bot)",
    )
    parser.add_argument(
        "--set-reward-active", action="store_true",
        help="Forza cycle_state=reward_active con reward_active_until nel futuro",
    )
    parser.add_argument(
        "--expire-reward", action="store_true",
        help="Se già in reward_active, fa scadere reward_active_until nel passato",
    )
    parser.add_argument("--run-reset-job", action="store_true", help="Lancia subito _nightly_streak_reset_job")
    args = parser.parse_args()

    if args.run_reset_job:
        bot._nightly_streak_reset_job()
        print("[simulate_streak] Job di reset notturno eseguito.")
        return

    if not args.chat_id:
        parser.error("--chat-id è obbligatorio (tranne con --run-reset-job)")

    chat_id = str(args.chat_id)
    _get_or_create(chat_id)

    if args.show:
        _print_state(chat_id)
        return

    if args.set_near_target:
        _set_streak(
            chat_id,
            current_streak_days=args.target - 1,
            streak_target_days=args.target,
            last_qualifying_date=date.today() - timedelta(days=1),
            cycle_state="counting",
            reward_active_until=None,
        )
        print(
            f"[simulate_streak] {chat_id} a {args.target - 1}/{args.target} giorni. "
            "Manda 2 spese/entrate reali al bot per completare il ciclo e vedere il "
            "messaggio di congratulazioni + la barra in /status."
        )

    elif args.set_reward_active:
        _set_streak(
            chat_id,
            current_streak_days=0,
            streak_target_days=args.target,
            cycle_state="reward_active",
            reward_active_until=datetime.utcnow() + timedelta(days=14),
        )
        print(f"[simulate_streak] {chat_id} in reward_active, prossimo target {args.target}. Prova /status.")

    elif args.expire_reward:
        _set_streak(chat_id, reward_active_until=datetime.utcnow() - timedelta(minutes=1))
        print(
            f"[simulate_streak] reward_active_until di {chat_id} forzato nel passato. "
            "La prossima spesa/entrata reale deve far ripartire il conteggio."
        )

    _print_state(chat_id)


if __name__ == "__main__":
    main()
