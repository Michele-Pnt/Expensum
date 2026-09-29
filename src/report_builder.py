"""
src/report_builder.py — Assembla il contenuto strutturato dei report mostrati
in webapp (settimanale, mensile "pesante", piano mensile previsionale).

Il layout (KPI, tabelle, elenchi) è sempre costruito qui in modo deterministico
a partire dai dati statistici: l'AI (quando disponibile) contribuisce solo la
prosa narrativa e i consigli, mai numeri o tabelle — vedi `ReportContent` in
`src/report_schema.py`. In modalità dry-run (o in caso di fallimento AI), la
narrazione ricade su testo generato localmente senza chiamare Mistral.
"""

import calendar as _calendar
import logging
from datetime import date, timedelta
from typing import TYPE_CHECKING

from src.data_processor import (
    TrendReport,
    WeeklyPatternAnalyzer,
    MonthlyResidualCalc,
    CategoryMomentum,
    MonthlySummary,
    MonthlyPatternAnalyzer,
    MonthlyCategoryStats,
    MonthlyBudgetTargetCalc,
    WeeklyBudgetCalc,
    CategoryBudgetResult,
)
from src.income_forecast import IncomeForecastEngine
from src.forecaster import ForecastResult
from src.report_schema import (
    ListSection,
    ReportContent,
    TableSection,
    kpi,
    list_section,
    narrative_section,
    new_report_content,
    table_section,
    validated_str_list,
)

if TYPE_CHECKING:
    from src.storage.base import FinancialStorage

logger = logging.getLogger("financial_agent.report_builder")

# Indice di sezione da cui il piano Free sfoca il contenuto: 0 = blocca TUTTE
# le sezioni, lasciando visibili solo titolo e KPI come "peek" (stesso confine
# del vecchio schema Markdown, dove il peek era il paragrafo di riepilogo
# prima della tabella categorie — vedi splitReportPeek in ReportContent.tsx).
# Le sezioni contengono sempre dati reali (tabelle, importi): NON usare un
# indice > 0, altrimenti la prima sezione (es. "Spesa per categorie") resta
# in chiaro anche per un utente bloccato.
_LOCKED_FROM_SECTION = 0


