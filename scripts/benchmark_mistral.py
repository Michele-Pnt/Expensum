"""
scripts/benchmark_mistral.py — Benchmark Mistral Small 3.1 vs Gemini 2.5 Flash.

Testa due task reali del bot:
  1. Parsing spese/entrate (testo libero → JSON strutturato)
  2. Analisi trend mensile (dati aggregati → report Markdown)

Stack target (da architecture decision):
  - Parsing testo/speech → mistral-small-latest (Mistral Small 3.1)
  - Analisi trend        → mistral-small-latest (Mistral Small 3.1)

Uso:
  cd Finance-Agents
  # Aggiungi MISTRAL_API_KEY al .env prima di eseguire
  python scripts/benchmark_mistral.py
  python scripts/benchmark_mistral.py --only parsing
  python scripts/benchmark_mistral.py --only analisi
  python scripts/benchmark_mistral.py --no-gemini        # solo Mistral
  python scripts/benchmark_mistral.py --delay-ms 6000    # pausa tra chiamate (Gemini free = 10 RPM)
"""

import sys
import os
import time
import json
import argparse
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from rich import box
from rich.rule import Rule
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console(record=True)

# ---------------------------------------------------------------------------
# SYSTEM PROMPT (identico a expense_parser.py)
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = """Sei un assistente finanziario. Il tuo compito è estrarre informazioni finanziarie da messaggi scritti in modo informale in italiano. Devi capire dal contesto se si tratta di un'uscita (spesa) o di un'entrata (stipendio, regalo, rimborso, bonifico ricevuto).

REGOLE TASSATIVE:
1. Rispondi SOLO con un oggetto JSON valido, senza altro testo.
2. Il JSON deve avere esattamente questi 6 campi:
   - "type": stringa. Deve essere ASSOLUTAMENTE "expense" (se è una spesa/uscita) oppure "income" (se è un introito/entrata).
   - "amount": numero (float). DEVI interpretare anche i numeri a parole. Esempi: "150 mila euro" -> 150000.0, "cento euro" -> 100.0, "15" -> 15.0. Se non specificato, metti null.
   - "category": stringa. RIGOROSAMENTE UNA SOLA voce dalla lista fornita di Categorie. Se `type` è "income", metti null.
   - "income_type": stringa. SOLO se `type` è "income": scegli OBBLIGATORIAMENTE una voce tra [Stipendio, Bonus, Rimborso, Regalo, Cashback, Dividendi, Affitto, Interessi, Mance, Ripetizioni, Paghetta]. Se `type` è "expense", metti null.
   - "name": stringa, breve descrizione (es. "Pizza amici", "Stipendio", "Busta Nonna"). Max 3 parole.
   - "date": stringa in formato "YYYY-MM-DD". Se non specificata, usa la data di oggi fornita.
3. Se il messaggio NON sembra una transazione finanziaria, rispondi con: {"error": "not_expense"}
4. NON inventare importi.

ESEMPI SPESE:
- "ieri pizza 25€" → {"type": "expense", "amount": 25.0, "category": "Ristoranti", "income_type": null, "name": "Pizza", "date": "2026-03-20"}
- "netflix" → {"type": "expense", "amount": null, "category": "Abbonamenti", "income_type": null, "name": "Netflix", "date": "2026-03-21"}
- "ho speso 67 euro al supermercato" → {"type": "expense", "amount": 67.0, "category": "Supermercato", "income_type": null, "name": "Spesa supermercato", "date": "2026-03-21"}

ESEMPI ENTRATE:
- "ho ricevuto lo stipendio 1500" → {"type": "income", "amount": 1500.0, "category": null, "income_type": "Stipendio", "name": "Stipendio", "date": "2026-03-22"}
- "rimborso spese 120€" → {"type": "income", "amount": 120.0, "category": null, "income_type": "Rimborso", "name": "Rimborso spese", "date": "2026-03-22"}
- "regalo compleanno 50 euro" → {"type": "income", "amount": 50.0, "category": null, "income_type": "Regalo", "name": "Regalo compleanno", "date": "2026-03-22"}
"""

_ANALYSIS_PROMPT_TEMPLATE = """
Sei un Senior Financial Analyst specializzato in finanza personale.
Hai ricevuto i seguenti dati strutturati sulle spese mensili di un cliente:

--- DATI ANALIZZATI ---
{data_block}

--- STATO DEI CONTI ---
{accounts_block}

--- DATI PREVISIONE ---
{forecast_block}

# OUTPUT RICHIESTO
Produci ESATTAMENTE il seguente report in formato Markdown per Telegram.
USA questi emoji esatti nelle intestazioni.
NON inventare numeri non presenti nei dati.
NON ricalcolare il "Denaro sui conti": usa ESATTAMENTE il valore già fornito.
Usa *grassetto* solo con singolo asterisco (esempio: *testo*), MAI con doppio asterisco.

---

📊 *Riepilogo {current_month}*
Spesa totale: *€{total_amount}*
Entrate totali: *€{total_income}*
🏦 Denaro sui conti: *€{total_accounts_balance}*
Risparmio mensile: *{net_savings}*

*Spesa per categorie:*
[Lista completa di tutte le categorie di spesa del mese attuale con relativo importo e percentuale]

---

📉 *Analisi e Confronto Trend*
- *Spese*: [Confronto testuale e numerico del totale speso: mese corrente vs storico]
- *Entrate*: [Confronto entrate mese corrente vs storico o commento sulla stabilità]
- *Risparmio*: [Confronto del risparmio mensile corrente vs i mesi storici]
- *Categorie*: [Confronto spese per categoria, evidenziando sforamenti o virtuosismi]

---

🔮 *Previsione {next_month}*

Stima ottimistica: *€[valore]*
Stima base: *€[valore]*
Stima pessimistica: *€[valore]*

[Spiega brevemente i fattori principali che influenzano la previsione]

---

💡 *3 Consigli Azionabili*

Basati ESCLUSIVAMENTE sulle anomalie e i trend nei dati:

1️⃣ [Consiglio specifico con numero reale dai dati]
2️⃣ [Consiglio specifico con numero reale dai dati]
3️⃣ [Consiglio specifico con numero reale dai dati]

---
_Report generato automaticamente dall'Agente Finanziario 🤖_
"""

