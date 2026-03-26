"""
main.py — Orchestratore principale dell'Agente Analista & Predittore Finanziario.

Pipeline:
  1. Estrazione dati da Notion (con paginazione e retry)
  2. Elaborazione statistica: consuntivo, trend, anomalie
  3. Previsione statistica mese successivo
  4. Analisi AI con Gemini 2.5 Flash (Chain of Thought)
  5. Costruzione report Markdown
  6. Invio report su Telegram

Modalità:
  --dry-run     Usa dati di test fittizi, mostra report a schermo senza
                inviare su Telegram e senza chiamare Gemini.
  --debug-data  Scarica dati REALI da Notion ma analizza solo in locale. Stampa
                il testo esatto da inviare al prompt di Gemini e un JSON con
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
from src.notion_client import NotionExpenseClient
from src.data_processor import DataProcessor
from src.forecaster import Forecaster
from src.gemini_client import GeminiClient
from src.ollama_client import OllamaClient
from src.telegram_client import TelegramClient
from src.report_builder import ReportBuilder
from src.chart_generator import ChartGenerator


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


# ---------------------------------------------------------------------------
# Funzione principale
# ---------------------------------------------------------------------------

async def run_agent(target_year: int, target_month: int, dry_run: bool, debug_data: bool = False) -> None:
    """Esegue la pipeline completa dell'agente finanziario."""
    logger = logging.getLogger("financial_agent.main")
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
        logger.info(f"  [DRY-RUN] Usando {len(transactions)} transazioni mock")
    else:
        notion = NotionExpenseClient()
        months_back = Config.HISTORY_MONTHS + 1
        start_year = target_year
        start_month = target_month - months_back
        while start_month <= 0:
            start_month += 12
            start_year -= 1
        start_date = date(start_year, start_month, 1)
        end_date = date(target_year, target_month, monthrange(target_year, target_month)[1])

        transactions = notion.fetch_all_transactions(
            start_date=start_date, end_date=end_date
        )

        logger.info("▶ Step 1b/7: Estrazione Monthly Balance (Risparmio Netto)")
        monthly_balances = notion.fetch_monthly_balances(
            start_date=start_date, end_date=end_date
        )

        logger.info("▶ Step 1c/7: Estrazione Entrate e Conti Correnti")
        incomes = notion.fetch_income(start_date=start_date, end_date=end_date)
        accounts = notion.fetch_accounts()
        if accounts:
            accounts_log = ", ".join(
                f"{acc.get('name', 'Sconosciuto')}=€{float(acc.get('current_balance', 0.0)):.2f}"
                for acc in accounts
            )
            logger.info(f"Bilanci account letti da Notion: {accounts_log}")
        else:
            logger.warning("Nessun account valido letto da Notion.")

    if not transactions:
        logger.error("Nessuna transazione trovata. Uscita.")
        return

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
        return

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
    llm_provider = Config.LLM_PROVIDER
    logger.info(f"▶ Step 4/7: Analisi AI con provider '{llm_provider}'")
    net_savings_str = f"€{current_mb['net_savings']:.2f}" if current_mb else "n/d"
    if dry_run:
        logger.info(f"  [DRY-RUN] Salto {llm_provider}, uso report statistico locale")
        final_report = ReportBuilder.build_fallback_report(report, forecast, accounts=accounts)
    else:
        try:
            if llm_provider == "ollama":
                llm_client = OllamaClient()
                logger.info(f"  Usando Ollama con modello {Config.OLLAMA_MODEL}")
            else:
                llm_client = GeminiClient()
                logger.info(f"  Usando Gemini con modello {Config.GEMINI_MODEL}")

            llm_start = time.time()
            final_report = llm_client.analyze_and_generate_report(
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
            llm_elapsed = time.time() - llm_start
            logger.info(f"  ⏱️ Tempo inferenza {llm_provider}: {llm_elapsed:.1f}s")
        except Exception as e:
            logger.error(f"Errore {llm_provider}: {e}. Uso fallback statistico.")
            final_report = ReportBuilder.build_fallback_report(report, forecast, accounts=accounts)

    final_report = _insert_accounts_section_near_summary(final_report, accounts)

    # 5. LOG DEL REPORT
    logger.info("▶ Step 5/7: Report generato")
    if dry_run:
        print("\n" + "=" * 60)
        print("📱 ANTEPRIMA REPORT TELEGRAM")
        print("=" * 60)
        print(final_report)
        print("=" * 60 + "\n")
        logger.info("[DRY-RUN] Report mostrato a schermo. Nessun messaggio inviato.")
        return

    # 6. INVIO TELEGRAM
    logger.info("▶ Step 6/7: Invio report su Telegram")
    telegram = TelegramClient()
    
    # Invia prima i grafici
    for path in chart_paths:
        try:
            await telegram.send_photo(photo_path=path)
        except Exception as e:
            logger.error(f"Errore durante l'invio del grafico {path}: {e}")
            
    # Poi invia il testo
    await telegram.send_report(final_report)
    logger.info("✅ Report inviato con successo su Telegram!")
    
    # Cleanup delle immagini temporanee
    for path in chart_paths:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            logger.warning(f"Impossibile eliminare file temporaneo {path}: {e}")


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
        today = date.today()
        if today.month == 1:
            target_month, target_year = 12, today.year - 1
        else:
            target_month, target_year = today.month - 1, today.year

    if not args.dry_run:
        try:
            Config.validate()
        except EnvironmentError as e:
            logger.error(str(e))
            logger.error("Copia .env.example in .env e inserisci le tue credenziali.")
            sys.exit(1)

    asyncio.run(run_agent(target_year, target_month, dry_run=args.dry_run, debug_data=args.debug_data))


if __name__ == "__main__":
    main()
