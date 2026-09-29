"""
src/data_processor.py — Elaborazione, aggregazione e analisi statistica
delle transazioni di spesa.

Funzionalità:
- Aggregazione per mese e categoria
- Calcolo statistiche mensili (totale, media, top categorie)
- Analisi dei trend (confronto mese attuale vs media storica)
- Rilevamento anomalie (variazioni sopra soglia configurabile)
- Compattazione dati in testo strutturato per il prompt AI
- Analisi settimanale: pattern per categoria, residuo mensile, momentum
"""

import logging
import math
from calendar import month_name
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional

from config import Config

logger = logging.getLogger("financial_agent.processor")


# ---------------------------------------------------------------------------
# Strutture dati di output
# ---------------------------------------------------------------------------

class MonthlySummary:
    """Riepilogo delle spese di un singolo mese."""

    def __init__(self, year: int, month: int):
        self.year = year
        self.month = month
        self.label = f"{month_name[month]} {year}"
        self.total: float = 0.0
        self.by_category: dict[str, float] = {}
        self.by_category_average: dict[str, float] = {}
        self.transaction_count: int = 0
        self.daily_avg: float = 0.0

    def top_categories(self, n: int = 5) -> list[tuple[str, float]]:
        """Ritorna le top N categorie per importo, ordinate discendente."""
        return sorted(self.by_category.items(), key=lambda x: x[1], reverse=True)[:n]

    def __repr__(self) -> str:
        return f"MonthlySummary({self.label}, totale={self.total:.2f}€)"


class TrendReport:
    """Risultato dell'analisi dei trend."""

    def __init__(self):
        self.current_month: Optional[MonthlySummary] = None
        self.history: list[MonthlySummary] = []
        self.historical_avg: float = 0.0
        self.delta_pct: float = 0.0          # % variazione rispetto alla media storica
        self.trend_direction: str = "stabile" # "crescita" | "contrazione" | "stabile"
        self.total_income: float = 0.0
        self.incomes: list[dict] = []


# ---------------------------------------------------------------------------
# DataProcessor principale
# ---------------------------------------------------------------------------