# ---------------------------------------------------------------------------
# MESSAGGI RAW — stringhe grezze come le manda un utente su Telegram
# Nessun expected output: si valuta l'output visivamente side-by-side.
# ---------------------------------------------------------------------------
_CATEGORIES = [
    "Affitto", "Supermercato", "Abbonamenti", "Ristoranti", "Trasporti",
    "Salute", "Abbigliamento", "Utility", "Intrattenimento", "Regali",
    "Istruzione", "Sport", "Viaggi", "Tecnologia", "Altro",
]

_RAW_MESSAGES: list[str] = [
    # basilari
    "pizza 15",
    "benzina",
    "affitto",
    # colloquiali / sporchi
    "ieri sera mangiato fuori tipo 40 con i ragazzi",
    "ho preso caffè e cornetto stamattina 2.70",
    "spesa esselunga ieri circa 90",
    "sushi con marta venerdì 55€",
    # importo ambiguo o assente
    "100 euro",
    "trasferito 200",
    "netflix",
    # income
    "arrivato lo stipendio",
    "bonus 300€",
    "mi hanno rimborsato il viaggio 120",
    # typo / forma dialettale
    "stipentio 1800",
    "mutuo marzo 800",
    # non transazione
    "ok grazie",
    "domani devo pagare l'affitto",
    # edge case
    "farmacia ieri 23.50",
    "ricarica telefono 15",
    "palestra mensile",
]

# ---------------------------------------------------------------------------
# MOCK DATA — 6 mesi di storico realistico (Sep 2025 – Feb 2026)
#
# Caratteristiche:
#  - Affitto fisso 700€/mese
#  - Abbonamenti fissi (Netflix 13.99 + Spotify 9.99 = 23.98€/mese)
#  - Supermercato variabile 160-230€ (picco Natale)
#  - Ristoranti variabile 80-220€ (sforamento a Febbraio: 220€ vs media 115€)
#  - Utility più alta in inverno (Ott-Feb)
#  - Abbigliamento: saldi estivi Ott, saldi invernali Gen
#  - Viaggi: weekend a Novembre
#  - Salute: sporadica
#  - Stipendio 1800€/mese fisso + bonus una tantum a Dicembre
# ---------------------------------------------------------------------------

