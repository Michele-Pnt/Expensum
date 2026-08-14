"""
scripts/benchmark_parsing_text.py — Parsing testo libero -> transazione strutturata:
Mistral Small 3.1 (attuale, via ExpenseParser reale) vs modelli self-hosted
(gemma3n, gemma2:2b via Ollama).

A differenza di scripts/benchmark_mistral.py (system prompt e schema a 6 campi,
categorie fittizie tipo "Ristoranti"/"Trasporti" mai esistite in produzione), questo
script usa:
  - _SYSTEM_PROMPT / _build_user_prompt / _build_response_schema / _normalize
    REALI da src/expense_parser.py (8 campi, supporto transfer, multi-transazione,
    enum strict sulle categorie)
  - DEFAULT_CATEGORIES reali da src/workspace_bootstrapper.py
  - Per Mistral: l'istanza ExpenseParser reale (stesso identico codice di bot.py)
  - Per Ollama: stesso system+user prompt, stesso JSON Schema passato come "format"
    (fedeltà all'enforcement strict che Mistral riceve via response_format), poi
    normalizzato con lo STESSO ExpenseParser._normalize (cosi' le differenze di score
    riflettono la qualita' del JSON grezzo del modello, non differenze di normalizzazione)

Uso:
  python scripts/benchmark_parsing_text.py
  python scripts/benchmark_parsing_text.py --only gemma2:2b
  python scripts/benchmark_parsing_text.py --runs 2
"""

import argparse
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from rich import box
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.rule import Rule
from rich.table import Table

from config import Config
from src.expense_parser import (
    ExpenseParser,
    _SYSTEM_PROMPT,
    _build_user_prompt,
    _build_response_schema,
    _extract_json,
)
from src.workspace_bootstrapper import DEFAULT_CATEGORIES

console = Console(record=True)
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

# Ancora temporale fissa per riproducibilità (i messaggi con date relative sono
# calcolati rispetto a questa data, non a datetime.now()).
WHEN = datetime(2026, 4, 10, 13, 0, 0)
TODAY = WHEN.date()

# ---------------------------------------------------------------------------
# TEST CASE — messaggio, ground truth (None = campo atteso null)
# Categorie usate: SOLO quelle reali in DEFAULT_CATEGORIES.
# ---------------------------------------------------------------------------

_CASES: list[dict] = [
    # --- spese semplici ---
    {"msg": "pizza 15", "type": "expense", "amount": 15.0, "category": "Ristorante"},
    {"msg": "benzina 40 euro", "type": "expense", "amount": 40.0, "category": "Carburante"},
    {"msg": "affitto", "type": "expense", "amount": None, "category": "Affitto"},
    {"msg": "netflix", "type": "expense", "amount": None, "category": None},  # nessuna cat "Abbonamenti" nei default -> ambiguo, non scoriamo categoria
    # --- colloquiale / sporco ---
    {"msg": "ieri sera mangiato fuori tipo 40 con i ragazzi", "type": "expense", "amount": 40.0,
     "category": "Ristorante", "date": "2026-04-09"},
    {"msg": "ho preso caffè e cornetto stamattina 2.70", "type": "expense", "amount": 2.70, "category": "Bar"},
    {"msg": "spesa esselunga ieri circa 90", "type": "expense", "amount": 90.0,
     "category": "Spese Alimentari", "date": "2026-04-09"},
    # --- importo a parole / ambiguo ---
    {"msg": "cento euro di spesa", "type": "expense", "amount": 100.0, "category": "Spese Alimentari"},
    {"msg": "100 euro", "type": None},  # non è chiaro sia una transazione -> attesa not_expense o incerto
    # --- income ---
    {"msg": "arrivato lo stipendio 1800", "type": "income", "amount": 1800.0, "income_type": "Stipendio"},
    {"msg": "bonus 300€", "type": "income", "amount": 300.0, "income_type": "Bonus"},
    {"msg": "mi hanno rimborsato il viaggio 120", "type": "income", "amount": 120.0, "income_type": "Rimborso"},
    {"msg": "regalo di compleanno 50 euro dalla nonna", "type": "income", "amount": 50.0, "income_type": "Regalo"},
    # --- transfer ---
    {"msg": "sposta 100 euro dal conto corrente al conto risparmio", "type": "transfer", "amount": 100.0,
     "from_account": "conto corrente", "to_account": "conto risparmio"},
    {"msg": "giroconto di 50€ da Revolut a Fineco", "type": "transfer", "amount": 50.0,
     "from_account": "Revolut", "to_account": "Fineco"},
    # --- date relative a distanza ---
    {"msg": "3 settimane fa ho pagato 80 euro di dentista", "type": "expense", "amount": 80.0,
     "category": "Medicina", "date": "2026-03-20"},
    {"msg": "il mese scorso bolletta della luce 95 euro", "type": "expense", "amount": 95.0,
     "category": "Bollette luce", "date": "2026-03-01"},
    # --- non transazione ---
    {"msg": "ok grazie", "type": None},
    # Nota: "domani devo pagare l'affitto" NON è un caso "non transazione" — è
    # un'intenzione futura legittima, correttamente interpretabile come spesa
    # Affitto datata domani (2026-04-11, ancora rispetto a WHEN=2026-04-10).
    {"msg": "domani devo pagare l'affitto", "type": "expense", "amount": None,
     "category": "Affitto", "date": "2026-04-11"},
    # --- multi-transazione ---
    {"msg": "ho speso 10 euro per il pranzo, 20 di benzina e 5 di caffè ieri", "type": "multi",
     "count": 3, "date": "2026-04-09"},
    {"msg": "oggi 15 euro di spesa e ieri ho ricevuto un rimborso di 50 euro", "type": "multi", "count": 2},
    # --- edge: farmacia, tipo dialettale, ricarica ---
    {"msg": "farmacia ieri 23.50", "type": "expense", "amount": 23.50, "category": "Farmacia", "date": "2026-04-09"},
    {"msg": "ricarica telefono 15", "type": "expense", "amount": 15.0, "category": "Telefono"},
]