class DataProcessor:
    """Elabora le transazioni grezze e produce statistiche e analisi."""

    def __init__(self):
        self.history_months = Config.HISTORY_MONTHS

    # ------------------------------------------------------------------
    # Punto d'ingresso principale
    # ------------------------------------------------------------------
    def process(
        self,
        transactions: list[dict],
        target_year: int,
        target_month: int,
        incomes: list[dict] = None,
    ) -> TrendReport:
        """
        Elabora tutte le transazioni e produce un TrendReport completo.

        Args:
            transactions: Lista di dict {date, category, name, amount}
            target_year: Anno del mese da analizzare
            target_month: Mese da analizzare (1-12)

        Returns:
            TrendReport con mese corrente, storico e anomalie
        """
        if not transactions:
            logger.warning("Nessuna transazione ricevuta!")
            return TrendReport()

        df = self._to_dataframe(transactions)
        monthly_summaries = self._aggregate_by_month(df)

        report = TrendReport()
        report.current_month = monthly_summaries.get((target_year, target_month))

        if report.current_month is None:
            logger.warning(
                f"Nessuna transazione trovata per {month_name[target_month]} {target_year}"
            )
            report.current_month = MonthlySummary(target_year, target_month)

        # Storico: ultimi N mesi ESCLUSO il mese corrente
        hist_keys = sorted(
            [k for k in monthly_summaries if k != (target_year, target_month)]
        )[-self.history_months:]
        report.history = [monthly_summaries[k] for k in hist_keys]

        # Trend globale
        if report.history:
            report.historical_avg = sum(m.total for m in report.history) / len(report.history)
            if report.historical_avg > 0:
                report.delta_pct = (
                    (report.current_month.total - report.historical_avg)
                    / report.historical_avg
                ) * 100
                if report.delta_pct > 5:
                    report.trend_direction = "crescita"
                elif report.delta_pct < -5:
                    report.trend_direction = "contrazione"
                else:
                    report.trend_direction = "stabile"

        if incomes:
            # Filtra le entrate fittizie
            filtered_incomes = [
                inc for inc in incomes 
                if inc.get("name") not in ["Movimenti", "Pareggio Conti"]
            ]
            report.incomes = filtered_incomes
            report.total_income = sum(
                inc["amount"] for inc in filtered_incomes 
                if inc["date"].year == target_year and inc["date"].month == target_month
            )

        logger.info(
            f"Elaborazione completata: {report.current_month.label}, "
            f"totale_spese={report.current_month.total:.2f}€, "
            f"totale_entrate={report.total_income:.2f}€, "
            f"trend={report.trend_direction} ({report.delta_pct:+.1f}%)"
        )
        return report

    # ------------------------------------------------------------------
    # Aggregazione per mese
    # ------------------------------------------------------------------
    def _to_dataframe(self, transactions: list[dict]):
        import pandas as pd
        df = pd.DataFrame(transactions)
        
        # Filtra le finte spese (trasferimenti/pareggi)
        df = df[~df["category"].isin(["Movimenti", "Pareggio Conti"])]
        
        df["date"] = pd.to_datetime(df["date"])
        df["year"] = df["date"].dt.year
        df["month"] = df["date"].dt.month
        df["amount"] = df["amount"].abs()  # Normalizza a positivo
        return df

    def _aggregate_by_month(self, df) -> dict[tuple, MonthlySummary]:
        """Aggrega le transazioni per (anno, mese) e ritorna un dict di MonthlySummary."""
        import pandas as pd
        summaries: dict[tuple, MonthlySummary] = {}

        for (year, month), group in df.groupby(["year", "month"]):
            summary = MonthlySummary(int(year), int(month))
            summary.total = float(group["amount"].sum())
            summary.transaction_count = len(group)

            # Giorni nel mese per media giornaliera
            days_in_month = (
                pd.Timestamp(year, month, 1) + pd.offsets.MonthEnd(0)
            ).day
            summary.daily_avg = summary.total / days_in_month

            # Aggregazione per categoria
            cat_totals = group.groupby("category")["amount"].sum()
            summary.by_category = cat_totals.to_dict()
            
            # Recupero medie Notion per le categorie di questo mese
            if "category_average" in group.columns:
                cat_averages = group.groupby("category")["category_average"].first()
                summary.by_category_average = cat_averages.to_dict()

            summaries[(int(year), int(month))] = summary

        return summaries



    # ------------------------------------------------------------------
    # Compattazione dati per il prompt Gemini
    # ------------------------------------------------------------------
    def to_prompt_text(self, report: TrendReport) -> str:
        """
        Compatta il TrendReport in un unico blocco di testo strutturato
        da inserire nel prompt Gemini, minimizzando i token usati.
        """
        lines = []
        cur = report.current_month

        lines.append(f"=== MESE ANALIZZATO: {cur.label} ===")
        lines.append(f"Spese totali: €{cur.total:.2f}")
        lines.append(f"Entrate totali (Income): €{report.total_income:.2f}")
        lines.append(f"Numero transazioni spesa: {cur.transaction_count}")
        lines.append(f"Media giornaliera spese: €{cur.daily_avg:.2f}")
        lines.append("")
        lines.append("SPESE PER CATEGORIA MESE ATTUALE VS BUDGET/MEDIA (da Notion):")
        for cat, amt in sorted(cur.by_category.items(), key=lambda x: x[1], reverse=True):
            pct = (amt / cur.total * 100) if cur.total > 0 else 0
            avg_notion = cur.by_category_average.get(cat, 0.0)
            avg_info = f"vs Media Notion €{avg_notion:.2f}" if avg_notion > 0 else "(no media Notion)"
            lines.append(f"  {cat}: €{amt:.2f} ({pct:.1f}%) {avg_info}")

        lines.append("")
        lines.append(f"=== STORICO ULTIMI {len(report.history)} MESI ===")
        lines.append(f"Media mensile storica: €{report.historical_avg:.2f}")
        lines.append(f"Variazione vs media: {report.delta_pct:+.1f}% ({report.trend_direction})")
        lines.append("")
        lines.append("DETTAGLIO MESI PRECEDENTI:")
        for m in report.history:
            lines.append(f"  {m.label}: €{m.total:.2f} ({m.transaction_count} transazioni)")



        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Strutture dati per il piano settimanale