_MOCK_TRANSACTIONS: list[dict] = [
    # ── SETTEMBRE 2025 ────────────────────────────────────────────────────
    {"date": date(2025, 9,  1), "category": "Affitto",         "name": "Affitto Settembre",   "amount": 700.00},
    {"date": date(2025, 9,  3), "category": "Supermercato",    "name": "Esselunga",            "amount": 92.40},
    {"date": date(2025, 9,  5), "category": "Abbonamenti",     "name": "Netflix",              "amount": 13.99},
    {"date": date(2025, 9,  5), "category": "Abbonamenti",     "name": "Spotify",              "amount":  9.99},
    {"date": date(2025, 9,  8), "category": "Ristoranti",      "name": "Pranzo rientro",       "amount": 38.00},
    {"date": date(2025, 9, 10), "category": "Trasporti",       "name": "Abbonamento Metro",    "amount": 35.00},
    {"date": date(2025, 9, 14), "category": "Supermercato",    "name": "Conad",                "amount": 74.60},
    {"date": date(2025, 9, 18), "category": "Ristoranti",      "name": "Cena amici",           "amount": 55.00},
    {"date": date(2025, 9, 20), "category": "Utility",         "name": "Bolletta Luce",        "amount": 62.00},
    {"date": date(2025, 9, 25), "category": "Salute",          "name": "Farmacia",             "amount": 18.90},
    {"date": date(2025, 9, 28), "category": "Intrattenimento", "name": "Concerti",             "amount": 45.00},
    # totale Set: 1145.88

    # ── OTTOBRE 2025 ──────────────────────────────────────────────────────
    {"date": date(2025, 10,  1), "category": "Affitto",        "name": "Affitto Ottobre",      "amount": 700.00},
    {"date": date(2025, 10,  3), "category": "Supermercato",   "name": "Esselunga",            "amount": 88.20},
    {"date": date(2025, 10,  5), "category": "Abbonamenti",    "name": "Netflix",              "amount": 13.99},
    {"date": date(2025, 10,  5), "category": "Abbonamenti",    "name": "Spotify",              "amount":  9.99},
    {"date": date(2025, 10,  8), "category": "Ristoranti",     "name": "Pizzeria",             "amount": 32.00},
    {"date": date(2025, 10, 10), "category": "Trasporti",      "name": "Abbonamento Metro",    "amount": 35.00},
    {"date": date(2025, 10, 12), "category": "Abbigliamento",  "name": "Saldi autunnali",      "amount": 145.00},
    {"date": date(2025, 10, 16), "category": "Supermercato",   "name": "Conad",                "amount": 71.50},
    {"date": date(2025, 10, 20), "category": "Utility",        "name": "Bolletta Luce",        "amount": 74.00},
    {"date": date(2025, 10, 22), "category": "Utility",        "name": "Bolletta Gas",         "amount": 48.00},
    {"date": date(2025, 10, 25), "category": "Ristoranti",     "name": "Aperitivo",            "amount": 42.00},
    {"date": date(2025, 10, 28), "category": "Salute",         "name": "Visita medica",        "amount": 50.00},
    # totale Ott: 1309.68

    # ── NOVEMBRE 2025 ─────────────────────────────────────────────────────
    {"date": date(2025, 11,  1), "category": "Affitto",        "name": "Affitto Novembre",     "amount": 700.00},
    {"date": date(2025, 11,  3), "category": "Supermercato",   "name": "Esselunga",            "amount": 95.80},
    {"date": date(2025, 11,  5), "category": "Abbonamenti",    "name": "Netflix",              "amount": 13.99},
    {"date": date(2025, 11,  5), "category": "Abbonamenti",    "name": "Spotify",              "amount":  9.99},
    {"date": date(2025, 11,  7), "category": "Viaggi",         "name": "Weekend Firenze",      "amount": 210.00},
    {"date": date(2025, 11, 10), "category": "Trasporti",      "name": "Abbonamento Metro",    "amount": 35.00},
    {"date": date(2025, 11, 14), "category": "Supermercato",   "name": "Conad",                "amount": 68.40},
    {"date": date(2025, 11, 18), "category": "Ristoranti",     "name": "Cena team",            "amount": 78.00},
    {"date": date(2025, 11, 21), "category": "Utility",        "name": "Bolletta Luce",        "amount": 82.00},
    {"date": date(2025, 11, 22), "category": "Utility",        "name": "Bolletta Gas",         "amount": 65.00},
    {"date": date(2025, 11, 26), "category": "Intrattenimento","name": "Teatro",               "amount": 30.00},
    # totale Nov: 1388.18

    # ── DICEMBRE 2025 — Natale, spese extra ───────────────────────────────
    {"date": date(2025, 12,  1), "category": "Affitto",        "name": "Affitto Dicembre",     "amount": 700.00},
    {"date": date(2025, 12,  3), "category": "Supermercato",   "name": "Spesa Natale",         "amount": 152.00},
    {"date": date(2025, 12,  5), "category": "Abbonamenti",    "name": "Netflix",              "amount": 13.99},
    {"date": date(2025, 12,  5), "category": "Abbonamenti",    "name": "Spotify",              "amount":  9.99},
    {"date": date(2025, 12,  8), "category": "Regali",         "name": "Regali Natale",        "amount": 280.00},
    {"date": date(2025, 12, 10), "category": "Trasporti",      "name": "Abbonamento Metro",    "amount": 35.00},
    {"date": date(2025, 12, 14), "category": "Supermercato",   "name": "Conad",                "amount": 88.50},
    {"date": date(2025, 12, 18), "category": "Ristoranti",     "name": "Cena Natale aziendale","amount": 95.00},
    {"date": date(2025, 12, 21), "category": "Utility",        "name": "Bolletta Luce",        "amount": 110.00},
    {"date": date(2025, 12, 22), "category": "Utility",        "name": "Bolletta Gas",         "amount": 88.00},
    {"date": date(2025, 12, 24), "category": "Ristoranti",     "name": "Cena Vigilia",         "amount": 65.00},
    {"date": date(2025, 12, 27), "category": "Abbigliamento",  "name": "Saldi invernali",      "amount": 118.00},
    # totale Dic: 1755.48

    # ── GENNAIO 2026 — post-feste, spese ridotte ──────────────────────────
    {"date": date(2026, 1,  1), "category": "Affitto",         "name": "Affitto Gennaio",      "amount": 700.00},
    {"date": date(2026, 1,  5), "category": "Abbonamenti",     "name": "Netflix",              "amount": 13.99},
    {"date": date(2026, 1,  5), "category": "Abbonamenti",     "name": "Spotify",              "amount":  9.99},
    {"date": date(2026, 1,  7), "category": "Supermercato",    "name": "Esselunga",            "amount": 85.30},
    {"date": date(2026, 1, 10), "category": "Trasporti",       "name": "Abbonamento Metro",    "amount": 35.00},
    {"date": date(2026, 1, 12), "category": "Ristoranti",      "name": "Pranzo fuori",         "amount": 28.00},
    {"date": date(2026, 1, 16), "category": "Supermercato",    "name": "Conad",                "amount": 62.10},
    {"date": date(2026, 1, 20), "category": "Utility",         "name": "Bolletta Luce",        "amount": 95.00},
    {"date": date(2026, 1, 22), "category": "Utility",         "name": "Bolletta Gas",         "amount": 72.00},
    {"date": date(2026, 1, 25), "category": "Salute",          "name": "Farmacia",             "amount": 22.50},
    {"date": date(2026, 1, 28), "category": "Intrattenimento", "name": "Cinema",               "amount": 15.00},
    # totale Gen: 1138.88

    # ── FEBBRAIO 2026 — mese target: sforamento ristoranti ────────────────
    {"date": date(2026, 2,  1), "category": "Affitto",         "name": "Affitto Febbraio",     "amount": 700.00},
    {"date": date(2026, 2,  3), "category": "Supermercato",    "name": "Esselunga",            "amount": 91.20},
    {"date": date(2026, 2,  5), "category": "Abbonamenti",     "name": "Netflix",              "amount": 13.99},
    {"date": date(2026, 2,  5), "category": "Abbonamenti",     "name": "Spotify",              "amount":  9.99},
    {"date": date(2026, 2,  8), "category": "Ristoranti",      "name": "Pizzeria da Mario",    "amount": 48.00},
    {"date": date(2026, 2, 10), "category": "Trasporti",       "name": "Abbonamento Metro",    "amount": 35.00},
    {"date": date(2026, 2, 12), "category": "Supermercato",    "name": "Conad",                "amount": 67.80},
    {"date": date(2026, 2, 14), "category": "Ristoranti",      "name": "Cena San Valentino",   "amount": 85.00},
    {"date": date(2026, 2, 15), "category": "Salute",          "name": "Farmacia",             "amount": 31.50},
    {"date": date(2026, 2, 18), "category": "Ristoranti",      "name": "Aperitivo amici",      "amount": 52.00},
    {"date": date(2026, 2, 20), "category": "Abbigliamento",   "name": "Zara",                 "amount": 94.00},
    {"date": date(2026, 2, 22), "category": "Supermercato",    "name": "Esselunga",            "amount": 78.40},
    {"date": date(2026, 2, 25), "category": "Utility",         "name": "Bolletta Luce",        "amount": 88.00},
    {"date": date(2026, 2, 26), "category": "Ristoranti",      "name": "Cena compleanno",      "amount": 125.00},
    {"date": date(2026, 2, 28), "category": "Intrattenimento", "name": "Evento",               "amount": 35.00},
    # totale Feb: 1554.88
]