# ---------------------------------------------------------------------------
# SCORING — confronta il risultato normalizzato con la ground truth.
# Ogni caso singolo vale fino a 5 punti: type, amount, category, income_type/account, date.
# I casi "None" (non-transazione attesa) valgono 1 punto (successo/fallimento binario).
# I casi "multi" valgono 2 punti: count corretto (1) + tutti i sotto-campi type coerenti (1).
# ---------------------------------------------------------------------------

def _score_case(case: dict, results: list[dict] | None) -> tuple[float, float, list[str]]:
    notes: list[str] = []

    if case["type"] is None:
        max_pts = 1.0
        if results is None:
            return 1.0, max_pts, notes
        notes.append(f"atteso 'non è una transazione', ottenuto {len(results)} transazione/i")
        return 0.0, max_pts, notes

    if case["type"] == "multi":
        max_pts = 2.0
        if not results:
            notes.append("nessuna transazione estratta, attese multiple")
            return 0.0, max_pts, notes
        pts = 0.0
        if len(results) == case["count"]:
            pts += 1.0
        else:
            notes.append(f"count: atteso {case['count']}, ottenuto {len(results)}")
        if all(r.get("type") in ("expense", "income", "transfer") for r in results):
            pts += 1.0
        else:
            notes.append("tipo non valido in una o più sotto-transazioni")
        return pts, max_pts, notes

    max_pts = 5.0
    if not results:
        notes.append("nessuna transazione estratta")
        return 0.0, max_pts, notes
    r = results[0]
    pts = 0.0

    if r.get("type") == case["type"]:
        pts += 1.0
    else:
        notes.append(f"type: atteso={case['type']} got={r.get('type')}")

    exp_amount = case.get("amount")
    got_amount = r.get("amount")
    if exp_amount is None:
        pts += 1.0 if got_amount is None else 0.0
        if got_amount is not None:
            notes.append(f"amount: atteso None got={got_amount}")
    elif got_amount is not None and abs(float(got_amount) - exp_amount) < 0.01:
        pts += 1.0
    else:
        notes.append(f"amount: atteso={exp_amount} got={got_amount}")

    exp_cat = case.get("category")
    if exp_cat is None:
        pts += 1.0  # non scoriamo la categoria per i casi ambigui
    elif r.get("category") == exp_cat:
        pts += 1.0
    else:
        notes.append(f"category: atteso={exp_cat} got={r.get('category')}")

    if case["type"] == "income":
        exp_it = case.get("income_type")
        if r.get("income_type") == exp_it:
            pts += 1.0
        else:
            notes.append(f"income_type: atteso={exp_it} got={r.get('income_type')}")
    elif case["type"] == "transfer":
        exp_from, exp_to = case.get("from_account"), case.get("to_account")
        from_ok = bool(r.get("from_account")) == bool(exp_from)
        to_ok = bool(r.get("to_account")) == bool(exp_to)
        if from_ok and to_ok:
            pts += 1.0
        else:
            notes.append(f"from/to_account: atteso from={exp_from!r} to={exp_to!r} "
                          f"got from={r.get('from_account')!r} to={r.get('to_account')!r}")
    else:
        pts += 1.0  # expense: nessun campo aggiuntivo da validare oltre category

    exp_date = case.get("date", TODAY.isoformat())
    got_date = r.get("date")
    got_date_str = got_date.isoformat() if hasattr(got_date, "isoformat") else str(got_date)
    if got_date_str == exp_date:
        pts += 1.0
    else:
        notes.append(f"date: atteso={exp_date} got={got_date_str}")

    return pts, max_pts, notes


