"""
scripts/score_colab_results.py — Punteggia gemma_colab_results.json (output grezzo
generato dal notebook Colab) con le STESSE funzioni di scoring usate per Mistral
(benchmark_parsing_text.py, benchmark_reports_selfhosted.py) — nessun doppio standard
tra provider locali/cloud.

Uso:
  python scripts/score_colab_results.py <path_al_json>
"""

import json
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rich import box
from rich.console import Console
from rich.table import Table

from src.expense_parser import ExpenseParser, _extract_json
from src.workspace_bootstrapper import DEFAULT_CATEGORIES
from src.report_builder import WeeklyPlanBuilder, MonthlyPlanBuilder

from benchmark_parsing_text import _CASES, _score_case, TODAY
from benchmark_reports_selfhosted import FakeStorage, REFERENCE_DATE, _score_weekly_plan, _score_monthly_plan
from benchmark_mistral import _MOCK_TRANSACTIONS, _MOCK_INCOMES

console = Console()


def score_text_parsing(results_by_msg: dict[str, str]) -> tuple[float, float, list[tuple]]:
    """results_by_msg: {msg: raw_output_text}. Ritorna (punti, punti_max, dettagli)."""
    parser = ExpenseParser(categories=DEFAULT_CATEGORIES)
    total_pts, total_max = 0.0, 0.0
    details = []

    for case in _CASES:
        raw = results_by_msg.get(case["msg"])
        if raw is None:
            details.append((case["msg"], 0.0, 0.0, ["messaggio mancante nel JSON Colab"]))
            continue

        parsed = _extract_json(raw)
        if parsed is None or "error" in parsed:
            results = None
        else:
            raw_txs = parsed["transactions"] if isinstance(parsed.get("transactions"), list) else [parsed]
            results = [parser._normalize(item, TODAY) for item in raw_txs if isinstance(item, dict)]

        pts, max_pts, notes = _score_case(case, results)
        total_pts += pts
        total_max += max_pts
        details.append((case["msg"], pts, max_pts, notes))

    return total_pts, total_max, details


