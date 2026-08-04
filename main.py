"""
main.py — Orchestratore principale dell'Agente Analista & Predittore Finanziario.

Pipeline:
  1. Estrazione dati da Notion (con paginazione e retry)
  2. Elaborazione statistica: consuntivo, trend, anomalie
  3. Previsione statistica mese successivo
  4. Analisi AI con Mistral Small 3.1 (Chain of Thought)
  5. Costruzione report Markdown
  6. Invio report su Telegram

Modalità:
  --dry-run     Usa dati di test fittizi, mostra report a schermo senza
                inviare su Telegram e senza chiamare Mistral.
  --debug-data  Scarica dati REALI da Notion ma analizza solo in locale. Stampa
                il testo esatto da inviare al prompt di Mistral e un JSON con
                i dati estratti e si ferma prima della chiamata API.
  --month YYYY-MM   Analizza un mese specifico (default: mese scorso).
"""

import argparse
import asyncio
import logging
import sys
import os
import time
from calendar import monthrange
from datetime import date, datetime

from config import Config, setup_logging
from src.notion_client import NotionFinanceClient
from src.storage.notion_storage import NotionStorage
from src.storage.postgres_storage import PostgresStorage
from src.data_processor import DataProcessor
from src.forecaster import Forecaster
from src.mistral_client import MistralClient
from src.telegram_client import TelegramClient
from src.report_builder import ReportBuilder
from src.chart_generator import ChartGenerator
from src.llm_usage_tracker import build_request_key, estimate_reserved_tokens, normalize_usage_metadata
from src.user_store import UserStore
from src.report_notify import notify_webapp_report


# ---------------------------------------------------------------------------
# Mock data per dry-run
# ---------------------------------------------------------------------------
MOCK_TRANSACTIONS = [
    # Mese corrente (mese scorso in produzione)
    {"date": date(2026, 2, 1),  "category": "Affitto",        "name": "Affitto Febbraio",  "amount": 650.0},
    {"date": date(2026, 2, 3),  "category": "Supermercato",   "name": "Esselunga",          "amount": 87.50},
    {"date": date(2026, 2, 5),  "category": "Abbonamenti",    "name": "Netflix",            "amount": 13.99},
    {"date": date(2026, 2, 5),  "category": "Abbonamenti",    "name": "Spotify",            "amount": 9.99},
    {"date": date(2026, 2, 8),  "category": "Ristoranti",     "name": "Pizzeria da Mario",  "amount": 45.00},
    {"date": date(2026, 2, 10), "category": "Trasporti",      "name": "Abbonamento Metro",  "amount": 35.00},
    {"date": date(2026, 2, 12), "category": "Supermercato",   "name": "Conad",              "amount": 62.30},
    {"date": date(2026, 2, 15), "category": "Salute",         "name": "Farmacia",           "amount": 28.50},
    {"date": date(2026, 2, 18), "category": "Ristoranti",     "name": "Aperitivo",          "amount": 55.00},
    {"date": date(2026, 2, 20), "category": "Abbigliamento",  "name": "Zara",               "amount": 89.00},
    {"date": date(2026, 2, 22), "category": "Supermercato",   "name": "Esselunga",          "amount": 73.20},
    {"date": date(2026, 2, 25), "category": "Utility",        "name": "Bolletta Luce",      "amount": 78.00},
    {"date": date(2026, 2, 26), "category": "Ristoranti",     "name": "Cena compleanno",    "amount": 120.00},
    {"date": date(2026, 2, 28), "category": "Intrattenimento","name": "Cinema",             "amount": 22.00},
    # Mesi precedenti (storico)
    {"date": date(2026, 1, 1),  "category": "Affitto",        "name": "Affitto Gennaio",    "amount": 650.0},
    {"date": date(2026, 1, 5),  "category": "Abbonamenti",    "name": "Netflix",            "amount": 13.99},
    {"date": date(2026, 1, 5),  "category": "Abbonamenti",    "name": "Spotify",            "amount": 9.99},
    {"date": date(2026, 1, 8),  "category": "Supermercato",   "name": "Spesa settimana",    "amount": 95.00},
    {"date": date(2026, 1, 12), "category": "Ristoranti",     "name": "Pranzo fuori",       "amount": 38.00},
    {"date": date(2026, 1, 15), "category": "Trasporti",      "name": "Abbonamento Metro",  "amount": 35.00},
    {"date": date(2026, 1, 18), "category": "Supermercato",   "name": "Conad",              "amount": 67.80},
    {"date": date(2026, 1, 22), "category": "Utility",        "name": "Bolletta Luce",      "amount": 85.00},
    {"date": date(2026, 1, 25), "category": "Salute",         "name": "Farmacia",           "amount": 31.00},
    {"date": date(2026, 1, 28), "category": "Intrattenimento","name": "Teatro",             "amount": 30.00},
    {"date": date(2025, 12, 1), "category": "Affitto",        "name": "Affitto Dicembre",   "amount": 650.0},
    {"date": date(2025, 12, 5), "category": "Abbonamenti",    "name": "Netflix",            "amount": 13.99},
    {"date": date(2025, 12, 5), "category": "Abbonamenti",    "name": "Spotify",            "amount": 9.99},
    {"date": date(2025, 12, 10),"category": "Supermercato",   "name": "Spesa Natale",       "amount": 145.00},
    {"date": date(2025, 12, 15),"category": "Regali",         "name": "Regali Natale",      "amount": 250.00},
    {"date": date(2025, 12, 18),"category": "Ristoranti",     "name": "Cena Natale",        "amount": 85.00},
    {"date": date(2025, 12, 20),"category": "Trasporti",      "name": "Abbonamento Metro",  "amount": 35.00},
    {"date": date(2025, 12, 26),"category": "Abbigliamento",  "name": "Saldi invernali",    "amount": 120.00},
    {"date": date(2025, 12, 28),"category": "Utility",        "name": "Bolletta Luce",      "amount": 110.00},
]