# ---------------------------------------------------------------------------
# PROVIDERS
# ---------------------------------------------------------------------------

class MistralTextProvider:
    """Architettura attuale: ExpenseParser reale (stesso codice di bot.py)."""

    name = "Mistral Small 3.1 (attuale)"

    def __init__(self):
        self._parser = ExpenseParser(categories=DEFAULT_CATEGORIES)

    def parse(self, message: str) -> tuple[list[dict] | None, float, str | None]:
        t0 = time.time()
        try:
            results, _usage = self._parser.parse_multi_with_usage(message, when=WHEN)
            return results, time.time() - t0, None
        except Exception as e:
            return None, time.time() - t0, str(e)


class OllamaTextProvider:
    """Modello self-hosted: stesso system+user prompt e schema JSON di produzione,
    normalizzazione riusata da ExpenseParser._normalize per un confronto ad armi pari."""

    def __init__(self, model: str, timeout_s: int = 120):
        self.model = model
        self.name = model
        self._timeout = timeout_s
        self._parser = ExpenseParser(categories=DEFAULT_CATEGORIES)  # solo per _normalize

    def parse(self, message: str) -> tuple[list[dict] | None, float, str | None]:
        user_prompt = _build_user_prompt(message, DEFAULT_CATEGORIES, WHEN)
        schema = _build_response_schema(DEFAULT_CATEGORIES)

        t0 = time.time()
        try:
            resp = requests.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    "format": schema,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 1024},
                },
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            content = (data.get("message") or {}).get("content", "") or ""
            elapsed = time.time() - t0
        except requests.exceptions.RequestException as e:
            return None, time.time() - t0, str(e)

        parsed = _extract_json(content)
        if parsed is None:
            return None, elapsed, f"JSON non estraibile: {content[:120]!r}"
        if "error" in parsed:
            return None, elapsed, None  # not_expense: risultato legittimo, non un errore

        raw_transactions = parsed["transactions"] if isinstance(parsed.get("transactions"), list) else [parsed]
        results = [self._parser._normalize(item, TODAY) for item in raw_transactions if isinstance(item, dict)]
        return (results or None), elapsed, None


# ---------------------------------------------------------------------------
# RUNNER
# ---------------------------------------------------------------------------

def run_benchmark(providers: list, runs: int) -> dict:
    console.print(Rule("[bold cyan]PARSING TESTO[/bold cyan]"))
    console.print(f"[dim]{len(_CASES)} casi di test | {runs} run per provider[/dim]\n")

    all_results = {}
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  console=console, transient=True) as progress:
        for provider in providers:
            run_scores = []
            case_details = []  # solo dell'ultimo run, per il report note
            for run_i in range(runs):
                task = progress.add_task(f"[cyan]{provider.name}[/cyan] — run {run_i+1}/{runs}...",
                                          total=len(_CASES))
                total_pts, total_max = 0.0, 0.0
                run_case_details = []
                errors = 0
                for case in _CASES:
                    results, elapsed, error = provider.parse(case["msg"])
                    if error:
                        errors += 1
                        run_case_details.append((case["msg"], 0.0, 0.0, [f"ERRORE: {error}"]))
                        progress.advance(task)
                        continue
                    pts, max_pts, notes = _score_case(case, results)
                    total_pts += pts
                    total_max += max_pts
                    run_case_details.append((case["msg"], pts, max_pts, notes))
                    progress.advance(task)
                run_scores.append({"total_pts": total_pts, "total_max": total_max, "errors": errors})
                case_details = run_case_details
            all_results[provider.name] = {"runs": run_scores, "case_details": case_details}

    _print_results(all_results)
    return all_results