class ReportBuilder:
    """Assembla il contenuto strutturato del report mensile "pesante"."""

    @staticmethod
    def build_content(
        report: TrendReport,
        forecast: ForecastResult,
        accounts: list[dict] | None = None,
        budget_by_cat: dict[str, float] | None = None,
        net_savings: float | None = None,
        ai_narrative: dict | None = None,
    ) -> ReportContent:
        """Costruisce il report mensile "pesante" come `ReportContent`.

        `ai_narrative`, se fornito e valido, sostituisce i paragrafi di analisi
        e i consigli generati staticamente con la prosa di Mistral — atteso
        nella forma `{"trend_paragraphs": [...], "tips": [...]}`. KPI e tabella
        categorie sono SEMPRE calcolati qui dai dati reali, mai dall'AI.
        """
        cur = report.current_month
        accounts = accounts or []

        tot_acc = sum(a.get("current_balance", 0.0) for a in accounts)
        kpis = [
            kpi("Spesa totale", f"€{cur.total:.2f}"),
            kpi("Entrate totali", f"€{report.total_income:.2f}"),
            kpi("Denaro sui conti", f"€{tot_acc:.2f}"),
            kpi(
                "Risparmio mensile",
                f"€{net_savings:.2f}" if net_savings is not None else "n/d",
                tone="positive" if (net_savings or 0) > 0 else "neutral",
            ),
        ]

        sections = [ReportBuilder._build_category_table(cur, budget_by_cat)]

        trend_paragraphs = ReportBuilder._generate_trend_paragraphs(report, cur)
        tips = ReportBuilder._generate_basic_tips(report, forecast)
        if ai_narrative:
            ai_paragraphs = validated_str_list(ai_narrative.get("trend_paragraphs"), max_items=4)
            ai_tips = validated_str_list(ai_narrative.get("tips"), max_items=3)
            trend_paragraphs = ai_paragraphs or trend_paragraphs
            tips = ai_tips or tips

        sections.append(narrative_section("Analisi e Confronto Trend", trend_paragraphs))
        sections.append(ReportBuilder._build_forecast_section(forecast))
        sections.append(list_section("Consigli Azionabili", tips))

        if accounts:
            sections.append(
                list_section(
                    "Liquidità per conto",
                    [f"{a.get('name', 'Sconosciuto')}: €{float(a.get('current_balance', 0.0)):.2f}" for a in accounts],
                )
            )

        return new_report_content(
            title=f"Riepilogo {cur.label}",
            kpis=kpis,
            sections=sections,
            locked_from_section=_LOCKED_FROM_SECTION,
            footer_note="Generato con AI: verifica sempre i numeri",
        )

    @staticmethod
    def _build_category_table(cur: MonthlySummary, budget_by_cat: dict[str, float] | None) -> TableSection:
        """Tabella "Spesa per categorie" del mese, con colonna Budget/% se disponibile."""
        c_list = sorted(cur.by_category.items(), key=lambda x: x[1], reverse=True)
        has_budget = bool(budget_by_cat)

        if has_budget:
            columns = [
                {"key": "categoria", "label": "Categoria", "align": "left"},
                {"key": "spesa", "label": "Spesa", "align": "right"},
                {"key": "budget", "label": "Budget", "align": "right"},
                {"key": "pct", "label": "% mensile", "align": "right"},
            ]
        else:
            columns = [
                {"key": "categoria", "label": "Categoria", "align": "left"},
                {"key": "spesa", "label": "Spesa", "align": "right"},
                {"key": "pct", "label": "% sul mese", "align": "right"},
            ]

        rows = []
        for cat, amt in c_list:
            if amt <= 0:
                continue
            pct = (amt / cur.total * 100) if cur.total > 0 else 0
            cells = {"categoria": cat, "spesa": f"€{amt:.2f}", "pct": f"{pct:.1f}%"}
            over = False
            if has_budget:
                budget = budget_by_cat.get(cat)
                over = budget is not None and amt > budget
                cells["budget"] = f"€{budget:.2f}" if budget else "—"
            rows.append({"cells": cells, "tone": "warning" if over else None})

        return table_section(
            "Spesa per categorie",
            columns,
            rows,
            empty_message="Nessuna spesa registrata questo mese." if not rows else None,
        )

    @staticmethod
    def _build_forecast_section(forecast: ForecastResult) -> ListSection:
        """Sezione previsione (stime ottimistica/base/pessimistica + spese fisse)."""
        items = [
            f"Stima ottimistica: €{forecast.optimistic_forecast:.2f}",
            f"Stima base: €{forecast.base_forecast:.2f}",
            f"Stima pessimistica: €{forecast.pessimistic_forecast:.2f}",
        ]
        if forecast.fixed_items:
            items.append(
                f"Spese fisse identificate ({len(forecast.fixed_items)}): €{forecast.fixed_expenses:.2f}/mese"
            )
        return list_section(f"Previsione {forecast.target_month_label}", items)

    @staticmethod
    def _generate_trend_paragraphs(report: TrendReport, cur: MonthlySummary) -> list[str]:
        """Paragrafi di analisi deterministici (fallback quando l'AI non è disponibile)."""
        paragraphs = []

        if report.historical_avg > 0:
            delta_eur = cur.total - report.historical_avg
            sign = "+" if delta_eur >= 0 else ""
            paragraphs.append(
                f"Spese: la spesa è in {report.trend_direction} rispetto alla media storica. "
                f"La media è €{report.historical_avg:.2f} ({sign}€{delta_eur:.2f}, {report.delta_pct:+.1f}%)."
            )
        else:
            paragraphs.append("Spese: dati storici insufficienti per un confronto.")

        paragraphs.append("Entrate: statistiche locali non comparabili pienamente.")
        paragraphs.append("Risparmio: dato elaborato esternamente (vedi app).")

        cat_lines = []
        for cat, amt in list(cur.by_category.items())[:3]:
            avg_notion = cur.by_category_average.get(cat, 0.0)
            if amt > 0 and avg_notion > 0:
                cat_lines.append(f"{cat}: speso €{amt:.2f} vs media €{avg_notion:.2f}")
        if cat_lines:
            paragraphs.append("Categorie: " + "; ".join(cat_lines) + ".")

        return paragraphs

    @staticmethod
    def _generate_basic_tips(report: TrendReport, forecast: ForecastResult) -> list[str]:
        """Genera 3 consigli azionabili basati sui dati statistici."""
        tips = []
        cur = report.current_month

        # Consiglio 1: basato sul trend generale
        if report.delta_pct > 10:
            tips.append(
                f"La tua spesa totale è cresciuta del {report.delta_pct:.0f}% rispetto "
                f"alla media storica. Considera di fissare un budget mensile di "
                f"€{report.historical_avg:.0f} più vicino alla tua media."
            )
        elif report.historical_avg > 0:
            tips.append(
                f"Stai gestendo bene le spese. Per ottimizzare ulteriormente, "
                f"punta a mantenere la spesa mensile sotto €{report.historical_avg:.0f} "
                f"(la tua media storica)."
            )

        # Consiglio 2: basato sulla categoria più costosa
        top_cats = cur.top_categories(1)
        if top_cats:
            cat_name, cat_amt = top_cats[0]
            cat_pct = (cat_amt / cur.total * 100) if cur.total > 0 else 0
            if cat_pct > 30:
                tips.append(
                    f"La categoria {cat_name} rappresenta il {cat_pct:.0f}% del totale "
                    f"(€{cat_amt:.0f}). Valuta se ci sono margini di riduzione in quest'area."
                )

        # Fallback generici se non ci sono dati sufficienti
        while len(tips) < 3:
            generics = [
                "Monitora le piccole spese ricorrenti: spesso sfuggono ma si accumulano.",
                "Confronta i prezzi degli abbonamenti attivi: potresti trovare piani migliori.",
                "Imposta un fondo di emergenza pari a 3 mesi di spese medie.",
            ]
            for g in generics:
                if g not in tips:
                    tips.append(g)
                if len(tips) == 3:
                    break

        return tips[:3]


# ---------------------------------------------------------------------------
# SubscriptionScheduler
# ---------------------------------------------------------------------------

_DOW_IT = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]