# ---------------------------------------------------------------------------

class WeeklyCategoryStats:
    """Statistiche settimanali per una singola categoria."""

    def __init__(self, name: str):
        self.name = name
        self.weekly_amounts: list[float] = []   # importo per ciascuna delle 8 settimane
        self.mean: float = 0.0
        self.std_dev: float = 0.0
        self.p75: float = 0.0                   # 75° percentile
        self.day_of_week_share: dict[int, float] = {}  # 0=Lun ... 6=Dom → % media settimana


class WeeklyAnalysis:
    """Output completo dell'analisi settimanale."""

    def __init__(self):
        self.category_stats: dict[str, WeeklyCategoryStats] = {}
        self.spent_this_month_by_cat: dict[str, float] = {}
        self.total_spent_this_month: float = 0.0
        self.weeks_remaining: float = 1.0
        self.momentum: dict[str, str] = {}   # categoria → "in miglioramento" | "stabile" | "in peggioramento"
        self.target_by_cat: dict[str, float] = {}   # target settimanale per categoria


# ---------------------------------------------------------------------------
# WeeklyPatternAnalyzer
# ---------------------------------------------------------------------------

class WeeklyPatternAnalyzer:
    """Analizza i pattern di spesa settimanale dalle ultime N settimane."""

    WEEKS_HISTORY = 8
    # Categorie filtrate (trasferimenti interni)
    _FAKE_CATEGORIES = frozenset(["Movimenti", "Pareggio Conti"])

    def compute(self, transactions: list[dict]) -> dict[str, WeeklyCategoryStats]:
        """
        Aggrega le transazioni per settimana ISO e categoria.

        Args:
            transactions: lista di dict {date, category, amount, ...}
                          coprono almeno le ultime 8 settimane

        Returns:
            dict categoria → WeeklyCategoryStats
        """
        if not transactions:
            return {}

        today = date.today()
        # Settimana ISO: (anno, numero_settimana)
        week_of = lambda d: (d.isocalendar()[0], d.isocalendar()[1])
        current_week = week_of(today)

        # Costruisco la lista ordinata delle 8 settimane (esclusa la corrente)
        week_sequence: list[tuple] = []
        cursor = today - timedelta(days=today.weekday())  # lunedì corrente
        for _ in range(self.WEEKS_HISTORY):
            cursor -= timedelta(weeks=1)
            w = week_of(cursor)
            week_sequence.append(w)
        week_sequence.reverse()   # ordine cronologico

        week_set = set(week_sequence)

        # Aggregazione: {categoria: {settimana: totale}} e day_of_week
        cat_week: dict[str, dict[tuple, float]] = defaultdict(lambda: defaultdict(float))
        cat_dow: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))

        for tx in transactions:
            cat = str(tx.get("category") or "Altro")
            if cat in self._FAKE_CATEGORIES:
                continue
            tx_date = tx.get("date")
            if isinstance(tx_date, str):
                tx_date = date.fromisoformat(tx_date)
            if not isinstance(tx_date, date):
                continue
            w = week_of(tx_date)
            if w not in week_set:
                continue
            amt = abs(float(tx.get("amount", 0.0)))
            cat_week[cat][w] += amt
            cat_dow[cat][tx_date.weekday()] += amt

        stats: dict[str, WeeklyCategoryStats] = {}
        for cat, week_totals in cat_week.items():
            s = WeeklyCategoryStats(cat)
            s.weekly_amounts = [week_totals.get(w, 0.0) for w in week_sequence]
            n = len(s.weekly_amounts)
            s.mean = sum(s.weekly_amounts) / n
            variance = sum((x - s.mean) ** 2 for x in s.weekly_amounts) / n
            s.std_dev = math.sqrt(variance)
            sorted_amounts = sorted(s.weekly_amounts)
            # p75 tramite interpolazione lineare
            idx = 0.75 * (n - 1)
            lo, hi = int(idx), min(int(idx) + 1, n - 1)
            s.p75 = sorted_amounts[lo] + (idx - lo) * (sorted_amounts[hi] - sorted_amounts[lo])
            # Distribuzione giorno della settimana
            dow_total = sum(cat_dow[cat].values())
            s.day_of_week_share = {
                d: cat_dow[cat][d] / dow_total if dow_total > 0 else 0.0
                for d in range(7)
            }
            stats[cat] = s

        return stats