def _print_results(all_results: dict) -> None:
    perf = Table(title="Punteggio parsing testo (media su N run)", box=box.ROUNDED, header_style="bold")
    perf.add_column("Provider")
    perf.add_column("Score medio", justify="center")
    perf.add_column("Score % (min-max)", justify="center")
    perf.add_column("Errori/run", justify="center")

    for pname, data in all_results.items():
        runs = data["runs"]
        pcts = [r["total_pts"] / r["total_max"] * 100 for r in runs]
        avg_pct = sum(pcts) / len(pcts)
        c = "green" if avg_pct >= 80 else "yellow" if avg_pct >= 50 else "red"
        avg_errors = sum(r["errors"] for r in runs) / len(runs)
        perf.add_row(
            pname,
            f"[{c}]{runs[-1]['total_pts']:.1f}/{runs[-1]['total_max']:.0f}[/{c}]",
            f"[{c}]{avg_pct:.0f}% ({min(pcts):.0f}–{max(pcts):.0f})[/{c}]",
            f"{avg_errors:.1f}",
        )
    console.print(perf)
    console.print()

    fails = Table(title="Casi falliti (ultimo run, dettaglio)", box=box.SIMPLE_HEAD, header_style="bold")
    fails.add_column("Provider", style="bold")
    fails.add_column("Messaggio", max_width=40)
    fails.add_column("Score", justify="center")
    fails.add_column("Note", max_width=60)

    for pname, data in all_results.items():
        for msg, pts, max_pts, notes in data["case_details"]:
            if max_pts > 0 and pts < max_pts:
                fails.add_row(pname, msg, f"{pts:.1f}/{max_pts:.0f}", "; ".join(notes)[:120])
    console.print(fails)
    console.print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark parsing testo: Mistral vs self-hosted")
    parser.add_argument("--only", help="Testa solo un provider per nome (es. 'gemma2:2b')")
    parser.add_argument("--no-mistral", action="store_true")
    parser.add_argument("--ollama-models", default="gemma3n:e2b,gemma2:2b")
    parser.add_argument("--runs", type=int, default=2)
    args = parser.parse_args()

    console.print(Rule("[bold magenta]BENCHMARK PARSING TESTO: Mistral vs self-hosted[/bold magenta]"))
    console.print(f"[dim]Ancora temporale test: {WHEN.isoformat()}[/dim]\n")

    providers = []
    if not args.no_mistral:
        if not Config.MISTRAL_API_KEY:
            console.print("[red]MISTRAL_API_KEY non trovata — aggiungi la chiave o usa --no-mistral.[/red]")
            sys.exit(1)
        providers.append(MistralTextProvider())

    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        r.raise_for_status()
        available = [m["name"] for m in r.json().get("models", [])]
    except requests.exceptions.RequestException as e:
        console.print(f"[yellow]Impossibile contattare Ollama: {e} — salto i modelli self-hosted.[/yellow]")
        available = []

    for model in [m.strip() for m in args.ollama_models.split(",") if m.strip()]:
        if model not in available:
            console.print(f"[yellow]Modello '{model}' non disponibile in Ollama ({available}) — salto.[/yellow]")
            continue
        providers.append(OllamaTextProvider(model))

    if args.only:
        providers = [p for p in providers if p.name == args.only]

    if not providers:
        console.print("[red]Nessun provider disponibile.[/red]")
        sys.exit(1)

    console.print(f"Provider attivi: [bold cyan]{', '.join(p.name for p in providers)}[/bold cyan]\n")
    run_benchmark(providers, args.runs)
    console.print(Rule("[bold green]BENCHMARK COMPLETATO[/bold green]"))


if __name__ == "__main__":
    main()