# Entrate mensili (stipendio fisso + bonus Dicembre)
_MOCK_INCOMES: list[dict] = [
    {"date": date(2025, 9, 27),  "name": "Stipendio Settembre", "amount": 1800.00, "income_type": "Stipendio"},
    {"date": date(2025, 10, 27), "name": "Stipendio Ottobre",   "amount": 1800.00, "income_type": "Stipendio"},
    {"date": date(2025, 11, 27), "name": "Stipendio Novembre",  "amount": 1800.00, "income_type": "Stipendio"},
    {"date": date(2025, 12, 27), "name": "Stipendio Dicembre",  "amount": 1800.00, "income_type": "Stipendio"},
    {"date": date(2025, 12, 20), "name": "Bonus fine anno",     "amount":  500.00, "income_type": "Bonus"},
    {"date": date(2026, 1, 27),  "name": "Stipendio Gennaio",   "amount": 1800.00, "income_type": "Stipendio"},
    {"date": date(2026, 2, 27),  "name": "Stipendio Febbraio",  "amount": 1800.00, "income_type": "Stipendio"},
]

# Valori attesi per scoring report (derivati dai mock sopra)
_MOCK_EXPECTED = {
    "total_expenses": 1554.88,          # totale Feb 2026
    "total_income": 1800.00,            # stipendio Feb
    "top_category": "Affitto",          # 700€ = 45%
    "anomaly_category": "Ristoranti",   # 310€ vs media storica ~65€
    "hist_avg_approx": 1347.42,         # media Set-Gen (5 mesi)
    "base_forecast_range": (1100, 1600),# range plausibile per Mar 2026
}

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# SCORING REPORT — metriche oggettive per valutare il report di analisi
# ---------------------------------------------------------------------------
# Punteggio massimo: 14 punti
#
#  Struttura (4 pt)  — ogni sezione emoji presente vale 1 punto
#  Accuracy  (4 pt)  — totale spese citato, top categoria, anomalia Ristoranti,
#                       income citato
#  Formato   (2 pt)  — nessun ** (grassetto Markdown non Telegram),
#                       nessun ### (header Markdown)
#  Consigli  (3 pt)  — ogni consiglio contiene almeno un numero/€ reale
#  Forecast  (1 pt)  — stima base nel range plausibile

