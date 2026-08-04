"""
backfill_gamification.py — Assegna retroattivamente gli achievement già meritati.

Gli utenti beta usano Expensum da mesi: senza questo passo il motore di gamification
partirebbe da zero anche per chi ha centinaia di spese registrate alle spalle.

Idempotente e rieseguibile: lo unique constraint su `user_achievements` impedisce
sia i doppioni sia il doppio accredito di XP, quindi eventuali eventi live avvenuti
fra il deploy e l'esecuzione non vengono duplicati.

Gli sblocchi retroattivi nascono con `notified_telegram=True`: nessuno deve ricevere
trenta messaggi di congratulazioni in fila. Restano invece `seen_at = NULL`, così al
primo accesso alla webapp il profilo appare già popolato.

Usa:
    python scripts/backfill_gamification.py --dry-run       # mostra cosa farebbe
    python scripts/backfill_gamification.py                 # esegue
    python scripts/backfill_gamification.py --chat-id 123   # un solo utente
    python scripts/backfill_gamification.py --limit 5       # primi N utenti
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import Config
from src.gamification import backfill
from src.storage.postgres_storage import PostgresStorage
from src.user_store import User, UserStore


def _make_storage_factory(store: UserStore):
    """Costruisce lo storage finanziario per un utente, o None se non applicabile.

    Le sessioni restano aperte per la durata della singola elaborazione utente e
    vengono chiuse dal chiamante: aprirne una per tutto il backfill terrebbe una
    transazione viva per minuti.
    """
    sessions = []

    def factory(chat_id: str):
        with store.Session() as s:
            user = s.query(User).filter_by(chat_id=chat_id).first()
            backend = user.storage_backend if user else None
        if backend != "postgres":
            return None
        session = store.Session()
        sessions.append(session)
        return PostgresStorage(session=session, user_id=chat_id)

    return factory, sessions


def main() -> None:
    """Esegue il backfill degli achievement retroattivi."""
    parser = argparse.ArgumentParser(
        description="Assegna retroattivamente gli achievement già meritati."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Mostra i contatori calcolati senza scrivere nulla")
    parser.add_argument("--chat-id", help="Elabora un solo utente")
    parser.add_argument("--limit", type=int, help="Elabora al massimo N utenti")
    args = parser.parse_args()

    store = UserStore(db_url=Config.DATABASE_URL)
    factory, sessions = _make_storage_factory(store)

    try:
        if args.dry_run:
            _dry_run(store, factory, args)
            return

        if args.chat_id:
            result = backfill.backfill_user(store, args.chat_id, factory(args.chat_id))
            print(f"[backfill] {result['chat_id']}: {result['unlocked']} sblocchi "
                  f"({', '.join(result['codes']) or 'nessuno'})")
            return

        summary = backfill.backfill_all(store, factory, limit=args.limit)
        for detail in summary["details"]:
            if detail["unlocked"]:
                print(f"[backfill] {detail['chat_id']}: {detail['unlocked']} sblocchi")
        print(f"[backfill] Fatto. {summary['users']} utenti, "
              f"{summary['unlocked']} achievement assegnati.")
    finally:
        for session in sessions:
            session.close()


def _dry_run(store: UserStore, factory, args) -> None:
    """Mostra i contatori che verrebbero scritti, senza toccare gli achievement."""
    from src.gamification import backfill as bf

    chat_ids = [args.chat_id] if args.chat_id else [
        u.chat_id for u in store.get_all_active_users()
    ]
    if args.limit:
        chat_ids = chat_ids[:args.limit]

    print(f"[backfill] (dry-run) {len(chat_ids)} utenti da elaborare.\n")
    for chat_id in chat_ids:
        storage = factory(chat_id)
        # `recompute_metrics` scrive i contatori ma NON sblocca achievement: in
        # dry-run è accettabile, sono comunque ricalcolabili dalle sorgenti.
        counters = bf.recompute_metrics(store, chat_id, storage)
        interesting = {k: v for k, v in sorted(counters.items()) if v}
        print(f"  {chat_id}: {interesting or 'nessun dato'}")
    print("\n[backfill] (dry-run) Nessun achievement assegnato.")


if __name__ == "__main__":
    main()