# ---------------------------------------------------------------------------
# MonthlyResidualCalc
# ---------------------------------------------------------------------------

class MonthlyResidualCalc:
    """Calcola quanto budget rimane per categoria nel mese corrente."""

    def compute(
        self,
        transactions_this_month: list[dict],
        categories: list[dict],
        reference_date: date | None = None,
    ) -> tuple[dict[str, float], dict[str, float], float]:
        """
        Args:
            transactions_this_month: transazioni dal 1° del mese a oggi
            categories: lista di dict {name, monthly_budget, ...}
            reference_date: data di riferimento (default: oggi)

        Returns:
            (spent_by_cat, budget_by_cat, weeks_remaining)
            - spent_by_cat: speso per categoria nel mese
            - budget_by_cat: budget mensile per categoria (None → 0)
            - weeks_remaining: settimane equivalenti rimaste nel mese (min 1.0)
        """
        ref = reference_date or date.today()

        # Calcolo settimane rimaste (fino a fine mese)
        import calendar
        last_day = calendar.monthrange(ref.year, ref.month)[1]
        end_of_month = date(ref.year, ref.month, last_day)
        days_remaining = (end_of_month - ref).days + 1
        weeks_remaining = max(days_remaining / 7.0, 1.0)

        # Budget per categoria
        budget_by_cat = {
            c["name"]: float(c["monthly_budget"] or 0.0)
            for c in categories
            if c.get("monthly_budget")
        }

        # Speso per categoria questo mese
        spent_by_cat: dict[str, float] = defaultdict(float)
        for tx in transactions_this_month:
            cat = str(tx.get("category") or "Altro")
            if cat in ("Movimenti", "Pareggio Conti"):
                continue
            spent_by_cat[cat] += abs(float(tx.get("amount", 0.0)))

        return dict(spent_by_cat), budget_by_cat, weeks_remaining


# ---------------------------------------------------------------------------
# CategoryMomentum
# ---------------------------------------------------------------------------

class CategoryMomentum:
    """Calcola il momentum di spesa per categoria (ultime 4 settimane vs media 8w)."""

    IMPROVEMENT_THRESHOLD = -0.10    # -10% vs media → "in miglioramento"
    WORSENING_THRESHOLD = 0.10       # +10% vs media → "in peggioramento"

    def compute(self, category_stats: dict[str, WeeklyCategoryStats]) -> dict[str, str]:
        """
        Args:
            category_stats: output di WeeklyPatternAnalyzer.compute()

        Returns:
            dict categoria → "in miglioramento" | "stabile" | "in peggioramento"
        """
        momentum: dict[str, str] = {}
        for cat, s in category_stats.items():
            if len(s.weekly_amounts) < 4:
                momentum[cat] = "stabile"
                continue
            last_4w_avg = sum(s.weekly_amounts[-4:]) / 4
            if s.mean > 0:
                delta = (last_4w_avg - s.mean) / s.mean
                if delta <= self.IMPROVEMENT_THRESHOLD:
                    momentum[cat] = "in miglioramento"
                elif delta >= self.WORSENING_THRESHOLD:
                    momentum[cat] = "in peggioramento"
                else:
                    momentum[cat] = "stabile"
            else:
                momentum[cat] = "stabile"
        return momentum


# ---------------------------------------------------------------------------
# WeeklyTargetCalc
# ---------------------------------------------------------------------------