def _score_report(report_text: str) -> tuple[int, dict[str, int], list[str]]:
    """
    Valuta il report di analisi trend.

    Returns:
        (punteggio_totale, {criterio: punteggio}, [note])
    """
    import re
    scores: dict[str, int] = {}
    notes: list[str] = []
    exp = _MOCK_EXPECTED

    # ── Struttura ───────────────────────────────────────────────────────────
    for emoji, label in [("📊", "riepilogo"), ("📉", "trend"), ("🔮", "forecast"), ("💡", "consigli")]:
        scores[f"sez_{label}"] = 1 if emoji in report_text else 0
        if emoji not in report_text:
            notes.append(f"sezione '{emoji} {label}' assente")

    # ── Accuratezza numerica ────────────────────────────────────────────────
    # Totale spese: accetta formati "1554", "1.554", "1554,88", "1554.88"
    total_str = f"{exp['total_expenses']:.2f}"          # "1554.88"
    total_alt = f"{exp['total_expenses']:.0f}"          # "1554"
    scores["acc_totale"] = 1 if (total_str in report_text or total_alt in report_text) else 0
    if not scores["acc_totale"]:
        notes.append(f"totale spese {total_str} non trovato nel report")

    # Top categoria (Affitto)
    scores["acc_top_cat"] = 1 if exp["top_category"].lower() in report_text.lower() else 0
    if not scores["acc_top_cat"]:
        notes.append(f"categoria '{exp['top_category']}' non citata")

    # Anomalia ristoranti citata
    scores["acc_anomalia"] = 1 if exp["anomaly_category"].lower() in report_text.lower() else 0
    if not scores["acc_anomalia"]:
        notes.append(f"anomalia '{exp['anomaly_category']}' non citata")

    # Income citato (almeno "1800" o "stipendio")
    scores["acc_income"] = 1 if ("1800" in report_text or "stipendio" in report_text.lower()) else 0
    if not scores["acc_income"]:
        notes.append("income/stipendio non citato")

    # ── Formato Telegram ────────────────────────────────────────────────────
    scores["fmt_no_double_asterisk"] = 0 if "**" in report_text else 1
    if "**" in report_text:
        count = report_text.count("**")
        notes.append(f"grassetto doppio ** trovato ({count} occorrenze) — non valido per Telegram")

    scores["fmt_no_md_headers"] = 0 if re.search(r"^#{1,3}\s", report_text, re.MULTILINE) else 1
    if not scores["fmt_no_md_headers"]:
        notes.append("header Markdown # trovati — non validi per Telegram")

    # ── Consigli con numeri reali ────────────────────────────────────────────
    # Trova la sezione consigli e verifica che i 3 consigli contengano cifre
    consigli_section = ""
    if "💡" in report_text:
        consigli_section = report_text.split("💡", 1)[1]
    has_number = lambda s: bool(re.search(r"€\s*\d+|\d+[.,]\d+|\d{2,}", s))
    for i, emoji in enumerate(["1️⃣", "2️⃣", "3️⃣"]):
        if emoji in consigli_section:
            tip_text = consigli_section.split(emoji, 1)[1].split("\n")[0]
            scores[f"consiglio_{i+1}"] = 1 if has_number(tip_text) else 0
            if not scores[f"consiglio_{i+1}"]:
                notes.append(f"consiglio {i+1} senza numeri reali: '{tip_text[:60]}'")
        else:
            scores[f"consiglio_{i+1}"] = 0
            notes.append(f"consiglio {emoji} non trovato")

    # ── Previsione nel range plausibile ──────────────────────────────────────
    lo, hi = exp["base_forecast_range"]
    forecast_nums = re.findall(r"€\s*(\d{3,4}(?:[.,]\d{2})?)", report_text)
    in_range = any(lo <= float(n.replace(",", ".")) <= hi for n in forecast_nums)
    scores["forecast_range"] = 1 if in_range else 0
    if not in_range:
        notes.append(f"nessuna stima nel range €{lo}-{hi} (found: {forecast_nums[:5]})")

    total = sum(scores.values())
    return total, scores, notes


def _extract_json(text: str) -> dict | None:
    """Estrae JSON dal testo grezzo (supporta blocchi ```json```)."""
    import re
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None


def _score_parse(result: dict | None, exp_type: str | None, exp_amount: float | None,
                 exp_category: str | None, exp_income_type: str | None) -> tuple[int, list[str]]:
    """
    Restituisce (punteggio 0-4, lista errori).
    1 punto per: type, amount, category, income_type corretti.
    """
    score = 0
    errors = []

    if exp_type is None:
        # Aspettiamo {"error": "not_expense"} o None
        if result is None or "error" in result:
            score += 4
        else:
            errors.append("doveva essere not_expense")
        return score, errors

    if result is None or "error" in result:
        errors.append("JSON non estratto o not_expense inatteso")
        return 0, errors

    # type
    got_type = result.get("type")
    if got_type == exp_type:
        score += 1
    else:
        errors.append(f"type: atteso={exp_type} got={got_type}")

    # amount
    got_amount = result.get("amount")
    if exp_amount is None and got_amount is None:
        score += 1
    elif exp_amount is not None and got_amount is not None:
        if abs(float(got_amount) - exp_amount) < 0.01:
            score += 1
        else:
            errors.append(f"amount: atteso={exp_amount} got={got_amount}")
    else:
        errors.append(f"amount: atteso={exp_amount} got={got_amount}")

    # category
    got_cat = result.get("category")
    if exp_category is None and got_cat is None:
        score += 1
    elif exp_category and got_cat and exp_category.lower() == got_cat.lower():
        score += 1
    else:
        errors.append(f"category: atteso={exp_category} got={got_cat}")

    # income_type
    got_it = result.get("income_type")
    if exp_income_type is None and got_it is None:
        score += 1
    elif exp_income_type and got_it and exp_income_type.lower() == got_it.lower():
        score += 1
    else:
        errors.append(f"income_type: atteso={exp_income_type} got={got_it}")

    return score, errors


# ---------------------------------------------------------------------------
# PROVIDERS
# ---------------------------------------------------------------------------

class MistralParser:
    """Parsing spese con Mistral Small 3.1."""

    def __init__(self):
        from mistralai.client.sdk import Mistral as MistralSDK
        from mistralai.client.models import ResponseFormat
        self._client = MistralSDK(api_key=Config.MISTRAL_API_KEY)
        self._model = Config.MISTRAL_SMALL_MODEL
        self._ResponseFormat = ResponseFormat

    def parse(self, message: str) -> tuple[dict | None, float]:
        today = date.today().isoformat()
        cats = ", ".join(_CATEGORIES)
        user_prompt = (
            f"Data di oggi: {today}\n"
            f"Categorie disponibili: [{cats}]\n\n"
            f"Messaggio dell'utente: \"{message}\""
        )
        t0 = time.time()
        response = self._client.chat.complete(
            model=self._model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=512,
            response_format=self._ResponseFormat(type="json_object"),
        )
        elapsed = time.time() - t0
        raw = response.choices[0].message.content or ""
        return _extract_json(raw), elapsed

    def generate_analysis(self, prompt: str) -> tuple[str, float]:
        t0 = time.time()
        response = self._client.chat.complete(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=2048,
        )
        elapsed = time.time() - t0
        return response.choices[0].message.content or "", elapsed