def _add_months(base: date, months: int, anchor_day: int) -> date:
    """Aggiunge `months` mesi a `base`, ancorando il giorno a `anchor_day`.

    Il giorno viene limitato all'ultimo giorno del mese di destinazione
    (es. 31 gennaio + 1 mese -> 28/29 febbraio).
    """
    import calendar
    total = base.month - 1 + months
    year = base.year + total // 12
    month = total % 12 + 1
    day = min(anchor_day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _next_due(sub: dict, reference: date) -> date | None:
    """Calcola la prossima data di scadenza di un abbonamento."""
    last_billed_raw = sub.get("last_billed")
    if not last_billed_raw:
        return None
    if isinstance(last_billed_raw, str):
        try:
            last_billed = date.fromisoformat(last_billed_raw)
        except ValueError:
            return None
    else:
        last_billed = last_billed_raw

    sub_type = str(sub.get("sub_type") or "mensile").lower()

    # Frequenze basate su un passo in mesi (nome normalizzato -> numero di mesi)
    monthly_steps = {
        "mensile": 1, "monthly": 1,
        "bimestrale": 2, "bi-mensile": 2, "bimensile": 2, "bimonthly": 2,
        "trimestrale": 3, "quarterly": 3,
        "semestrale": 6, "semi-annual": 6, "semiannual": 6, "biannual": 6,
    }
    if sub_type in monthly_steps:
        step = monthly_steps[sub_type]
        k = 1
        candidate = _add_months(last_billed, step, last_billed.day)
        # Avanza finché la scadenza non è >= reference
        while candidate < reference:
            k += 1
            candidate = _add_months(last_billed, step * k, last_billed.day)
        return candidate

    if sub_type in ("annuale", "annual", "yearly"):
        candidate = date(last_billed.year + 1, last_billed.month, last_billed.day)
        while candidate < reference:
            candidate = date(candidate.year + 1, candidate.month, candidate.day)
        return candidate

    if sub_type in ("settimanale", "weekly"):
        candidate = last_billed + timedelta(weeks=1)
        while candidate < reference:
            candidate += timedelta(weeks=1)
        return candidate

    return None


class SubscriptionScheduler:
    """Determina quali abbonamenti scadono nella settimana o nel mese target."""

    def due_this_week(
        self, subscriptions: list[dict], reference: date | None = None
    ) -> list[dict]:
        """
        Args:
            subscriptions: lista da storage.fetch_subscriptions()
            reference: data di riferimento (default: oggi)

        Returns:
            Lista di abbonamenti con campo extra 'due_date' (data scadenza)
        """
        ref = reference or date.today()
        week_end = ref + timedelta(days=6)
        result = []
        for sub in subscriptions:
            due = _next_due(sub, ref)
            if due is not None and ref <= due <= week_end:
                result.append({**sub, "due_date": due})
        return result

    def due_this_month(
        self, subscriptions: list[dict], target_month_date: date | None = None
    ) -> list[dict]:
        """
        Restituisce gli abbonamenti in scadenza nel mese target.

        Args:
            subscriptions: lista da storage.fetch_subscriptions()
            target_month_date: qualsiasi data nel mese target (default: primo del mese prossimo)

        Returns:
            Lista di abbonamenti con campo extra 'due_date'
        """
        if target_month_date is None:
            today = date.today()
            if today.month == 12:
                target_month_date = date(today.year + 1, 1, 1)
            else:
                target_month_date = date(today.year, today.month + 1, 1)

        month_start = date(target_month_date.year, target_month_date.month, 1)
        last_day = _calendar.monthrange(target_month_date.year, target_month_date.month)[1]
        month_end = date(target_month_date.year, target_month_date.month, last_day)

        result = []
        for sub in subscriptions:
            due = _next_due(sub, month_start)
            if due is not None and month_start <= due <= month_end:
                result.append({**sub, "due_date": due})
        return result


# ---------------------------------------------------------------------------
# WeeklyPlanBuilder
# ---------------------------------------------------------------------------

class WeeklyPlanBuilder:
    """Costruisce il report budget mensile settimanale usando FinancialStorage."""

    WEEKS_HISTORY = 8

    def build(
        self,
        storage: "FinancialStorage",
        reference_date: date | None = None,
    ) -> "WeeklyPlanData":
        """
        Raccoglie tutti i dati necessari per il report budget settimanale.

        Args:
            storage: istanza FinancialStorage già configurata per l'utente
            reference_date: data di riferimento (default: oggi)

        Returns:
            WeeklyPlanData con tutti i dati pre-calcolati
        """
        ref = reference_date or date.today()

        # 1. Storico 8 settimane (esclusa settimana corrente)
        history_start = ref - timedelta(weeks=self.WEEKS_HISTORY)
        monday_this_week = ref - timedelta(days=ref.weekday())
        transactions_history = storage.fetch_all_transactions(
            history_start, monday_this_week - timedelta(days=1)
        )

        # 2. Spese mese corrente (dal 1° a oggi)
        month_start = date(ref.year, ref.month, 1)
        transactions_this_month = storage.fetch_all_transactions(month_start, ref)

        # 3. Entrate mese corrente
        incomes_this_month = storage.fetch_income(month_start, ref)

        # 4. Conti, abbonamenti, categorie
        accounts = storage.fetch_accounts()
        subscriptions = storage.fetch_subscriptions()
        categories = storage.get_categories(include_archived=True)

        # Speso nella settimana scorsa (lun-dom)
        monday_last_week = monday_this_week - timedelta(weeks=1)
        sunday_last_week = monday_this_week - timedelta(days=1)
        spent_last_week_by_cat: dict[str, float] = {}
        for tx in transactions_history:
            tx_date = tx.get("date")
            if isinstance(tx_date, str):
                tx_date = date.fromisoformat(tx_date)
            if not isinstance(tx_date, date):
                continue
            if not (monday_last_week <= tx_date <= sunday_last_week):
                continue
            cat = str(tx.get("category") or "Altro")
            if cat in ("Movimenti", "Pareggio Conti"):
                continue
            spent_last_week_by_cat[cat] = (
                spent_last_week_by_cat.get(cat, 0.0) + abs(float(tx.get("amount", 0.0)))
            )

        # --- Analisi ---
        pattern_stats = WeeklyPatternAnalyzer().compute(transactions_history)
        spent_by_cat, budget_by_cat, weeks_remaining = MonthlyResidualCalc().compute(
            transactions_this_month, categories, ref
        )
        momentum = CategoryMomentum().compute(pattern_stats)

        budget_results = WeeklyBudgetCalc().compute(
            budget_by_cat,
            spent_by_cat,
            weeks_remaining,
            pattern_stats,
            ref,
            recent_spent_by_cat=spent_last_week_by_cat,
        )

        no_budget_cats = {
            cat: stats.mean
            for cat, stats in pattern_stats.items()
            if cat not in budget_by_cat and stats.mean > 0
        }

        # Abbonamenti in scadenza questa settimana
        due_subs = SubscriptionScheduler().due_this_week(subscriptions, ref)
        subs_total = sum(float(s.get("amount") or 0.0) for s in due_subs)

        total_income_month = sum(abs(float(i.get("amount", 0.0))) for i in incomes_this_month)
        total_spent_month = sum(spent_by_cat.values())
        total_accounts = sum(float(a.get("current_balance", 0.0)) for a in accounts)

        data = WeeklyPlanData()
        data.reference_date = ref
        data.pattern_stats = pattern_stats
        data.spent_by_cat = spent_by_cat
        data.spent_last_week_by_cat = spent_last_week_by_cat
        data.budget_by_cat = budget_by_cat
        data.weeks_remaining = weeks_remaining
        data.momentum = momentum
        data.budget_results = budget_results
        data.no_budget_cats = no_budget_cats
        data.due_subscriptions = due_subs
        data.subs_total_week = subs_total
        data.total_income_month = total_income_month
        data.total_spent_month = total_spent_month
        data.total_accounts = total_accounts
        return data

    def build_content(self, data: "WeeklyPlanData", ai_narrative: dict | None = None) -> ReportContent:
        """Costruisce il report budget settimanale come `ReportContent`.

        `ai_narrative`, se fornito e valido (`{"tips": [...]}`), sostituisce i
        consigli generici con quelli generati da Mistral. KPI, abbonamenti e
        tabella budget restano sempre calcolati qui dai dati reali.
        """
        ref = data.reference_date
        week_end = ref + timedelta(days=6)

        kpis = [
            kpi("Saldo conti", f"€{data.total_accounts:.2f}"),
            kpi("Entrate mese", f"€{data.total_income_month:.2f}"),
            kpi("Spese mese", f"€{data.total_spent_month:.2f}"),
            kpi("Settimane rimaste", f"{data.weeks_remaining:.1f}"),
        ]

        sections = []

        sub_items = [
            f"{s['name']}: €{float(s.get('amount') or 0):.2f}, scade {s['due_date'].strftime('%d/%m')}"
            for s in data.due_subscriptions
        ]
        if sub_items:
            sub_items.append(f"Totale: €{data.subs_total_week:.2f}")
        sections.append(
            list_section(
                "Abbonamenti in uscita questa settimana",
                sub_items,
                empty_message="Nessun abbonamento in scadenza questa settimana. 🎉",
            )
        )

        budget_rows = []
        for cat, r in sorted(data.budget_results.items(), key=lambda x: x[1].budget_monthly, reverse=True):
            budget_rows.append(
                {
                    "cells": {
                        "categoria": cat,
                        "recente": f"€{r.recent_weekly_pace:.2f}/sett",
                        "consigliato": (
                            f"€{r.limite_reale:.2f}/sett"
                            if r.status != "sforato" else "—"
                        ),
                        "stato": {
                            "ok": "In linea",
                            "attenzione": "Sopra ritmo",
                            "sforato": "Budget superato",
                        }.get(r.status, r.status),
                    },
                    "tone": {"ok": "positive", "attenzione": "warning", "sforato": "negative"}.get(r.status),
                }
            )
        sections.append(
            table_section(
                "Budget per categoria",
                [
                    {"key": "categoria", "label": "Categoria", "align": "left"},
                    {"key": "recente", "label": "Ritmo recente", "align": "right"},
                    {
                        "key": "consigliato",
                        "label": "Ritmo consigliato",
                        "align": "right",
                    },
                    {"key": "stato", "label": "Stato", "align": "left"},
                ],
                budget_rows,
                empty_message="Nessuna categoria con budget impostato. Usa /modify per aggiungerne uno.",
            )
        )

        if data.no_budget_cats:
            sections.append(
                list_section(
                    "Categorie senza budget (stima storica)",
                    [
                        f"{cat}: ~€{avg:.2f}/sett. (media storica)"
                        for cat, avg in sorted(data.no_budget_cats.items(), key=lambda x: x[1], reverse=True)
                    ],
                )
            )

        tips = self._generate_weekly_tips(data)
        if ai_narrative:
            ai_tips = validated_str_list(ai_narrative.get("tips"), max_items=3)
            tips = ai_tips or tips
        if tips:
            sections.append(list_section("Consigli per questa settimana", tips))

        return new_report_content(
            title=f"Piano Settimanale {ref.strftime('%d/%m')} → {week_end.strftime('%d/%m')}",
            kpis=kpis,
            sections=sections,
            locked_from_section=_LOCKED_FROM_SECTION,
        )

    @staticmethod
    def _generate_weekly_tips(data: "WeeklyPlanData") -> list[str]:
        """Consigli deterministici di fallback basati sullo stato budget."""
        tips = []
        for cat, r in sorted(data.budget_results.items(), key=lambda x: x[1].budget_monthly, reverse=True):
            if r.status == "sforato":
                tips.append(f"Hai già superato il budget mensile di {cat} di €{r.overrun:.2f}: rallenta questa settimana.")
            elif r.status == "attenzione" and len(tips) < 3:
                tips.append(
                    f"In {cat} il ritmo recente è €{r.recent_weekly_pace:.2f}/sett, "
                    f"sopra i €{r.limite_reale:.2f}/sett consigliati."
                )
            if len(tips) == 3:
                break
        if not tips:
            tips.append("Le tue categorie con budget sono tutte in target questa settimana: continua così.")
        return tips[:3]

    def build_budget_table_image(
        self,
        data: "WeeklyPlanData",
        output_dir: str = "/tmp",
    ) -> str:
        """
        Genera un'immagine PNG della tabella budget settimanale.
        Restituisce il path del file generato, oppure "" se non ci sono dati.
        """
        from src.chart_generator import ChartGenerator

        ref = data.reference_date
        week_end = ref + timedelta(days=6)
        title = f"Budget Settimanale: {ref.strftime('%d/%m')} → {week_end.strftime('%d/%m/%Y')}"

        return ChartGenerator(output_dir=output_dir).generate_weekly_budget_table(
            budget_results=data.budget_results,
            spent_last_week_by_cat=data.spent_last_week_by_cat,
            title=title,
        )


class WeeklyPlanData:
    """Dati pre-calcolati per il report budget mensile settimanale."""

    def __init__(self):
        self.reference_date: date = date.today()
        self.pattern_stats: dict = {}
        self.spent_by_cat: dict[str, float] = {}
        self.spent_last_week_by_cat: dict[str, float] = {}
        self.budget_by_cat: dict[str, float] = {}
        self.weeks_remaining: float = 1.0
        self.momentum: dict[str, str] = {}
        self.budget_results: dict[str, CategoryBudgetResult] = {}
        self.no_budget_cats: dict[str, float] = {}
        self.due_subscriptions: list[dict] = []
        self.subs_total_week: float = 0.0
        self.total_income_month: float = 0.0
        self.total_spent_month: float = 0.0
        self.total_accounts: float = 0.0

    def to_prompt_text(self) -> str:
        """Serializza i dati in testo strutturato per il prompt AI."""
        ref = self.reference_date
        week_end = ref + timedelta(days=6)
        lines = []

        lines.append(
            f"=== PIANO SETTIMANALE: {ref.strftime('%d/%m/%Y')} → {week_end.strftime('%d/%m/%Y')} ==="
        )
        lines.append(f"Settimane rimanenti nel mese: {self.weeks_remaining:.1f}")
        lines.append(f"Totale speso questo mese: €{self.total_spent_month:.2f}")
        lines.append(f"Entrate totali questo mese: €{self.total_income_month:.2f}")
        lines.append(f"Saldo totale conti: €{self.total_accounts:.2f}")
        lines.append("")

        if self.due_subscriptions:
            lines.append(
                f"ABBONAMENTI IN SCADENZA QUESTA SETTIMANA (totale €{self.subs_total_week:.2f}):"
            )
            for s in self.due_subscriptions:
                due_str = s["due_date"].strftime("%d/%m")
                lines.append(f"  {s['name']}: €{float(s.get('amount') or 0):.2f}, scade {due_str}")
            lines.append("")

        lines.append(
            "BUDGET MENSILE PER CATEGORIA "
            "(ritmo_consigliato = residuo / settimane equivalenti rimaste, minimo 1; "
            "ritmo_recente = spesa dell'ultima settimana completa; "
            "status = ok/attenzione/sforato dal confronto fra i due ritmi):"
        )
        for cat, r in sorted(
            self.budget_results.items(), key=lambda x: x[1].budget_monthly, reverse=True
        ):
            if r.status == "sforato":
                budget_line = (
                    f"  {cat}: budget €{r.budget_monthly:.2f} | speso mese €{r.spent_month:.2f} | "
                    f"SFORATO di €{r.overrun:.2f} | ritmo_recente "
                    f"€{r.recent_weekly_pace:.2f}/s | status: sforato"
                )
            else:
                budget_line = (
                    f"  {cat}: budget €{r.budget_monthly:.2f} | speso mese €{r.spent_month:.2f} | "
                    f"residuo €{r.residuo:.2f} | ritmo_recente "
                    f"€{r.recent_weekly_pace:.2f}/s | ritmo_consigliato "
                    f"€{r.limite_reale:.2f}/s | status: {r.status}"
                )
            lines.append(budget_line)

        if self.no_budget_cats:
            lines.append("")
            lines.append("CATEGORIE SENZA BUDGET (stima storica, non vincoli utente):")
            for cat, avg in sorted(self.no_budget_cats.items(), key=lambda x: x[1], reverse=True):
                last_week = self.spent_last_week_by_cat.get(cat, 0.0)
                lines.append(
                    f"  {cat}: media storica €{avg:.2f}/s | speso sett. scorsa €{last_week:.2f}"
                )

        lines.append("")
        lines.append("PATTERN GIORNALIERI (% spesa per giorno della settimana):")
        DOW_NAMES = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]
        for cat, stats in self.pattern_stats.items():
            if not stats.day_of_week_share:
                continue
            top_days = sorted(stats.day_of_week_share.items(), key=lambda x: x[1], reverse=True)[:3]
            day_str = ", ".join(f"{DOW_NAMES[d]}={pct*100:.0f}%" for d, pct in top_days)
            lines.append(f"  {cat}: spesa concentrata su {day_str}")

        lines.append("")
        lines.append(
            "IMPORTANTE: confronta sempre 'ritmo recente' con 'ritmo consigliato'. "
            "Il primo descrive l'ultima settimana completa; il secondo è il massimo "
            "settimanale sostenibile per restare nel budget mensile."
        )

        return "\n".join(lines)