def score_reports(raw_weekly: str, raw_monthly: str) -> dict:
    storage = FakeStorage(_MOCK_TRANSACTIONS, _MOCK_INCOMES)
    wdata = WeeklyPlanBuilder().build(storage, reference_date=REFERENCE_DATE)
    mdata = MonthlyPlanBuilder().build(storage, reference_date=REFERENCE_DATE)

    w_score, w_detail, w_notes = _score_weekly_plan(raw_weekly, wdata)
    m_score, m_detail, m_notes = _score_monthly_plan(raw_monthly, mdata)
    return {
        "weekly": {"score": w_score, "max": 13, "notes": w_notes},
        "monthly": {"score": m_score, "max": 11, "notes": m_notes},
    }


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "gemma_colab_results.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    console.print("[bold magenta]SCORING RISULTATI COLAB — stesse metriche usate per Mistral[/bold magenta]\n")

    # --- Parsing testo ---
    table = Table(title="Parsing testo — confronto", box=box.ROUNDED, header_style="bold")
    table.add_column("Provider")
    table.add_column("Score", justify="center")
    table.add_column("%", justify="center")

    text_results = {}
    for provider, cases in data.get("text_parsing", {}).items():
        by_msg = {c["msg"]: c["raw_output"] for c in cases}
        pts, max_pts, details = score_text_parsing(by_msg)
        text_results[provider] = (pts, max_pts, details)
        pct = pts / max_pts * 100 if max_pts else 0
        c = "green" if pct >= 90 else "yellow" if pct >= 70 else "red"
        table.add_row(provider, f"{pts:.1f}/{max_pts:.0f}", f"[{c}]{pct:.0f}%[/{c}]")

    console.print(table)
    console.print()

    for provider, (pts, max_pts, details) in text_results.items():
        fails = [(m, p, mx, n) for m, p, mx, n in details if mx > 0 and p < mx]
        if fails:
            console.print(f"[bold]{provider}[/bold] — casi con punteggio parziale/nullo:")
            for msg, p, mx, notes in fails:
                console.print(f"  [dim]{msg[:45]:45s}[/dim] {p:.1f}/{mx:.0f}  {'; '.join(notes)[:100]}")
            console.print()

    # --- Report ---
    report_table = Table(title="Report settimanale/mensile — confronto", box=box.ROUNDED, header_style="bold")
    report_table.add_column("Provider")
    report_table.add_column("Weekly", justify="center")
    report_table.add_column("Monthly", justify="center")

    reports = data.get("reports", {})
    providers_seen = sorted({k.rsplit("_", 1)[0] for k in reports if k.endswith("_weekly") or k.endswith("_monthly")})
    for provider in providers_seen:
        w = reports.get(f"{provider}_weekly")
        m = reports.get(f"{provider}_monthly")
        if not w or not m:
            continue
        scored = score_reports(w["raw_output"], m["raw_output"])
        w_pct = scored["weekly"]["score"] / scored["weekly"]["max"] * 100
        m_pct = scored["monthly"]["score"] / scored["monthly"]["max"] * 100
        wc = "green" if w_pct >= 90 else "yellow" if w_pct >= 70 else "red"
        mc = "green" if m_pct >= 90 else "yellow" if m_pct >= 70 else "red"
        report_table.add_row(
            provider,
            f"[{wc}]{scored['weekly']['score']}/{scored['weekly']['max']} ({w_pct:.0f}%)[/{wc}]",
            f"[{mc}]{scored['monthly']['score']}/{scored['monthly']['max']} ({m_pct:.0f}%)[/{mc}]",
        )
        if scored["weekly"]["notes"] or scored["monthly"]["notes"]:
            console.print(f"[bold]{provider}[/bold]:")
            for n in scored["weekly"]["notes"]:
                console.print(f"  [dim](weekly) {n}[/dim]")
            for n in scored["monthly"]["notes"]:
                console.print(f"  [dim](monthly) {n}[/dim]")

    console.print()
    console.print(report_table)
    console.print()

    # --- Foto / Audio: solo diagnosi, NON scoring rigoroso (harness inaffidabile) ---
    if "photo" in data:
        console.print("[yellow bold]FOTO — diagnosi qualitativa (non un punteggio comparativo affidabile):[/yellow bold]")
        for provider, cases in data["photo"].items():
            date_correct = 0
            amount_close = 0
            for c in cases:
                parsed = _extract_json(c["raw_output"]) or {}
                gt_total = float(c["ground_truth"]["total"])
                got_amount = parsed.get("amount")
                if got_amount is not None and abs(float(got_amount) - gt_total) < 0.5:
                    amount_close += 1
                # confronto approssimativo: la data GT è dd/mm/yyyy, quella del modello YYYY-MM-DD
                gt_d, gt_m, gt_y = c["ground_truth"]["date"].split("/")
                gt_iso = f"{gt_y}-{gt_m}-{gt_d}"
                if parsed.get("date") == gt_iso:
                    date_correct += 1
            console.print(f"  {provider}: totale corretto in {amount_close}/{len(cases)} casi, "
                           f"data corretta in {date_correct}/{len(cases)} casi (sempre 'oggi', mai quella sullo scontrino)")
        console.print()

    if "audio" in data:
        console.print("[red bold]AUDIO — INVALIDATO: harness di test non funzionante[/red bold]")
        for provider, cases in data["audio"].items():
            outs = [c["raw_output"] for c in cases]
            distinct = len(set(outs))
            console.print(f"  {provider}: {distinct} output distinti su {len(cases)} input DIVERSI "
                           f"({len(cases) - distinct} ripetizioni identiche indipendenti dal contenuto audio)")
        console.print("  [dim]Il modello ignora l'audio e produce risposte generiche/ripetute — "
                       "bug nella pipeline di preprocessing audio del notebook, non un dato valido "
                       "sulla capacità di gemma3n. Non incluso nel confronto finale.[/dim]")


if __name__ == "__main__":
    main()