class GeminiParser:
    """Parsing spese con Gemini 2.5 Flash."""

    def __init__(self):
        from google import genai
        from google.genai import types as gtypes
        self._client = genai.Client(api_key=Config.GEMINI_API_KEY)
        self._gtypes = gtypes

    def parse(self, message: str) -> tuple[dict | None, float]:
        today = date.today().isoformat()
        cats = ", ".join(_CATEGORIES)
        user_prompt = (
            f"Data di oggi: {today}\n"
            f"Categorie disponibili: [{cats}]\n\n"
            f"Messaggio dell'utente: \"{message}\""
        )
        t0 = time.time()
        response = self._client.models.generate_content(
            model=Config.GEMINI_MODEL,
            contents=user_prompt,
            config=self._gtypes.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                temperature=0.1,
                max_output_tokens=512,
                response_mime_type="application/json",
            ),
        )
        elapsed = time.time() - t0
        raw = response.text or ""
        return _extract_json(raw), elapsed

    def generate_analysis(self, prompt: str) -> tuple[str, float]:
        from google.genai import types as gtypes
        t0 = time.time()
        response = self._client.models.generate_content(
            model=Config.GEMINI_MODEL,
            contents=prompt,
            config=gtypes.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=4096,
            ),
        )
        elapsed = time.time() - t0
        raw = response.text or ""
        # Rimuovi eventuale sezione Chain of Thought
        parts = raw.split("📊", 1)
        if len(parts) == 2:
            raw = "📊" + parts[1]
        return raw.strip(), elapsed


# ---------------------------------------------------------------------------
# BENCHMARK PARSING
# ---------------------------------------------------------------------------

def run_parsing_benchmark(providers: dict[str, object], delay_ms: int = 0) -> dict:
    """Esegue il benchmark parsing su tutti i test case per ogni provider."""
    console.print(Rule("[bold cyan]BENCHMARK 1 — PARSING SPESE[/bold cyan]"))
    if delay_ms:
        console.print(f"[dim]Delay tra chiamate: {delay_ms}ms[/dim]")

    results: dict[str, list] = {name: [] for name in providers}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        for pname, parser in providers.items():
            task = progress.add_task(f"[cyan]{pname}[/cyan] — parsing {len(_RAW_MESSAGES)} messaggi...", total=len(_RAW_MESSAGES))
            for i, msg in enumerate(_RAW_MESSAGES):
                if delay_ms and i > 0:
                    time.sleep(delay_ms / 1000)
                try:
                    result, elapsed = parser.parse(msg)
                    error = None
                except Exception as e:
                    result, elapsed, error = None, 0.0, str(e)
                results[pname].append({
                    "msg": msg,
                    "result": result,
                    "elapsed": elapsed,
                    "error": error,
                })
                progress.advance(task)

    _print_parsing_table(results)
    return results


def _fmt_result(cd: dict) -> str:
    """Formatta il risultato di un singolo parsing per la tabella."""
    if cd["error"]:
        return f"[red]ERR: {cd['error'][:30]}[/red]"
    r = cd["result"]
    ms = f"[dim]{cd['elapsed']*1000:.0f}ms[/dim]"
    if r is None or "error" in r:
        return f"[dim]— non transazione —[/dim]  {ms}"
    rtype = r.get("type", "?")
    amt   = r.get("amount")
    cat   = r.get("category") or r.get("income_type") or "?"
    name  = r.get("name", "")
    amt_str = f"€{amt}" if amt is not None else "€?"
    color = "green" if rtype == "expense" else "blue" if rtype == "income" else "dim"
    return f"[{color}]{rtype}[/{color}] {amt_str}  [{color}]{cat}[/{color}]\n[dim]{name}[/dim]  {ms}"


def _print_parsing_table(results: dict[str, list]) -> None:
    provider_names = list(results.keys())

    table = Table(
        title="Output Parsing — side-by-side",
        box=box.ROUNDED,
        show_lines=True,
        header_style="bold white on dark_blue",
    )
    table.add_column("#", style="dim", width=3)
    table.add_column("Messaggio utente", style="white", min_width=30, max_width=36)
    for pname in provider_names:
        table.add_column(pname, min_width=28, max_width=36)

    for i, base in enumerate(results[provider_names[0]]):
        row = [str(i + 1), f"[bold]{base['msg']}[/bold]"]
        for pname in provider_names:
            row.append(_fmt_result(results[pname][i]))
        table.add_row(*row)

    console.print(table)
    console.print()

    # Riepilogo performance (solo tempo, JSON valido, non-transazione rilevate)
    perf = Table(title="Performance Parsing", box=box.SIMPLE_HEAD, header_style="bold")
    perf.add_column("Provider", style="bold")
    perf.add_column("Tempo medio", justify="center")
    perf.add_column("Tempo totale", justify="center")
    perf.add_column("JSON validi", justify="center")
    perf.add_column("Non-transazioni", justify="center")
    perf.add_column("Errori API", justify="center")

    for pname, cases in results.items():
        times     = [c["elapsed"] for c in cases if not c["error"]]
        valid     = sum(1 for c in cases if c["result"] and "error" not in c["result"] and not c["error"])
        non_trans = sum(1 for c in cases if c["result"] and "error" in c["result"])
        api_errs  = sum(1 for c in cases if c["error"])
        avg_t = sum(times) / len(times) if times else 0
        total_t = sum(times)
        perf.add_row(
            pname,
            f"{avg_t * 1000:.0f}ms",
            f"{total_t:.1f}s",
            f"{valid}/{len(cases)}",
            str(non_trans),
            f"[red]{api_errs}[/red]" if api_errs else "0",
        )

    console.print(perf)
    console.print()