_MONTHS_IT = [
    "", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre",
]


# ---------------------------------------------------------------------------
# MonthlyPlanData
# ---------------------------------------------------------------------------

class MonthlyPlanData:
    """Dati pre-calcolati per il piano mensile."""

    def __init__(self):
        self.reference_date: date = date.today()
        self.target_month: date = date.today()           # primo giorno del mese target
        self.pattern_stats: dict[str, MonthlyCategoryStats] = {}
        self.budget_by_cat: dict[str, float] = {}        # budget mensile da storage
        self.suggested_targets: dict[str, float] = {}    # output MonthlyBudgetTargetCalc
        self.subscriptions_month: list[dict] = []        # abbonamenti in scadenza nel mese target
        self.subs_total_month: float = 0.0
        self.income_forecast: float = 0.0                # previsione entrate del mese target
        self.income_forecast_sources: list[dict[str, object]] = []
        self.savings_goal: float = 0.0                   # entrate - targets - abbonamenti
        self.category_overrides: dict[str, float] = {}
        self.total_spent_last_month: float = 0.0
        self.total_accounts: float = 0.0
        self.spent_by_cat: dict[str, float] = {}         # spesa per categoria del mese scorso
        self.monthly_history: list[dict] = []            # storico mensile {month, income, expenses, net}
        self.savings_goals_summary: list[dict] = []       # {name, progress_pct, score_label, explanation}

    def to_prompt_text(self) -> str:
        """Serializza i dati in testo strutturato per il prompt AI."""
        tm = self.target_month
        month_label = f"{_MONTHS_IT[tm.month]} {tm.year}"
        lines = []

        lines.append(f"=== PIANO MENSILE: {month_label} ===")
        lines.append(f"Data riferimento: {self.reference_date.strftime('%d/%m/%Y')}")
        lines.append(f"Previsione entrate mese: €{self.income_forecast:.2f}")
        lines.append(f"Spese totale mese scorso: €{self.total_spent_last_month:.2f}")
        lines.append(f"Saldo totale conti: €{self.total_accounts:.2f}")
        lines.append(f"Obiettivo risparmio stimato: €{self.savings_goal:.2f}")
        lines.append("")

        if self.subscriptions_month:
            lines.append(f"ABBONAMENTI IN SCADENZA NEL MESE (totale €{self.subs_total_month:.2f}):")
            for s in self.subscriptions_month:
                due_str = s["due_date"].strftime("%d/%m")
                lines.append(f"  {s['name']}: €{float(s.get('amount') or 0):.2f}, scade {due_str}")
            lines.append("")

        lines.append("TARGET MENSILE PER CATEGORIA (basato su storico 6 mesi):")
        for cat, target in sorted(self.suggested_targets.items(), key=lambda x: x[1], reverse=True):
            stats = self.pattern_stats.get(cat)
            mean_6m = f"€{stats.mean_monthly:.2f}" if stats else "n/d"
            trend = stats.trend if stats else "stabile"
            budget = self.budget_by_cat.get(cat, 0.0)
            override_note = " [VINCOLO UTENTE]" if cat in self.category_overrides else ""
            lines.append(
                f"  {cat}: target €{target:.2f}/mese | media 6m {mean_6m} | "
                f"trend: {trend} | budget mensile €{budget:.2f}{override_note}"
            )

        if self.category_overrides:
            lines.append("")
            lines.append("VINCOLI ESPLICITI DELL'UTENTE:")
            for cat, val in self.category_overrides.items():
                lines.append(f"  {cat}: max €{val:.2f}/mese")

        if self.savings_goals_summary:
            lines.append("")
            lines.append("OBIETTIVI DI RISPARMIO:")
            for g in self.savings_goals_summary:
                lines.append(f"  🎯 {g['name']}: {g['score_label']} ({g['progress_pct']:.0f}% raggiunto)")
                lines.append(f"     {g['explanation']}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# MonthlyPlanBuilder
# ---------------------------------------------------------------------------

class MonthlyPlanBuilder:
    """Costruisce il piano mensile intelligente usando FinancialStorage."""

    MONTHS_HISTORY = 6

    def build(
        self,
        storage: "FinancialStorage",
        reference_date: date | None = None,
        category_overrides: dict[str, float] | None = None,
    ) -> "MonthlyPlanData":
        """
        Raccoglie tutti i dati necessari per il piano mensile.

        Args:
            storage: istanza FinancialStorage già configurata per l'utente
            reference_date: data di riferimento (default: oggi)
            category_overrides: vincoli utente {categoria: target_max_mensile}

        Returns:
            MonthlyPlanData con tutti i dati pre-calcolati
        """
        ref = reference_date or date.today()

        # Mese target = mese successivo
        if ref.month == 12:
            target_year, target_month = ref.year + 1, 1
        else:
            target_year, target_month = ref.year, ref.month + 1
        target_month_start = date(target_year, target_month, 1)

        # Fine dello storico = ultimo giorno del mese precedente a ref
        current_month_start = date(ref.year, ref.month, 1)
        history_end = current_month_start - timedelta(days=1)

        # Inizio storico = 6 mesi prima del mese corrente
        y, m = ref.year, ref.month
        for _ in range(self.MONTHS_HISTORY):
            m -= 1
            if m == 0:
                m = 12
                y -= 1
        history_start = date(y, m, 1)

        # 1. Storico 6 mesi completi (spese e entrate per il piano)
        transactions_history = storage.fetch_all_transactions(history_start, history_end)
        incomes_history = storage.fetch_income(history_start, history_end)

        # Il forecast conserva la sua media sui sei mesi completi, ma richiede
        # almeno 19 mesi fino a oggi per riconoscere cadenze trimestrali e
        # semestrali. Non usare questo intervallo esteso per lo storico del report.
        income_forecast_history_start = _add_months(current_month_start, -18, 1)
        income_forecast_history = storage.fetch_income(income_forecast_history_start, ref)

        # 2. Mese scorso (per contesto total_spent_last_month)
        last_month_end = current_month_start - timedelta(days=1)
        last_month_start = date(last_month_end.year, last_month_end.month, 1)
        transactions_last_month = storage.fetch_all_transactions(last_month_start, last_month_end)

        # 3. Conti, abbonamenti, categorie
        accounts = storage.fetch_accounts()
        subscriptions = storage.fetch_subscriptions()
        categories = storage.get_categories(include_archived=True)

        # --- Analisi ---
        pattern_stats = MonthlyPatternAnalyzer().compute(transactions_history)
        target_month_end = date(
            target_month_start.year,
            target_month_start.month,
            _calendar.monthrange(target_month_start.year, target_month_start.month)[1],
        )
        income_result = IncomeForecastEngine().forecast(
            income_forecast_history,
            month_start=target_month_start,
            month_end=target_month_end,
            as_of=ref,
        )
        income_forecast = income_result.full_month_total
        due_subs = SubscriptionScheduler().due_this_month(subscriptions, target_month_start)
        subs_total = sum(float(s.get("amount") or 0.0) for s in due_subs)
        suggested_targets = MonthlyBudgetTargetCalc().compute(
            pattern_stats, categories, income_forecast, subs_total
        )

        # Applica override utente
        if category_overrides:
            for cat, val in category_overrides.items():
                suggested_targets[cat] = val

        # Totale speso il mese scorso + breakdown per categoria
        total_spent_last_month = 0.0
        spent_by_cat: dict[str, float] = {}
        for tx in transactions_last_month:
            cat = str(tx.get("category") or "Altro")
            if cat in ("Movimenti", "Pareggio Conti"):
                continue
            amt = abs(float(tx.get("amount", 0.0)))
            total_spent_last_month += amt
            spent_by_cat[cat] = spent_by_cat.get(cat, 0.0) + amt

        # Storico mensile: aggrega spese e entrate per mese (ultimi 6 mesi)
        monthly_expenses: dict[str, float] = {}
        for tx in transactions_history:
            tx_date = tx.get("date")
            if isinstance(tx_date, str):
                try:
                    tx_date = date.fromisoformat(tx_date)
                except ValueError:
                    continue
            if not isinstance(tx_date, date):
                continue
            cat = str(tx.get("category") or "")
            if cat in ("Movimenti", "Pareggio Conti"):
                continue
            key = tx_date.strftime("%Y-%m")
            monthly_expenses[key] = monthly_expenses.get(key, 0.0) + abs(float(tx.get("amount", 0.0)))

        monthly_incomes: dict[str, float] = {}
        for inc in incomes_history:
            inc_date = inc.get("date")
            if isinstance(inc_date, str):
                try:
                    inc_date = date.fromisoformat(inc_date)
                except ValueError:
                    continue
            if not isinstance(inc_date, date):
                continue
            key = inc_date.strftime("%Y-%m")
            monthly_incomes[key] = monthly_incomes.get(key, 0.0) + abs(float(inc.get("amount", 0.0)))

        all_months = sorted(set(monthly_expenses) | set(monthly_incomes))
        monthly_history = [
            {
                "month": m,
                "income": round(monthly_incomes.get(m, 0.0), 2),
                "expenses": round(monthly_expenses.get(m, 0.0), 2),
                "net": round(monthly_incomes.get(m, 0.0) - monthly_expenses.get(m, 0.0), 2),
            }
            for m in all_months
        ]

        # Obiettivo risparmio
        total_targets = sum(suggested_targets.values())
        savings_goal = max(income_forecast - total_targets - subs_total, 0.0)

        total_accounts = sum(float(a.get("current_balance", 0.0)) for a in accounts)

        data = MonthlyPlanData()
        data.reference_date = ref
        data.target_month = target_month_start
        data.pattern_stats = pattern_stats
        data.budget_by_cat = {
            c["name"]: float(c["monthly_budget"] or 0.0)
            for c in categories
            if c.get("monthly_budget")
        }
        data.suggested_targets = suggested_targets
        data.subscriptions_month = due_subs
        data.subs_total_month = subs_total
        data.income_forecast = income_forecast
        data.income_forecast_sources = [
            {
                "source_key": source.source_key,
                "full_month_amount": round(source.full_month_amount, 2),
                "recorded_month_amount": round(source.recorded_month_amount, 2),
                "remaining_amount": round(source.remaining_amount, 2),
                "scheduled_dates": [day.isoformat() for day in source.scheduled_dates],
                "periodicity_confidence": round(source.periodicity_confidence, 2),
            }
            for source in income_result.sources
        ]
        data.savings_goal = savings_goal
        data.category_overrides = category_overrides or {}
        data.total_spent_last_month = total_spent_last_month
        data.total_accounts = total_accounts
        data.spent_by_cat = spent_by_cat
        data.monthly_history = monthly_history

        # Obiettivi di risparmio: stessa funzione di calcolo usata da webapp e dal
        # job mensile (bot.py::_savings_goals_monthly_job) — così i numeri nella
        # spiegazione sono sempre coerenti su tutti i canali. No-op per Notion
        # (fetch_savings_goals -> [] di default in FinancialStorage).
        try:
            from src.savings_goals_service import (
                _category_name_for, compute_goal_progress, compute_monthly_score, explain_score,
            )
            active_goals = storage.fetch_savings_goals(status="active")
            for goal in active_goals:
                progress = compute_goal_progress(storage, goal)
                score = compute_monthly_score(storage, goal, progress)
                category_name = (
                    _category_name_for(storage, goal.get("category_id"))
                    if goal["goal_type"] == "category_spending_reduction" else None
                )
                data.savings_goals_summary.append({
                    "name": goal["name"],
                    "progress_pct": progress["progress_pct"],
                    "score_label": score["score_label"],
                    "eta_date": progress["eta_date"].isoformat() if progress["eta_date"] else None,
                    "explanation": explain_score(goal, score, markdown=False, category_name=category_name),
                })
        except Exception:
            logger.warning("Impossibile popolare il riepilogo obiettivi di risparmio nel piano mensile", exc_info=True)

        return data

    def build_content(self, data: "MonthlyPlanData", ai_narrative: dict | None = None) -> ReportContent:
        """Costruisce il piano mensile previsionale come `ReportContent`.

        `ai_narrative`, se fornito e valido (`{"tips": [...]}`), sostituisce i
        consigli generici con quelli generati da Mistral. KPI, abbonamenti e
        tabella target restano sempre calcolati qui dai dati reali.
        """
        tm = data.target_month
        month_label = f"{_MONTHS_IT[tm.month]} {tm.year}"

        kpis = [
            kpi("Saldo conti", f"€{data.total_accounts:.2f}"),
            kpi("Previsione entrate", f"€{data.income_forecast:.2f}"),
            kpi("Spese mese scorso", f"€{data.total_spent_last_month:.2f}"),
            kpi("Obiettivo risparmio", f"€{data.savings_goal:.2f}", tone="positive"),
        ]

        sections = []

        if data.subscriptions_month:
            sub_items = [
                f"{s['name']}: €{float(s.get('amount') or 0):.2f}, scade {s['due_date'].strftime('%d/%m')}"
                for s in data.subscriptions_month
            ]
            sub_items.append(f"Totale: €{data.subs_total_month:.2f}")
            sections.append(list_section("Abbonamenti in scadenza", sub_items))

        target_rows = []
        for cat, target in sorted(data.suggested_targets.items(), key=lambda x: x[1], reverse=True):
            stats = data.pattern_stats.get(cat)
            trend = stats.trend if stats else "stabile"
            categoria = cat + (" (obiettivo tuo)" if cat in data.category_overrides else "")
            target_rows.append(
                {
                    "cells": {"categoria": categoria, "target": f"€{target:.2f}/mese", "trend": trend},
                    "tone": "positive" if trend == "in calo" else ("warning" if trend == "in crescita" else None),
                }
            )
        sections.append(
            table_section(
                "Target mensile per categoria",
                [
                    {"key": "categoria", "label": "Categoria", "align": "left"},
                    {"key": "target", "label": "Target", "align": "right"},
                    {"key": "trend", "label": "Trend", "align": "left"},
                ],
                target_rows,
                empty_message="Nessun target disponibile per questo mese.",
            )
        )

        tips = self._generate_monthly_tips(data)
        if ai_narrative:
            ai_tips = validated_str_list(ai_narrative.get("tips"), max_items=3)
            tips = ai_tips or tips
        if tips:
            sections.append(list_section("Consigli per questo mese", tips))

        return new_report_content(
            title=f"Piano Mensile {month_label}",
            kpis=kpis,
            sections=sections,
            locked_from_section=_LOCKED_FROM_SECTION,
            footer_note="Generato con AI: verifica sempre i numeri. Scrivi per modificare un obiettivo.",
        )

    @staticmethod
    def _generate_monthly_tips(data: "MonthlyPlanData") -> list[str]:
        """Consigli deterministici di fallback basati sui trend per categoria."""
        tips = []
        for cat, target in sorted(data.suggested_targets.items(), key=lambda x: x[1], reverse=True):
            stats = data.pattern_stats.get(cat)
            trend = stats.trend if stats else "stabile"
            if trend == "in crescita" and len(tips) < 3:
                tips.append(f"{cat} è in crescita negli ultimi mesi: punta al target di €{target:.2f}/mese per contenerla.")
            if len(tips) == 3:
                break
        if not tips:
            tips.append("Le tue categorie principali sono stabili o in calo: mantieni gli attuali target mensili.")
        return tips[:3]