def _build_accounts_liquidity_section(accounts: list[dict]) -> str:
    """Costruisce una sezione Markdown con la liquidità per ogni account."""
    lines = ["🏦 *Liquidità per account*"]
    if not accounts:
        lines.append("- Nessun conto disponibile")
        return "\n".join(lines)

    for acc in accounts:
        name = acc.get("name", "Sconosciuto")
        balance = float(acc.get("current_balance", 0.0))
        lines.append(f"- {name}: *€{balance:.2f}*")

    return "\n".join(lines)


def _insert_accounts_section_near_summary(report_text: str, accounts: list[dict]) -> str:
    """Inserisce la sezione liquidità account subito dopo 'Risparmio mensile'."""
    section = _build_accounts_liquidity_section(accounts)
    lines = report_text.splitlines()

    for idx, line in enumerate(lines):
        if line.strip().startswith("Risparmio mensile:"):
            insertion = ["", section]
            return "\n".join(lines[: idx + 1] + insertion + lines[idx + 1 :])

    return report_text + "\n\n---\n" + section


def _resolve_default_target_month(today: date) -> tuple[int, int]:
    """Ritorna (anno, mese) del consuntivo mensile di default: il mese scorso."""
    if today.month == 1:
        return today.year - 1, 12
    return today.year, today.month - 1


def _build_monthly_history(report) -> list[dict]:
    """Costruisce lo storico mensile per il report web usando il report già elaborato."""
    summaries = [m for m in [*(report.history or []), report.current_month] if m is not None]
    summaries.sort(key=lambda m: (m.year, m.month))

    income_by_month: dict[tuple[int, int], float] = {}
    for inc in report.incomes or []:
        inc_date = inc.get("date") or inc.get("income_date")
        if isinstance(inc_date, str):
            try:
                inc_date = date.fromisoformat(inc_date)
            except ValueError:
                continue
        elif isinstance(inc_date, datetime):
            inc_date = inc_date.date()

        if not isinstance(inc_date, date):
            continue

        key = (inc_date.year, inc_date.month)
        income_by_month[key] = income_by_month.get(key, 0.0) + abs(float(inc.get("amount") or 0.0))

    return [
        {
            "month": summary.label,
            "income": round(income_by_month.get((summary.year, summary.month), 0.0), 2),
            "expenses": round(summary.total, 2),
            "net": round(income_by_month.get((summary.year, summary.month), 0.0) - summary.total, 2),
        }
        for summary in summaries
    ]


def _build_monthly_report_payload(report, target_year: int, target_month: int, total_accounts_balance: float, budget_by_cat: dict[str, float]) -> dict:
    """Normalizza il payload JSON del report mensile condiviso sul web."""
    by_category = dict(report.current_month.by_category)
    return {
        "type": "monthly_full",
        "target_year": target_year,
        "target_month": target_month,
        "by_category": by_category,
        "spent_by_cat": by_category,
        "total": report.current_month.total,
        "total_income": report.total_income,
        "total_accounts": total_accounts_balance,
        "budget_by_cat": budget_by_cat,
        "monthly_history": _build_monthly_history(report),
    }