# ---------------------------------------------------------------------------
# BENCHMARK ANALISI TREND
# ---------------------------------------------------------------------------

def run_analysis_benchmark(providers: dict[str, object]) -> dict:
    """Esegue il benchmark analisi trend con dati mock (6 mesi + income)."""
    console.print(Rule("[bold cyan]BENCHMARK 2 — ANALISI TREND MENSILE[/bold cyan]"))

    from src.data_processor import DataProcessor
    from src.forecaster import Forecaster

    processor = DataProcessor()
    report = processor.process(_MOCK_TRANSACTIONS, 2026, 2, incomes=_MOCK_INCOMES)
    data_text = processor.to_prompt_text(report)

    forecaster = Forecaster()
    forecast = forecaster.predict(report, 3, 2026)
    forecast_text = forecast.to_prompt_text()

    total_balance = 3240.00  # saldo realistico dopo 6 mesi
    accounts_text = (
        f"Conti Correnti attuali:\n"
        f"Totale saldi conti: €{total_balance:.2f}\n"
        f"- Conto corrente principale: €2890.00\n"
        f"- Conto risparmio: €350.00\n"
    )

    net_savings = f"+€{report.total_income - report.current_month.total:.2f}" if report.total_income > 0 else "n/d"

    prompt = _ANALYSIS_PROMPT_TEMPLATE.format(
        data_block=data_text,
        accounts_block=accounts_text,
        forecast_block=forecast_text,
        current_month=report.current_month.label,
        next_month=forecast.target_month_label,
        total_income=f"{report.total_income:.2f}",
        total_amount=f"{report.current_month.total:.2f}",
        total_accounts_balance=f"{total_balance:.2f}",
        net_savings=net_savings,
    )

    # Mostra un riepilogo dei dati che verranno passati al modello
    exp = _MOCK_EXPECTED
    console.print(
        f"[dim]Dati mock: Feb 2026 | spese €{exp['total_expenses']:.2f} "
        f"| income €{exp['total_income']:.2f} "
        f"| media storica ~€{exp['hist_avg_approx']:.0f} "
        f"| anomalia: {exp['anomaly_category']}[/dim]"
    )
    console.print()

    analysis_results = {}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        for pname, parser in providers.items():
            task = progress.add_task(f"[cyan]{pname}[/cyan] — generazione report...", total=1)
            try:
                report_text, elapsed = parser.generate_analysis(prompt)
                score, score_detail, score_notes = _score_report(report_text)
                analysis_results[pname] = {
                    "report": report_text,
                    "elapsed": elapsed,
                    "score": score,
                    "score_detail": score_detail,
                    "score_notes": score_notes,
                    "error": None,
                }
            except Exception as e:
                analysis_results[pname] = {
                    "report": "", "elapsed": 0,
                    "score": 0, "score_detail": {}, "score_notes": [],
                    "error": str(e),
                }
            progress.advance(task)

    _print_analysis_results(analysis_results)
    return analysis_results


# Legenda categorie scoring
_SCORE_GROUPS = {
    "Struttura (4 pt)":  ["sez_riepilogo", "sez_trend", "sez_forecast", "sez_consigli"],
    "Accuracy  (4 pt)":  ["acc_totale", "acc_top_cat", "acc_anomalia", "acc_income"],
    "Formato   (2 pt)":  ["fmt_no_double_asterisk", "fmt_no_md_headers"],
    "Consigli  (3 pt)":  ["consiglio_1", "consiglio_2", "consiglio_3"],
    "Forecast  (1 pt)":  ["forecast_range"],
}

_SCORE_LABELS = {
    "sez_riepilogo": "📊 riepilogo",
    "sez_trend": "📉 trend",
    "sez_forecast": "🔮 forecast",
    "sez_consigli": "💡 consigli",
    "acc_totale": "totale €1554 citato",
    "acc_top_cat": "Affitto citato",
    "acc_anomalia": "Ristoranti anomalia",
    "acc_income": "income/stipendio",
    "fmt_no_double_asterisk": "no **grassetto**",
    "fmt_no_md_headers": "no ### headers",
    "consiglio_1": "consiglio 1 con €",
    "consiglio_2": "consiglio 2 con €",
    "consiglio_3": "consiglio 3 con €",
    "forecast_range": f"stima base {_MOCK_EXPECTED['base_forecast_range']}",
}


