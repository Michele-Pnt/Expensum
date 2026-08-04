"""
src/savings_goals_service.py — Logica di calcolo per la feature "Obiettivi di risparmio".

Non e' storage layer: compone in Python i fetch grezzi di FinancialStorage
(fetch_accounts/fetch_income/fetch_all_transactions/get_categories), esattamente
come fanno gli endpoint /api/analytics/wealth, /capital-trend, /budget-status in
src/dashboard/app.py. Il valore "adesso" di un obiettivo non e' mai persistito:
si ricalcola on-read ad ogni chiamata.

5 tipi di obiettivo supportati (vedi SavingsGoal.goal_type):
- net_savings: risparmio netto cumulato (entrate - uscite) dal start_date del goal.
- account_balance: saldo di un conto specifico.
- net_worth: capitale totale (somma saldi di tutti i conti).
- savings_rate: quota di reddito risparmiata nel mese corrente (ricorrente, non
  cumulativo — target_amount e' una percentuale, non un importo).
- category_spending_reduction: spesa mensile in una categoria, da tenere sotto
  una soglia (target_amount).
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date
from math import ceil

from src.wealth import build_wealth_series

GOAL_TYPES = {
    "net_savings",
    "account_balance",
    "net_worth",
    "savings_rate",
    "category_spending_reduction",
}

# Finestra di storico usata per stimare il ritmo mensile (ETA) — stessa finestra
# usata da MonthlyPlanBuilder.MONTHS_HISTORY per coerenza con il resto del progetto.
ETA_HISTORY_MONTHS = 6


# ---------------------------------------------------------------------------
# Helper generici
# ---------------------------------------------------------------------------

def _add_months(d: date, months: int) -> date:
    """Aggiunge N mesi a una data, clampando il giorno se il mese target è più corto."""
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, monthrange(year, month)[1])
    return date(year, month, day)


def _month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def _format_date_it(iso_date: str) -> str:
    """GG-MM-AAAA — stesso formato di frontend/src/lib/date.ts::formatDateIt,
    per non mostrare date in due stili diversi tra webapp e testo del voto."""
    try:
        d = date.fromisoformat(iso_date)
    except ValueError:
        return iso_date
    return d.strftime("%d-%m-%Y")


def _weighted_monthly_delta(values: list[float]) -> float | None:
    """Media ponderata lineare dei delta mese-su-mese di una serie di valori.

    I pesi crescono verso il delta più recente (1..N-1) — coerente con lo schema
    già usato in Forecaster._weighted_variable_avg. Usa TUTTI i mesi della serie,
    non solo i due estremi: un singolo mese anomalo pesa meno di una media di
    soli due punti, ma il ritmo recente conta di più di quello vecchio.
    Ritorna None se la serie ha meno di 2 punti.
    """
    if len(values) < 2:
        return None
    deltas = [values[i] - values[i - 1] for i in range(1, len(values))]
    weights = list(range(1, len(deltas) + 1))
    weight_total = sum(weights)
    if weight_total == 0:
        return None
    return sum(d * w for d, w in zip(deltas, weights)) / weight_total


def _eta_from_increasing_series(
    monthly_values: list[float], current: float, target: float, today: date
) -> date | None:
    """Stima la data di raggiungimento di `target` a partire da una serie mensile
    "più alto è meglio" (per i goal in cui il valore deve ridursi, invertire il
    segno della serie e dei target prima di chiamare questa funzione).

    None se il ritmo medio stimato è <= 0 (obiettivo non raggiungibile al ritmo attuale).
    """
    avg_delta = _weighted_monthly_delta(monthly_values)
    if avg_delta is None or avg_delta <= 0:
        return None
    remaining = target - current
    if remaining <= 0:
        return today
    months_needed = ceil(remaining / avg_delta)
    return _add_months(today, months_needed)


# ---------------------------------------------------------------------------
# Calcolo del valore corrente per tipo di obiettivo
# ---------------------------------------------------------------------------

def _net_savings_current(storage, goal: dict, today: date) -> float:
    """Surplus cumulato (entrate - uscite) dal `start_date` del goal ad oggi."""
    start = date.fromisoformat(goal["start_date"])
    incomes = storage.fetch_income(start, today)
    expenses = storage.fetch_all_transactions(start, today)
    return sum(i["amount"] for i in incomes) - sum(e["amount"] for e in expenses)


def _net_savings_monthly_series(storage, goal: dict, today: date) -> list[float]:
    """Serie mensile del risparmio netto CUMULATO dal start_date, un punto per mese."""
    start = date.fromisoformat(goal["start_date"])
    balances = storage.fetch_monthly_balances(start, today)
    balances.sort(key=lambda b: (b["year"], b["month"]))
    cumulative = 0.0
    series = []
    for b in balances:
        cumulative += b["net_savings"]
        series.append(cumulative)
    return series[-(ETA_HISTORY_MONTHS + 1):]


def _account_balance_current(storage, goal: dict) -> float | None:
    """Saldo corrente del conto associato al goal. None se il conto non esiste più."""
    for acc in storage.fetch_accounts():
        if acc["id"] == goal["account_id"]:
            return acc["current_balance"]
    return None


def _wealth_monthly_series(storage, today: date, account_id: int | None = None) -> list[float]:
    """Serie mensile del capitale (un conto o tutti), ultimi mesi utili per l'ETA.

    Delega a `src.wealth.build_wealth_series`, sorgente unica di verità condivisa
    con /api/analytics/capital-trend.
    """
    series = build_wealth_series(storage, today, account_id=account_id)
    if not series.points:
        return []
    return series.totals[-(ETA_HISTORY_MONTHS + 1):]


def _net_worth_current(storage) -> float:
    return sum(a["current_balance"] for a in storage.fetch_accounts())


def _savings_rate_current_month(storage, today: date) -> dict:
    """Valuta il mese corrente: quota di reddito risparmiata.

    Ritorna {'evaluable': bool, 'saved_pct': float|None, 'income': float, 'spent': float}.
    Non valutabile se il reddito del mese e' zero.
    """
    month_start = _month_start(today)
    incomes = storage.fetch_income(month_start, today)
    expenses = storage.fetch_all_transactions(month_start, today)
    income_mese = sum(i["amount"] for i in incomes)
    spesa_mese = sum(e["amount"] for e in expenses)
    if income_mese <= 0:
        return {"evaluable": False, "saved_pct": None, "income": income_mese, "spent": spesa_mese}
    saved_pct = (income_mese - spesa_mese) / income_mese * 100
    return {"evaluable": True, "saved_pct": saved_pct, "income": income_mese, "spent": spesa_mese}


def _category_name_for(storage, category_id: int | None) -> str | None:
    if category_id is None:
        return None
    for c in storage.get_categories():
        if c["id"] == category_id:
            return c["name"]
    return None


def _category_spending_current_month(storage, goal: dict, today: date) -> float:
    """Spesa nel mese corrente per la categoria del goal (0 se la categoria non esiste più)."""
    cat_name = _category_name_for(storage, goal.get("category_id"))
    if cat_name is None:
        return 0.0
    month_start = _month_start(today)
    expenses = storage.fetch_all_transactions(month_start, today)
    return sum(e["amount"] for e in expenses if (e.get("category") or "") == cat_name)


def _category_spending_monthly_series(storage, goal: dict, today: date) -> list[float]:
    """Serie mensile della spesa nella categoria del goal (ultimi ETA_HISTORY_MONTHS+1 mesi)."""
    cat_name = _category_name_for(storage, goal.get("category_id"))
    if cat_name is None:
        return []
    y, m = today.year, today.month
    for _ in range(ETA_HISTORY_MONTHS):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    start = date(y, m, 1)
    expenses = storage.fetch_all_transactions(start, today)
    totals: dict[tuple[int, int], float] = {}
    for e in expenses:
        if (e.get("category") or "") != cat_name:
            continue
        key = (e["date"].year, e["date"].month)
        totals[key] = totals.get(key, 0.0) + e["amount"]
    return [totals[k] for k in sorted(totals.keys())]


# ---------------------------------------------------------------------------
# API principale: progresso corrente + ETA
# ---------------------------------------------------------------------------

def compute_goal_progress(storage, goal: dict, today: date | None = None) -> dict:
    """Calcola stato attuale, percentuale di completamento e stima ETA per un goal.

    Ritorna un dict con almeno: current, progress_pct, eta_date, evaluable, note.
    `progress_pct` è clampata a [0, 100+] (può superare 100 se il target è già battuto).
    """
    today = today or date.today()
    goal_type = goal["goal_type"]
    target = float(goal["target_amount"])

    if goal_type == "net_savings":
        current = _net_savings_current(storage, goal, today)
        series = _net_savings_monthly_series(storage, goal, today)
        pct = round(max(current, 0.0) / target * 100, 1) if target > 0 else 0.0
        eta = _eta_from_increasing_series(series, current, target, today)
        return {"current": current, "progress_pct": pct, "eta_date": eta, "evaluable": True, "note": None}

    if goal_type == "account_balance":
        current = _account_balance_current(storage, goal)
        if current is None:
            return {"current": None, "progress_pct": 0.0, "eta_date": None,
                     "evaluable": False, "note": "Il conto collegato non esiste più"}
        series = _wealth_monthly_series(storage, today, account_id=goal["account_id"])
        pct = round(max(current, 0.0) / target * 100, 1) if target > 0 else 0.0
        eta = _eta_from_increasing_series(series, current, target, today)
        return {"current": current, "progress_pct": pct, "eta_date": eta, "evaluable": True, "note": None}

    if goal_type == "net_worth":
        current = _net_worth_current(storage)
        series = _wealth_monthly_series(storage, today, account_id=None)
        pct = round(max(current, 0.0) / target * 100, 1) if target > 0 else 0.0
        eta = _eta_from_increasing_series(series, current, target, today)
        return {"current": current, "progress_pct": pct, "eta_date": eta, "evaluable": True, "note": None}

    if goal_type == "savings_rate":
        rate = _savings_rate_current_month(storage, today)
        if not rate["evaluable"]:
            return {"current": None, "progress_pct": 0.0, "eta_date": None,
                     "evaluable": False, "note": "Dati insufficienti (nessuna entrata questo mese)"}
        pct = round(rate["saved_pct"] / target * 100, 1) if target > 0 else 0.0
        return {"current": rate["saved_pct"], "progress_pct": pct, "eta_date": None,
                 "evaluable": True, "note": None}

    if goal_type == "category_spending_reduction":
        spent = _category_spending_current_month(storage, goal, today)
        cat_name = _category_name_for(storage, goal.get("category_id"))
        if cat_name is None:
            return {"current": None, "progress_pct": 0.0, "eta_date": None,
                     "evaluable": False, "note": "La categoria collegata non esiste più"}
        # "Progresso" = quanto sei sotto la soglia (100% = esattamente in linea col target)
        pct = round(max(0.0, (1 - spent / target)) * 100, 1) if target > 0 else 0.0
        series = _category_spending_monthly_series(storage, goal, today)
        # Serie invertita: la spesa deve SCENDERE, quindi trattiamo -spesa come
        # "più alto e' meglio" verso il target -target (stesso schema generico).
        eta = _eta_from_increasing_series(
            [-v for v in series], current=-spent, target=-target, today=today
        )
        return {"current": spent, "progress_pct": pct, "eta_date": eta, "evaluable": True, "note": None}

    raise ValueError(f"goal_type sconosciuto: {goal_type}")


# ---------------------------------------------------------------------------
# Voto mensile
# ---------------------------------------------------------------------------

def _label_from_ratio(ratio: float) -> str:
    if ratio >= 1.1:
        return "In anticipo"
    if ratio >= 0.9:
        return "In linea"
    if ratio >= 0.5:
        return "In ritardo"
    return "A rischio"


def _label_from_pct_no_deadline(pct: float) -> str:
    if pct >= 90:
        return "In anticipo"
    if pct >= 60:
        return "In linea"
    if pct >= 30:
        return "In ritardo"
    return "A rischio"


def compute_monthly_score(storage, goal: dict, progress: dict, today: date | None = None) -> dict:
    """Calcola l'etichetta del voto mensile e i due numeri che lo spiegano.

    Ritorna {'score_label': str, 'pace_effettivo': float|None, 'pace_richiesto': float|None}.
    Per savings_rate il "pace" non si applica: si valuta solo il mese chiuso.
    """
    today = today or date.today()
    goal_type = goal["goal_type"]

    if not progress["evaluable"]:
        return {"score_label": "Dati insufficienti", "pace_effettivo": None, "pace_richiesto": None}

    if goal_type == "savings_rate":
        target = float(goal["target_amount"])
        saved_pct = progress["current"]
        if saved_pct >= target + 5:
            label = "Ottimo mese"
        elif saved_pct >= target:
            label = "Obiettivo centrato"
        elif saved_pct >= target * 0.7:
            label = "Vicino all'obiettivo"
        else:
            label = "Sotto obiettivo"
        return {"score_label": label, "pace_effettivo": saved_pct, "pace_richiesto": target}

    target_date_str = goal.get("target_date")
    if not target_date_str:
        return {
            "score_label": _label_from_pct_no_deadline(progress["progress_pct"]),
            "pace_effettivo": None,
            "pace_richiesto": None,
        }

    target_date = date.fromisoformat(target_date_str)
    start_date = date.fromisoformat(goal["start_date"])
    target = float(goal["target_amount"])
    current = progress["current"]

    months_total = max(1, (target_date.year - start_date.year) * 12 + (target_date.month - start_date.month))
    months_elapsed = max(
        1, (today.year - start_date.year) * 12 + (today.month - start_date.month)
    )
    months_remaining = max(1, months_total - months_elapsed + 1)

    if goal_type == "category_spending_reduction":
        # "pace" qui e' la riduzione di spesa mensile necessaria/effettiva.
        remaining_reduction = max(0.0, current - target)
        pace_richiesto = remaining_reduction / months_remaining
        series = _category_spending_monthly_series(storage, goal, today)
        pace_effettivo = _weighted_monthly_delta([-v for v in series]) if len(series) >= 2 else None
    else:
        pace_richiesto = (target - current) / months_remaining if target > current else 0.0
        if goal_type == "net_savings":
            series = _net_savings_monthly_series(storage, goal, today)
        elif goal_type == "account_balance":
            series = _wealth_monthly_series(storage, today, account_id=goal["account_id"])
        else:  # net_worth
            series = _wealth_monthly_series(storage, today, account_id=None)
        pace_effettivo = _weighted_monthly_delta(series) if len(series) >= 2 else None

    if pace_richiesto <= 0:
        label = _label_from_pct_no_deadline(progress["progress_pct"])
    elif pace_effettivo is None:
        label = "Dati insufficienti"
    else:
        label = _label_from_ratio(pace_effettivo / pace_richiesto)

    return {"score_label": label, "pace_effettivo": pace_effettivo, "pace_richiesto": pace_richiesto}


# ---------------------------------------------------------------------------
# Spiegazione testuale — stessa funzione per webapp e Telegram
# ---------------------------------------------------------------------------

def explain_score(goal: dict, score: dict, markdown: bool = True) -> str:
    """Genera la frase di spiegazione del voto, identica (a meno dello stile) su
    webapp e Telegram — mai numeri incoerenti tra i due canali.
    """
    label = score["score_label"]
    bold = (lambda s: f"**{s}**") if markdown else (lambda s: s)

    if label == "Dati insufficienti":
        return f"{bold(label)} — non ci sono ancora abbastanza dati per valutare questo obiettivo."

    if goal["goal_type"] == "savings_rate":
        saved_pct = score["pace_effettivo"]
        target_pct = score["pace_richiesto"]
        return (
            f"{bold(label)} — questo mese hai risparmiato il {saved_pct:.0f}% del reddito, "
            f"il tuo obiettivo è {target_pct:.0f}%."
        )

    pace_eff = score.get("pace_effettivo")
    pace_req = score.get("pace_richiesto")
    if pace_eff is None or pace_req is None or pace_req <= 0:
        return f"{bold(label)} — obiettivo raggiunto o senza scadenza definita."

    target_date_str = goal.get("target_date")
    target_label = f" entro {_format_date_it(target_date_str)}" if target_date_str else ""
    return (
        f"{bold(label)} — stai risparmiando ~{pace_eff:.0f}€/mese, per centrare "
        f"l'obiettivo{target_label} ne servirebbero ~{pace_req:.0f}€/mese."
    )


# ---------------------------------------------------------------------------
# Hook per un futuro agente RAG conversazionale (nessun agente costruito qui)
# ---------------------------------------------------------------------------

def get_savings_goals_context(storage) -> dict:
    """Riassunto strutturato dei goal dell'utente, pensato per essere iniettato
    nel contesto di un futuro agente conversazionale. Nessuna logica di
    prompting qui — solo dati, nessun testo generato da LLM.
    """
    active = storage.fetch_savings_goals(status="active")
    completed = storage.fetch_savings_goals(status="completed")

    def _summarize(g: dict) -> dict:
        progress = compute_goal_progress(storage, g)
        score = compute_monthly_score(storage, g, progress)
        return {
            "id": g["id"],
            "name": g["name"],
            "goal_type": g["goal_type"],
            "progress_pct": progress["progress_pct"],
            "score_label": score["score_label"],
            "eta_date": progress["eta_date"].isoformat() if progress["eta_date"] else None,
        }

    return {
        "active_goals": [_summarize(g) for g in active],
        "completed_goals": [{"id": g["id"], "name": g["name"]} for g in completed],
    }


# ---------------------------------------------------------------------------
# Rilevamento del raggiungimento, in tempo reale
# ---------------------------------------------------------------------------

def is_goal_reached(storage, goal: dict, today: date | None = None) -> bool:
    """True se l'obiettivo è già raggiunto, calcolato senza le serie storiche.

    Variante leggera di `compute_goal_progress`: salta la ricostruzione mensile
    necessaria all'ETA e calcola solo il valore corrente. Serve a rilevare il
    traguardo subito dopo una transazione, invece di aspettare il job del 1° del
    mese, senza appesantire il salvataggio della spesa.

    `savings_rate` è escluso di proposito: è un obiettivo ricorrente mese per mese,
    non si "completa" mai — stessa regola del job mensile.
    """
    today = today or date.today()
    goal_type = goal["goal_type"]
    target = float(goal["target_amount"])
    if target <= 0 or goal_type == "savings_rate":
        return False

    if goal_type == "net_savings":
        return _net_savings_current(storage, goal, today) >= target
    if goal_type == "account_balance":
        current = _account_balance_current(storage, goal)
        return current is not None and current >= target
    if goal_type == "net_worth":
        return _net_worth_current(storage) >= target
    if goal_type == "category_spending_reduction":
        # Obiettivo di contenimento: "raggiunto" significa aver chiuso il mese
        # sotto soglia, cosa che si può dire solo a mese finito. In corsa non si
        # completa mai: resta al job mensile.
        return False
    return False


def detect_completed_goals(storage, today: date | None = None) -> list[dict]:
    """Obiettivi attivi che risultano raggiunti adesso.

    Pensata per essere chiamata dopo una transazione confermata: non solleva mai,
    perché un errore qui non deve poter far fallire il salvataggio della spesa.
    """
    try:
        goals = storage.fetch_savings_goals(status="active")
    except Exception:  # noqa: BLE001 — backend senza obiettivi o errore transitorio
        return []

    reached = []
    for goal in goals:
        try:
            if is_goal_reached(storage, goal, today):
                reached.append(goal)
        except Exception:  # noqa: BLE001 — un goal malformato non blocca gli altri
            continue
    return reached
