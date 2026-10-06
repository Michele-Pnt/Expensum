"""
Process queued Telegram chat ID reassignment jobs.

This worker uses the migration database role for the cross-tenant operation. The bot
and dashboard only enqueue jobs and never perform the privileged update directly. Chiude qui la richiesta arruolata da
`UserStore.enqueue_chat_id_reassignment` (collegamento webapp<->Telegram, cambio account
Telegram) eseguendo `UserStore.process_pending_reassignment_jobs`, che internamente apre
`_owner_session()` — necessaria perché l'operazione è cross-tenant (sposta righe da
old_chat_id a new_chat_id) e la RLS con WITH CHECK non la permette sotto il ruolo
applicativo. This keeps privileged operations out of request handlers.

Non riceve mai input di rete diretto: legge solo dalla tabella job (arruolata dall'app
col ruolo DML-only), non da Telegram/HTTP. Run it as a separate process with the same environment configuration as the application.

Uso:
    python scripts/process_reassignment_jobs.py                  # loop continuo
    python scripts/process_reassignment_jobs.py --once            # un solo giro (test/cron)

For PostgreSQL, configure `MIGRATION_DATABASE_URL` with a migration role that can
perform the cross-tenant update. SQLite development does not require a separate role.
"""

import argparse
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from config import Config, setup_logging
from src.user_store import UserStore

logger = logging.getLogger("financial_agent.reassign_worker")

POLL_INTERVAL_SECONDS = 2.0


def run(once: bool = False) -> None:
    if not os.getenv("MIGRATION_DATABASE_URL"):
        logger.warning(
            "reassignment_worker_no_owner_url",
            extra={"domain": "security", "event": "reassignment_worker_no_owner_url", "meta": {}},
        )
    store = UserStore(db_url=Config.DATABASE_URL)
    logger.info(
        "reassignment_worker_started",
        extra={"domain": "security", "event": "reassignment_worker_started", "meta": {}},
    )
    while True:
        processed = store.process_pending_reassignment_jobs()
        if processed:
            logger.info(
                "reassignment_jobs_processed",
                extra={"domain": "security", "event": "reassignment_jobs_processed",
                       "meta": {"count": processed}},
            )
        if once:
            return
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    setup_logging()
    parser = argparse.ArgumentParser(
        description="Worker fuori banda per chat_id_reassignment_jobs."
    )
    parser.add_argument("--once", action="store_true", help="Un solo giro, poi esce (utile per test/cron).")
    args = parser.parse_args()
    run(once=args.once)