class WeeklyTargetCalc:
    """Calcola il target settimanale per categoria combinando residuo e momentum."""

    def compute(
        self,
        category_stats: dict[str, WeeklyCategoryStats],
        spent_by_cat: dict[str, float],
        budget_by_cat: dict[str, float],
        momentum: dict[str, str],
        weeks_remaining: float,
    ) -> dict[str, float]:
        """
        Returns:
            dict categoria → target settimanale in €
        """
        targets: dict[str, float] = {}
        all_cats = set(category_stats.keys()) | set(budget_by_cat.keys())

        for cat in all_cats:
            stats = category_stats.get(cat)
            budget = budget_by_cat.get(cat, 0.0)
            spent = spent_by_cat.get(cat, 0.0)
            mom = momentum.get(cat, "stabile")

            if budget > 0:
                residuo = max(budget - spent, 0.0)
                base_target = residuo / weeks_remaining
            elif stats:
                base_target = stats.mean
            else:
                continue

            if mom == "in miglioramento":
                target = base_target * 0.95
            elif mom == "in peggioramento" and stats:
                target = max(base_target, stats.mean * 1.05)
            else:
                target = base_target

            targets[cat] = round(target, 2)

        return targets


# ---------------------------------------------------------------------------
# WeeklyBudgetCalc — limite reale + soft cap per categoria
# ---------------------------------------------------------------------------

class CategoryBudgetResult:
    """Risultato del calcolo budget settimanale per una singola categoria."""

    def __init__(self):
        self.budget_monthly: float = 0.0
        self.spent_month: float = 0.0
        self.residuo: float = 0.0
        self.overrun: float = 0.0
        self.limite_reale: float = 0.0
        self.recent_weekly_pace: float = 0.0
        self.soft_cap: float | None = None
        self.reduction_pct: float = 0.0
        self.soft_cap_reason: str = ""
        self.status: str = "ok"   # "ok" | "attenzione" | "sforato"


class WeeklyBudgetCalc:
    """Calcola limite reale e soft cap settimanale per categoria.

    - limite_reale = residuo_budget_mensile / settimane_restanti
    - soft_cap = limite_reale * (1 - riduzione), solo se trend in peggioramento recente
    - riduzione proporzionale al delta ultime 4w vs media 8w, capped al 25%
    - status basato sul confronto tra ultima settimana completa e limite reale
    """

    MAX_REDUCTION = 0.25
    SOFTCAP_THRESHOLD = 0.10   # soglia minima +10% per applicare soft cap

    def compute(
        self,
        budget_by_cat: dict[str, float],
        spent_by_cat: dict[str, float],
        weeks_remaining: float,
        pattern_stats: dict[str, "WeeklyCategoryStats"],
        reference_date: "date | None" = None,
        recent_spent_by_cat: dict[str, float] | None = None,
    ) -> dict[str, CategoryBudgetResult]:
        """
        Args:
            budget_by_cat: budget mensile per categoria (solo categorie con budget)
            spent_by_cat: speso nel mese corrente per categoria
            weeks_remaining: settimane equivalenti rimaste nel mese (min 1.0)
            pattern_stats: output WeeklyPatternAnalyzer — usato per calcolare soft cap
            reference_date: mantenuto per compatibilità dei chiamanti
            recent_spent_by_cat: spesa dell'ultima settimana completa per categoria

        Returns:
            dict categoria → CategoryBudgetResult (solo categorie CON budget)
        """
        _ = reference_date
        recent_spent_by_cat = recent_spent_by_cat or {}

        results: dict[str, CategoryBudgetResult] = {}

        for cat, budget in budget_by_cat.items():
            if budget <= 0:
                continue

            spent = spent_by_cat.get(cat, 0.0)
            residuo = max(budget - spent, 0.0)
            overrun = max(spent - budget, 0.0)
            limite_reale = residuo / weeks_remaining if weeks_remaining > 0 else 0.0
            recent_weekly_pace = recent_spent_by_cat.get(cat, 0.0)

            # Soft cap: calcola delta reale da pattern_stats (usato solo per limite visivo)
            soft_cap: float | None = None
            reduction_pct = 0.0
            soft_cap_reason = ""

            stats = pattern_stats.get(cat)
            if stats and len(stats.weekly_amounts) >= 4 and stats.mean > 0:
                last_4w_avg = sum(stats.weekly_amounts[-4:]) / 4
                delta = (last_4w_avg - stats.mean) / stats.mean
                if delta > self.SOFTCAP_THRESHOLD:
                    reduction_pct = min(delta, self.MAX_REDUCTION)
                    soft_cap = round(limite_reale * (1 - reduction_pct), 2)
                    soft_cap_reason = (
                        f"ultime 4 sett. +{delta * 100:.0f}% vs media 8 sett."
                    )

            if overrun > 0:
                status = "sforato"
            elif recent_weekly_pace > limite_reale:
                status = "attenzione"
            else:
                status = "ok"

            r = CategoryBudgetResult()
            r.budget_monthly = budget
            r.spent_month = spent
            r.residuo = round(residuo, 2)
            r.overrun = round(overrun, 2)
            r.limite_reale = round(limite_reale, 2)
            r.recent_weekly_pace = round(recent_weekly_pace, 2)
            r.soft_cap = soft_cap
            r.reduction_pct = round(reduction_pct * 100, 1)
            r.soft_cap_reason = soft_cap_reason
            r.status = status
            results[cat] = r

        return results