# ---------------------------------------------------------------------------
# Funzione principale
# ---------------------------------------------------------------------------

async def run_agent(
    target_year: int,
    target_month: int,
    dry_run: bool,
    debug_data: bool = False,
    chat_id: str | None = None,
    shared_store: UserStore | None = None,
) -> str | None:
    """Esegue la pipeline completa dell'agente finanziario.

    `shared_store` è opzionale: se passato (es. dal bot o dalla webapp, già connessi
    al DB), viene riusato invece di aprire nuove connessioni Postgres per ogni chiamata.

    Ritorna lo `share_token` del report salvato, o `None` se non è stato generato
    nulla (nessuna transazione nel mese target, dry-run, debug-data).
    """
    logger = logging.getLogger("financial_agent.main")
    usage_store = shared_store or UserStore(db_url=(f"sqlite:///{Config.LOG_DIR / 'token_usage_measure.db'}" if dry_run else Config.DATABASE_URL))
    usage_store.add_user("system")
    if not chat_id:
        chat_id = Config.TELEGRAM_CHAT_ID
    logger.info(
        f"{'[DRY-RUN] ' if dry_run else ''}Avvio agente — target: "
        f"{target_month:02d}/{target_year}"
    )

    # Calcola mese successivo
    if target_month == 12:
        next_month, next_year = 1, target_year + 1
    else:
        next_month, next_year = target_month + 1, target_year

    # 1. ESTRAZIONE DATI
    logger.info("▶ Step 1/7: Estrazione dati da Notion")
    if dry_run:
        transactions = MOCK_TRANSACTIONS
        monthly_balances = []  # nessun dato Monthly Balance in dry-run
        incomes = []           # nessun dato Income in dry-run
        accounts = [{"name": "Mock Bank", "current_balance": 1500.0}]
        budget_by_cat: dict[str, float] = {}
        logger.info(f"  [DRY-RUN] Usando {len(transactions)} transazioni mock")
    else:
        user_store = shared_store or UserStore(db_url=Config.DATABASE_URL)
        user = user_store.get_user(chat_id) if chat_id else None

        months_back = Config.HISTORY_MONTHS + 1
        start_year = target_year
        start_month = target_month - months_back
        while start_month <= 0:
            start_month += 12
            start_year -= 1
        start_date = date(start_year, start_month, 1)
        end_date = date(target_year, target_month, monthrange(target_year, target_month)[1])

        if user and user.storage_backend == "postgres":
            logger.info(f"Usando PostgreSQL storage per utente {chat_id}")
            _pg_session = user_store.Session()
            try:
                storage = PostgresStorage(_pg_session, user_id=chat_id)
                transactions = storage.fetch_all_transactions(start_date=start_date, end_date=end_date)
                logger.info("▶ Step 1b/7: Estrazione Monthly Balance (Risparmio Netto)")
                monthly_balances = storage.fetch_monthly_balances(start_date=start_date, end_date=end_date)
                logger.info("▶ Step 1c/7: Estrazione Entrate e Conti Correnti")
                incomes = storage.fetch_income(start_date=start_date, end_date=end_date)
                accounts = storage.fetch_accounts()
            finally:
                _pg_session.close()
        else:
            if user and user.notion_access_token:
                db_schemas = user_store.get_database_schemas(chat_id)
                notion_client = NotionFinanceClient(
                    api_key=user.notion_access_token,
                    expense_db_id=user.expense_db_id,
                    income_db_id=user.income_db_id,
                    categories_db_id=user.categories_db_id,
                    monthly_balance_db_id=user.monthly_balance_db_id,
                    accounts_db_id=user.accounts_db_id,
                    subscriptions_db_id=user.subscriptions_db_id,
                    pay_transfer_db_id=user.pay_transfer_db_id,
                    db_schemas=db_schemas,
                )
                logger.info(f"Usando Notion OAuth per utente {chat_id}")
            else:
                notion_client = NotionFinanceClient()
                logger.warning(f"Utente {chat_id} senza token Notion — fallback a Config .env")
            storage = NotionStorage(notion_client)
            transactions = storage.fetch_all_transactions(start_date=start_date, end_date=end_date)
            logger.info("▶ Step 1b/7: Estrazione Monthly Balance (Risparmio Netto)")
            monthly_balances = storage.fetch_monthly_balances(start_date=start_date, end_date=end_date)
            logger.info("▶ Step 1c/7: Estrazione Entrate e Conti Correnti")
            incomes = storage.fetch_income(start_date=start_date, end_date=end_date)
            accounts = storage.fetch_accounts()
        if accounts:
            accounts_log = ", ".join(
                f"{acc.get('name', 'Sconosciuto')}=€{float(acc.get('current_balance', 0.0)):.2f}"
                for acc in accounts
            )
            logger.info(f"Bilanci account letti da Notion: {accounts_log}")
        else:
            logger.warning("Nessun account valido letto da Notion.")

        # Fetch budget per categoria (per evidenziazione sforamenti nel report)
        try:
            categories_data = storage.get_categories(include_archived=True)
            budget_by_cat: dict[str, float] = {
                c["name"]: float(c["monthly_budget"])
                for c in categories_data
                if c.get("monthly_budget") is not None
            }
        except Exception as e:
            logger.warning(f"Impossibile recuperare budget categorie: {e}")
            budget_by_cat = {}

    if not transactions:
        logger.info(
            "Nessuna transazione nel periodo richiesto, invio nudge invece del report.",
            extra={"domain": "app", "event": "monthly_report_no_transactions"},
        )
        if chat_id and not dry_run and not str(chat_id).startswith("web_"):
            try:
                telegram = TelegramClient(chat_id=chat_id)
                await telegram.send_report(
                    "📭 *Non siamo riusciti a prepararti la tua dashboard*\n\n"
                    "Il motivo è semplice: non risulta nessuna transazione registrata per "
                    "questo periodo.\n\n"
                    "Ti invitiamo a prendere consapevolezza delle tue spese: scrivi a Moneo la "
                    "tua prossima spesa o entrata e scopri tutti i vantaggi che Expensum può "
                    "portarti nella gestione delle tue finanze! 💪"
                )
            except Exception as e:
                logger.warning(f"Impossibile inviare nudge 'nessuna transazione' a utente: {e}")
        return None

    # 2. ELABORAZIONE DATI
    logger.info("▶ Step 2/7: Elaborazione dati (aggregazione, trend, anomalie)")
    processor = DataProcessor()
    report = processor.process(transactions, target_year, target_month, incomes=incomes)
    data_text = processor.to_prompt_text(report)
    
    # Genera i grafici
    chart_gen = ChartGenerator()
    chart_paths = chart_gen.generate_all_charts(report)

    # Aggiungi dati Monthly Balance al blocco di testo per Gemini
    if monthly_balances:
        mb_lines = ["\n=== MONTHLY BALANCE (dato certo Notion) ==="]
        for mb in monthly_balances:
            mb_lines.append(f"  {mb['label']}: Risparmio Netto = €{mb['net_savings']:.2f}")
        data_text += "\n" + "\n".join(mb_lines)

        # Trova il risparmio netto del mese corrente per il report
        current_mb = next(
            (mb for mb in monthly_balances
             if mb["year"] == target_year and mb["month"] == target_month),
            None
        )
        if current_mb:
            logger.info(
                f"Risparmio Netto {report.current_month.label}: "
                f"€{current_mb['net_savings']:.2f} (dato Monthly Balance)"
            )
    else:
        current_mb = None

    # 3. PREVISIONE STATISTICA
    logger.info("▶ Step 3/7: Calcolo previsione statistica")
    forecaster = Forecaster()
    forecast = forecaster.predict(report, next_month, next_year)
    forecast_text = forecast.to_prompt_text()

    if debug_data:
        import json
        
        # Salva le transazioni estratte in locale per poterle ispezionare
        def default_serializer(obj):
            if isinstance(obj, (date, datetime)):
                return obj.isoformat()
            raise TypeError(f"Type {type(obj)} not serializable")
            
        with open("debug_transactions.json", "w", encoding="utf-8") as f:
            json.dump(transactions, f, default=default_serializer, indent=2, ensure_ascii=False)
            
        print("\n\n" + "="*80)
        print("🛑 MODALITÀ --debug-data ATTIVA 🛑")
        print("I dati reali sono stati estratti da Notion, salvati in 'debug_transactions.json'")
        print("ed elaborati statisticamente. Mostro di seguito il PROMPT che verrebbe")
        print("inviato all'Intelligenza Artificiale (Gemini):")
        print("="*80 + "\n")
        
        print("=== TESTO DATI (data_text) ===")
        print(data_text)
        print("\n=== TESTO PREVISIONI (forecast_text) ===")
        print(forecast_text)
        print("\n=== GRAFICI GENERATI ===")
        for p in chart_paths:
            print(f"- {p}")
        print("\n" + "="*80)
        print("Chiamata API cancellata pre-risoluzione come richiesto. Fine esecuzione.")
        
        # Cleanup immagini mock debug
        for path in chart_paths:
            if os.path.exists(path):
                os.remove(path)
        return None

    total_accounts_balance = sum(acc.get("current_balance", 0.0) for acc in accounts)

    # Costruisci testo conti correnti per il prompt
    accounts_text = "Conti Correnti attuali:\n"
    if accounts:
        accounts_text += f"Totale saldi conti (dato certo): €{total_accounts_balance:.2f}\n"
        for acc in accounts:
            accounts_text += f"- {acc['name']}: €{acc['current_balance']:.2f}\n"
    else:
        accounts_text += "Nessun conto trovato.\n"

    # 4. ANALISI AI
    logger.info("▶ Step 4/7: Analisi AI con Mistral Small 3.1")
    net_savings_str = f"€{current_mb['net_savings']:.2f}" if current_mb else "n/d"
    if dry_run:
        logger.info("  [DRY-RUN] Salto Mistral, uso report statistico locale")
        final_report = ReportBuilder.build_fallback_report(report, forecast, accounts=accounts, budget_by_cat=budget_by_cat)
    else:
        request_key = build_request_key("monthly_report", target_year, target_month, report.current_month.label, forecast.target_month_label)
        reservation_created = False
        try:
            usage_store.reserve_llm_tokens(
                chat_id=chat_id,
                request_key=request_key,
                operation="monthly_report",
                provider="mistral",
                model=Config.MISTRAL_SMALL_MODEL,
                reserved_tokens=estimate_reserved_tokens("monthly_report"),
            )
            reservation_created = True
        except Exception as e:
            logger.warning("Reservation report mensile non creata: %s", e)

        try:
            llm_client = MistralClient()
            logger.info(f"  Usando Mistral con modello {Config.MISTRAL_SMALL_MODEL}")

            llm_start = time.time()
            final_report, _llm_usage = llm_client.analyze_and_generate_report(
                data_text=data_text,
                accounts_text=accounts_text,
                forecast_text=forecast_text,
                current_month_label=report.current_month.label,
                next_month_label=forecast.target_month_label,
                total_income=f"{report.total_income:.2f}",
                total_amount=f"{report.current_month.total:.2f}",
                total_accounts_balance=f"{total_accounts_balance:.2f}",
                net_savings=net_savings_str,
            )
            if _llm_usage:
                _llm_usage = normalize_usage_metadata(_llm_usage)
                try:
                    usage_store.finalize_llm_usage(
                        chat_id=chat_id,
                        request_key=request_key,
                        prompt_tokens=_llm_usage.get("prompt_tokens", 0),
                        completion_tokens=_llm_usage.get("completion_tokens", 0),
                        total_tokens=_llm_usage.get("total_tokens", 0),
                        provider=_llm_usage.get("provider", "mistral"),
                        model=_llm_usage.get("model", Config.MISTRAL_SMALL_MODEL),
                        operation="monthly_report",
                    )
                except Exception as e:
                    logger.warning("Impossibile finalizzare usage report mensile: %s", e)
            elif reservation_created:
                try:
                    usage_store.release_llm_reservation(chat_id, request_key, reason="no_usage_metadata")
                except Exception:
                    pass
            llm_elapsed = time.time() - llm_start
            logger.info(
                "  ⏱️ Tempo inferenza Mistral: %.1fs — token usati: %s",
                llm_elapsed,
                _llm_usage.get("total_tokens", "n/d"),
            )
        except Exception as e:
            if reservation_created:
                try:
                    usage_store.release_llm_reservation(chat_id, request_key, reason=str(e))
                except Exception:
                    pass
            logger.error(f"Errore Mistral: {e}. Uso fallback statistico.")
            final_report = ReportBuilder.build_fallback_report(report, forecast, accounts=accounts, budget_by_cat=budget_by_cat)

    final_report = _insert_accounts_section_near_summary(final_report, accounts)

    if not dry_run:
        try:
            final_report += user_store.get_referral_footer_text(user.email if user else None)
        except Exception as e:
            logger.warning(f"Impossibile aggiungere footer referral al report: {e}")

    # 5. LOG DEL REPORT
    logger.info("▶ Step 5/7: Report generato")
    if dry_run:
        print("\n" + "=" * 60)
        print("📱 ANTEPRIMA REPORT TELEGRAM")
        print("=" * 60)
        print(final_report)
        print("=" * 60 + "\n")
        logger.info("[DRY-RUN] Report mostrato a schermo. Nessun messaggio inviato.")
        return None

    # 6. SALVATAGGIO + INVIO
    telegram_connected = bool(chat_id) and not str(chat_id).startswith("web_")

    # Salva report nel DB (sessione dedicata, indipendente dalla sessione di lettura)
    report_share_token: str = ""
    if chat_id and not dry_run:
        try:
            _save_store = shared_store or UserStore(db_url=Config.DATABASE_URL)
            _save_user = _save_store.get_user(chat_id)
            if _save_user and _save_user.storage_backend == "postgres":
                _save_session = _save_store.Session()
                try:
                    _save_storage = PostgresStorage(_save_session, user_id=chat_id)
                    report_share_token = _save_storage.save_report(
                        user_id=chat_id,
                        report_type="monthly",
                        # report_date = 1° del mese successivo a quello analizzato (es. analisi
                        # di giugno -> datata 1 luglio, il giorno in cui diventa disponibile).
                        report_date=date(next_year, next_month, 1),
                        text_content=final_report,
                        report_data=_build_monthly_report_payload(
                            report=report,
                            target_year=target_year,
                            target_month=target_month,
                            total_accounts_balance=total_accounts_balance,
                            budget_by_cat=budget_by_cat,
                        ),
                    )
                finally:
                    _save_session.close()
        except Exception as e:
            logger.warning(f"Salvataggio report mensile nel DB fallito: {e}")

    if telegram_connected:
        logger.info("▶ Step 6/7: Invio report su Telegram")
        telegram = TelegramClient(chat_id=chat_id)
        # Invia prima i grafici
        for path in chart_paths:
            try:
                await telegram.send_photo(photo_path=path)
            except Exception as e:
                logger.error(f"Errore durante l'invio del grafico {path}: {e}")
        # Poi invia il testo
        await telegram.send_report(final_report)
        logger.info("✅ Report inviato con successo su Telegram!")
    else:
        logger.info("▶ Step 6/7: Utente solo-webapp, invio Telegram saltato")

    if report_share_token and chat_id:
        notify_webapp_report(_save_store, chat_id, "monthly", report.current_month.label, report_share_token)
        _save_store.record_report_event(chat_id, report_share_token, "monthly", "generated", "job")

    # Cleanup delle immagini temporanee
    for path in chart_paths:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            logger.warning(f"Impossibile eliminare file temporaneo {path}: {e}")

    return report_share_token or None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    setup_logging()
    logger = logging.getLogger("financial_agent.main")

    parser = argparse.ArgumentParser(
        description="Agente Analista & Predittore Finanziario"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Usa dati mock, mostra report a schermo senza chiamare API",
    )
    parser.add_argument(
        "--debug-data",
        action="store_true",
        help="Usa dati REALI, salva in locale e mostra prompt senza chiamare API",
    )
    parser.add_argument(
        "--month",
        type=str,
        default=None,
        metavar="YYYY-MM",
        help="Mese da analizzare (default: mese scorso). Formato: 2026-01",
    )
    args = parser.parse_args()

    # Determina il mese target
    if args.month:
        try:
            dt = datetime.strptime(args.month, "%Y-%m")
            target_year, target_month = dt.year, dt.month
        except ValueError:
            logger.error("Formato --month non valido. Usa YYYY-MM (es. 2026-01)")
            sys.exit(1)
    else:
        target_year, target_month = _resolve_default_target_month(date.today())

    if not args.dry_run:
        try:
            Config.validate()
        except EnvironmentError as e:
            logger.error(str(e))
            logger.error("Copia .env.example in .env e inserisci le tue credenziali.")
            sys.exit(1)

    chat_id = os.environ.get("TELEGRAM_CHAT_ID") or Config.TELEGRAM_CHAT_ID
    asyncio.run(run_agent(target_year, target_month, dry_run=args.dry_run, debug_data=args.debug_data, chat_id=chat_id))


if __name__ == "__main__":
    main()