def _print_analysis_results(results: dict) -> None:
    max_score = 14

    # Tabella punteggi per gruppo
    score_table = Table(
        title=f"Scoring Report Analisi (max {max_score} pt)",
        box=box.ROUNDED,
        header_style="bold white on dark_blue",
        show_lines=True,
    )
    score_table.add_column("Criterio", style="white", min_width=24)
    for pname in results:
        score_table.add_column(pname, justify="center", min_width=22)

    for group_label, keys in _SCORE_GROUPS.items():
        score_table.add_section()
        # riga intestazione gruppo
        group_cells = [f"[bold dim]{group_label}[/bold dim]"]
        for pname, data in results.items():
            if data["error"]:
                group_cells.append("[red]ERRORE[/red]")
            else:
                grp_score = sum(data["score_detail"].get(k, 0) for k in keys)
                grp_max = len(keys)
                c = "green" if grp_score == grp_max else "yellow" if grp_score > 0 else "red"
                group_cells.append(f"[{c}]{grp_score}/{grp_max}[/{c}]")
        score_table.add_row(*group_cells, style="dim")

        for key in keys:
            label = _SCORE_LABELS.get(key, key)
            row = [f"  {label}"]
            for pname, data in results.items():
                if data["error"]:
                    row.append("–")
                else:
                    val = data["score_detail"].get(key, 0)
                    row.append("[green]✓[/green]" if val else "[red]✗[/red]")
            score_table.add_row(*row)

    # Riga totale
    score_table.add_section()
    total_row = ["[bold]TOTALE[/bold]"]
    for pname, data in results.items():
        if data["error"]:
            total_row.append("[red]–[/red]")
        else:
            s = data["score"]
            pct = s / max_score * 100
            c = "green" if pct >= 80 else "yellow" if pct >= 50 else "red"
            total_row.append(f"[{c}][bold]{s}/{max_score}[/bold] ({pct:.0f}%)[/{c}]")
    score_table.add_row(*total_row)

    console.print(score_table)
    console.print()

    # Note/errori scoring per provider
    for pname, data in results.items():
        if data.get("score_notes"):
            console.print(f"[yellow]Note {pname}:[/yellow]")
            for note in data["score_notes"]:
                console.print(f"  [dim]• {note}[/dim]")
            console.print()

    # Tabella metriche rapide (tempo, lunghezza)
    perf_table = Table(title="Performance", box=box.SIMPLE_HEAD, header_style="bold")
    perf_table.add_column("Provider", style="bold")
    perf_table.add_column("Tempo", justify="center")
    perf_table.add_column("Lunghezza output", justify="center")

    for pname, data in results.items():
        if data["error"]:
            perf_table.add_row(pname, "–", f"[red]ERRORE: {data['error'][:50]}[/red]")
        else:
            perf_table.add_row(pname, f"{data['elapsed']:.1f}s", f"{len(data['report'])} chars")

    console.print(perf_table)
    console.print()

    # Report side-by-side (pannelli)
    panels = []
    for pname, data in results.items():
        if data["error"]:
            content = f"[red]ERRORE:[/red]\n{data['error']}"
        else:
            content = data["report"][:3500] + ("…" if len(data["report"]) > 3500 else "")
        score_line = f"Score: {data['score']}/{max_score}" if not data["error"] else "ERRORE"
        panels.append(Panel(
            content,
            title=f"[bold cyan]{pname}[/bold cyan]  {data['elapsed']:.1f}s  |  {score_line}",
            border_style="cyan",
            expand=True,
        ))

    if len(panels) == 2:
        console.print(Columns(panels, equal=True))
    else:
        for p in panels:
            console.print(p)

    console.print()


# ---------------------------------------------------------------------------
# SALVATAGGIO RISULTATI
# ---------------------------------------------------------------------------

def save_results(_parsing_results: dict, analysis_results: dict) -> None:
    output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # HTML (rich)
    html_path = os.path.join(output_dir, f"benchmark_mistral_{ts}.html")
    html = console.export_html(theme=None)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    # Report Markdown per ogni provider
    for pname, data in analysis_results.items():
        if data.get("report"):
            md_path = os.path.join(output_dir, f"benchmark_report_{pname.lower()}_{ts}.md")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(f"# Report {pname} (tempo: {data['elapsed']:.1f}s)\n\n")
                f.write(data["report"])

    console.print(f"[green]Report HTML salvato:[/green] {html_path}")
    console.print(f"[green]Report Markdown salvati in:[/green] {output_dir}/")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Mistral Small 3.1 vs Gemini 2.5 Flash")
    parser.add_argument("--only", choices=["parsing", "analisi"], help="Esegui solo un task")
    parser.add_argument("--no-gemini",  action="store_true", help="Salta Gemini (solo Mistral)")
    parser.add_argument("--no-mistral", action="store_true", help="Salta Mistral (solo Gemini)")
    parser.add_argument(
        "--delay-ms", type=int, default=0,
        help="Pausa in ms tra chiamate consecutive (es. 6000 per Gemini free tier = 10 RPM)",
    )
    args = parser.parse_args()

    console.print(Rule("[bold magenta]BENCHMARK: Mistral Small 3.1 vs Gemini 2.5 Flash[/bold magenta]"))
    console.print(f"[dim]Data: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim]")
    if args.delay_ms:
        console.print(f"[dim]Delay inter-call: {args.delay_ms}ms[/dim]")
    console.print()

    # Costruisci dizionario provider attivi
    providers = {}
    if not args.no_mistral:
        if not Config.MISTRAL_API_KEY:
            console.print("[red]MISTRAL_API_KEY non trovata nel .env — aggiungi la chiave e riprova.[/red]")
            sys.exit(1)
        providers["Mistral Small 3.1"] = MistralParser()

    if not args.no_gemini:
        if Config.GEMINI_API_KEY:
            providers["Gemini 2.5 Flash"] = GeminiParser()
        else:
            console.print("[yellow]GEMINI_API_KEY non configurata — salto Gemini.[/yellow]")

    if not providers:
        console.print("[red]Nessun provider disponibile.[/red]")
        sys.exit(1)

    provider_list = ", ".join(providers.keys())
    console.print(f"Provider attivi: [bold cyan]{provider_list}[/bold cyan]")
    console.print(f"Messaggi parsing: [bold]{len(_RAW_MESSAGES)}[/bold]  |  Storico mock: 6 mesi (Set 2025 – Feb 2026)")
    console.print()

    parsing_results = {}
    analysis_results = {}

    if args.only != "analisi":
        parsing_results = run_parsing_benchmark(providers, delay_ms=args.delay_ms)

    if args.only != "parsing":
        analysis_results = run_analysis_benchmark(providers)

    save_results(parsing_results, analysis_results)
    console.print(Rule("[bold green]BENCHMARK COMPLETATO[/bold green]"))


if __name__ == "__main__":
    main()