# ---------------------------------------------------------------------------
# Monthly Plan analysis
# ---------------------------------------------------------------------------

class MonthlyCategoryStats:
    """Statistiche mensili per una singola categoria (storico 6 mesi)."""

    def __init__(self, name: str):
        self.name: str = name
        self.monthly_amounts: list[float] = []   # importo per ciascuno dei 6 mesi (cronologico)
        self.mean_monthly: float = 0.0
        self.std_dev: float = 0.0
        self.p75: float = 0.0
        self.trend: str = "stabile"              # "in crescita" | "stabile" | "in calo"


class MonthlyPatternAnalyzer:
    """Analizza i pattern di spesa mensile degli ultimi 6 mesi completati."""

    MONTHS_HISTORY = 6
    TREND_THRESHOLD = 0.10   # ±10% per classificare il trend

    def compute(self, transactions: list[dict]) -> dict[str, MonthlyCategoryStats]:
        """
        Aggrega le transazioni per mese e categoria.

        Args:
            transactions: lista di dict {date, category, amount, ...}
                          coprono gli ultimi 6 mesi completati (escluso mese corrente)

        Returns:
            dict categoria → MonthlyCategoryStats
        """
        if not transactions:
            return {}

        today = date.today()

        # Costruisce la sequenza degli ultimi 6 mesi completati in ordine cronologico
        month_sequence: list[tuple[int, int]] = []
        cursor_year, cursor_month = today.year, today.month
        for _ in range(self.MONTHS_HISTORY):
            cursor_month -= 1
            if cursor_month == 0:
                cursor_month = 12
                cursor_year -= 1
            month_sequence.append((cursor_year, cursor_month))
        month_sequence.reverse()

        month_set = set(month_sequence)

        # Aggregazione: {categoria: {(anno, mese): totale}}
        cat_month: dict[str, dict[tuple[int, int], float]] = defaultdict(lambda: defaultdict(float))

        for tx in transactions:
            cat = str(tx.get("category") or "Altro")
            tx_date = tx.get("date")
            if isinstance(tx_date, str):
                try:
                    tx_date = date.fromisoformat(tx_date)
                except ValueError:
                    continue
            if not isinstance(tx_date, date):
                continue
            ym = (tx_date.year, tx_date.month)
            if ym not in month_set:
                continue
            amt = abs(float(tx.get("amount", 0.0)))
            cat_month[cat][ym] += amt

        stats: dict[str, MonthlyCategoryStats] = {}
        for cat, month_totals in cat_month.items():
            s = MonthlyCategoryStats(cat)
            s.monthly_amounts = [month_totals.get(m, 0.0) for m in month_sequence]
            n = len(s.monthly_amounts)
            s.mean_monthly = sum(s.monthly_amounts) / n
            variance = sum((x - s.mean_monthly) ** 2 for x in s.monthly_amounts) / n
            s.std_dev = math.sqrt(variance)
            sorted_amounts = sorted(s.monthly_amounts)
            idx = 0.75 * (n - 1)
            lo, hi = int(idx), min(int(idx) + 1, n - 1)
            s.p75 = sorted_amounts[lo] + (idx - lo) * (sorted_amounts[hi] - sorted_amounts[lo])

            # Trend: ultimi 3 mesi vs primi 3 mesi
            first3_avg = sum(s.monthly_amounts[:3]) / 3
            last3_avg = sum(s.monthly_amounts[-3:]) / 3
            if first3_avg > 0:
                delta = (last3_avg - first3_avg) / first3_avg
                if delta > self.TREND_THRESHOLD:
                    s.trend = "in crescita"
                elif delta < -self.TREND_THRESHOLD:
                    s.trend = "in calo"
                else:
                    s.trend = "stabile"
            elif last3_avg > 0:
                s.trend = "in crescita"
            else:
                s.trend = "stabile"

            stats[cat] = s

        return stats


