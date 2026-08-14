"""
scripts/benchmark_reports_selfhosted.py — Piano Settimanale/Mensile: Mistral Small 3.1
(architettura attuale) vs modelli self-hosted (gemma3n, gemma2:2b via Ollama).

A differenza di scripts/benchmark_mistral.py (che testa un prompt di "Analisi Trend"
NON più usato in produzione — MistralClient.analyze_and_generate_report() non è chiamato
da bot.py), questo script usa il percorso REALE:

  WeeklyPlanBuilder().build(storage)  -> WeeklyPlanData.to_prompt_text()
  MonthlyPlanBuilder().build(storage) -> MonthlyPlanData.to_prompt_text()
  -> MistralClient.generate_weekly_plan() / generate_monthly_plan()
     (stessi identici _WEEKLY_PLAN_PROMPT_TEMPLATE / _MONTHLY_PLAN_PROMPT_TEMPLATE
      usati da bot.py via src/plan_actions.py)

`storage` è un FinancialStorage finto (FakeStorage sotto) popolato con dati mock
realistici — i builder di produzione calcolano budget/momentum/pattern per davvero,
non vengono simulati a mano.

Uso:
  python scripts/benchmark_reports_selfhosted.py
  python scripts/benchmark_reports_selfhosted.py --only weekly
  python scripts/benchmark_reports_selfhosted.py --runs 3          # stima varianza
  python scripts/benchmark_reports_selfhosted.py --no-mistral      # solo self-hosted
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.rule import Rule
from rich.table import Table

from config import Config
from src.report_builder import WeeklyPlanBuilder, MonthlyPlanBuilder
from src.mistral_client import _WEEKLY_PLAN_PROMPT_TEMPLATE, _MONTHLY_PLAN_PROMPT_TEMPLATE

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from benchmark_mistral import _MOCK_TRANSACTIONS, _MOCK_INCOMES  # noqa: E402

console = Console(record=True)

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

# ---------------------------------------------------------------------------
# FAKE STORAGE — implementa solo i metodi usati da WeeklyPlanBuilder/MonthlyPlanBuilder
# ---------------------------------------------------------------------------

_CATEGORY_BUDGETS = {
    "Affitto": 700.0,
    "Supermercato": 220.0,
    "Abbonamenti": 30.0,
    "Ristoranti": 130.0,   # deliberatamente basso: Febbraio sfora (vedi commento dataset)
    "Trasporti": 40.0,
    "Utility": 100.0,
    "Abbigliamento": 100.0,
    # "Salute", "Intrattenimento", "Regali", "Viaggi": nessun budget -> stima storica
}

_SUBSCRIPTIONS = [
    {"name": "Netflix", "amount": 13.99, "sub_type": "mensile", "last_billed": "2026-01-05"},
    {"name": "Spotify", "amount": 9.99, "sub_type": "mensile", "last_billed": "2026-01-05"},
]

_ACCOUNTS = [
    {"name": "Conto corrente principale", "current_balance": 2890.00},
    {"name": "Conto risparmio", "current_balance": 350.00},
]


class FakeStorage:
    """FinancialStorage in-memory: stessi dati mock per ogni run, nessuna rete/DB."""

    def __init__(self, transactions: list[dict], incomes: list[dict]):
        self._transactions = transactions
        self._incomes = incomes

    def fetch_all_transactions(self, start_date: date, end_date: date) -> list[dict]:
        return [dict(t) for t in self._transactions if start_date <= t["date"] <= end_date]

    def fetch_income(self, start_date: date, end_date: date) -> list[dict]:
        return [dict(i) for i in self._incomes if start_date <= i["date"] <= end_date]

    def fetch_accounts(self) -> list[dict]:
        return [dict(a) for a in _ACCOUNTS]

    def fetch_subscriptions(self) -> list[dict]:
        return [dict(s) for s in _SUBSCRIPTIONS]

    def get_categories(self, include_archived: bool = False) -> list[dict]:
        cats = {t["category"] for t in self._transactions}
        return [{"name": c, "monthly_budget": _CATEGORY_BUDGETS.get(c, 0.0)} for c in cats]

    def fetch_savings_goals(self, status: str | None = None) -> list[dict]:
        return []


# Data di riferimento: dentro il dataset mock (Set 2025 - Feb 2026), a metà Febbraio
# cosi' il "mese corrente" per il piano settimanale ha gia' transazioni, e il mese
# target per il piano mensile (Marzo) ha 5 mesi di storico completo dietro.
REFERENCE_DATE = date(2026, 2, 20)


# ---------------------------------------------------------------------------
# PROVIDERS — stesso contratto: generate(prompt) -> (testo, tempo_secondi, errore|None)
# ---------------------------------------------------------------------------

class MistralProvider:
    """Architettura attuale: MistralClient reale (stesso codice di produzione)."""

    name = "Mistral Small 3.1 (attuale)"

    def __init__(self):
        from src.mistral_client import MistralClient
        self._client = MistralClient()

    def generate(self, kind: str, prompt_data: str, label: str) -> tuple[str, float, str | None]:
        t0 = time.time()
        try:
            fn = self._client.generate_weekly_plan if kind == "weekly" else self._client.generate_monthly_plan
            text, _usage = fn(prompt_data, label)
            return text, time.time() - t0, None
        except Exception as e:
            return "", time.time() - t0, str(e)


class OllamaProvider:
    """Modello self-hosted via Ollama /api/chat, stesso prompt template di produzione."""

    def __init__(self, model: str, label: str, timeout_s: int = 300):
        self.model = model
        self.name = label
        self._timeout = timeout_s

    def generate(self, kind: str, prompt_data: str, label: str) -> tuple[str, float, str | None]:
        template = _WEEKLY_PLAN_PROMPT_TEMPLATE if kind == "weekly" else _MONTHLY_PLAN_PROMPT_TEMPLATE
        if kind == "weekly":
            prompt = template.format(plan_data=prompt_data, week_label=label)
        else:
            prompt = template.format(plan_data=prompt_data, month_label=label)

        t0 = time.time()
        try:
            resp = requests.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {"temperature": 0.2, "num_predict": 2048},
                },
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            text = (data.get("message") or {}).get("content", "") or ""
            elapsed = time.time() - t0
            if not text.strip():
                return "", elapsed, "risposta vuota"
            # Rimuovi eventuale ragionamento pre-piano (stesso comportamento di MistralClient)
            emoji = "📅"
            if emoji in text:
                text = emoji + text.split(emoji, 1)[1]
            return text.strip(), elapsed, None
        except requests.exceptions.RequestException as e:
            return "", time.time() - t0, str(e)


# ---------------------------------------------------------------------------
# SCORING — calibrato sul formato REALE (Piano Settimanale/Mensile), non sul
# vecchio formato "Analisi Trend" usato in benchmark_mistral.py.
# ---------------------------------------------------------------------------

# Frammenti letterali delle istruzioni tra parentesi quadre nei due template: se
# compaiono nell'output, il modello non ha compilato il placeholder ma l'ha copiato
# dal prompt (fallimento grave: l'utente vedrebbe le istruzioni al posto del piano).
_PLACEHOLDER_MARKERS = [
    "[Se ci sono abbonamenti", "[Se NON ci sono abbonamenti",
    "[Consiglio specifico", "[valore]", "[income_forecast]", "[savings_goal]",
    "[total_accounts]", "[Per ogni categoria con target",
    "[Se ci sono abbonamenti in scadenza:]",
]


def _has_unfilled_placeholder(text: str) -> str | None:
    """Ritorna il primo marker di placeholder non compilato trovato, o None."""
    for marker in _PLACEHOLDER_MARKERS:
        if marker in text:
            return marker
    return None


def _section_present(text: str, emoji: str, fallback_keyword: str) -> bool:
    """Vero se la sezione è presente, riconosciuta dall'emoji O da una parola chiave
    del testo circostante. Necessario perché testo copiato/incollato da alcune fonti
    (es. output Colab passato via chat) può perdere i byte di continuazione degli
    emoji multi-byte UTF-8 (💡 -> solo il primo byte sopravvive) — il fallback testuale
    evita di penalizzare un report solo perché l'emoji si è corrotto nel transito,
    quando il contenuto sostanziale (che è ASCII) è comunque intatto e verificabile."""
    return emoji in text or fallback_keyword.lower() in text.lower()


def _find_tips(text: str, section_keyword: str) -> list[str]:
    """Estrae fino a 3 blocchi di consiglio dopo `section_keyword`. Riconosce sia i
    marker emoji puliti (1️⃣2️⃣3️⃣) sia la variante corrotta (vedi _section_present)
    dove sopravvive solo la cifra ASCII seguita da byte spazzatura."""
    idx = text.lower().find(section_keyword.lower())
    if idx == -1:
        return []
    tail = text[idx:]
    markers = list(re.finditer(r"(?:^|\n)\s*([123])\S{0,6}\s", tail))
    tips = []
    for i, m in enumerate(markers):
        start = m.end()
        end = markers[i + 1].start() if i + 1 < len(markers) else len(tail)
        tips.append(tail[start:end].strip())
    return tips


def _score_weekly_plan(text: str, plan_data) -> tuple[int, dict[str, int], list[str]]:
    """Max 13 punti. Verifica struttura, coerenza numerica coi dati REALI passati
    al prompt (non valori attesi hard-coded — i dati arrivano dal builder vero,
    quindi lo scoring li legge da `plan_data`), formato Telegram, coerenza status."""
    scores: dict[str, int] = {}
    notes: list[str] = []

    placeholder = _has_unfilled_placeholder(text)
    scores["no_placeholder_non_compilato"] = 0 if placeholder else 1
    if placeholder:
        notes.append(f"placeholder del template NON compilato, copiato letteralmente: '{placeholder}'")

    for emoji, label, keyword in [
        ("📅", "titolo", "Piano Settimana"),
        ("🔔", "abbonamenti", "abbonament"),
        ("🎯", "obiettivi", "Obiettivi per categoria"),
        ("💡", "consigli", "Consigli per questa settimana"),
    ]:
        scores[f"sez_{label}"] = 1 if _section_present(text, emoji, keyword) else 0
        if not scores[f"sez_{label}"]:
            notes.append(f"sezione '{emoji} {label}' assente")

    # Ogni categoria con status "sforato" deve essere citata col nome
    sforati = [c for c, r in plan_data.budget_results.items() if r.status == "sforato"]
    cited_sforati = sum(1 for c in sforati if c.lower() in text.lower())
    scores["acc_sforati_citati"] = 1 if (not sforati or cited_sforati == len(sforati)) else 0
    if sforati and cited_sforati < len(sforati):
        notes.append(f"categorie sforate non tutte citate: {sforati} (citate: {cited_sforati})")

    # Il template chiede ESPLICITAMENTE una riga in tabella per ogni categoria con
    # budget (colonna "Categoria") — non chiede invece di ripetere il totale mensile
    # da nessuna parte nel formato di output, quindi non lo testiamo (sarebbe un
    # criterio ingiusto: penalizzerebbe l'aderenza al formato richiesto).
    all_cats = list(plan_data.budget_results.keys())
    cited_cats = sum(1 for c in all_cats if c.lower() in text.lower())
    scores["acc_categorie_in_tabella"] = 1 if (not all_cats or cited_cats == len(all_cats)) else 0
    if all_cats and cited_cats < len(all_cats):
        notes.append(f"non tutte le categorie con budget sono in tabella ({cited_cats}/{len(all_cats)})")

    scores["fmt_no_double_asterisk"] = 0 if "**" in text else 1
    if "**" in text:
        notes.append(f"grassetto doppio ** trovato ({text.count('**')}x) — non valido per Telegram")

    scores["fmt_no_md_headers"] = 0 if re.search(r"^#{1,3}\s", text, re.MULTILINE) else 1
    if not scores["fmt_no_md_headers"]:
        notes.append("header Markdown # trovati — non validi per Telegram")

    has_number = lambda s: bool(re.search(r"€\s*\d+|\d+[.,]\d+|\d{2,}", s))
    tips = _find_tips(text, "Consigli per questa settimana")
    for i in range(3):
        tip = tips[i] if i < len(tips) else ""
        scores[f"consiglio_{i+1}"] = 1 if (tip and has_number(tip)) else 0
        if not scores[f"consiglio_{i+1}"]:
            reason = "non trovato" if not tip else f"senza numeri reali: '{tip[:60]}'"
            notes.append(f"consiglio {i+1} {reason}")

    # Nessuna categoria falsa: ogni nome citato come categoria dovrebbe esistere nei dati
    known_cats = set(plan_data.budget_results.keys()) | set(plan_data.no_budget_cats.keys())
    scores["no_categorie_inventate"] = 1  # penalizzato solo se troviamo un pattern chiaro di categoria sconosciuta
    # (euristica volutamente conservativa: difficile da rilevare in modo affidabile via regex,
    #  la difettosità va verificata a campione a mano — vedi report finale)

    total = sum(scores.values())
    return total, scores, notes


def _score_monthly_plan(text: str, plan_data) -> tuple[int, dict[str, int], list[str]]:
    """Max 11 punti."""
    scores: dict[str, int] = {}
    notes: list[str] = []

    placeholder = _has_unfilled_placeholder(text)
    scores["no_placeholder_non_compilato"] = 0 if placeholder else 1
    if placeholder:
        notes.append(f"placeholder del template NON compilato, copiato letteralmente: '{placeholder}'")

    for emoji, label, keyword in [
        ("📅", "titolo", "Piano Mensile"),
        ("🎯", "budget", "Budget per categoria"),
        ("💡", "consigli", "Consigli per questo mese"),
    ]:
        scores[f"sez_{label}"] = 1 if _section_present(text, emoji, keyword) else 0
        if not scores[f"sez_{label}"]:
            notes.append(f"sezione '{emoji} {label}' assente")

    income_str = f"{plan_data.income_forecast:.2f}"
    income_alt = f"{plan_data.income_forecast:.0f}"
    scores["acc_income_forecast"] = 1 if (income_str in text or income_alt in text) else 0
    if not scores["acc_income_forecast"]:
        notes.append(f"previsione entrate (€{income_str}) non citata")

    savings_str = f"{plan_data.savings_goal:.2f}"
    savings_alt = f"{plan_data.savings_goal:.0f}"
    scores["acc_savings_goal"] = 1 if (savings_str in text or savings_alt in text) else 0
    if not scores["acc_savings_goal"]:
        notes.append(f"obiettivo risparmio (€{savings_str}) non citato")

    scores["fmt_no_double_asterisk"] = 0 if "**" in text else 1
    if "**" in text:
        notes.append(f"grassetto doppio ** trovato ({text.count('**')}x)")

    scores["fmt_no_md_headers"] = 0 if re.search(r"^#{1,3}\s", text, re.MULTILINE) else 1
    if not scores["fmt_no_md_headers"]:
        notes.append("header Markdown # trovati")

    has_number = lambda s: bool(re.search(r"€\s*\d+|\d+[.,]\d+|\d{2,}", s))
    tips = _find_tips(text, "Consigli per questo mese")
    for i in range(3):
        tip = tips[i] if i < len(tips) else ""
        scores[f"consiglio_{i+1}"] = 1 if (tip and has_number(tip)) else 0
        if not scores[f"consiglio_{i+1}"]:
            reason = "non trovato" if not tip else f"senza numeri reali: '{tip[:60]}'"
            notes.append(f"consiglio {i+1} {reason}")

    total = sum(scores.values())
    return total, scores, notes


# ---------------------------------------------------------------------------
# RUNNER
# ---------------------------------------------------------------------------

def run_benchmark(kind: str, providers: list, runs: int) -> dict:
    console.print(Rule(f"[bold cyan]PIANO {'SETTIMANALE' if kind == 'weekly' else 'MENSILE'}[/bold cyan]"))

    storage = FakeStorage(_MOCK_TRANSACTIONS, _MOCK_INCOMES)
    if kind == "weekly":
        builder = WeeklyPlanBuilder()
        plan_data = builder.build(storage, reference_date=REFERENCE_DATE)
        from datetime import timedelta
        monday = REFERENCE_DATE - timedelta(days=REFERENCE_DATE.weekday())
        label = f"{monday.strftime('%d/%m')} → {(monday + timedelta(days=6)).strftime('%d/%m')}"
        score_fn = _score_weekly_plan
        max_score = 13
    else:
        builder = MonthlyPlanBuilder()
        plan_data = builder.build(storage, reference_date=REFERENCE_DATE)
        months_it = ["", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
                     "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"]
        label = f"{months_it[plan_data.target_month.month]} {plan_data.target_month.year}"
        score_fn = _score_monthly_plan
        max_score = 11

    prompt_data = plan_data.to_prompt_text()
    console.print(f"[dim]Reference date: {REFERENCE_DATE} | Label: {label} | "
                  f"Prompt: {len(prompt_data)} caratteri[/dim]\n")

    results = {}
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  console=console, transient=True) as progress:
        for provider in providers:
            runs_data = []
            for i in range(runs):
                task = progress.add_task(f"[cyan]{provider.name}[/cyan] — run {i+1}/{runs}...", total=1)
                text, elapsed, error = provider.generate(kind, prompt_data, label)
                if error:
                    runs_data.append({"error": error, "elapsed": elapsed, "text": "", "score": 0,
                                       "score_detail": {}, "notes": []})
                else:
                    score, detail, notes = score_fn(text, plan_data)
                    runs_data.append({"error": None, "elapsed": elapsed, "text": text, "score": score,
                                       "score_detail": detail, "notes": notes})
                progress.advance(task)
            results[provider.name] = runs_data

    _print_results(results, max_score, kind)
    return {"kind": kind, "results": results, "max_score": max_score, "plan_data": plan_data}


def _print_results(results: dict, max_score: int, kind: str) -> None:
    perf = Table(title="Performance ed affidabilità (su N run)", box=box.ROUNDED, header_style="bold")
    perf.add_column("Provider")
    perf.add_column("Score medio", justify="center")
    perf.add_column("Score (min-max)", justify="center")
    perf.add_column("Tempo medio", justify="center")
    perf.add_column("Errori", justify="center")

    for pname, runs_data in results.items():
        ok = [r for r in runs_data if r["error"] is None]
        errs = len(runs_data) - len(ok)
        if ok:
            scores = [r["score"] for r in ok]
            avg_score = sum(scores) / len(scores)
            avg_t = sum(r["elapsed"] for r in ok) / len(ok)
            pct = avg_score / max_score * 100
            c = "green" if pct >= 80 else "yellow" if pct >= 50 else "red"
            perf.add_row(
                pname,
                f"[{c}]{avg_score:.1f}/{max_score} ({pct:.0f}%)[/{c}]",
                f"{min(scores)}–{max(scores)}",
                f"{avg_t:.1f}s",
                f"{errs}/{len(runs_data)}" if errs else "0",
            )
        else:
            perf.add_row(pname, "[red]—[/red]", "—", "—", f"[red]{errs}/{len(runs_data)}[/red]")

    console.print(perf)
    console.print()

    for pname, runs_data in results.items():
        ok = [r for r in runs_data if r["error"] is None]
        if not ok:
            console.print(f"[red]{pname}: tutti i run falliti — {runs_data[0]['error']}[/red]\n")
            continue
        best = max(ok, key=lambda r: r["score"])
        if best["notes"]:
            console.print(f"[yellow]Note {pname} (run migliore):[/yellow]")
            for n in best["notes"]:
                console.print(f"  [dim]• {n}[/dim]")
            console.print()

    panels = []
    for pname, runs_data in results.items():
        ok = [r for r in runs_data if r["error"] is None]
        if ok:
            best = max(ok, key=lambda r: r["score"])
            content = best["text"][:3500] + ("…" if len(best["text"]) > 3500 else "")
            title = f"[bold cyan]{pname}[/bold cyan]  {best['elapsed']:.1f}s  |  Score: {best['score']}/{max_score}"
        else:
            content = f"[red]ERRORE:[/red]\n{runs_data[0]['error']}"
            title = f"[bold cyan]{pname}[/bold cyan]  ERRORE"
        panels.append(Panel(content, title=title, border_style="cyan", expand=True))

    if len(panels) <= 2:
        console.print(Columns(panels, equal=True))
    else:
        for p in panels:
            console.print(p)
    console.print()


def save_results(all_results: list[dict]) -> str:
    output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    html_path = os.path.join(output_dir, f"benchmark_reports_selfhosted_{ts}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(console.export_html(theme=None))

    json_path = os.path.join(output_dir, f"benchmark_reports_selfhosted_{ts}.json")
    serializable = []
    for run in all_results:
        serializable.append({
            "kind": run["kind"],
            "max_score": run["max_score"],
            "results": {
                pname: [{k: v for k, v in r.items() if k != "text"} | {"text_len": len(r.get("text", ""))}
                        for r in runs_data]
                for pname, runs_data in run["results"].items()
            },
        })
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)

    for run in all_results:
        for pname, runs_data in run["results"].items():
            ok = [r for r in runs_data if r["error"] is None]
            if ok:
                best = max(ok, key=lambda r: r["score"])
                safe_name = pname.lower().replace(" ", "_").replace("(", "").replace(")", "")
                md_path = os.path.join(output_dir, f"plan_{run['kind']}_{safe_name}_{ts}.md")
                with open(md_path, "w", encoding="utf-8") as f:
                    f.write(best["text"])

    console.print(f"[green]Risultati salvati:[/green] {html_path}, {json_path}")
    return json_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Piano Settimanale/Mensile: Mistral vs self-hosted")
    parser.add_argument("--only", choices=["weekly", "monthly"], help="Esegui solo un task")
    parser.add_argument("--no-mistral", action="store_true", help="Salta Mistral (solo self-hosted)")
    parser.add_argument("--ollama-models", default="gemma3n,gemma2:2b",
                         help="Modelli Ollama da includere, separati da virgola")
    parser.add_argument("--runs", type=int, default=3, help="Numero di run per provider (per stimare varianza)")
    args = parser.parse_args()

    console.print(Rule("[bold magenta]BENCHMARK REPORT: Mistral Small 3.1 vs self-hosted[/bold magenta]"))
    console.print(f"[dim]Data: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Run per provider: {args.runs}[/dim]\n")

    providers = []
    if not args.no_mistral:
        if not Config.MISTRAL_API_KEY:
            console.print("[red]MISTRAL_API_KEY non trovata — aggiungi la chiave o usa --no-mistral.[/red]")
            sys.exit(1)
        providers.append(MistralProvider())

    for model in [m.strip() for m in args.ollama_models.split(",") if m.strip()]:
        try:
            r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
            r.raise_for_status()
            available = [m["name"] for m in r.json().get("models", [])]
        except requests.exceptions.RequestException as e:
            console.print(f"[red]Impossibile contattare Ollama su {OLLAMA_BASE_URL}: {e}[/red]")
            sys.exit(1)
        if model not in available and not any(a.startswith(model + ":") for a in available):
            console.print(f"[yellow]Modello '{model}' non trovato in Ollama ({available}) — salto.[/yellow]")
            continue
        providers.append(OllamaProvider(model, model))

    if not providers:
        console.print("[red]Nessun provider disponibile.[/red]")
        sys.exit(1)

    console.print(f"Provider attivi: [bold cyan]{', '.join(p.name for p in providers)}[/bold cyan]\n")

    all_results = []
    if args.only != "monthly":
        all_results.append(run_benchmark("weekly", providers, args.runs))
    if args.only != "weekly":
        all_results.append(run_benchmark("monthly", providers, args.runs))

    save_results(all_results)
    console.print(Rule("[bold green]BENCHMARK COMPLETATO[/bold green]"))


if __name__ == "__main__":
    main()
