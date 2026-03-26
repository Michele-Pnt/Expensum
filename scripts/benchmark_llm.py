"""
scripts/benchmark_llm.py — Confronto performance Gemini vs Ollama.

Esegue la stessa analisi con entrambi i provider (usando dati mock)
e confronta:
  - Tempo di risposta
  - Lunghezza del report
  - Salva i report in file per confronto manuale side-by-side

Uso:
  cd Finance-Agents
  python scripts/benchmark_llm.py [--month YYYY-MM]
"""

import sys
import os
import time
import logging

# Aggiungi la root del progetto al PATH
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config, setup_logging
from src.data_processor import DataProcessor
from src.forecaster import Forecaster
from datetime import date

setup_logging()
logger = logging.getLogger("benchmark")

# --- Dati mock (copiati da main.py) ---
MOCK_TRANSACTIONS = [
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

MOCK_ACCOUNTS = [{"name": "Mock Bank", "current_balance": 1500.0}]


def prepare_data(target_year=2026, target_month=2):
    """Prepara i dati di test per il benchmark."""
    processor = DataProcessor()
    report = processor.process(MOCK_TRANSACTIONS, target_year, target_month)
    data_text = processor.to_prompt_text(report)

    if target_month == 12:
        next_month, next_year = 1, target_year + 1
    else:
        next_month, next_year = target_month + 1, target_year

    forecaster = Forecaster()
    forecast = forecaster.predict(report, next_month, next_year)
    forecast_text = forecast.to_prompt_text()

    total_accounts_balance = sum(a.get("current_balance", 0.0) for a in MOCK_ACCOUNTS)
    accounts_text = f"Conti Correnti attuali:\nTotale saldi conti (dato certo): €{total_accounts_balance:.2f}\n"
    for acc in MOCK_ACCOUNTS:
        accounts_text += f"- {acc['name']}: €{acc['current_balance']:.2f}\n"

    return {
        "data_text": data_text,
        "accounts_text": accounts_text,
        "forecast_text": forecast_text,
        "current_month_label": report.current_month.label,
        "next_month_label": forecast.target_month_label,
        "total_income": "0.00",
        "total_amount": f"{report.current_month.total:.2f}",
        "total_accounts_balance": f"{total_accounts_balance:.2f}",
        "net_savings": "n/d",
    }


def benchmark_provider(provider_name, client_class, kwargs, runs=1):
    """Esegue il benchmark per un singolo provider."""
    results = []
    for i in range(runs):
        print(f"\n{'─' * 40}")
        print(f"  {provider_name} — Run {i + 1}/{runs}")
        print(f"{'─' * 40}")
        try:
            client = client_class()
            start = time.time()
            report = client.analyze_and_generate_report(**kwargs)
            elapsed = time.time() - start
            results.append({
                "run": i + 1,
                "time_s": elapsed,
                "length": len(report),
                "report": report,
                "error": None,
            })
            print(f"  ✅ Completato in {elapsed:.1f}s ({len(report)} caratteri)")
        except Exception as e:
            results.append({
                "run": i + 1,
                "time_s": None,
                "length": 0,
                "report": None,
                "error": str(e),
            })
            print(f"  ❌ Errore: {e}")
    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Benchmark Gemini vs Ollama")
    parser.add_argument("--runs", type=int, default=1, help="Numero di run per provider")
    parser.add_argument("--only", choices=["gemini", "ollama"], help="Testa solo un provider")
    args = parser.parse_args()

    print("=" * 60)
    print("🏁 BENCHMARK LLM: Gemini vs Ollama")
    print("=" * 60)

    kwargs = prepare_data()
    results = {}

    # --- Gemini ---
    if args.only != "ollama":
        if Config.GEMINI_API_KEY:
            from src.gemini_client import GeminiClient
            results["gemini"] = benchmark_provider("Gemini", GeminiClient, kwargs, runs=args.runs)
        else:
            print("\n⚠️  GEMINI_API_KEY non configurata, salto Gemini.")

    # --- Ollama ---
    if args.only != "gemini":
        from src.ollama_client import OllamaClient
        results["ollama"] = benchmark_provider("Ollama", OllamaClient, kwargs, runs=args.runs)

    # --- Risultati ---
    print("\n" + "=" * 60)
    print("📊 RISULTATI BENCHMARK")
    print("=" * 60)

    output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
    os.makedirs(output_dir, exist_ok=True)

    for provider, runs_data in results.items():
        successful = [r for r in runs_data if r["error"] is None]
        if successful:
            avg_time = sum(r["time_s"] for r in successful) / len(successful)
            avg_len = sum(r["length"] for r in successful) / len(successful)
            print(f"\n  {provider.upper()}:")
            print(f"    Tempo medio:     {avg_time:.1f}s")
            print(f"    Lunghezza media: {avg_len:.0f} caratteri")
            print(f"    Successi:        {len(successful)}/{len(runs_data)}")

            # Salva l'ultimo report per confronto
            report_path = os.path.join(output_dir, f"benchmark_report_{provider}.md")
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(f"# Report {provider.upper()} (tempo: {successful[-1]['time_s']:.1f}s)\n\n")
                f.write(successful[-1]["report"])
            print(f"    Report salvato:  {report_path}")
        else:
            print(f"\n  {provider.upper()}: ❌ Tutti i run falliti")

    print("\n" + "=" * 60)
    print("✅ Benchmark completato!")
    print(f"Confronta i report in: {output_dir}/")
    print("=" * 60)


if __name__ == "__main__":
    main()
