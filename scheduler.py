"""
scheduler.py — Schedulatore mensile per l'Agente Finanziario.

Avvia un processo persistente che esegue automaticamente l'agente
il 1° di ogni mese all'ora configurata in .env (default: 07:00 UTC).

Utilizzo:
    python scheduler.py           # Avvia in background
    python scheduler.py --now     # Esegui subito (test)

Per eseguirlo come servizio di sistema con systemd, vedi il README.
"""

import argparse
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from config import Config, setup_logging
from main import run_agent


def scheduled_job():
    """Job mensile: analizza il mese precedente."""
    logger = logging.getLogger("financial_agent.scheduler")
    today = datetime.now()
    logger.info(f"🚀 Job mensile avviato il {today.strftime('%d/%m/%Y %H:%M')}")

    # Analizza il mese precedente
    if today.month == 1:
        target_month, target_year = 12, today.year - 1
    else:
        target_month, target_year = today.month - 1, today.year

    try:
        asyncio.run(run_agent(target_year, target_month, dry_run=False))
        logger.info("✅ Job mensile completato con successo.")
    except Exception as e:
        logger.exception(f"❌ Errore durante l'esecuzione del job: {e}")


def main():
    setup_logging()
    logger = logging.getLogger("financial_agent.scheduler")

    parser = argparse.ArgumentParser(description="Scheduler mensile Agente Finanziario")
    parser.add_argument("--now", action="store_true", help="Esegui subito il job")
    args = parser.parse_args()

    if args.now:
        logger.info("Esecuzione immediata richiesta (--now)")
        scheduled_job()
        return

    Config.validate()

    timezone = ZoneInfo("Europe/Rome")
    scheduler = BlockingScheduler(timezone=timezone)
    trigger = CronTrigger(
        day=1,
        hour=Config.SCHEDULE_HOUR,
        minute=Config.SCHEDULE_MINUTE,
        timezone=timezone,
    )
    scheduler.add_job(
        scheduled_job,
        trigger=trigger,
        id="monthly_financial_report",
        name="Report Finanziario Mensile",
        misfire_grace_time=3600,  # Tollera fino a 1h di ritardo
    )

    next_run = trigger.get_next_fire_time(None, datetime.now(timezone))
    logger.info(
        f"⏰ Scheduler avviato. Prossima esecuzione: {next_run.strftime('%d/%m/%Y %H:%M %Z')}"
    )
    logger.info("Premi Ctrl+C per fermare.")

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Scheduler fermato dall'utente.")
        scheduler.shutdown()


if __name__ == "__main__":
    main()