class IncomeForecaster:
    """Prevede le entrate del mese successivo basandosi sulla media degli ultimi 6 mesi."""

    MONTHS_LOOKBACK = 6

    def compute(
        self,
        incomes_history: list[dict],
        reference_date: date | None = None,
    ) -> float:
        """
        Args:
            incomes_history: lista di dict {date, amount, name, ...}
                             coprono gli ultimi 6 mesi completati
            reference_date: data che definisce il mese corrente; se omessa usa oggi.

        Returns:
            Media mensile delle entrate (float)
        """
        if not incomes_history:
            return 0.0

        today = reference_date or date.today()

        # Costruisce i 6 mesi completati
        month_sequence: list[tuple[int, int]] = []
        cursor_year, cursor_month = today.year, today.month
        for _ in range(self.MONTHS_LOOKBACK):
            cursor_month -= 1
            if cursor_month == 0:
                cursor_month = 12
                cursor_year -= 1
            month_sequence.append((cursor_year, cursor_month))

        month_set = set(month_sequence)
        monthly_totals: dict[tuple[int, int], float] = {m: 0.0 for m in month_set}

        for inc in incomes_history:
            inc_date = inc.get("date")
            if isinstance(inc_date, str):
                try:
                    inc_date = date.fromisoformat(inc_date)
                except ValueError:
                    continue
            if not isinstance(inc_date, date):
                continue
            ym = (inc_date.year, inc_date.month)
            if ym not in month_set:
                continue
            monthly_totals[ym] += abs(float(inc.get("amount", 0.0)))

        total = sum(monthly_totals.values())
        if total == 0:
            return 0.0
        return total / self.MONTHS_LOOKBACK


class MonthlyBudgetTargetCalc:
    """Calcola il target mensile per categoria combinando budget, storico e trend."""

    TREND_GROWTH_FACTOR = 1.05   # +5% se il trend è in crescita
    TREND_DECLINE_FACTOR = 0.95  # -5% se il trend è in calo

    def compute(
        self,
        pattern_stats: dict[str, MonthlyCategoryStats],
        categories: list[dict],
        income_forecast: float,
        subscriptions_total: float,
    ) -> dict[str, float]:
        """
        Args:
            pattern_stats: output di MonthlyPatternAnalyzer.compute()
            categories: lista da storage.get_categories() con {name, monthly_budget}
            income_forecast: entrate previste (informativo, non usato nel calcolo target)
            subscriptions_total: totale abbonamenti mese (informativo)

        Returns:
            dict categoria → target mensile in €
        """
        budget_by_cat = {
            c["name"]: float(c["monthly_budget"] or 0.0)
            for c in categories
            if c.get("monthly_budget")
        }

        targets: dict[str, float] = {}
        all_cats = set(pattern_stats.keys()) | set(budget_by_cat.keys())

        for cat in all_cats:
            stats = pattern_stats.get(cat)
            budget = budget_by_cat.get(cat, 0.0)

            if budget > 0:
                base_target = budget
            elif stats:
                base_target = stats.mean_monthly
            else:
                continue

            if stats:
                if stats.trend == "in crescita":
                    target = base_target * self.TREND_GROWTH_FACTOR
                elif stats.trend == "in calo":
                    target = base_target * self.TREND_DECLINE_FACTOR
                else:
                    target = base_target
            else:
                target = base_target

            targets[cat] = round(target, 2)

        return targets
