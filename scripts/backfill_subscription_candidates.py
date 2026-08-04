"""
backfill_subscription_candidates.py — Popola i candidati abbonamento dallo storico.

L'hook incrementale (`src/subscription_detector.evaluate_and_track`, agganciato in
bot.py subito dopo ogni spesa confermata) vede solo le spese future rispetto al
deploy della feature. Questo script applica la stessa identica logica, spesa per
spesa in ordine cronologico, allo storico già esistente (fino a
`Config.SUBSCRIPTION_LOOKBACK_DAYS_CASCADE` giorni indietro), così gli utenti già
iscritti da mesi non restano indietro rispetto a chi si iscrive oggi.

Idempotente e rieseguibile: `evaluate_and_track` ragiona sullo stato corrente dei
`subscription_candidates` (occorrenze/cadenza per categoria+importo), non su un
log di eventi consumati — rieseguendo sullo stesso insieme di spese nello stesso
ordine i conteggi restano gli stessi. Non manda alcuna notifica Telegram: i
candidati risultanti restano `pending`/`awaiting_confirm` finché l'utente non li
rivede con /scova_abbonamenti (stessa scelta della gamification: nessuno deve
ricevere una raffica di messaggi al lancio della feature).

Usa:
    python scripts/backfill_subscription_candidates.py --dry-run       # mostra cosa farebbe
    python scripts/backfill_subscription_candidates.py                 # esegue
    python scripts/backfill_subscription_candidates.py --chat-id 123   # un solo utente
    python scripts/backfill_subscription_candidates.py --limit 5       # primi N utenti
"""
import argparse
import json
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import Config
from src import subscription_detector
from src.notion_client import NotionFinanceClient
from src.storage.notion_storage import NotionStorage
from src.storage.postgres_storage import PostgresStorage
from src.user_store import User, UserStore


def _safe_json_load(raw):
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}


def _build_storage(store: UserStore, user: User, session):
    """Ricostruisce lo storage finanziario per un utente, backend-agnostico.

    Stesso schema di `_get_storage` in bot.py, senza la cache cross-richiesta:
    qui ogni utente viene processato una volta sola per esecuzione.
    """
    if user.storage_backend == "postgres":
        return PostgresStorage(session=session, user_id=user.chat_id)

    db_schemas = store.get_database_schemas(user.chat_id)
    schemas = {}
    for db_key, schema_data in db_schemas.items():
        schemas[db_key] = {
            "raw": _safe_json_load(schema_data.get("properties")),
            "mapped": _safe_json_load(schema_data.get("mapped")),
        }
    client = NotionFinanceClient(
        api_key=user.notion_access_token,
        expense_db_id=user.expense_db_id,
        income_db_id=user.income_db_id,
        categories_db_id=user.categories_db_id,
        monthly_balance_db_id=user.monthly_balance_db_id,
        accounts_db_id=user.accounts_db_id,
        subscriptions_db_id=user.subscriptions_db_id,
        pay_transfer_db_id=user.pay_transfer_db_id,
        db_schemas=schemas,
    )
    return NotionStorage(client, store=store, user_id=user.chat_id)


def _lookback_start(today: date) -> date:
    """Il backfill non ha bisogno della cascata 90/60/30 del comando on-demand
    (pensata per non bloccare chi ha poco storico): può permettersi di guardare
    sempre la finestra più larga in un colpo solo."""
    return today - timedelta(days=max(Config.SUBSCRIPTION_LOOKBACK_DAYS_CASCADE))


def backfill_user(store: UserStore, chat_id: str, dry_run: bool = False) -> dict:
    """Rielabora lo storico di un utente. Ritorna un riepilogo per il logging."""
    with store.Session() as session:
        user = session.query(User).filter_by(chat_id=chat_id).first()
        if user is None or not user.is_active:
            return {"chat_id": chat_id, "skipped": "utente non trovato o inattivo"}

        storage = _build_storage(store, user, session)
        today = date.today()
        transactions = storage.fetch_all_transactions(_lookback_start(today), today)
        transactions = [t for t in transactions if t.get("date") and t.get("amount")]
        transactions.sort(key=lambda t: t["date"])

        if dry_run:
            relevant = sum(
                1 for t in transactions
                if subscription_detector.is_subscription_prone_category(t.get("category"))
            )
            return {
                "chat_id": chat_id,
                "transactions_scanned": len(transactions),
                "candidates_touched": relevant,
                "awaiting_confirmation": 0,
            }

        touched = 0
        awaiting = 0
        for tx in transactions:
            result = subscription_detector.evaluate_and_track(
                session,
                chat_id,
                tx["date"],
                float(tx["amount"]),
                tx.get("category"),
                tx.get("name") or "",
            )
            if result.candidate_id:
                touched += 1
            if result.awaiting_confirmation:
                awaiting += 1

        return {
            "chat_id": chat_id,
            "transactions_scanned": len(transactions),
            "candidates_touched": touched,
            "awaiting_confirmation": awaiting,
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Popola i candidati abbonamento dallo storico esistente."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Conta le spese in categorie subscription-prone senza scrivere nulla")
    parser.add_argument("--chat-id", help="Elabora un solo utente")
    parser.add_argument("--limit", type=int, help="Elabora al massimo N utenti")
    args = parser.parse_args()

    store = UserStore(db_url=Config.DATABASE_URL)

    chat_ids = [args.chat_id] if args.chat_id else [
        u.chat_id for u in store.get_all_active_users()
    ]
    if args.limit:
        chat_ids = chat_ids[:args.limit]

    print(f"[backfill] {len(chat_ids)} utenti da elaborare"
          f"{' (dry-run)' if args.dry_run else ''}.\n")

    total_awaiting = 0
    for chat_id in chat_ids:
        try:
            summary = backfill_user(store, chat_id, dry_run=args.dry_run)
        except Exception as e:
            print(f"  {chat_id}: ERRORE — {e}")
            continue
        if summary.get("skipped"):
            continue
        total_awaiting += summary.get("awaiting_confirmation", 0)
        if summary["candidates_touched"]:
            print(
                f"  {chat_id}: {summary['transactions_scanned']} spese scansionate, "
                f"{summary['candidates_touched']} candidati toccati, "
                f"{summary['awaiting_confirmation']} pronti per conferma"
            )

    print(f"\n[backfill] Fatto. {total_awaiting} candidati pronti per conferma in totale "
          "(l'utente li vede con /scova_abbonamenti).")


if __name__ == "__main__":
    main()
